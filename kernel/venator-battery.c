// SPDX-License-Identifier: GPL-2.0-only
/*
 * venator-battery.c — Acer Predator PH16-71 battery health control
 *
 * The PH16-71 firmware exposes WMBE (WMI GUID WMID_GUID5 in Linuwu-
 * Sense's naming) with two methods:
 *
 *   0x14 (GET)  in: 4 bytes  [bat_no=1, query=1, 0, 0]
 *               out: 8 bytes [func_list, ret[2], status[5]]
 *                            -> byte 3 = HEALTH_MODE state (0/1)
 *                            -> byte 4 = CALIBRATION_MODE state (0/1)
 *
 *   0x15 (SET)  in: 8 bytes  [bat_no=1, func_mask, status, 0,0,0,0,0]
 *               out: 4 bytes [ret, reserved, ...]  (ret==0 = ok)
 *
 *   func_mask = 1 -> HEALTH_MODE     (firmware-fixed 80% charge cap)
 *   func_mask = 2 -> CALIBRATION_MODE (one-shot full discharge/charge)
 *
 * Wire format reverse-engineered from the WMBE method on a real
 * PH16-71 + cross-checked against Linuwu-Sense's struct layout.
 *
 * Sysfs surface:
 *   /sys/class/predator/battery0/health_mode               (RW, 0/1)
 *   /sys/class/predator/battery0/calibration_mode          (RW, 0/1)
 *   /sys/class/predator/battery0/charge_control_end_threshold (RW, 80|100)
 *
 * The charge_control_end_threshold attr is a convenience that mirrors
 * mainline acer_wmi_battery's interface: writing "80" enables the
 * health-mode cap, "100" disables it. The hardware itself doesn't
 * support an arbitrary percent; the firmware just toggles a fixed 80%
 * cap. We accept 81..99 by clamping to 80 so existing tooling that
 * passes e.g. "75" still does the closest thing.
 */

#include <linux/acpi.h>
#include <linux/device.h>
#include <linux/err.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/wmi.h>

#include "venator.h"

#define BATTERY_NO_1     0x01
#define HEALTH_LIMIT_PCT 80

struct predator_battery {
	struct wmi_device *wdev;
	struct device     *class_dev;
	struct mutex       lock;
};

static struct predator_battery *the_battery;     /* singleton */

/* ------------------------------------------------------------- low-level */

static int wmbe_get(struct predator_battery *bat, u8 query, u8 status_out[5])
{
	u8 in_buf[4] = { BATTERY_NO_1, query, 0, 0 };
	struct acpi_buffer in  = { sizeof(in_buf), in_buf };
	struct acpi_buffer out = { ACPI_ALLOCATE_BUFFER, NULL };
	union acpi_object  *obj;
	acpi_status         status;
	int                 ret = 0;

	mutex_lock(&bat->lock);
	status = wmidev_evaluate_method(bat->wdev, 0,
					WMBE_GET_BATTERY_HEALTH, &in, &out);
	mutex_unlock(&bat->lock);

	if (ACPI_FAILURE(status))
		return -EIO;

	obj = out.pointer;
	if (!obj || obj->type != ACPI_TYPE_BUFFER ||
	    obj->buffer.length != 8) {
		ret = -EINVAL;
		goto done;
	}
	/* Skip func_list (byte 0) + ret[2] (bytes 1-2), copy status[5]. */
	memcpy(status_out, obj->buffer.pointer + 3, 5);
done:
	kfree(out.pointer);
	return ret;
}

static int wmbe_set(struct predator_battery *bat, u8 func_mask, u8 enable)
{
	u8 in_buf[8] = { BATTERY_NO_1, func_mask, !!enable, 0, 0, 0, 0, 0 };
	struct acpi_buffer in  = { sizeof(in_buf), in_buf };
	struct acpi_buffer out = { ACPI_ALLOCATE_BUFFER, NULL };
	union acpi_object  *obj;
	acpi_status         status;
	int                 ret = 0;

	mutex_lock(&bat->lock);
	status = wmidev_evaluate_method(bat->wdev, 0,
					WMBE_SET_BATTERY_HEALTH, &in, &out);
	mutex_unlock(&bat->lock);

	if (ACPI_FAILURE(status))
		return -EIO;

	obj = out.pointer;
	if (!obj || obj->type != ACPI_TYPE_BUFFER ||
	    obj->buffer.length < 1) {
		ret = -EINVAL;
		goto done;
	}
	if (obj->buffer.pointer[0] != 0) {
		dev_warn(&bat->wdev->dev,
			 "WMBE set mask=%u status=%u rejected (ret=0x%02x)\n",
			 func_mask, enable, obj->buffer.pointer[0]);
		ret = -EINVAL;
	}
done:
	kfree(out.pointer);
	return ret;
}

static int read_mode(struct predator_battery *bat, u8 query, int *out)
{
	u8 status[5];
	int err = wmbe_get(bat, query, status);

	if (err)
		return err;
	/* For HEALTH (query=1) and CALIBRATION (query=2) the firmware
	 * returns the same 5-byte status[] block; byte 0 of it is the
	 * state of the queried function.
	 */
	*out = !!status[0];
	return 0;
}

/* --------------------------------------------------- sysfs attributes */

static ssize_t health_mode_show(struct device *dev,
				struct device_attribute *attr, char *buf)
{
	struct predator_battery *bat = dev_get_drvdata(dev);
	int v, err;

