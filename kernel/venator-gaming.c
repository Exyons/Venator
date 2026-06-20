// SPDX-License-Identifier: GPL-2.0-only
/*
 * venator-gaming.c — Acer Predator PH16-71 "gaming misc" settings.
 *
 * On Windows, PredatorSense routes toggles like LCD_OVERDRIVE,
 * BOOT_SOUND, STICKY_KEY, WIN_KEY and CUSTOM_BOOT_LOGO through a named
 * pipe (\\.\pipe\predatorsense_hardware_service_) to a SYSTEM-privileged
 * Acer service, which then performs the actual WMBH (AcerGamingFunction)
 * WMI call. We skip the pipe entirely — this driver IS the SYSTEM-side
 * helper.
 *
 * Each per-feature wrapper inside AcerAgentService.exe identifies the
 * downstream WMBH method by its logger label
 * ("namedpipe_hardware_service_function::WMISetGamingMiscSetting" etc.):
 *
 *   LCD_OVERDRIVE  → method  8 SetGamingProfileSetting
 *                    in u64: byte0 = 0x10 (feature),
 *                            byte6 bit0 = 1 ⇒ ON, 0 ⇒ OFF
 *                    (raw values OFF=0x10, ON=0x1000000000010)
 *
 *   BOOT_SOUND     → method 22 SetGamingMiscSetting
 *                    in u64: byte0 = 0x02 (feature),
 *                            byte1 = state + 1 (1 = OFF, 2 = ON)
 *
 * Both pack formats are reverse-engineered from the Ghidra decompile of
 * AcerAgentService.exe's named-pipe IPC layer.
 *
 * Sysfs surface (under /sys/class/venator/gaming0/):
 *   lcd_overdrive   (RW 0/1)  — 165 Hz LCD overdrive
 *   boot_sound      (RW 0/1)  — Acer startup chime
 *
 * Other misc settings (WIN_KEY, CUSTOM_BOOT_LOGO, BATTERY_BOOST, …) will
 * be added once their per-feature wrappers are decompiled and their pack
 * formats confirmed. Adding them blind risks writing to the wrong
 * feature index.
 */

#include <linux/acpi.h>
#include <linux/device.h>
#include <linux/err.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/wmi.h>

#include "venator.h"

struct venator_gaming {
	struct wmi_device *wdev;
	struct device     *class_dev;          /* /sys/class/venator/gaming0   */
	struct device     *lightbar_dev;       /* /sys/class/venator/lightbar0 */
	struct mutex       lock;

	/* Cached lightbar state. Writes are staged here, then committed by
	 * a write to `apply`. Mirrors the keyboard half's pattern in
	 * venator-main.c.
	 */
	u8  lb_mode;        /* 0..7 (off / breathing / neon / rainbow /
	                     *       wave / ripple / scanner / strobe) */
	u8  lb_speed;       /* 1..10 — animation rate */
	u8  lb_brightness;  /* 0..255 */
	u8  lb_dir;         /* direction byte; semantics TBD */
	u8  lb_r, lb_g, lb_b;
};

static struct venator_gaming *the_gaming;

/* ----------------------------------------------------------- low-level */

static void pack_u64_le(u8 buf[8], u64 v)
{
	int i;

	for (i = 0; i < 8; i++)
		buf[i] = (u8)(v >> (8 * i));
}

static u64 unpack_u64_le(const u8 *p, size_t n)
{
	u64 v = 0;
	size_t i;

	for (i = 0; i < n && i < 8; i++)
		v |= (u64)p[i] << (8 * i);
	return v;
}

/*
 * WMBH SetGamingProfileSetting / SetGamingMiscSetting: u64 in → u32 out.
 * The return is a 4-byte buffer whose first byte is the WMI RETURN_CODE
 * (0 = SUCCESS, 1 = FAIL_TO_GET_DATA, 2 = TIMEOUT, 3 = WRONG_PARAMETERS).
 */
