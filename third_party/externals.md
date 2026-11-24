# External tools

The unlock workflow uses two external tools. Clone them into a work directory;
do not copy them into this repository unless their license allows it.

## Exynos

```bash
git clone https://github.com/henr1kas/Exynos.git
git -C Exynos checkout 176146dd3b0b22049acd2963d9fa69e64ac1654c
```

Used for `scripts/split.py`, `scripts/build.py`, and `scripts/sign.py`.
The upstream repository has no license file; it is linked, not vendored.

## houston

```bash
git clone https://github.com/halal-beef/houston-pub.git
git -C houston-pub checkout ec3135de1837cd27f8cf3e512933179fd4c849d7
```

Used for the EUB payload/session. GPL-2.0; keep the license with the source.

## Work directory

A useful layout:

```
work/
├── Exynos/           # pinned clone
├── houston-pub/      # pinned clone
├── input/            # your split firmware images
├── output/           # split and built chain
└── keys/             # your keys, never committed
```

`tools/unlock/fetch-externals.sh` clones the two source repositories and prints
the pins; it does not fetch firmware or keys.