	err = read_mode(bat, WMBE_FUNC_HEALTH, &v);
	if (err)
		return err;
	return sysfs_emit(buf, "%d\n", v);
}

static ssize_t health_mode_store(struct device *dev,
				 struct device_attribute *attr,
				 const char *buf, size_t count)
{
	struct predator_battery *bat = dev_get_drvdata(dev);
	bool enable;
	int err;

	err = kstrtobool(buf, &enable);
	if (err)
		return err;
	err = wmbe_set(bat, WMBE_FUNC_HEALTH, enable);
	return err ? err : count;
}
static DEVICE_ATTR_RW(health_mode);

static ssize_t calibration_mode_show(struct device *dev,
				     struct device_attribute *attr, char *buf)
{
	struct predator_battery *bat = dev_get_drvdata(dev);
	int v, err;

	err = read_mode(bat, WMBE_FUNC_CALIBRATION, &v);
	if (err)
		return err;
	return sysfs_emit(buf, "%d\n", v);
}

static ssize_t calibration_mode_store(struct device *dev,
				      struct device_attribute *attr,
				      const char *buf, size_t count)
{
	struct predator_battery *bat = dev_get_drvdata(dev);
	bool enable;
	int err;

	err = kstrtobool(buf, &enable);
	if (err)
		return err;
	err = wmbe_set(bat, WMBE_FUNC_CALIBRATION, enable);
	return err ? err : count;
}
static DEVICE_ATTR_RW(calibration_mode);

/* charge_control_end_threshold mirrors mainline acer_wmi_battery /
 * power_supply convention. The hardware only supports a fixed-80%
 * health-mode toggle, so:
 *    write 100  -> disable health mode (no cap)
 *    write 80   -> enable  health mode (80% cap)
 *    write 81..99 -> treat as 80 (closest available behaviour)
 *    write 1..79 -> reject  (firmware doesn't support arbitrary low caps)
 * Reading returns 80 when enabled, 100 when disabled.
 */
static ssize_t charge_control_end_threshold_show(struct device *dev,
		struct device_attribute *attr, char *buf)
{
	struct predator_battery *bat = dev_get_drvdata(dev);
	int v, err;

	err = read_mode(bat, WMBE_FUNC_HEALTH, &v);
	if (err)
		return err;
	return sysfs_emit(buf, "%d\n", v ? HEALTH_LIMIT_PCT : 100);
}

static ssize_t charge_control_end_threshold_store(struct device *dev,
		struct device_attribute *attr, const char *buf, size_t count)
{
	struct predator_battery *bat = dev_get_drvdata(dev);
	unsigned int v;
	int err;
	bool enable;

	err = kstrtouint(buf, 10, &v);
	if (err)
		return err;
	if (v == 100)
		enable = false;
	else if (v >= HEALTH_LIMIT_PCT && v < 100)
		enable = true;
	else
		return -ERANGE;
	err = wmbe_set(bat, WMBE_FUNC_HEALTH, enable);
	return err ? err : count;
}
static DEVICE_ATTR_RW(charge_control_end_threshold);

static struct attribute *predator_battery_attrs[] = {
	&dev_attr_health_mode.attr,
	&dev_attr_calibration_mode.attr,
	&dev_attr_charge_control_end_threshold.attr,
	NULL,
};

static const struct attribute_group predator_battery_group = {
	.attrs = predator_battery_attrs,
};
static const struct attribute_group *predator_battery_groups[] = {
	&predator_battery_group,
	NULL,
};

/* ------------------------------------------------------- WMI driver glue */

static int predator_battery_probe(struct wmi_device *wdev, const void *ctx)
{
	struct predator_battery *bat;
	int err;

	if (the_battery) {
		dev_warn(&wdev->dev,
			 "venator: WMBE already claimed; ignoring\n");
		return -EBUSY;
	}

	bat = kzalloc(sizeof(*bat), GFP_KERNEL);
	if (!bat)
		return -ENOMEM;
	bat->wdev = wdev;
	mutex_init(&bat->lock);

	if (!predator_class) {
		err = -ENODEV;
		goto out_free;
	}

	bat->class_dev = device_create_with_groups(predator_class, &wdev->dev,
				MKDEV(0, 0), bat,
				predator_battery_groups, "battery0");
	if (IS_ERR(bat->class_dev)) {
		err = PTR_ERR(bat->class_dev);
		goto out_free;
	}

	dev_set_drvdata(&wdev->dev, bat);
	the_battery = bat;
	dev_info(&wdev->dev, "venator: battery health control online\n");
	return 0;

out_free:
	kfree(bat);
	return err;
}

static void predator_battery_remove(struct wmi_device *wdev)
{
	struct predator_battery *bat = dev_get_drvdata(&wdev->dev);

	if (!bat)
		return;
	device_unregister(bat->class_dev);
	the_battery = NULL;
	kfree(bat);
}

static const struct wmi_device_id predator_battery_id_table[] = {
	{ .guid_string = PREDATOR_WMBE_GUID },
	{ }
};
MODULE_DEVICE_TABLE(wmi, predator_battery_id_table);

static struct wmi_driver predator_battery_wmi_driver = {
	.driver = {
		.name = "venator-battery",
	},
	.id_table = predator_battery_id_table,
	.probe    = predator_battery_probe,
	.remove   = predator_battery_remove,
};

int predator_battery_init(void)
{
	return wmi_driver_register(&predator_battery_wmi_driver);
}

void predator_battery_exit(void)
{
	wmi_driver_unregister(&predator_battery_wmi_driver);
}
