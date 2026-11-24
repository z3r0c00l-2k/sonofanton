# 08 — vbmeta

Android verified boot (AVB) is rooted in a hardware key-store entry read via
`SMC 0xC200101D`. The project's fuse payload writes the ROM secure boot key and
selectors, not that entry, so a Samsung-signed `vbmeta` can still validate. The
bootloader honours `VERIFICATION_DISABLED` only after the vbmeta's own hash
verifies.

## Two working options

### No-descriptor stub (recommended)

A 256-byte vbmeta with:

- `flags = 2` (`VERIFICATION_DISABLED`),
- algorithm `0`,
- no descriptors.

It cannot fail, and it forces *“Loading entire partition”*. This is what makes
recovery load.

### Stock vbmeta with `flags = 3`

Keeps the descriptors, but editing the flags breaks the vbmeta hash, so it
relies on the patched refusal paths. This is only safe on a bootloader whose
verification paths are patched; it is not a general fallback.

## The rule

Do not edit flags to `3` **and** keep descriptors on a stock bootloader. The
hash no longer matches; the image only works because the refusal path is
stubbed. The no-descriptor stub is the predictable choice.

## Checking

- Inspect the image with `avbtool info_image` (vendored at
  `third_party/avbtool/`).
- Confirm the recovery image boots after the vbmeta flash.
- If the device reports a hash mismatch, go back to the no-descriptor stub; do
  not iterate on flags.

## Related

- [Signing](05-signing.md)
- [Flashing](06-flashing.md)
- [Design: restore stock boot](../design/restore-stock.md)
