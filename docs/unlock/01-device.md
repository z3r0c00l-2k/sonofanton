# 01 — Device

## Hardware

| Item | Value |
|---|---|
| Model | SM-G990E, codename `r9s` |
| SoC | Samsung Exynos 2100 (S5E9840) |
| Base firmware | `G990EXXSNHZF5` — Android 16, One UI 8.0 |
| Base build fingerprint | `BP2A.250605.031.A3.G990EXXSNHZF5` |
| CPU | 8 cores, ARM64 |
| RAM | 8 GB |
| Storage | UFS |
| Display | 1080×2340 class panel; recovery UI uses the decon framebuffer |
| USB | USB-C; one role at a time (host with hub, or device for adb) |
| Bootloader | Samsung ABL inside `sboot`, custom-key signed |
| Fuse | project key, ST2 index `0x3e96f623` |

The device serial, Chip ID/DID, and MAC are omitted from this repository.

## Why not OEM unlock

The base firmware is One UI 8.0 / Android 16. One UI 8 no longer exposes the OEM
unlocking path: the toggle is absent and the bootloader reports
`androidboot.other.locked=1`. The familiar "enable OEM unlocking, unlock,
flash" route is therefore not available.

This project uses the recovery slot with a custom-key fused bootloader, reached
through the EUB test point. That is a one-way change, not a normal unlock. See
[Risks and disclaimer](../risks.md).

Evidence: Samsung's update page for `G990EXXSNHZF5` lists Android 16 / One UI
8.0, and One UI 8 reports from non-US devices describe the missing OEM unlocking
toggle and the `androidboot.other.locked=1` property
([Android Authority](https://www.androidauthority.com/samsung-bootloader-unlocking-disabled-one-ui-8-3581366/),
[XDA](https://xdaforums.com/t/bootloader-unlocking-option-removed-from-one-ui-8-0.4751904/)).
The device record also shows `other.locked=1`.

## Partitions that matter

| Partition | Role |
|---|---|
| `sboot` | bootloader chain (`bl1`, `bl2`, `bootload`, `el3_mon`, …) |
| `recovery` | the host slot: kernel, modules, ramdisk, launcher |
| `boot` | not usable on this device; aborts at the DT stage |
| `dtbo` | DTBO table with revision-keyed entries |
| `vbmeta` | Android verified boot metadata |
| `super` | dynamic partitions (stock Android) |
| `misc` | BCB / boot-mode control block |
| `userdata` | unencrypted f2fs; Debian root and container data |
| `param` | Samsung environment store; `param[0]` selects boot mode |

`param` layout: env struct at partition offset `0x700000`, `param[0]` at
`0x700200`, marker string id `0x47` at `0x703b00`.
`tools/unlock/patchers/param_bootmode.py get|set {0|4}` reads or writes it.

## Hard constraints

1. **The fuse is burned.** Only bootloader images signed with the project keys
   can run. A stock Samsung bootloader can never be restored.
2. **Never take a One UI OTA.** Its BL components are Samsung-signed and will be
   rejected or leave the device unbootable.
3. **The `boot` slot does not boot.** Every v2 recovery image boots; v3/GKI boot
   images fail before display/USB with three different kernels.
4. **A warm reboot can latch the previous boot mode.** Use a cold boot (power
   key only) after every flash.
5. **Download mode has no `OEM LOCK` field.** The unlock state is carried by the
   fused key and the patched chain, not by the stock UI.

## Boot modes

| Mode | Entry |
|---|---|
| Recovery | `param[0]` in `{4,5}` reaches the recovery block; v28 redirects the ordinary `0` path there |
| Download | Vol+ + Vol− + cable; USB `04e8:685d` |
| EUB | BootROM test point; USB `04e8:1100` |
| Normal boot | `param[0] == 0` (not usable for Linux here) |

## Verified boot

The device reports `verifiedbootstate=orange` with `other.locked=1`. The stock
AVB root of trust is a hardware key-store entry read via `SMC 0xC200101D`; the
fuse payload writes the ROM secure boot key and selectors, not that entry. The
vbmeta policy is therefore handled explicitly; see [vbmeta](08-vbmeta.md).

## Related

- [EUB](02-eub.md) — the rescue path
- [Keys and fuse](04-keys-and-fuse.md) — why the keys are irreplaceable
- [Reference: partitions](../reference/partitions.md)
