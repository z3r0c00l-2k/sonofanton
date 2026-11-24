# USB

## Modes

| Mode | VID:PID | Use |
|---|---|---|
| EUB / BootROM | `04e8:1100` | upload the RAM chain |
| Old DNW | `04e8:1234` | legacy tools |
| Download | `04e8:685d` | Odin / download mode |
| adb (device mode) | composite Android | `adb` while the phone is a USB device |

The USB-C port is one role at a time. With the hub attached, the port becomes a
host and adb disappears; with the hub detached, adb works and Ethernet does not.

## udev

Give the `users` group access to all three Samsung modes. On a system without a
`dialout` group, use:

```
SUBSYSTEM=="usb", ATTR{idVendor}=="04e8", MODE="0666", GROUP="users"
```

## Download-mode CDC console

The download-mode CDC-ACM interface (`04e8:685d`, EP `0x81`/`0x82` IN, `0x01`
OUT) is the ABL diagnostic console. `ATQ0\r` returns `OKAY`.

Command set (dispatcher `0x2add4`):

| Command | Meaning |
|---|---|
| `ODIN` | binary Odin session mode |
| `PROMPT` | exits the console; do not send casually |
| `DVIF` | device information |
| `SOD` / `SODSTART` / `SODTEST` / `SODEND` | Storage Offline Dump protocol |
| `AT+ENGMODES=<mode>` | ESS commands |
| `@#AuToTEst@#`, `@#AuToTEstRst@#` | test / reboot |
| `FPGM`, `SECCMD1`, `SECCMD2` | factory / secure commands |

The upload/log-dump path exists (`cmd_upload`, `do_upload`,
`is_upload_available`, `Gadget Serial`/`SEC_UPLOAD`), but the trigger previously
recorded as “Vol− + Power ×7” was never verified. The binary's upload-cause table
names `User Press Pwrkey 7s`, which is almost certainly **hold power 7 seconds**,
not seven presses. FMM lock can refuse upload outright.

## Related

- [EUB](../unlock/02-eub.md)
- [Flashing](../unlock/06-flashing.md)
