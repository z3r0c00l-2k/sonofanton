# Operations

## 6. Linux side

**Storage** — `userdata` reformatted unencrypted f2fs (105 GB). No SD card is
involved or assumed.

**Roots**

```
/data/linux                    Alpine 3.24 (bootstrap environment, 8.6 MB + packages)
/data/linux/data/debian        Debian 13.7 trixie (target rootfs, upgraded from 12.15;
                               bookworm rollback copy at /data/linux/data/debian_bookworm_backup)
/data/linux/data/podman        podman storage
```

**Network** — two different paths, because the USB-C port is one role at a time.

*Hub attached (normal operation).* The port becomes a USB host, adb disappears,
and a USB Ethernet adapter appears as `eth0`. `/system/bin/net-watch` waits for
that device, configures it and keeps it configured across replugs:

```
ADDR=192.0.2.10/24      static address; delete the file for DHCP
GW=192.0.2.1
DNS=192.0.2.1
```

in `/data/linux/net.conf` (read, not sourced, applied on the next plug or boot,
so changing the address needs no rebuild). The `192.0.2.0/24` block is the
documentation range; use your own subnet. With no file, `net-watch` runs
`dhclient`, so the address can be pinned by MAC on the router instead. Anything
else on the port — charging, adb, the proxy below — means the phone is a device
again and `eth0` is gone.

*Cable attached (development).* Package traffic goes `adb reverse tcp:3128` to a
userspace HTTP/CONNECT proxy on the host (`tools/adbproxy.py`).

**Clock and timezone** — the RTC reads 2020-01-01 on a cold boot and the root has
no time daemon, so every TLS client and apt refuse to work. `net-watch` sets the
clock once per link-up (`chronyd -q` against `pool.ntp.org`, then `hwclock -w`),
which is also the only step that makes the timestamp useful inside the recovery
log. The root's `/etc/localtime` points at `Asia/Kolkata`.

**The launcher** — containers need a real root, not a chroot. Measured:

```
chroot          crun/runc -> pivot_root: Invalid argument
pivot_root      container runs, bridge address assigned, gateway reachable
```

`tools/pivot_root.c` (static, built on device with Alpine gcc) implements it.
Three mechanics had to be discovered:

1. the recovery's `/` is `rootfs`, which cannot be `pivot_root`ed at all — the
   helper uses `switch_root` semantics instead: bind the target, `mount --move`
   it onto `/`, then `chroot`;
2. Android marks the tree `shared` — make it `MS_PRIVATE|MS_REC` first;
3. the target root must itself be a mount point — the helper binds it now.

The move matters for more than tidiness. The older bind+`chroot`+`pivot_root`
form attaches the new root at the bind mountpoint (`/.pivotbind`), not at `/`,
so the process stays "chrooted" relative to the mount namespace root. The
kernel's `create_user_ns()` then refuses with `EPERM` (no user namespaces, so no
`userns-remap`), and `..` can cross the mount stack into the host. Attaching the
root at the namespace root mountpoint fixes both: `unshare(CLONE_NEWUSER)` works
and `/etc/..` resolves to `/`.

Invocation:

```
unshare --mount --fork /data/linux/tmp/pivot_root <ROOT> /usr/bin/env -i ... /bin/sh
```

There is deliberately **no PID namespace**: Docker's `userns-remap` needs to create
user namespaces, and runc's `nsexec` is refused when the daemon runs inside a
nested PID namespace. Containers still get their own PID namespace from runc.

**Containers** — both runtimes work:

| runtime | notes |
| --- | --- |
| podman 5.8.9 | works without extra setup; `--cgroup-manager cgroupfs` |
| docker 29.9.2 | needs a **v1 `devices` cgroup** — kernel 5.4 has no device controller in cgroup v2 (5.15+). Hybrid: v2 for cpuset/cpu/io/memory/pids, v1 `devices` alongside; iptables must be switched to `iptables-legacy` (`CONFIG_NFT_NAT` is off, so nft NAT chains do not exist) |

**Docker at boot.** `linux-launch` starts it inside the mount namespace, before
it execs `sshd`, because the `devices` cgroup must be mounted after the pivot.
The boot entry:

1. stacks a private procfs on `/proc` (the mount namespace gets its own view);
2. mounts the hybrid v1 `devices` cgroup;
3. starts `dockerd --data-root=/var/lib/docker`, log at `/var/log/dockerd.log`.

There is no init system in the root: `systemctl` detects the chroot and ignores
every command. To start it by hand after killing it, repeat the same steps:

```bash
mount -t proc proc /proc
mkdir -p /sys/fs/cgroup/devices
mount -t cgroup -o devices devices /sys/fs/cgroup/devices
dockerd --data-root=/var/lib/docker > /var/log/dockerd.log 2>&1 &
```