static int wmbh_set_u64(struct venator_gaming *g, u8 method, u64 input)
{
	u8 in_buf[8];
	struct acpi_buffer in  = { sizeof(in_buf), in_buf };
	struct acpi_buffer out = { ACPI_ALLOCATE_BUFFER, NULL };
	union acpi_object *obj;
	acpi_status status;
	int ret = 0;

	pack_u64_le(in_buf, input);

	mutex_lock(&g->lock);
	status = wmidev_evaluate_method(g->wdev, 0, method, &in, &out);
	mutex_unlock(&g->lock);

	if (ACPI_FAILURE(status)) {
		dev_warn(&g->wdev->dev,
			 "WMBH method %u ACPI status 0x%x\n", method, status);
		return -EIO;
	}

	obj = out.pointer;
	if (!obj || obj->type != ACPI_TYPE_BUFFER ||
	    obj->buffer.length < 1) {
		dev_warn(&g->wdev->dev,
			 "WMBH method %u: unexpected response type\n", method);
		ret = -EINVAL;
		goto done;
	}
	if (obj->buffer.pointer[0] != 0) {
		dev_warn(&g->wdev->dev,
			 "WMBH method %u in=0x%llx rejected (ret=0x%02x)\n",
			 method, input, obj->buffer.pointer[0]);
		ret = -EINVAL;
	} else {
		dev_dbg(&g->wdev->dev,
			"WMBH method %u in=0x%llx accepted\n", method, input);
	}
done:
	kfree(out.pointer);
	return ret;
}

/*
 * WMBH GetGaming*Setting: u32 in (index) → u64 out (value << 8 | status).
 */
static int wmbh_get_u64(struct venator_gaming *g, u8 method, u8 index,
			u64 *value)
{
	u8 in_buf[4] = { index, 0, 0, 0 };
	struct acpi_buffer in  = { sizeof(in_buf), in_buf };
	struct acpi_buffer out = { ACPI_ALLOCATE_BUFFER, NULL };
	union acpi_object *obj;
	acpi_status status;
	int ret = 0;
	u64 raw;

	mutex_lock(&g->lock);
	status = wmidev_evaluate_method(g->wdev, 0, method, &in, &out);
	mutex_unlock(&g->lock);

	if (ACPI_FAILURE(status))
		return -EIO;

	obj = out.pointer;
	if (!obj) {
		ret = -EINVAL;
		goto done;
	}
	if (obj->type == ACPI_TYPE_BUFFER) {
		if (obj->buffer.length < 1) {
			ret = -EINVAL;
			goto done;
		}
		raw = unpack_u64_le(obj->buffer.pointer, obj->buffer.length);
	} else if (obj->type == ACPI_TYPE_INTEGER) {
		raw = obj->integer.value;
	} else {
		ret = -EINVAL;
		goto done;
	}
	if ((raw & 0xff) != 0) {
		dev_dbg(&g->wdev->dev,
			"WMBH method %u idx=0x%02x status=0x%02x\n",
			method, index, (u8)(raw & 0xff));
		ret = -EINVAL;
		goto done;
	}
	*value = raw >> 8;
done:
	kfree(out.pointer);
	return ret;
}

/* ----------------------------------------------------- feature wrappers */

/*
 * LCD_OVERDRIVE: derived from FUN_14003d7c0 in AcerAgentService.exe.
 * OFF → u64 = 0x10
 * ON  → u64 = 0x10 | (1ULL << 48)
 */
static int lcd_overdrive_write(struct venator_gaming *g, bool enable)
{
	u64 v = (u64)GP_INDEX_LCD_OVERDRIVE;

	if (enable)
		v |= 1ULL << 48;
	return wmbh_set_u64(g, WMBH_SET_PROFILE_SETTING, v);
}

static int lcd_overdrive_read(struct venator_gaming *g, bool *enable)
{
	u64 value;
	int err = wmbh_get_u64(g, WMBH_GET_PROFILE_SETTING,
			       GP_INDEX_LCD_OVERDRIVE, &value);

	if (err)
		return err;
	/* Bit 40 in the unpacked value corresponds to bit 48 in the
	 * original u64 (because GET returns value << 8, so the SET bit at
	 * position 48 lands at position 48-8 = 40 after the >>8 shift in
	 * wmbh_get_u64). Treat any non-zero state as ON.
	 */
	*enable = value != 0;
	return 0;
}

