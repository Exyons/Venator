// SPDX-License-Identifier: GPL-2.0-only
/*
 * venator.c -- Acer Predator Helios 16 PH16-71 RGB keyboard driver
 *
 * Binds the FF02 vendor HID interface of the Chicony keyboard MCU
 * (04F2:0117) and exposes a sysfs surface for colour, brightness, mode,
 * and a 384-byte per-key RGB framebuffer. Writes are staged; userspace
 * commits them by writing 1 to `apply`. This lets a GUI / CLI mutate
 * several sliders without flooding the USB bus with intermediate states.
 *
 * Wire protocol constants are in venator.h.
 */
#include <linux/module.h>
#include <linux/hid.h>
#include <linux/usb.h>
#include <linux/device.h>
#include <linux/slab.h>
#include <linux/mutex.h>
#include <linux/idr.h>
#include <linux/version.h>

#include "venator.h"

/* bin_attribute callbacks + attribute_group.bin_attrs were const-ified
 * upstream around 6.14. Older trees still take the non-const forms.
 */
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 14, 0)
typedef const struct bin_attribute	pred_bin_attr_cb_t;
#define PRED_BIN_ATTRS_FIELD		const struct bin_attribute * const
#else
typedef struct bin_attribute		pred_bin_attr_cb_t;
#define PRED_BIN_ATTRS_FIELD		struct bin_attribute *
#endif

struct predator_kbd {
	struct hid_device       *hdev;
	struct device           *class_dev;
	int                      instance;
	struct mutex             lock;          /* serialises stores + apply */

	/* Staged state, committed when userspace writes apply=1. */
	enum predator_mode       mode;
	u8                       r, g, b;
	u8                       brightness;
	u8                       effect_id_override;     /* 0 = use mode default; else raw EFF byte */
	u8                       frame[PREDATOR_FRAME_RGB_LEN];

	/* Persistent transfer buffers (kmalloc'd for DMA safety). */
	u8                      *cmd_buf;       /* PREDATOR_CMD_BUF_LEN (+1 for report-id byte) */
	u8                      *frame_buf;     /* PREDATOR_FRAME_BUF_LEN (+1 for report-id byte) */
};

/* Defined here, declared `extern` in venator.h so the
 * battery half (venator-battery.c, linked into the same .ko)
 * can hang its own device off /sys/class/predator/.
 */
struct class *predator_class;
static DEFINE_IDA(predator_ida);

static const char * const predator_mode_names[PMODE__COUNT] = {
	[PMODE_OFF]       = "off",
	[PMODE_STATIC]    = "static",
	[PMODE_BREATHING] = "breathing",
	[PMODE_RAINBOW]   = "rainbow",
	[PMODE_SNAKE]     = "snake",
	[PMODE_RIPPLE]    = "ripple",
	[PMODE_NEON]      = "neon",
	[PMODE_RAIN]      = "rain",
	[PMODE_EXPLOSION] = "explosion",
	[PMODE_PULSE]     = "pulse",
	[PMODE_STARS]     = "stars",
	[PMODE_METEOR]    = "meteor",
	[PMODE_AURA]      = "aura",
	[PMODE_PERKEY]    = "perkey",
};

/* ---- wire protocol ---------------------------------------------------- */

static u8 predator_cksum(const u8 *body7)
{
	int i, sum = 0;

	for (i = 0; i < 7; i++)
		sum += body7[i];
	return (0xFF - (sum & 0xFF)) & 0xFF;
}

static int predator_send_cmd(struct predator_kbd *kbd, u8 op,
			     u8 p1, u8 p2, u8 p3, u8 p4, u8 p5, u8 p6)
{
	u8 *b = kbd->cmd_buf;
	int ret;

	/* b[0] is the leading report-id byte. The device has no Report ID,
	 * so we leave it at 0; usbhid strips it before transmitting. The
	 * actual 8-byte command lives in b[1..9].
	 */
	b[0] = 0;
	b[1] = op;
	b[2] = p1; b[3] = p2; b[4] = p3;
	b[5] = p4; b[6] = p5; b[7] = p6;
	b[8] = predator_cksum(&b[1]);

	ret = hid_hw_raw_request(kbd->hdev, 0, b, PREDATOR_CMD_BUF_LEN,
				 HID_FEATURE_REPORT, HID_REQ_SET_REPORT);
	if (ret < 0) {
		hid_warn(kbd->hdev, "SET_REPORT(op=0x%02x) failed: %d\n",
			 op, ret);
		return ret;
	}
	return 0;
}