Two failure modes were found in practice. `/run` is on `userdata`, so a previous
boot's `docker.pid` survives and can name a live low PID in the new namespace;
the launcher removes `docker.pid` and `containerd.pid` first. And because there
is no PID namespace, killing sshd no longer tears down the daemon:
`r9s-server stop` stops `dockerd` first (which stops its containers) and then
sshd.

**Resource limits.** CPU and RAM are uncapped by the container stack — 8 cores
online with no `cpu.max`, `memory.max = max`, `io.max` empty, `pids.max = max`
— but four defaults had to be raised for a server workload:

| limit | stock | now | where |
| --- | --- | --- | --- |
| cpuset groups | 20 per boot (vendor `CS_CGROUP_COUNT`; the counter is never decremented) | no per-boot ceiling (vendor counter and write-only `requested_cs[]` table removed) | `patches/lineage-tree/0012-kernel-cpuset-drop-group-cap.patch` |
| open files | 1024 soft / 4096 hard, inherited by sshd and dockerd | 1M, also passed as dockerd's `--default-ulimit` | launcher |
| inotify | 128 instances / 8192 watches | 1024 / 1048576 | launcher sysctls |
| swap | none | 3 GiB zram, lz4, `swappiness=100`, `page-cluster=0` | launcher |

The cpuset ceiling is the one that looked like a Docker bug: BuildKit failed
with `mkdir /sys/fs/cgroup/docker/buildkit: cannot allocate memory` once 20
cgroups had been created in a boot. Raising the cap only moved the wall:
`requested_cs[]` is write-only and `cs_count` only ever increases, so `0012`
deletes both and the limit with them. Upstream cpuset has no per-boot cap.

The launcher also tries to remove `cpuset` from the Docker subtree's
`cgroup.subtree_control`. That write runs before dockerd populates the
subtree's controllers, so cpuset is back on at runtime; it is best-effort, not
the fix. To unblock a boot that has already exhausted the counter without
rebooting:

```bash
echo -cpuset > /sys/fs/cgroup/docker/cgroup.subtree_control
```

Child cgroups then stop consuming cpuset slots and existing containers keep
running. A reboot still resets the counter.

zram is built into this kernel but ships no `/dev/zram0` node; the launcher
creates it, sizes the device and enables swap. Compressed swap costs ~1–1.5 GiB
of real RAM at 3 GiB and avoids flash wear; `vm.swappiness=100` is the zram
policy, not a spinning-disk one.

Still unchanged, deliberately: `cgroup_disable=pressure` (no PSI metrics) and
`cgroup.memory=nokmem` (kernel memory not accounted); neither caps a container.

**Isolation.** The Linux root is entered `switch_root`-style (bind,
`mount --move` onto `/`, `chroot`), so a container's `..` clamps at its own root
and `docker export` contains only the container's files. `userns-remap` is *not*
usable on this 5.4 kernel: a container in a user namespace cannot mount or bind
the cgroup2 filesystem (`EPERM`/`EINVAL`), a capability that arrived in later
kernels. Isolation here comes from the root entry, not from UID mapping.

When a stack bind-mounts its data directory (Hermes does: `/opt/appdata/hermes`
→ `/opt/data`), that directory must stay owned by the image's runtime user —
**10000:10000 (`hermes`)** for the Hermes image — because s6 starts as root and
drops to that user. Changing it (for example while trying userns-remap) produces
`install state is not writable` and permission denied on `facts.json`/backups.

---

## 7. Tools

| tool | purpose |
| --- | --- |
| `tools/recovery_img.py` | split / rebuild / inspect header-v2 images |
| `tools/repack.py` | replace kernel + modules, sign, self-verify |
| `tools/ramdisk.py` | cpio newc list/extract/pack, ownership preserving |
| `tools/package_odin.sh` | ustar + md5 footer, deterministic hash |
| `tools/build-recovery.sh` | build → inject → sign → verify → package in one step |
| `tools/prepare-tree.sh` | clone/pin the Samsung projects, fix the HAL layout, apply `patches/lineage-tree` |
| `tools/build-kernel.sh` | pinned toolchain, delta merge, config gate, build |
| `tools/verify_kernel.py` | config delta + single vermagic, host-side |
| `tools/check_cfi_jt.py` | verifies every module exports `__cfi_check` |
| `tools/baseline_manifest.py` | writes `baseline/manifest.txt` |
| `tools/verify_on_device.sh` | the on-device gate (namespaces, config, modules, overlay, CFI, GUI) |
| `tools/fetch_crashlog.sh` | pulls pstore + recovery logs from the last failing boot |
| `../third_party/avbtool/avbtool.py`, `keys/testkey_rsa4096.pem` | AVB signing; the test key is public AOSP material, not shipped |
| `tools/pivot_root.c` | real-root helper |
| `tools/device/net-watch` | waits for the hub's `eth0`, applies the static or DHCP config, sets the clock, survives replugs |
| `tools/device/check_storage.sh` | starts dockerd and reports the storage driver, backing filesystem, and cgroup mode |
| `tools/device/test_docker.sh` | selects iptables-legacy, starts dockerd, and runs an Alpine probe container |
| `tools/make_logo.py` | redraws `assets/logo_sonofanton.png` (768×480, same palette as the stock wordmark); the build injects the committed PNG, so Pillow is not a build dependency |
| `tools/ssh-r9s.sh` | adb-forward SSH while the phone is a USB device |