/*
 * BOOT_SOUND: derived from FUN_14003d800.
 * In: u64 = ((state + 1) << 8) | 0x02
 *   state = 0 (OFF) → 0x0102
 *   state = 1 (ON)  → 0x0202
 */
static int boot_sound_write(struct venator_gaming *g, bool enable)
{
	u64 v = ((u64)(enable ? 2 : 1) << 8) | GM_INDEX_BOOT_SOUND;

	return wmbh_set_u64(g, WMBH_SET_MISC_SETTING, v);
}

static int boot_sound_read(struct venator_gaming *g, bool *enable)
{
	u64 value;
	int err = wmbh_get_u64(g, WMBH_GET_MISC_SETTING,
			       GM_INDEX_BOOT_SOUND, &value);

	if (err)
		return err;
	/* SET sends (state+1), so the firmware's stored value should be
	 * 1 or 2; treat 2 as ON, anything else as OFF.
	 */
	*enable = (value & 0xff) == 2;
	return 0;
}

/* --------------------------------------------------- sysfs attributes */

#define DEFINE_BOOL_ATTR(_name, _read, _write)				\
static ssize_t _name##_show(struct device *dev,				\
			    struct device_attribute *attr, char *buf)	\
{									\
	struct venator_gaming *g = dev_get_drvdata(dev);		\
	bool v;								\
	int err = _read(g, &v);						\
									\
	if (err)							\
		return err;						\
	return sysfs_emit(buf, "%d\n", v);				\
}									\
									\
static ssize_t _name##_store(struct device *dev,			\
			     struct device_attribute *attr,		\
			     const char *buf, size_t count)		\
{									\
	struct venator_gaming *g = dev_get_drvdata(dev);		\
	bool enable;							\
	int err = kstrtobool(buf, &enable);				\
									\
	if (err)							\
		return err;						\
	err = _write(g, enable);					\
	return err ? err : count;					\
}									\
static DEVICE_ATTR_RW(_name)

DEFINE_BOOL_ATTR(lcd_overdrive, lcd_overdrive_read, lcd_overdrive_write);
DEFINE_BOOL_ATTR(boot_sound,    boot_sound_read,    boot_sound_write);

static struct attribute *venator_gaming_attrs[] = {
	&dev_attr_lcd_overdrive.attr,
	&dev_attr_boot_sound.attr,
	NULL,
};

static const struct attribute_group venator_gaming_group = {
	.attrs = venator_gaming_attrs,
};
static const struct attribute_group *venator_gaming_groups[] = {
	&venator_gaming_group,
	NULL,
};

/* ---------------------------------------------------- lightbar control */
/*
 * The PH16-71 lightbar is driven by WMBH method 20 (SetGamingKBBacklight)
 * with a 16-byte input buffer. Reverse-engineered from
 * AcerECLightbarController.dll's AcerECLightBarController::SetMode +
 * confirmed on real hardware.
 *
 * Buffer layout (LE bytes):
 *   0  mode (LB_MODE_*)
 *   1  speed
 *   2  brightness
 *   3  0x00
 *   4  direction (semantics TBD; default 0x01)
 *   5  R
 *   6  G
 *   7  B
 *   8  0x03   ← constant tail markers the firmware expects
 *   9  0x02
 *  10..15  0x00 padding
 */
static int wmbh_set_lightbar(struct venator_gaming *g)
{
	u8 in_buf[16] = {
		g->lb_mode,
		g->lb_speed,
		g->lb_brightness,
		0x00,
		g->lb_dir,
		g->lb_r, g->lb_g, g->lb_b,
		0x03, 0x02,
		0, 0, 0, 0, 0, 0
	};
	struct acpi_buffer in  = { sizeof(in_buf), in_buf };
	struct acpi_buffer out = { ACPI_ALLOCATE_BUFFER, NULL };
	union acpi_object *obj;
	acpi_status status;
	int ret = 0;

	mutex_lock(&g->lock);
	status = wmidev_evaluate_method(g->wdev, 0,
					WMBH_SET_KB_BACKLIGHT, &in, &out);
	mutex_unlock(&g->lock);

	if (ACPI_FAILURE(status))
		return -EIO;

	obj = out.pointer;
	if (!obj || obj->type != ACPI_TYPE_BUFFER ||
	    obj->buffer.length < 1) {
		ret = -EINVAL;
		goto done;
	}
	if (obj->buffer.pointer[0] != 0) {
		dev_warn(&g->wdev->dev,
			 "lightbar mode=%u rejected (ret=0x%02x)\n",
			 g->lb_mode, obj->buffer.pointer[0]);
		ret = -EINVAL;
	}
done:
	kfree(out.pointer);
	return ret;
}

