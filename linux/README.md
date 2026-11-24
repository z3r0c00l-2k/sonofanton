# r9s-linux — Linux host build tree

This directory contains the reproducible recovery-image pipeline and the Linux
root launcher for the r9s (SM-G990E). The full guide lives in
[`../docs/linux/`](../docs/linux/README.md).

## Layout

| Path | Purpose |
|---|---|
| `tools/` | build, repack, sign, verify, and launcher tools |
| `tools/device/` | files injected into the recovery ramdisk |
| `patches/` | kernel build patches and the Lineage tree patch set |
| `configs/` | kernel config fragment for containers |
| `baseline/` | recovered kernel config and image metadata (no payloads) |
| `assets/` | the verified recovery logo |
| `out/` | built artifacts (ignored) and the committed `SHA256SUMS` ledger |

`tools/device/pivot_root` is the prebuilt static aarch64 helper compiled from
`tools/pivot_root.c`; the other files in `tools/device/` are shell scripts.
`tools/device/authorized_keys.example` is a provisioning template, not a live
credential.

`sources/`, `toolchains/`, `build/`, `out/` images, and `keys/` are ignored and
must be fetched or generated locally.

## Quickstart

```bash
tools/prepare-tree.sh              # clone, pin, lay out, patch the Lineage tree
tools/build-recovery.sh server_vN  # build, inject, sign, verify, package
```

See [`../docs/linux/build.md`](../docs/linux/build.md) for prerequisites and the
manual steps, and [`../docs/linux/operations.md`](../docs/linux/operations.md)
for the Debian root, networking, Docker, and the on-device runbook.

## Warnings

- The bootloader is fused to the project key. Never flash a stock Samsung
  bootloader or take a One UI OTA.
- All Linux work targets the recovery slot; the `boot` slot does not boot.
- No firmware, images, or keys are distributed in this repository.
