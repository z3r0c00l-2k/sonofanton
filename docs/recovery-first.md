# Recovery first

> **Read [Risks and disclaimer](risks.md) too.** This page is the rescue path,
> not a safety guarantee.

Read this before any flash. The device is fused to a custom key; there is no
stock bootloader to fall back to, and a failed write can leave only the EUB test
point.

## Two irreversible facts

1. **The BootROM trusts the project key.** The fuse points at ST2 key index
   `0x3e96f623`. Only bootloader images signed with the matching private keys
   can run. A Samsung-signed bootloader is rejected.
2. **A One UI OTA ships Samsung-signed bootloader components.** Never install
   one. It will fail or leave the bootloader unbootable.

Keep the signing keys and their backup offline. They are not in this repository.

## If the device does not boot

```
black screen / no download mode
        |
        v
EUB test point  (BootROM USB, 04e8:1100)
        |
        v
upload the RAM chain (Houston payload)
        |
        v
download mode  (04e8:685d)
        |
        v
flash the custom BL tar  ->  cold boot
```

The full protocol and the scripts are in
[Unlock > EUB](unlock/02-eub.md) and `tools/unlock/eub/`. The EUB path is the
reason a failed boot is survivable; it is also the reason the signing keys must
never be published.

## If download mode works

Use Odin to flash the BL tar built for this device. The image must be
signed with the project key and carry the rollback count at or above the
device's eFuse value. See [Flashing](unlock/06-flashing.md).

## Cold boot, not warm reboot

A warm reboot can latch the previous boot mode. After flashing, power the device
off and start it with the power key only.

## Battery and power

Do not flash at a low charge. The charge guard holds the pack under a ceiling
while the device is a host; check the battery before starting.

## What is recoverable

| State | Recovery path |
|---|---|
| Linux root broken | reflash the recovery image / re-provision the root |
| Kernel or modules broken | reflash the recovery image |
| Recovery image broken | download mode + custom BL tar, or EUB |
| Bootloader broken | EUB test point + RAM chain |
| Fuse burned | not reversible; keys are the only way forward |

## Do not

- Flash a stock Samsung BL or take a One UI OTA.
- Publish or commit `keys/`, `keys_backup_*/`, or `hmac.bin`.
- Flash a signed bootloader from this repository (there are none).
- Guess the rollback count or the key index; verify before writing.