static int predator_send_frame(struct predator_kbd *kbd)
{
	u8 *b = kbd->frame_buf;
	int i, ret;

	/* b[0] is the leading report-id byte (zero, stripped by usbhid).
	 * The 512-byte frame lives in b[1..513]. Each cell is the
	 * hardware-mandated 4-byte {0x00, R, G, B} from the USBPcap; the
	 * leading 0x00 in each cell is *not* the same as the leading
	 * report-id byte -- both happen to be zero but they're different
	 * fields. We hide both from userspace, which only sees the 384-byte
	 * RGB triplets in kbd->frame.
	 */
	b[0] = 0;
	for (i = 0; i < PREDATOR_NUM_CELLS; i++) {
		b[1 + i * 4 + 0] = 0;
		b[1 + i * 4 + 1] = kbd->frame[i * 3 + 0];
		b[1 + i * 4 + 2] = kbd->frame[i * 3 + 1];
		b[1 + i * 4 + 3] = kbd->frame[i * 3 + 2];
	}

	ret = hid_hw_output_report(kbd->hdev, b, PREDATOR_FRAME_BUF_LEN);
	if (ret < 0) {
		hid_warn(kbd->hdev, "output_report(frame) failed: %d\n", ret);
		return ret;
	}
	return 0;
}

/* Full apply transaction. Caller must hold kbd->lock. */
static int predator_apply_locked(struct predator_kbd *kbd)
{
	int ret;
	u8 eff;

	ret = predator_send_cmd(kbd, OP_BEGIN, 0, 0, 0, 0, 0, 0);
	if (ret)
		return ret;

	if (kbd->mode == PMODE_PERKEY) {
		ret = predator_send_cmd(kbd, OP_MODE_PERKEY,
					0, 0, 8, 0, 0, 0);
		if (ret)
			return ret;
		ret = predator_send_frame(kbd);
		if (ret)
			return ret;
		return predator_send_cmd(kbd, OP_APPLY, SUB_APPLY,
					 EFF_PERKEY, MODE_TAG,
					 kbd->brightness,
					 SCOPE_PERKEY, FLAG_DEFAULT);
	}

	ret = predator_send_cmd(kbd, OP_MODE_ZONE, 0, 0, 0, 0, 0, 0);
	if (ret)
		return ret;

	if (kbd->mode == PMODE_OFF) {
		return predator_send_cmd(kbd, OP_APPLY, SUB_APPLY,
					 EFF_STATIC, MODE_TAG, 0,
					 SCOPE_ZONE, FLAG_DEFAULT);
	}

	/* SET_COLOR: 0x14 00 00 R G B 00 csum.
	 *
	 * v0.1.x had R/G/B at bytes 4/5/6 (from the original byte-order
	 * derivation); user testing with color_flag=0xff + color=#ff0000
	 * produced greenish-yellow, which decoded to R at byte 3 + G at
	 * byte 4 (both set to 0xff). Layout corrected to bytes 3/4/5. The
	 * leading zero bytes are constant in every PredatorSense capture
	 * we've seen; the trailing byte at position 6 is also always zero
	 * here. If a future effect surfaces a meaning for those, expose a
	 * fresh knob then.
	 */
	ret = predator_send_cmd(kbd, OP_SET_COLOR,
				0, 0,
				kbd->r, kbd->g, kbd->b,
				0);
	if (ret)
		return ret;

	switch (kbd->mode) {
	case PMODE_STATIC:    eff = EFF_STATIC;    break;
	case PMODE_BREATHING: eff = EFF_BREATHING; break;
	case PMODE_RAINBOW:   eff = EFF_RAINBOW;   break;
	case PMODE_SNAKE:     eff = EFF_SNAKE;     break;
	case PMODE_RIPPLE:    eff = EFF_RIPPLE;    break;
	case PMODE_NEON:      eff = EFF_NEON;      break;
	case PMODE_RAIN:      eff = EFF_RAIN;      break;
	case PMODE_EXPLOSION: eff = EFF_EXPLOSION; break;
	case PMODE_PULSE:     eff = EFF_PULSE;     break;
	case PMODE_STARS:     eff = EFF_STARS;     break;
	case PMODE_METEOR:    eff = EFF_METEOR;    break;
	case PMODE_AURA:      eff = EFF_AURA;      break;
	default:
		return -EINVAL;
	}

	/* If userspace wrote a non-zero effect_id, use it raw -- escape
	 * hatch while we figure out the right mode->EFF mapping for this
	 * board. effect_id=0 means "use the mode's default".
	 */
	if (kbd->effect_id_override)
		eff = kbd->effect_id_override;

	return predator_send_cmd(kbd, OP_APPLY, SUB_APPLY,
				 eff, MODE_TAG, kbd->brightness,
				 SCOPE_ZONE, FLAG_DEFAULT);
}

