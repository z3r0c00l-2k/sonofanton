# Linux host

Debian 13.7 on `userdata`, booted from the phone's recovery slot by the
project launcher. The kernel is a rebuilt 5.4.302 from the pinned Samsung tree,
with the container delta and the image pipeline in `linux/`.

This is the Phase 2 guide. Start at [`../start-here.md`](../start-here.md) if you
have not unlocked the device or if it does not boot.

## Pages

| Page | Contents |
|---|---|
| [build.md](build.md) | Full recovery build: Lineage tree, patches, build, inject, sign, package |
| [architecture.md](architecture.md) | Device, boot chain, kernel, image packaging |
| [operations.md](operations.md) | Debian root, networking, Docker limits, runbook, failures |
| [isolation.md](isolation.md) | Root entry, namespaces, container isolation, ownership |
| [device.md](device.md) | Measured device facts and known constraints |
| [logo.md](logo.md) | Recovery logo canvas, palette, and decoder rules |

## Quickstart

Everything below runs from the `linux/` directory. `sources/`, `toolchains/`,
`build/`, `out/` images, and `keys/` are deliberately not in the repository.

```bash
cd linux

# Fetch the pinned LineageOS/Samsung sources and apply local patches
tools/prepare-tree.sh

# Build, inject the launcher, sign, verify, and package
tools/build-recovery.sh server_vN
```

The output is `out/RECOVERY_r9s_server_vN.img`, `.tar`, `.tar.md5`, and
`out/FLASH_r9s_server_vN.tar`, with hashes appended to `out/SHA256SUMS`.

## Status

The kernel and image pipeline are proven on the device. The server root runs
Debian 13.7, SSH, Docker, and the documented services. The remaining open work
is tracked in [`operations.md`](operations.md) and the repository root.

## Warnings

- The bootloader is fused to the project key. Never flash a stock Samsung
  bootloader or take a One UI OTA.
- The `boot` slot does not boot on this device; all Linux work targets the
  **recovery** slot.
- No firmware, recovery image, signed bootloader, or private key is distributed
  here. Supply your own and verify it against the hashes in the reference pages.
