# Glossary

| Term | Meaning |
|---|---|
| **ABL** | Android bootloader application inside Samsung `sboot`; the part patched here |
| **AVB** | Android Verified Boot; vbmeta carries the verification policy |
| **BCB** | Bootloader control block in `misc`; this ABL has no Android BCB parser |
| **BL1** | First bootloader stage; the custom-key payload is embedded at `+0x2000` |
| **BootROM** | Immutable first-stage code; the fuse lives here |
| **DTB / DTBO** | Device-tree blob / overlay; DTBO entries are revision-keyed |
| **decon** | Samsung display controller; exposes the recovery framebuffer |
| **EUB** | Emergency USB Boot; BootROM-level rescue through the test point |
| **efuse** | One-time-programmable fuse; the custom key and rollback counters live here |
| **efuse commitment** | 32-byte value derived from the ST1 public key and `hmac.bin` |
| **IGYI3** | A later Samsung bootloader generation with different offsets |
| **NHZF5** | The Samsung bootloader generation used by the running chain |
| **param** | Samsung environment store; `param[0]` selects the boot mode |
| **ST1 / ST2** | Samsung's two signing stages; the ST2 index is the fused trust anchor |
| **vbmeta** | Android verified-boot metadata partition |
| **vermagic** | Kernel/module ABI tag; kernel and modules must match |
| **VTS** | Vendor test suite (not used here) |