/* ---- sysfs control attrs --------------------------------------------- */

static ssize_t mode_show(struct device *dev, struct device_attribute *attr,
			 char *buf)
{
	struct predator_kbd *kbd = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%s\n", predator_mode_names[kbd->mode]);
}

static ssize_t mode_store(struct device *dev, struct device_attribute *attr,
			  const char *buf, size_t count)
{
	struct predator_kbd *kbd = dev_get_drvdata(dev);
	char name[16];
	size_t n;
	int i;

	n = strscpy(name, buf, sizeof(name));
	if (n == -E2BIG)
		return -EINVAL;
	if (n > 0 && name[n - 1] == '\n')
		name[n - 1] = '\0';

	for (i = 0; i < PMODE__COUNT; i++) {
		if (strcmp(name, predator_mode_names[i]) == 0) {
			mutex_lock(&kbd->lock);
			kbd->mode = i;
			mutex_unlock(&kbd->lock);
			return count;
		}
	}
	return -EINVAL;
}
static DEVICE_ATTR_RW(mode);

static ssize_t color_show(struct device *dev, struct device_attribute *attr,
			  char *buf)
{
	struct predator_kbd *kbd = dev_get_drvdata(dev);

	return sysfs_emit(buf, "#%02x%02x%02x\n", kbd->r, kbd->g, kbd->b);
}

static ssize_t color_store(struct device *dev, struct device_attribute *attr,
			   const char *buf, size_t count)
{
	struct predator_kbd *kbd = dev_get_drvdata(dev);
	unsigned int r, g, b;
	const char *p = buf;

	if (*p == '#')
		p++;
	if (sscanf(p, "%2x%2x%2x", &r, &g, &b) != 3)
		return -EINVAL;
	if (r > 0xFF || g > 0xFF || b > 0xFF)
		return -ERANGE;

	mutex_lock(&kbd->lock);
	kbd->r = r;
	kbd->g = g;
	kbd->b = b;
	mutex_unlock(&kbd->lock);
	return count;
}
static DEVICE_ATTR_RW(color);

static ssize_t brightness_show(struct device *dev,
			       struct device_attribute *attr, char *buf)
{
	struct predator_kbd *kbd = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%u\n", kbd->brightness);
}

static ssize_t brightness_store(struct device *dev,
				struct device_attribute *attr,
				const char *buf, size_t count)
{
	struct predator_kbd *kbd = dev_get_drvdata(dev);
	unsigned int v;
	int ret;

	ret = kstrtouint(buf, 0, &v);
	if (ret)
		return ret;
	if (v > 0xFF)
		return -ERANGE;

	mutex_lock(&kbd->lock);
	kbd->brightness = v;
	mutex_unlock(&kbd->lock);
	return count;
}
static DEVICE_ATTR_RW(brightness);

static ssize_t effect_id_show(struct device *dev,
			      struct device_attribute *attr, char *buf)
{
	struct predator_kbd *kbd = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%u\n", kbd->effect_id_override);
}

static ssize_t effect_id_store(struct device *dev,
			       struct device_attribute *attr,
			       const char *buf, size_t count)
{
	struct predator_kbd *kbd = dev_get_drvdata(dev);
	unsigned int v;
	int ret;

	ret = kstrtouint(buf, 0, &v);
	if (ret)
		return ret;
	if (v > 0xFF)
		return -ERANGE;

	mutex_lock(&kbd->lock);
	kbd->effect_id_override = v;
	mutex_unlock(&kbd->lock);
	return count;
}
static DEVICE_ATTR_RW(effect_id);

static ssize_t apply_store(struct device *dev, struct device_attribute *attr,
			   const char *buf, size_t count)
{
	struct predator_kbd *kbd = dev_get_drvdata(dev);
	unsigned int v;
	int ret;

	ret = kstrtouint(buf, 0, &v);
	if (ret)
		return ret;
	if (v == 0)
		return count;

	mutex_lock(&kbd->lock);
	ret = predator_apply_locked(kbd);
	mutex_unlock(&kbd->lock);
	return ret < 0 ? ret : count;
}
static DEVICE_ATTR_WO(apply);

static ssize_t frame_read(struct file *fp, struct kobject *kobj,
			  pred_bin_attr_cb_t *attr,
			  char *buf, loff_t off, size_t count)
{
	struct device *dev = kobj_to_dev(kobj);
	struct predator_kbd *kbd = dev_get_drvdata(dev);

	if (off >= sizeof(kbd->frame))
		return 0;
	if (off + count > sizeof(kbd->frame))
		count = sizeof(kbd->frame) - off;

	mutex_lock(&kbd->lock);
	memcpy(buf, kbd->frame + off, count);
	mutex_unlock(&kbd->lock);
	return count;
}

