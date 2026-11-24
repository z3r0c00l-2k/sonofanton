# Building the recovery image

> Third-party tools and authors: [CREDITS](../../CREDITS.md).

End-to-end instructions for producing the flashable image this project runs:
LineageOS 23.2 recovery UI with the **Server** page, plus the launcher that boots
Debian from `userdata` inside its own PID and mount namespace.

Nothing here touches `boot`, the bootloader, or `keys/`. The output is one
signed `recovery.img`, packaged as a plain tar for Odin.

- [1. What the build produces](#1-what-the-build-produces)
- [2. Host](#2-host)
- [3. LineageOS tree](#3-lineageos-tree)
- [4. Samsung projects and local patches](#4-samsung-projects-and-local-patches)
- [5. Build and package](#5-build-and-package)
- [6. What injection changes](#6-what-injection-changes)
- [7. Kernel configuration](#7-kernel-configuration)
- [8. Flash and roll back](#8-flash-and-roll-back)
- [9. Verify on the device](#9-verify-on-the-device)
- [10. Failures seen in practice](#10-failures-seen-in-practice)

---

## 1. What the build produces

`m recoveryimage` builds a recovery image only — no system image, no `boot.img`.
For r9s that target compiles, in one ninja graph:

| component | source |
| --- | --- |
| kernel `Image` | `kernel/samsung/universal2100`, config chain below |
| 271 kernel modules | same tree, shipped in the recovery ramdisk |
| recovery binary + UI | `bootable/recovery` (with this project's Server page) |
| ramdisk, `recovery_dtbo`, `dtb` | device tree `device/samsung/r9s` |

The build's own `out/target/product/r9s/recovery.img` is **not** flashable as-is:
it has no launcher, no server helper, no `ro.adb.secure.recovery=0`, and no AVB
signature for this device. Those are added afterwards by
`tools/build-recovery.sh`.

Final artifacts, all under `out/`:

| file | use |
| --- | --- |
| `out/RECOVERY_r9s_<tag>.img` | signed, 64 MiB, AVB verified |
| `out/FLASH_r9s_<tag>.tar` | what Odin gets (plain ustar, no md5 footer) |
| `out/RECOVERY_r9s_<tag>.tar.md5` | same tar with an md5 footer for other tools |
| `out/SHA256SUMS` | one line per artifact, appended per build |

## 2. Host

Measured on the machine this project was built on:

| | |
| --- | --- |
| CPU | AMD Ryzen 7 5700, 16 threads |
| RAM | 15 GiB, plus 15.5 GiB zram and 32 GiB swap |
| Disk | 293 GiB free under `/mnt/GGG`; `out/` of the tree grows to ~23 GiB |
| OS / tools | CachyOS (Arch), Python 3.14, git 2.56 |
| Missing prerequisite | `repo` — install it (`pacman -S repo` or the platform-tools package) before a fresh sync |

Build times seen: **26:29** for the first full build, then 14:47 and 08:32 for
incremental runs at `-j8` after touching recovery UI sources and the kernel
config. `-j8` has been reliable; `soong_build` peaks near 10 GiB, so higher job
counts risk the OOM killer on a 15 GiB host.

## 3. LineageOS tree

```bash
mkdir -p /mnt/GGG/BuildGround/lineage && cd /mnt/GGG/BuildGround/lineage
repo init -u https://github.com/LineageOS/android.git -b lineage-23.2
repo sync -j8 -c --no-clone-bundle
```

The tree this project builds on has 1164 projects and a manifest at
`9776e518` (2026-10-20). Sync state lives in `.repo/`, so `repo` must be
available; it is not needed for the build itself, only for syncing.

## 4. Samsung projects and local patches

The manifest carries only `hardware/samsung/nfc` from that family — not the
`hardware/samsung` umbrella, the device trees, the kernel or the vendor blobs.
The exynos HAL additionally arrives as eight split repositories that must sit
*inside* `hardware/samsung_slsi-linaro`; the umbrella clone leaves the nested
`nfc` project alone.

```bash
tools/prepare-tree.sh            # clone, pin, lay out, patch
tools/prepare-tree.sh --verify   # report state, change nothing
```

What it does, in order:

1. **Pins 15 repositories.** Seven top-level: `device/samsung/r9s`,
   `device/samsung/universal2100-common`, `vendor/samsung/r9s`,
   `vendor/samsung/universal2100-common`, `kernel/samsung/universal2100`,
   `hardware/samsung`, `hardware/samsung_slsi-linaro`. Eight inside the last
   one: `codec2 config exynos exynos5 graphics interfaces openmax sgpu`.
   Exact URLs and commit hashes are in the script; clones are reused when
   present, then checked out to the pinned commit.
2. **Removes the umbrella checkout's duplicate directories.** The umbrella repo
   at `031b49f` ships the same files flat (`tee/`, `gralloc/`, `enn_driver/`,
   …) that the split repositories provide nested. Verified identical, e.g.
   `tee/Android.bp` in the umbrella is byte-for-byte `exynos/tee/Android.bp`.
   Keeping both makes Soong define the same modules twice. The rule is explicit:
   keep `.gitignore Android.bp NOTICE epic include libsbwcdecomp ssp` plus the
   eight split repos, delete the other 44 top-level directories.
3. **Applies eleven patches** from `patches/lineage-tree/`:

   | patch | repository | purpose |
   | --- | --- | --- |
   | `0001-kernel-r9s-config-namespaces.patch` | `kernel/samsung/universal2100` | `PID/IPC/USER` namespaces, cgroup and netfilter options for the launcher and Docker |
   | `0002-recovery-server-menu.patch` | `bootable/recovery` | Server menu, submenu, `RunServerCommand()` |
   | `0003-external-skia-vendor-available.patch` | `external/skia` | `vendor_available` on `libskia_skcms` |
   | `0004-external-highway-vendor-available.patch` | `external/google-highway` | `vendor_available` on `libhwy` |
   | `0005-external-xmp-vendor-available.patch` | `external/XMP-Toolkit-SDK` | `vendor_available` on `xmp_toolkit_sdk` and `zuid_md5` |
   | `0006-universal2100-common-drop-epic-hal.patch` | `device/samsung/universal2100-common` | drops the EPIC HAL that has no source in this tree |
   | `0007-hardware-samsung-disable-lineage-health.patch` | `hardware/samsung` | disables the lineage health AIDL that does not compile here |
   | `0008-hardware-samsung_slsi-linaro-reduce-android-bp.patch` | `hardware/samsung_slsi-linaro` | reduces `Android.bp` to the namespace root plus `subdirs` |
   | `0009-recovery-screen-timeout.patch` | `bootable/recovery` | 30 s idle blank via the DRM CRTC, wake on touch/key |
   | `0010-recovery-status-row.patch` | `bootable/recovery` | Ethernet link and charge state beside the battery |
   | `0011-kernel-cpuset-group-cap.patch` | `kernel/samsung/universal2100` | raises the vendor cpuset-group cap 20 → 256; without it a Docker host runs out of cgroups and BuildKit fails with `ENOMEM` on `mkdir` |
   | `0012-kernel-cpuset-drop-group-cap.patch` | `kernel/samsung/universal2100` | removes the vendor counter and write-only `requested_cs[]` table outright, so cgroup creation has no per-boot ceiling |

All twelve are idempotent: the script reverse-checks before applying, so running
it twice is safe. `--verify` exits non-zero if any pin, directory or patch
drifted.

## 5. Build and package

```bash
tools/build-recovery.sh server_v5              # build, inject, sign, package
tools/build-recovery.sh --no-build server_v5   # package the existing build
```

The manual equivalent, if you want to see each step:

```bash
cd /mnt/GGG/BuildGround/lineage
source build/envsetup.sh
lunch lineage_r9s-trunk_staging-userdebug
m -j8 recoveryimage

python3 tools/recovery_img.py split out/target/product/r9s/recovery.img /tmp/w
python3 tools/make_launcher_ramdisk.py --ramdisk /tmp/w/parts/ramdisk --out /tmp/w/ramdisk.gz
python3 tools/repack.py --baseline /tmp/w --kernel /tmp/w/parts/kernel \
    --ramdisk /tmp/w/ramdisk.gz --sign --out out/RECOVERY_r9s_server_v5.img
tools/package_odin.sh out/RECOVERY_r9s_server_v5.img out/RECOVERY_r9s_server_v5.tar
```

`repack.py` signs with the AVB parameters recovered from the LineageOS recovery
image that boots on this device: salt `7d42cb82…`, `SHA256_RSA4096`, rollback
index 1, `keys/testkey_rsa4096.pem`, and the device fingerprint property. Its
self-check recomputes the payload digest, so a wrong salt or a stale vbmeta is
caught on the host, not on the phone.

The script refuses to package if the ramdisk is missing any piece: the five
launcher files executable, the project logo byte-identical to
`assets/logo_sonofanton.png`, `pgrep -x sshd` in the helper,
`ro.adb.secure.recovery=0`, the `r9slinux` service, module/`modules.load`
agreement, and every module's vermagic against the kernel release.

Builds are reproducible: injected cpio entries carry mtime 0 and the gzip header
is fixed, so rebuilding the same sources yields a byte-identical image.

`--no-build` only repackages `out/target/product/r9s/recovery.img` — it cannot
pick up a change to recovery's own source. Anything under `bootable/recovery`
(the menus in `recovery_ui/device.cpp`, the idle timeout in `recovery_ui/ui.cpp`,
the DRM blank in `minui/graphics_drm.cpp`) needs the `m … recoveryimage` step
first; only the injected files under `tools/device/` are repackaged directly.

Verify a finished image from scratch — the tool resolves the partition by the
descriptor's name, so the file has to be called `recovery.img` in its own
directory:

```bash
mkdir -p /tmp/avb && cp out/RECOVERY_r9s_server_v5.img /tmp/avb/recovery.img
python3 ../third_party/avbtool/avbtool.py verify_image --image /tmp/avb/recovery.img \
    --key keys/testkey_rsa4096.pem
```

`keys/testkey_rsa4096.pem` is the public AOSP test key, not shipped here. Take
it from `external/avb/test/data/` in an AOSP checkout, or pass your own key.

## 6. What injection changes

`tools/make_launcher_ramdisk.py` writes into the **first** cpio archive, before
`TRAILER!!!` (an earlier version appended a second archive that the kernel
unpacked but no tool could see):

| entry | role |
| --- | --- |
| `/system/bin/pivot_root` | static helper that enters the Debian root `switch_root`-style: bind, `mount --move` onto `/`, `chroot` (no `pivot_root`, so user namespaces work) |
| `/system/bin/linux-launch` | mounts `userdata`, starts the guard and the network watcher, enters `unshare --mount` (no PID namespace: Docker's userns-remap needs to create user namespaces), stacks a private procfs, starts `dockerd` if present, execs `sshd -D -e` |
| `/system/bin/charge-guard` | holds charging at the 80% ceiling, releases at 75% |
| `/system/bin/net-watch` | waits for the hub's `eth0`, applies `/data/linux/net.conf` (static) or DHCP, sets the clock from NTP and writes it to the RTC |
| `/system/bin/r9s-server` | `status`, `start`, `stop`, `logs` — used by the UI and by hand |
| `res/images/logo_image*.png` | project branding; the menu header is a 768×480 bitmap, not a string, so `assets/logo_sonofanton.png` replaces both the normal and the `dynamic_partitions` variant |
| `init.recovery.exynos2100.rc` | `service r9slinux …` and `on late-init start r9slinux` |
| `prop.default` | `ro.adb.secure.recovery=0`, so adb works without pressing *Enable ADB* |

The **Debian root is not in the image** — it lives on `userdata`, so injecting a
new ramdisk never changes it. Its own provisioning is separate and survives a
flash:

```bash
# clock: one .deb, every dependency already present
adb push chrony_4.3-2+deb12u3_arm64.deb /tmp/
chroot /data/linux/data/debian dpkg -i /tmp/chrony_4.3-2+deb12u3_arm64.deb

# timezone
ln -sf /usr/share/zoneinfo/Asia/Kolkata /data/linux/data/debian/etc/localtime
echo Asia/Kolkata > /data/linux/data/debian/etc/timezone
```

The root is now **trixie 13.7** (upgraded in place from 12.15 on 2026-10-26 with a
full copy kept at `/data/linux/data/debian_bookworm_backup`); trixie's chrony is
4.6.1 and comes from the Debian suite, so the manual `.deb` push above applies
only to a bookworm-era root.

`net-watch` uses `chronyd -q` (one-shot, nothing stays running) because the root
has no init and therefore no time daemon.

Docker is optional and needs no provisioning beyond its own package: if
`/usr/bin/dockerd` exists, the launcher starts it at boot inside the namespace
(fresh procfs, hybrid v1 `devices` cgroup, `--data-root=/var/lib/docker`) and
logs to `/var/log/dockerd.log`. A root without it boots normally. iptables must
stay on the legacy variant, which the provisioned root already is
(`iptables --version` prints `(legacy)`).

## 7. Kernel configuration

The device tree drives the kernel build:

```
TARGET_KERNEL_CONFIG := gki_defconfig samsung/exynos2100.config samsung/r9s.config
TARGET_KERNEL_SOURCE := kernel/samsung/universal2100
```

The project's container delta lives in `samsung/r9s.config` (patch 0001), not in
the device tree, so it applies to every build of this kernel. `CONFIG_CFI_PERMISSIVE`
is deliberately absent: enforcing CFI is proven on this device.

Confirm what the built kernel actually contains, not just what the config said
(from the tree root):

```bash
kernel/samsung/universal2100/scripts/extract-ikconfig \
    out/target/product/r9s/obj/KERNEL_OBJ/arch/arm64/boot/Image | grep -E "CONFIG_(PID|IPC|USER)_NS="
```

## 8. Flash and roll back

Odin, AP slot, **cold boot** afterwards — a warm reboot can latch the previous
boot mode. Keep the battery above the guard floor.

- flash: `out/FLASH_r9s_<tag>.tar`
- rollback: `out/ROLLBACK_LOS_recovery.tar.md5` (untouched working image)

Never flash a Samsung stock or OTA bootloader: this device is fused to the
project key.

## 9. Verify on the device

```bash
adb devices                                # recovery, no Enable ADB press needed
adb shell 'getprop ro.adb.secure.recovery' # 0
adb shell /system/bin/r9s-server status
tools/ssh-r9s.sh 'uname -a; cat /etc/debian_version'
```

Expected `status`: `server running (sshd pid …)`, `ssh listening on port 22`,
`charge guard running (ceiling 80%)`, battery and temperature lines, `last log`
naming the Debian root.

On the phone: **Server → Status**, **Stop server**, **Start server**,
**View server log** exercise the same helper.

## 10. Failures seen in practice

| symptom | cause | fix |
| --- | --- | --- |
| Odin: "md5 is invalid" | Odin on this device rejects the `.tar.md5` even when its footer verifies | flash the plain `.tar` |
| `unshare: Invalid argument`, server never starts | kernel built without `CONFIG_PID_NS` | patch 0001, rebuild |
| Status says `stopped` while sshd runs | toybox `pidof` matches argv[0], and OpenSSH rewrites it to `sshd: /usr/sbin/sshd …` | `pgrep -x sshd`, built into the helper |
| `adb` reports `unauthorized` after a cold boot | recovery adbd demands a host key and the image ships none | `ro.adb.secure.recovery=0` in `prop.default` |
| build stops at `hardware/samsung_slsi-linaro/config/config.mk does not exist` | split HAL repositories not cloned into the umbrella | `tools/prepare-tree.sh` |
| soong "missing variant" for `libhwy`, `libskia_skcms`, `xmp_toolkit_sdk`, `zuid_md5` | modules reachable from `vendor_available` libraries were never marked | patches 0003–0005 |
| recovery boots to the previous mode | warm reboot latched it | power off, then cold boot |

Kernel-side failures (CFI, vermagic, module load) are covered in
[Architecture §4](architecture.md#4-kernel), with `tools/check_cfi_jt.py` and
`tools/verify_kernel.py` as host-side gates.

---

Not covered here: the Debian root itself, Docker inside it, and the USB-C hub.
That work is described in [Operations](operations.md) and applies to
`userdata`, not to the recovery image.
