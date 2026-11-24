# Third-party notice

Pinned sources and licenses for the tools this project references. Nothing here
is a substitute for the upstream license text. Full author and repository links:
[CREDITS.md](../CREDITS.md).

| Tool | Author | Source | Pin | License |
|---|---|---|---|---|
| Exynos | [henr1kas](https://github.com/henr1kas) | <https://github.com/henr1kas/Exynos> | `176146dd3b0b22049acd2963d9fa69e64ac1654c` | no license file upstream; linked, not vendored |
| houston | [Umer Uddin (halal-beef)](https://github.com/halal-beef) | <https://github.com/halal-beef/houston-pub> | `ec3135de1837cd27f8cf3e512933179fd4c849d7` | GPL-2.0 |
| Linux kernel | [exy2100](https://github.com/exy2100) contributors | [exy2100/android_kernel_samsung_universal2100](https://github.com/exy2100/android_kernel_samsung_universal2100) | `34237952ad8c476c274856c997f7c6e4e92a9946` | GPL-2.0 |
| r9s device tree | [Daniel Ramirez (Daubfy)](https://github.com/Daubfy) | [Daubfy/android_device_samsung_r9s](https://github.com/Daubfy/android_device_samsung_r9s) | `67a2063ab578867eddddc3a6b76fc13d32469e1c` | see upstream |
| LineageOS recovery | [The LineageOS Project](https://github.com/LineageOS) | [github.com/LineageOS](https://github.com/LineageOS) | LineageOS 23.2 | Apache-2.0 and other AOSP licenses |

## Why Exynos is not vendored

The upstream repository has no license file, so copying it into this repository
would be a redistribution without a clear grant. The guide links to the pinned
commit and expects the reader to clone it. Its public sample keys are not the
project's keys.

## Why houston is linked

houston is GPL-2.0. It can be vendored with its license, but this repository
prefers a pinned clone so the source and the license stay together. If you copy
it in, include `LICENSE` and the corresponding source.

## Vendored avbtool

`avbtool` is a build dependency, not part of the credit list. It retains its own
MIT-style AOSP header in `avbtool/avbtool.py`; see `avbtool/README.md`.

## Firmware

Samsung firmware is proprietary and is not distributed here. Obtain it from your
own source and verify the hashes you trust.