static ssize_t frame_write(struct file *fp, struct kobject *kobj,
			   pred_bin_attr_cb_t *attr,
			   char *buf, loff_t off, size_t count)
{
	struct device *dev = kobj_to_dev(kobj);
	struct predator_kbd *kbd = dev_get_drvdata(dev);

	if (off + count > sizeof(kbd->frame))
		return -EFBIG;

	mutex_lock(&kbd->lock);
	memcpy(kbd->frame + off, buf, count);
	mutex_unlock(&kbd->lock);
	return count;
}
static BIN_ATTR_RW(frame, PREDATOR_FRAME_RGB_LEN);

static struct attribute *predator_control_attrs[] = {
	&dev_attr_mode.attr,
	&dev_attr_color.attr,
	&dev_attr_brightness.attr,
	&dev_attr_effect_id.attr,
	&dev_attr_apply.attr,
	NULL,
};

static PRED_BIN_ATTRS_FIELD predator_control_bin_attrs[] = {
	&bin_attr_frame,
	NULL,
};

static const struct attribute_group predator_control_group = {
	.attrs     = predator_control_attrs,
	.bin_attrs = predator_control_bin_attrs,
};

/* ---- sysfs info subgroup (read-only metadata) ------------------------ */

static ssize_t dev_vendor_show(struct device *dev,
			       struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%04x\n", ACER_USB_VID);
}
static DEVICE_ATTR_RO(dev_vendor);

static ssize_t dev_product_show(struct device *dev,
				struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%04x\n", ACER_KBD_PID);
}
static DEVICE_ATTR_RO(dev_product);

static ssize_t dev_name_show(struct device *dev,
			     struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "AcerUSBKeyboard PH16-71\n");
}
static DEVICE_ATTR_RO(dev_name);

static ssize_t num_cells_show(struct device *dev,
			      struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%d\n", PREDATOR_NUM_CELLS);
}
static DEVICE_ATTR_RO(num_cells);

static ssize_t available_modes_show(struct device *dev,
				    struct device_attribute *attr, char *buf)
{
	int i, n = 0;

	for (i = 0; i < PMODE__COUNT; i++)
		n += sysfs_emit_at(buf, n, "%s%s", i ? " " : "",
				   predator_mode_names[i]);
	n += sysfs_emit_at(buf, n, "\n");
	return n;
}
static DEVICE_ATTR_RO(available_modes);

static struct attribute *predator_info_attrs[] = {
	&dev_attr_dev_vendor.attr,
	&dev_attr_dev_product.attr,
	&dev_attr_dev_name.attr,
	&dev_attr_num_cells.attr,
	&dev_attr_available_modes.attr,
	NULL,
};

static const struct attribute_group predator_info_group = {
	.name  = "info",
	.attrs = predator_info_attrs,
};

static const struct attribute_group *predator_groups[] = {
	&predator_control_group,
	&predator_info_group,
	NULL,
};

/* ---- HID probe / remove --------------------------------------------- */

/*
 * Our id_table matches every interface of 04F2:0117 -- mi_00 boot
 * keyboard, mi_01 FF00, mi_02 consumer, mi_03 FF02. Only mi_03 carries
 * the LED command + frame channels; the other three are bound passively
 * (hid_parse + hid_hw_start(HID_CONNECT_DEFAULT), which is exactly what
 * hid-generic would have done) so keystrokes, media keys, etc. keep
 * working.
 *
 * Two earlier approaches both produced a dead boot keyboard:
 *  - returning -ENODEV from probe for the wrong interfaces
 *  - returning false from a .match callback for those interfaces
 * In either case bus_for_each_drv treats the negative return as a
 * terminal error and never tries hid-generic, leaving the interface
 * with no driver.
 */