/*
 * Mode catalog. PH16-71's firmware exposes a non-contiguous set:
 * 0x00..0x07 are the eight effects we cataloged via interactive
 * sweep; 0x08..0xFE silently no-op; 0xFF is the "Direct" / Static
 * mode we found via the OpenRGB SDK Wireshark capture. So the
 * underlying ID space is sparse — use a struct array, not an
 * index-by-id table.
 */
struct lb_mode_entry {
	u8           id;
	const char  *name;
};

static const struct lb_mode_entry lb_modes_catalog[] = {
	{LB_MODE_OFF,       "off"},
	{LB_MODE_BREATHING, "breathing"},
	{LB_MODE_NEON,      "neon"},
	{LB_MODE_RAINBOW,   "rainbow"},
	{LB_MODE_WAVE,      "wave"},
	{LB_MODE_RIPPLE,    "ripple"},
	{LB_MODE_SCANNER,   "scanner"},
	{LB_MODE_STROBE,    "strobe"},
	{LB_MODE_STATIC,    "static"},
};

static const char *lb_name_for(u8 id)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(lb_modes_catalog); i++)
		if (lb_modes_catalog[i].id == id)
			return lb_modes_catalog[i].name;
	return "?";
}

static int lb_id_for(const char *name, u8 *out)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(lb_modes_catalog); i++) {
		if (!strcmp(name, lb_modes_catalog[i].name)) {
			*out = lb_modes_catalog[i].id;
			return 0;
		}
	}
	return -ENOENT;
}

static int lb_id_is_known(u8 id)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(lb_modes_catalog); i++)
		if (lb_modes_catalog[i].id == id)
			return 1;
	return 0;
}

static ssize_t lb_mode_show(struct device *dev,
			    struct device_attribute *attr, char *buf)
{
	struct venator_gaming *g = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%s\n", lb_name_for(g->lb_mode));
}

static ssize_t lb_mode_store(struct device *dev,
			     struct device_attribute *attr,
			     const char *buf, size_t count)
{
	struct venator_gaming *g = dev_get_drvdata(dev);
	char name[16];
	unsigned int v;
	u8 id;

	if (count >= sizeof(name))
		return -EINVAL;

	/* Accept either "wave" or "4" / "0xff" — be lenient. */
	if (sscanf(buf, "%15s", name) == 1 && !lb_id_for(name, &id)) {
		g->lb_mode = id;
		return count;
	}
	if (kstrtouint(buf, 0, &v) == 0 && v <= 0xff && lb_id_is_known(v)) {
		g->lb_mode = v;
		return count;
	}
	return -EINVAL;
}
static DEVICE_ATTR(mode, 0644, lb_mode_show, lb_mode_store);

static ssize_t lb_brightness_show(struct device *dev,
				  struct device_attribute *attr, char *buf)
{
	struct venator_gaming *g = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%u\n", g->lb_brightness);
}
static ssize_t lb_brightness_store(struct device *dev,
				   struct device_attribute *attr,
				   const char *buf, size_t count)
{
	struct venator_gaming *g = dev_get_drvdata(dev);
	unsigned int v;
	int err = kstrtouint(buf, 0, &v);

	if (err)
		return err;
	if (v > 255)
		return -ERANGE;
	g->lb_brightness = v;
	return count;
}
static DEVICE_ATTR(brightness, 0644, lb_brightness_show, lb_brightness_store);

