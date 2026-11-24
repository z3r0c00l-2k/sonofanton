# Status

What is proven on the device and what is still open. Facts here were measured or
read from a shipped image; anything uncertain is marked.

## Device

| Item | Value |
|---|---|
| Model | SM-G990E (`r9s`), Exynos 2100 (S5E9840), 8 GB RAM, UFS |
| Base OS | Android 16 (API 36) |
| One UI | 8.0 |
| Build ID (PDA) | `G990EXXSNHZF5` |
| Android build fingerprint | `BP2A.250605.031.A3.G990EXXSNHZF5` |
| Security patch | 2026-06-05 |
| CSC | `G990EODMNHZF5` (INS) |
| Bootloader | NHZF5-based custom chain, v28 running; ordinary power-on selects recovery |
| Bootloader revision / rollback | 18 / `rp=23` |
| Fuse | project key, ST2 index `0x3e96f623` |
| Verified boot | `verifiedbootstate=orange`, `other.locked=1` |
| Usable slot | `recovery`; the `boot` slot aborts at the DT stage |
| Kernel | `5.4.302-g34237952ad8c-dirty`, built 2026-10-27 |
| Linux root | Debian 13.7 trixie on `userdata` (unencrypted f2fs) |
| Container runtime | Docker 29.9.2, containerd snapshotter, overlayfs |
| Server image | `FLASH_r9s_server_v9.tar` |
| Network | USB Ethernet, DHCP; address reserved by MAC on the router |
| GPU | `mali_kbase` loaded, `/dev/mali0` present, no userspace/DRM stack |

The device serial, Chip ID/DID, and MAC are deliberately omitted.

## Proven

- v28 boots recovery on ordinary power-on.
- Recovery slot boots the rebuilt kernel and module set.
- Debian root starts via the `switch_root`-style entry; `unshare(CLONE_NEWUSER)`
  succeeds and a container's `..` cannot reach the host.
- Docker runs containers; `docker export` contains no host paths.
- SSH, Docker, Hermes, Hawser, Seerr, Prowlarr, and Camoufox have run on the
  device.
- The charge guard and network watcher work across replugs.
- Kernel and modules are a matched pair with matching vermagic.

## Not yet

- The `boot` slot still fails at the DT stage.
- OrangeFox userspace with the same kernel is not finished.
- systemd as PID 1 inside the namespace is untested.
- The USB-C hub host-mode / adb coexistence is incomplete.
- The GPU has a kernel driver but no usable userspace.
- A 5.4 backport for CVE-2026-98432 is not applied (5.4 is EOL upstream).

## Last verified

2026-11-24 for v28 (ordinary power-on enters recovery); 2026-11-18 for the
server image, kernel, Docker, and the cpuset-cap workaround. See
[versions](reference/versions.md) and [checksums](reference/checksums.md) for
the exact build and hash record.