static int predator_probe(struct hid_device *hdev,
			  const struct hid_device_id *id)
{
	struct predator_kbd *kbd;
	struct usb_interface *intf;
	int ret;

	if (!hid_is_usb(hdev))
		return -ENODEV;

	intf = to_usb_interface(hdev->dev.parent);

	/* Same boilerplate hid-generic would have run -- always do this. */
	ret = hid_parse(hdev);
	if (ret) {
		hid_err(hdev, "hid_parse failed: %d\n", ret);
		return ret;
	}

	ret = hid_hw_start(hdev, HID_CONNECT_DEFAULT);
	if (ret) {
		hid_err(hdev, "hid_hw_start failed: %d\n", ret);
		return ret;
	}

	/* For non-LED interfaces, we're a transparent stand-in for
	 * hid-generic. No driver state, no sysfs.
	 */
	if (intf->cur_altsetting->desc.bInterfaceNumber != PREDATOR_LED_IFACE)
		return 0;

	kbd = devm_kzalloc(&hdev->dev, sizeof(*kbd), GFP_KERNEL);
	if (!kbd) {
		ret = -ENOMEM;
		goto err_stop;
	}

	kbd->hdev      = hdev;
	kbd->instance  = -1;
	mutex_init(&kbd->lock);
	kbd->mode      = PMODE_STATIC;
	kbd->r = kbd->g = kbd->b = 0xFF;        /* white */
	kbd->brightness = 200;

	kbd->cmd_buf   = devm_kzalloc(&hdev->dev, PREDATOR_CMD_BUF_LEN,
				      GFP_KERNEL);
	kbd->frame_buf = devm_kzalloc(&hdev->dev, PREDATOR_FRAME_BUF_LEN,
				      GFP_KERNEL);
	if (!kbd->cmd_buf || !kbd->frame_buf) {
		ret = -ENOMEM;
		goto err_stop;
	}

	hid_set_drvdata(hdev, kbd);

	kbd->instance = ida_alloc(&predator_ida, GFP_KERNEL);
	if (kbd->instance < 0) {
		ret = kbd->instance;
		goto err_stop;
	}

	kbd->class_dev = device_create_with_groups(predator_class, &hdev->dev,
						   MKDEV(0, 0), kbd,
						   predator_groups,
						   "keyboard%d",
						   kbd->instance);
	if (IS_ERR(kbd->class_dev)) {
		ret = PTR_ERR(kbd->class_dev);
		goto err_ida;
	}

	hid_info(hdev,
		 "bound; control at /sys/class/predator/keyboard%d/\n",
		 kbd->instance);
	return 0;

err_ida:
	ida_free(&predator_ida, kbd->instance);
err_stop:
	hid_hw_stop(hdev);
	return ret;
}

static void predator_remove(struct hid_device *hdev)
{
	struct predator_kbd *kbd = hid_get_drvdata(hdev);

	/* kbd is only set for mi_03 (the LED interface); the other three
	 * interfaces were bound passively with no per-interface state.
	 */
	if (kbd) {
		if (kbd->class_dev)
			device_unregister(kbd->class_dev);
		if (kbd->instance >= 0)
			ida_free(&predator_ida, kbd->instance);
	}
	hid_hw_stop(hdev);
}

/* ---- module boilerplate --------------------------------------------- */

static const struct hid_device_id predator_id_table[] = {
	{ HID_USB_DEVICE(ACER_USB_VID, ACER_KBD_PID) },
	{ }
};
MODULE_DEVICE_TABLE(hid, predator_id_table);

static struct hid_driver predator_driver = {
	.name     = "venator",
	.id_table = predator_id_table,
	.probe    = predator_probe,
	.remove   = predator_remove,
};

static int __init predator_init(void)
{
	int ret;

#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 4, 0)
	predator_class = class_create(THIS_MODULE, "predator");
#else
	predator_class = class_create("predator");
#endif
	if (IS_ERR(predator_class))
		return PTR_ERR(predator_class);

	ret = hid_register_driver(&predator_driver);
	if (ret) {
		class_destroy(predator_class);
		return ret;
	}
	ret = predator_battery_init();
	if (ret) {
		/* Non-fatal: the keyboard half is still useful even if the
		 * battery half can't claim WMBE (e.g. acer_wmi already
		 * bound it on some kernels). Log and continue.
		 */
		pr_warn("venator: battery half failed (%d); keyboard still up\n",
			ret);
	}
	ret = predator_gaming_init();
	if (ret) {
		/* Non-fatal: WMBH may already be claimed by wmbh-probe.ko or
		 * the user may not have the firmware-revision that exposes
		 * the gaming methods. Keyboard + battery halves are unaffected.
		 */
		pr_warn("venator: gaming half failed (%d); continuing\n",
			ret);
	}
	return 0;
}

static void __exit predator_exit(void)
{
	predator_gaming_exit();
	predator_battery_exit();
	hid_unregister_driver(&predator_driver);
	class_destroy(predator_class);
}

module_init(predator_init);
module_exit(predator_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Predator-Sense Linux contributors");
MODULE_DESCRIPTION("Acer Predator Helios 16 PH16-71 RGB keyboard driver");
MODULE_VERSION("0.1.0");
