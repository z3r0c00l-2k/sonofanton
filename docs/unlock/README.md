# Unlock guide

Phase 0: from a locked bootloader to a bootable recovery slot, with the Linux
host on top. The device is a Samsung Galaxy S21 FE (SM-G990E / `r9s`, Exynos
2100 / S5E9840).

> **No images and no keys are included.** You must supply the Samsung firmware,
> generate your own signing keys, and verify everything before flashing. The
> fuse is irreversible and the device can be destroyed. Read
> [Risks and disclaimer](../risks.md) and
> [Recovery first](../recovery-first.md) first.

## Why not OEM unlock

The NHZF5 base is One UI 8.0 / Android 16. One UI 8 no longer exposes the OEM
unlocking path: the toggle is absent and the bootloader reports
`androidboot.other.locked=1`. The standard "enable OEM unlocking, unlock,
flash" route is not available on this device.

The project's route is the recovery slot with a custom-key fused bootloader,
reached through the EUB test point. It is one-way; see
[Risks and disclaimer](../risks.md).

## Chapters

| Chapter | Contents |
|---|---|
| [01 Device](01-device.md) | hardware, partitions, fuse, boot slots, constraints |
| [02 EUB](02-eub.md) | test point, BootROM USB, RAM chain, download mode |
| [03 ABL patching](03-abl-patching.md) | every patch site and what it changes |
| [04 Keys and fuse](04-keys-and-fuse.md) | key generation, ST1/ST2, hmac, efuse, fuse |
| [05 Signing](05-signing.md) | split, patch, sign, lz4, tar, verify |
| [06 Flashing](06-flashing.md) | Odin, BL tar, cold boot, rollback |
| [07 DT and recovery](07-dt-and-recovery.md) | DT stage, DTBO, Lineage recovery |
| [08 vbmeta](08-vbmeta.md) | verification-disabled policy |
| [09 Failures](09-failures.md) | falsified attempts and do-not-repeat list |
| [10 Build ladder](10-build-ladder.md) | NHZF5 and IGYI3 builds, what each carries |

## The chain

```
stock firmware
   |
   | split + patch ABL + embed BL1 payload + sign
   v
custom BL tar  --Odin-->  device
   |
   | EUB RAM chain (if UFS chain is broken)
   v
recovery slot  --launcher-->  Debian on userdata
```

## Prerequisites

- Samsung firmware for the device (exact build recorded in
  [versions](../reference/versions.md)); verify the hashes you obtain.
- [Exynos](https://github.com/henr1kas/Exynos) at the pinned revision, and
  [houston](https://github.com/halal-beef/houston-pub) for EUB (both linked, not
  vendored). Authors and licenses: [CREDITS.md](../../CREDITS.md).
- Odin for the download-mode flash.
- A Linux host with Python 3, `lz4`, `pyusb`, and the udev rules for Samsung
  USB modes.
- Your own signing keys and `hmac.bin`; see [Keys and fuse](04-keys-and-fuse.md).
- A charged battery and the EUB test point accessible.

## Read the history when a step does not match

The distilled chapters describe the current method. The chronological evidence,
including failed paths and exact logs, is in
[history/runbook.md](../history/runbook.md). The designs explain why the chain
looks the way it does.