static ssize_t lb_speed_show(struct device *dev,
			     struct device_attribute *attr, char *buf)
{
	struct venator_gaming *g = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%u\n", g->lb_speed);
}
static ssize_t lb_speed_store(struct device *dev,
			      struct device_attribute *attr,
			      const char *buf, size_t count)
{
	struct venator_gaming *g = dev_get_drvdata(dev);
	unsigned int v;
	int err = kstrtouint(buf, 0, &v);

	if (err)
		return err;
	if (v > 255)
		return -ERANGE;
	g->lb_speed = v;
	return count;
}
static DEVICE_ATTR(speed, 0644, lb_speed_show, lb_speed_store);

static ssize_t lb_direction_show(struct device *dev,
				 struct device_attribute *attr, char *buf)
{
	struct venator_gaming *g = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%u\n", g->lb_dir);
}
static ssize_t lb_direction_store(struct device *dev,
				  struct device_attribute *attr,
				  const char *buf, size_t count)
{
	struct venator_gaming *g = dev_get_drvdata(dev);
	unsigned int v;
	int err = kstrtouint(buf, 0, &v);

	if (err)
		return err;
	if (v > 255)
		return -ERANGE;
	g->lb_dir = v;
	return count;
}
static DEVICE_ATTR(direction, 0644, lb_direction_show, lb_direction_store);

static ssize_t lb_color_show(struct device *dev,
			     struct device_attribute *attr, char *buf)
{
	struct venator_gaming *g = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%02x%02x%02x\n",
			  g->lb_r, g->lb_g, g->lb_b);
}
static ssize_t lb_color_store(struct device *dev,
			      struct device_attribute *attr,
			      const char *buf, size_t count)
{
	struct venator_gaming *g = dev_get_drvdata(dev);
	const char *p = buf;
	unsigned int r, gr, b;

	/* Accept "#rrggbb" or "rrggbb". */
	if (*p == '#')
		p++;
	if (sscanf(p, "%2x%2x%2x", &r, &gr, &b) != 3)
		return -EINVAL;
	g->lb_r = r;
	g->lb_g = gr;
	g->lb_b = b;
	return count;
}
static DEVICE_ATTR(color, 0644, lb_color_show, lb_color_store);

static ssize_t lb_apply_store(struct device *dev,
			      struct device_attribute *attr,
			      const char *buf, size_t count)
{
	struct venator_gaming *g = dev_get_drvdata(dev);
	int err = wmbh_set_lightbar(g);

	return err ? err : count;
}
static DEVICE_ATTR(apply, 0200, NULL, lb_apply_store);

/* Convenience compact "set" attribute: write "<mode> <bright> <speed> <r> <g> <b>"
 * (decimal or 0x hex per token) and the driver atomically updates state
 * and commits. Mirrors the keyboard half's "static_mode" knob.
 */
static ssize_t lb_set_store(struct device *dev,
			    struct device_attribute *attr,
			    const char *buf, size_t count)
{
	struct venator_gaming *g = dev_get_drvdata(dev);
	unsigned int mode, bright, speed, r, gr, b;
	int n, err;

	n = sscanf(buf, "%u %u %u %u %u %u",
		   &mode, &bright, &speed, &r, &gr, &b);
	if (n != 6)
		return -EINVAL;
	if (mode > 0xff || bright > 255 || speed > 255 ||
	    r > 255 || gr > 255 || b > 255)
		return -ERANGE;
	if (!lb_id_is_known(mode))
		return -EINVAL;

	g->lb_mode = mode;
	g->lb_brightness = bright;
	g->lb_speed = speed;
	g->lb_r = r;
	g->lb_g = gr;
	g->lb_b = b;
	err = wmbh_set_lightbar(g);
	return err ? err : count;
}
static DEVICE_ATTR(set, 0200, NULL, lb_set_store);

static ssize_t lb_modes_show(struct device *dev,
			     struct device_attribute *attr, char *buf)
{
	int i;
	ssize_t n = 0;

	for (i = 0; i < ARRAY_SIZE(lb_modes_catalog); i++) {
		n += sysfs_emit_at(buf, n, "0x%02x %s\n",
				   lb_modes_catalog[i].id,
				   lb_modes_catalog[i].name);
	}
	return n;
}
static DEVICE_ATTR(modes, 0444, lb_modes_show, NULL);

