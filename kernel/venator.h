/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * venator.h -- protocol constants for the Acer Predator Helios 16
 * PH16-71 RGB keyboard MCU (04F2:0117 Chicony, vendor interface 3, FF02).
 *
 * Every value here is verified against an authoritative source: a
 * USBPcap capture of PredatorSense V3 5.0.1463.0 (79 cmds + 9 frames),
 * confirmed by replaying it on real hardware to light the LEDs.
 */
#ifndef _VENATOR_H_
#define _VENATOR_H_

#define ACER_USB_VID            0x04F2
#define ACER_KBD_PID            0x0117

/* Only this interface carries the LED command + frame channels. */
#define VENATOR_LED_IFACE      3

/* Wire sizes. */
#define VENATOR_CMD_LEN        8       /* 8-byte HID feature reports */
#define VENATOR_NUM_CELLS      128     /* 128 logical key cells in per-key mode */
#define VENATOR_FRAME_LEN      (VENATOR_NUM_CELLS * 4)        /* 512 bytes on EP4 */
#define VENATOR_FRAME_RGB_LEN  (VENATOR_NUM_CELLS * 3)        /* 384 bytes seen by userspace */

/* Transfer-buffer sizes (= wire size + 1 leading byte for the HID report
 * ID). The device declares no Report ID, but Linux's usbhid raw_request
 * and output_report assume the caller's buffer has byte 0 reserved for
 * the report ID and strip it before placing the bytes on the wire.
 * We allocate one extra byte so the actual payload lives in buf[1..].
 */
#define VENATOR_CMD_BUF_LEN    (VENATOR_CMD_LEN + 1)          /* 9 */
#define VENATOR_FRAME_BUF_LEN  (VENATOR_FRAME_LEN + 1)        /* 513 */

/* Opcodes (byte 0 of every 8-byte command). */
#define OP_BEGIN                0x88
#define OP_MODE_ZONE            0xB1
#define OP_MODE_PERKEY          0x12
#define OP_SET_COLOR            0x14
#define OP_APPLY                0x08

/* APPLY sub-fields: 0x08 SUB_APPLY EFF MODE_TAG BRIGHT SCOPE FLAG csum */
#define SUB_APPLY               0x02
#define MODE_TAG                0x05    /* unknown semantic, always 0x05 in capture */
#define FLAG_DEFAULT            0x01    /* probably "save to flash" -- always 0x01 */

/* EFF byte (byte 2 of APPLY). Verified by EFF-fuzzing on PH16-71 against
 * the keyboard MCU itself. Many EFF bytes are aliases of these canonical
 * effects; we expose the canonical one as a named mode and let userspace
 * reach the rest via the `effect_id` sysfs knob.
 */
#define EFF_STATIC              0x01    /* solid, all keys same colour */
#define EFF_BREATHING           0x02    /* solid colour, fade in/out */
#define EFF_RAINBOW             0x03    /* multi-colour wave, hardcoded palette */
#define EFF_SNAKE               0x05    /* single-colour traveling wave, row by row */
#define EFF_RIPPLE              0x06    /* reactive concentric ripple from keypress */
#define EFF_NEON                0x08    /* all keys same colour, slowly cycling hue */
#define EFF_RAIN                0x0A    /* random keys flicker down, drip pattern */
#define EFF_EXPLOSION           0x12    /* auto-firing radial bursts at random keys */
#define EFF_PULSE               0x25    /* low-brightness baseline; key press pulses bright */
#define EFF_STARS               0x26    /* twinkling random keys */
#define EFF_METEOR              0x27    /* directional reactive fireball on keypress */
#define EFF_AURA                0x28    /* reactive area around keypress, sticky while held */
#define EFF_PERKEY              0x33    /* uses the 128-cell per-key buffer sent on EP4 */

/* SCOPE byte (byte 5 of APPLY). */
#define SCOPE_ZONE              0x01
#define SCOPE_PERKEY            0x08

enum venator_mode {
        PMODE_OFF = 0,
        PMODE_STATIC,
        PMODE_BREATHING,
        PMODE_RAINBOW,
        PMODE_SNAKE,
        PMODE_RIPPLE,
        PMODE_NEON,
        PMODE_RAIN,
        PMODE_EXPLOSION,
        PMODE_PULSE,
        PMODE_STARS,
        PMODE_METEOR,
        PMODE_AURA,
        PMODE_PERKEY,
        PMODE__COUNT,
};

