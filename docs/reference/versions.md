# Versions

Exact versions and pins. Hashes are in [checksums](checksums.md). No firmware or
images are stored in this repository. Authors and repository links for every
tool: [CREDITS](../../CREDITS.md).

## Device

| Item | Value |
|---|---|
| Model | SM-G990E (`r9s`) |
| SoC | Samsung Exynos 2100 (S5E9840) |
| RAM / storage | 8 GB / UFS |
| Base OS | Android 16 (API 36) |
| One UI | 8.0 |
| Build ID (PDA) | `G990EXXSNHZF5` |
| Android build fingerprint | `BP2A.250605.031.A3.G990EXXSNHZF5` |
| Security patch | 2026-06-05 |
| CSC | `G990EODMNHZF5` (INS) |
| Bootloader | NHZF5-based custom chain, v28 running; ordinary power-on selects recovery |
| Bootloader revision | 18 |
| Rollback count | `rp=23` (`RB=23`) |
| Fuse | project key, ST2 index `0x3e96f623` |
| Verified boot | `verifiedbootstate=orange`, `other.locked=1` |

## Software

| Component | Version / pin |
|---|---|
| Kernel | `5.4.302-g34237952ad8c-dirty` |
| Kernel source | `exy2100/android_kernel_samsung_universal2100` @ `34237952ad8c476c274856c997f7c6e4e92a9946` |
| Kernel build | Android clang 21.0.0 (r563880c), LLD 21.0.0 |
| Toolchain (standalone) | LLVM 21.1.0 Linux X64 |
| LineageOS | 23.2, `lineage_r9s-trunk_staging-userdebug` |
| Recovery base | LineageOS recovery, `ANDROID!` header v2 |
| Debian | 13.7 trixie |
| Docker | 29.9.2, containerd snapshotter, overlayfs |
| Server image | `FLASH_r9s_server_v9.tar` (see checksums) |
| Exynos tooling | `henr1kas/Exynos` @ `176146dd3b0b22049acd2963d9fa69e64ac1654c` |
| houston | `halal-beef/houston-pub` @ `ec3135de1837cd27f8cf3e512933179fd4c849d7` |
| avbtool | vendored from AOSP `external/avb` (Apache-2.0) |

## Firmware families

| Family | Use |
|---|---|
| NHZF5 | base for the running custom chain and the v22/v28 builds; One UI 8.0 / Android 16; PDA `G990EXXSNHZF5` |
| IGYI3 | alternate generation used for the downgrade experiments; One UI 7; PDA `G990EXXSIGYI3`; different offsets |

The NHZF5 build was released with the 2026-06-05 security patch and bootloader
bit `N` (23), matching the device's `rp=23`. The build number reported by the
firmware metadata is `BP2A.250605.031.A3.G990EXXSNHZF5`; the Samsung update page
lists the same PDA as Android 16 / One UI 8.0.

The exact firmware build strings are recorded in the history and in the
`baseline/manifest.txt` below `linux/`. Obtain firmware from your own source and
verify the hashes you trust; this repository does not distribute it.
