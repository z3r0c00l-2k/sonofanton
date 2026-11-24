# Notice

This project is not affiliated with Samsung, Google, LineageOS, or the authors of
the third-party tools it references. Samsung, Galaxy, Exynos, Odin, and related
names are trademarks of their respective owners.

Author and repository credits for every tool used are in
[CREDITS.md](CREDITS.md). The pinned revisions and licenses are in
[third_party/NOTICE.md](third_party/NOTICE.md).

## Third-party components

| Component | Use | License / source |
|---|---|---|
| LineageOS recovery | recovery base image | Apache-2.0 and other AOSP licenses; source from LineageOS |
| `henr1kas/Exynos` | split, patch, and sign the bootloader | no license file in the upstream repository; linked, not vendored |
| `halal-beef/houston-pub` | EUB payload/session tooling | GPL-2.0; linked, not vendored |
| Linux kernel | kernel source and patches | GPL-2.0 |

The vendored `avbtool` retains its own MIT-style AOSP header in
`third_party/avbtool/avbtool.py`; it is a build dependency, not part of the
credit list.

## Firmware and images

No Samsung firmware, recovery image, signed bootloader, or OTA package is
distributed here. Obtain them from your own source and verify them before use.

## Signing keys

No private keys, `hmac.bin`, or key backups are distributed here. The public
sample keys in the Exynos repository are **not** the project's keys and do not
produce the ST2 index this device trusts.

## Security

See [SECURITY.md](SECURITY.md) for the key-handling and fuse rules.