/*
 * Per-zone colour (WMBH method 6 SetGamingRgbKb) WAS implemented here
 * but the firmware on PH16-71 rejects every call with FAIL_TO_GET_DATA
 * regardless of lightbar_id (1..4) or zone (1..8). Confirmed via
 * hardware probe + Wireshark of the OpenRGB SDK traffic from
 * PredatorSense — the Windows side sends the bytes too and the result
 * is the same (single colour applied to all three zones). Per-zone is
 * therefore not implemented; if a future chassis turns out to support
 * it, the path can be added here.
 */

static struct attribute *venator_lightbar_attrs[] = {
	&dev_attr_mode.attr,
	&dev_attr_brightness.attr,
	&dev_attr_speed.attr,
	&dev_attr_direction.attr,
	&dev_attr_color.attr,
	&dev_attr_apply.attr,
	&dev_attr_set.attr,
	&dev_attr_modes.attr,
	NULL,
};
static const struct attribute_group venator_lightbar_group = {
	.attrs = venator_lightbar_attrs,
};
static const struct attribute_group *venator_lightbar_groups[] = {
	&venator_lightbar_group,
	NULL,
};

/* ------------------------------------------------------- WMI driver glue */

static int venator_gaming_probe(struct wmi_device *wdev, const void *ctx)
{
	struct venator_gaming *g;
	int err;

	if (the_gaming) {
		dev_warn(&wdev->dev,
			 "venator: WMBH already claimed; ignoring\n");
		return -EBUSY;
	}

	g = kzalloc(sizeof(*g), GFP_KERNEL);
	if (!g)
		return -ENOMEM;
	g->wdev = wdev;
	mutex_init(&g->lock);

	/* Sensible defaults for the lightbar state cache. */
	g->lb_mode       = LB_MODE_BREATHING;
	g->lb_speed      = 5;
	g->lb_brightness = 100;
	g->lb_dir        = 1;
	g->lb_r = 0xff; g->lb_g = 0x00; g->lb_b = 0x00;

	if (!venator_class) {
		err = -ENODEV;
		goto out_free;
	}

	g->class_dev = device_create_with_groups(venator_class, &wdev->dev,
				MKDEV(0, 0), g,
				venator_gaming_groups, "gaming0");
	if (IS_ERR(g->class_dev)) {
		err = PTR_ERR(g->class_dev);
		goto out_free;
	}

	g->lightbar_dev = device_create_with_groups(venator_class, &wdev->dev,
				MKDEV(0, 0), g,
				venator_lightbar_groups, "lightbar0");
	if (IS_ERR(g->lightbar_dev)) {
		err = PTR_ERR(g->lightbar_dev);
		dev_warn(&wdev->dev,
			 "venator: lightbar sysfs init failed (%d); "
			 "gaming misc settings still up\n", err);
		g->lightbar_dev = NULL;
		/* Non-fatal — keep the misc-setting half online. */
	}

	dev_set_drvdata(&wdev->dev, g);
	the_gaming = g;
	dev_info(&wdev->dev,
		 "venator: gaming + lightbar control online\n");
	return 0;

out_free:
	kfree(g);
	return err;
}

static void venator_gaming_remove(struct wmi_device *wdev)
{
	struct venator_gaming *g = dev_get_drvdata(&wdev->dev);

	if (!g)
		return;
	if (g->lightbar_dev)
		device_unregister(g->lightbar_dev);
	device_unregister(g->class_dev);
	the_gaming = NULL;
	kfree(g);
}

static const struct wmi_device_id venator_gaming_id_table[] = {
	{ .guid_string = VENATOR_WMBH_GUID },
	{ }
};
MODULE_DEVICE_TABLE(wmi, venator_gaming_id_table);

static struct wmi_driver venator_gaming_wmi_driver = {
	.driver = {
		.name = "venator-gaming",
	},
	.id_table = venator_gaming_id_table,
	.probe    = venator_gaming_probe,
	.remove   = venator_gaming_remove,
};

int venator_gaming_init(void)
{
	return wmi_driver_register(&venator_gaming_wmi_driver);
}

void venator_gaming_exit(void)
{
	wmi_driver_unregister(&venator_gaming_wmi_driver);
}