---

## 8. Runbook

**Fetch prerequisites** (nothing heavy is committed)

```bash
# sources
git clone --depth 1 -b lineage-23.2 https://github.com/exy2100/android_kernel_samsung_universal2100.git sources/kernel-samsung-universal2100
git clone --depth 1 -b lineage-23.2 https://github.com/Daubfy/android_device_samsung_r9s.git sources/device-samsung-r9s
git clone --depth 1 -b lineage-23.2 https://github.com/exy2100/android_device_samsung_universal2100-common.git sources/device-samsung-universal2100-common

# signing key (AOSP public test key, the one the LOS build used)
mkdir -p keys
curl -fsSL "https://android.googlesource.com/platform/external/avb/+/refs/heads/main/test/data/testkey_rsa4096.pem?format=TEXT" | base64 -d > keys/testkey_rsa4096.pem

# baseline payloads, from the workspace's untouched recovery tarball
tar -xf ../recovery/LOS_recovery.tar -C /tmp && mv /tmp/recovery.img baseline/LOS_recovery.img
python3 tools/recovery_img.py split baseline/LOS_recovery.img baseline
python3 tools/baseline_manifest.py
```

**Build**

The complete source-built flow — fresh sync, tree preparation, build, injection,
signing, flashing and on-device verification — is in [build.md](build.md). The
header logo spec (canvas, RGB-only decoder rules, palette, safe area) is in
[logo.md](logo.md). Short form (run from `linux/`):

```bash
tools/prepare-tree.sh
tools/build-recovery.sh server_vN
```

```bash
TOOLCHAIN=$PWD/toolchains/LLVM-21.1.0-Linux-X64 JOBS=6 tools/build-kernel.sh
python3 tools/verify_kernel.py
python3 tools/check_cfi_jt.py                     # see section 4
```

**Repack and sign**

```bash
python3 tools/repack.py --baseline baseline --build build \
  --kernel build/arch/arm64/boot/Image \
  --out out/RECOVERY_r9s_kernel_vN.img --sign
tools/package_odin.sh out/RECOVERY_r9s_kernel_vN.img out/RECOVERY_r9s_kernel_vN.tar
```

**Source-built recovery with the server page** — the LineageOS build produces
the UI but not the launcher: injection, signing and packaging are post-build
steps into the packed ramdisk. `tools/build-recovery.sh` runs the whole chain
and refuses to package an image whose ramdisk is missing a piece (launcher
files, init service, `ro.adb.secure.recovery=0`, module/vermagic agreement).

```bash
# the working copy carries two changes a fresh sync would not have
git -C /mnt/GGG/BuildGround/lineage/kernel/samsung/universal2100 apply \
    patches/lineage-tree/0001-kernel-r9s-config-namespaces.patch
git -C /mnt/GGG/BuildGround/lineage/bootable/recovery apply \
    patches/lineage-tree/0002-recovery-server-menu.patch

tools/build-recovery.sh server_vN              # build, inject, sign, package
tools/build-recovery.sh --no-build server_vN   # package what is already built
```

Output is `out/RECOVERY_r9s_<tag>.img/.tar/.tar.md5` plus `out/FLASH_r9s_<tag>.tar`
(plain tar, the form Odin accepts on this device), with hashes appended to
`out/SHA256SUMS`. Rebuilding the same sources yields a byte-identical image:
injected cpio entries carry mtime 0 and the gzip header is fixed.

**Flash** — AP slot, recovery only, battery above floor, then **cold boot**
(a warm reboot can latch the previous boot mode).

**Rollback** — `out/ROLLBACK_LOS_recovery.tar.md5` is the untouched working
image. The `boot` slot and the bootloader are never modified.

**On device**

```bash
tools/verify_on_device.sh          # kernel gate
tools/fetch_crashlog.sh            # after any failed boot
```

---