/* --------------- battery / power-management bits --------------- */

/* WMI GUID for Acer's "WMID_GUID5" -- Battery Extension. Confirmed
 * present on PH16-71 firmware (object-id "BE"). Used for the 80%
 * charge cap (HEALTH_MODE) and calibration trigger (CALIBRATION_MODE).
 * Wire format reverse-engineered from the WMBE method and matches
 * Linuwu-Sense's struct layout 1:1.
 */
#define VENATOR_WMBE_GUID "79772EC5-04B1-4BFD-843C-61E7F77B6CC9"

/* WMBE method IDs (Arg1 to wmidev_evaluate_method). */
#define WMBE_GET_BATTERY_HEALTH 0x14
#define WMBE_SET_BATTERY_HEALTH 0x15

/* Function mask values (byte 1 of SET input / byte 1 of GET input). */
#define WMBE_FUNC_HEALTH       0x01      /* 80% charge cap */
#define WMBE_FUNC_CALIBRATION  0x02      /* one-shot calibration run */

/* --------------- gaming-misc (WMBH) bits ----------------------- */

/* WMI GUID for Acer's "WMID_GUID4" -- AcerGamingFunction. Same GUID
 * Linuwu-Sense calls "WMID_GUID4". Carries the misc-setting toggles
 * PredatorSense routes through the predatorsense_hardware_service
 * named pipe on Windows.
 *
 * Pack formats here were derived from the per-feature wrappers in
 * AcerAgentService.exe.
 */
#define VENATOR_WMBH_GUID "7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56"

/* WMBH method IDs (Arg1). Subset implemented today.
 */
#define WMBH_SET_PROFILE_SETTING 0x08   /* in u64 out u32 */
#define WMBH_GET_PROFILE_SETTING 0x09   /* in u32 out u64 */
#define WMBH_SET_KB_BACKLIGHT    0x14   /* in UInt8Array (16B) out u32  --
                                         * despite the name, this method
                                         * drives the EC-attached lightbar
                                         * on PH16-71. Decoded from
                                         * AcerECLightbarController.dll.
                                         */
#define WMBH_SET_MISC_SETTING    0x16   /* in u64 out u32 */
#define WMBH_GET_MISC_SETTING    0x17   /* in u32 out u64 */

/* WMBH method 6 (SetGamingRgbKb) WAS the documented per-zone path but
 * the firmware on PH16-71 returns FAIL_TO_GET_DATA for every input
 * combination we've tested (verified vs. PredatorSense's actual
 * Wireshark traffic). Per-zone is not exposed on this chassis.
 */

/* Feature indexes (byte 0 of the SET u64; byte 0 of the GET u32). */
#define GP_INDEX_LCD_OVERDRIVE   0x10   /* via method 8/9 */
#define GM_INDEX_BOOT_SOUND      0x02   /* via method 22/23 */

/* PH16-71 lightbar effect IDs (byte 0 of the 16-byte SetGamingKBBacklight
 * buffer). Cataloged from an interactive hardware sweep.
 *
 * Note the gap: mode IDs 0x08..0xFE silently no-op on this chassis.
 * Mode 0xFF is "Direct"/Static — confirmed via Wireshark of the
 * OpenRGB SDK UpdateMode packets PredatorSense sends. It's a single
 * solid colour with no animation.
 */
#define LB_MODE_OFF        0x00
#define LB_MODE_BREATHING  0x01
#define LB_MODE_NEON       0x02
#define LB_MODE_RAINBOW    0x03
#define LB_MODE_WAVE       0x04
#define LB_MODE_RIPPLE     0x05
#define LB_MODE_SCANNER    0x06
#define LB_MODE_STROBE     0x07
#define LB_MODE_STATIC     0xFF   /* "Direct" mode — solid colour */

/* Shared bits used by both halves of the module. The struct class is
 * created in venator.c init and reused by the battery + gaming
 * halves to hang /sys/class/venator/{battery0,gaming0} off it.
 */
struct class;
extern struct class *venator_class;

int  venator_battery_init(void);
void venator_battery_exit(void);

int  venator_gaming_init(void);
void venator_gaming_exit(void);

#endif /* _VENATOR_H_ */
