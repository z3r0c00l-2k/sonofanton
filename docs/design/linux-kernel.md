> Exported from the project's OpenSpec design record and sanitized for publication.

# Design

## Context

See `proposal.md` for motivation. The constraints that shape the approach:

- The recovery slot boots; the `boot` slot dies at the bootloader's DT stage. Every candidate must therefore live in `recovery`.
- The device is fused to the project key. Only images packaged for that key can run, and the custom bootloader is the only one that will ever run.
- Three recovery images exist locally with different provenance:

  | image | kernel | shipped modules | coherent |
  | --- | --- | --- | --- |
  | LOS | `5.4.302-g51d63cf4924c` | `5.4.302-g51d63cf4924c` | yes |
  | TWRP 3.6.1 | `5.4.129-afaneh92-…` | `5.4.129-23339874-abG990EXXS1BVB8` | no |
  | OrangeFox R11.3 | same as TWRP | same as TWRP | no |

- The kernel configuration that boots today is recoverable from the Image itself (`IKCFG_ST`…`IKCFG_ED`), 7,600 lines.
- Container-primitive options absent from that config: `PID_NS`, `IPC_NS`, `USER_NS`, `CGROUP_DEVICE`, `CGROUP_PIDS`, `BRIDGE_NETFILTER`, `NETFILTER_XT_MATCH_ADDRTYPE`, `NFT`, `NFT_COMPAT`, `MACVLAN`, `POSIX_MQUEUE`, `TMPFS_XATTR`.
- Sources are public: kernel `exy2100/android_kernel_samsung_universal2100` (`lineage-23.2`, 5.4.302, HEAD `34237952`), device tree `Daubfy/android_device_samsung_r9s`, common tree `exy2100/android_device_samsung_universal2100-common`. The OrangeFox trees are prebuilt-kernel trees and never compile a kernel.
- Build host: 16 threads, 15 GB RAM, 70 GB free after cloning. A kernel-only build fits; an AOSP build does not.

## Goals / Non-Goals

**Goals**

- Produce one kernel + module artifact that is internally consistent and boots on this device.
- Make the repack pipeline auditable: every byte change explained.
- Keep the GUI and the headless Linux service on the same slot without either degrading the other.
- Make the USB-C hub a first-class console and network path.

**Non-Goals**

- Making Android boot again.
- Rebuilding the TWRP/OrangeFox GUI from source; this change repacks their ramdisk, it does not fork it.
- GPU, camera, modem, NPU or sensor functionality.
- Moving off the 5.4 series.
- Wi-Fi configuration (BCM4375 over PCIe is present; it stays a fallback, not this change's deliverable).

## Decisions

### D1 — Kernel source and configuration base

Build from `exy2100/android_kernel_samsung_universal2100` at `lineage-23.2`, using the **configuration extracted from the booting Image** as the base, plus the delta.

*Why:* the extracted config is empirical — it is the exact set of options that produced a kernel this device boots. The tree's fragment chain (`gki_defconfig` + `samsung/exynos2100.config` + `samsung/r9s.config`) is the reproducible recipe, but re-merging it can silently change hundreds of unrelated options and adds variables to a boot experiment.

*Alternative rejected:* build from the fragments only. Cleaner provenance, worse determinism against the image that works.

*Recorded caveat:* the running build's SHA (`51d63cf4924c`) is not in the public tree; HEAD is `34237952`, built the same day. `make olddefconfig` reconciles any option the public tree no longer carries.

### D2 — Delta as its own fragment

The container/USB delta goes into a new fragment, `arch/arm64/configs/samsung/docker.config`, merged after `r9s.config`, rather than editing `r9s.config`.

*Why:* `r9s.config` is upstream device truth; a separate file is auditable, re-appliable against a future tree, and easy to diff when something regresses.

```ini
# container + userspace delta
CONFIG_PID_NS=y
CONFIG_IPC_NS=y
CONFIG_USER_NS=y
CONFIG_CGROUP_DEVICE=y
CONFIG_CGROUP_PIDS=y
CONFIG_BRIDGE_NETFILTER=y
CONFIG_NETFILTER_XT_MATCH_ADDRTYPE=y
CONFIG_NFT=y
CONFIG_NFT_COMPAT=y
CONFIG_MACVLAN=y
CONFIG_POSIX_MQUEUE=y
CONFIG_TMPFS_XATTR=y
```

### D3 — Recovery remains the only OS slot

Candidates are written to `recovery` and nothing else. The `boot` slot stays as it is.

*Why:* the DT-stage failure is unresolved and orthogonal to this project. Using the slot that provably boots keeps every experiment recoverable.

### D4 — Kernel travels; GUI is a ramdisk property

Sequence: rebuild the LOS image (proven container, minimal GUI) → verify the kernel there → then put the *same* Image and module set into the OrangeFox ramdisk.

*Why:* the OrangeFox ramdisk is the desired GUI, but its shipped pairing is broken. The kernel is portable between the two because both are header-v2 images with the same base/offsets; what binds a ramdisk to a kernel is the module set and the init scripts, not the GUI binary.

*Alternative rejected:* fork and build OrangeFox from source. Correct long-term, but it needs an AOSP tree the host cannot currently hold, and it is not required to answer the kernel question.

### D5 — Modules are replaced wholesale

Every `.ko` in the candidate ramdisk comes from the new build; `modules.load.recovery` is regenerated from the build output; `modules.dep` likewise.

*Why:* vermagic is exact-match. A partial replacement is the failure mode already present in the OrangeFox image.

### D6 — The DT payload is copied, never rebuilt

The DT/DTBO tail of the booting LOS image is carried into every candidate byte-for-byte. DTS rebuilds happen only if a boot failure is provably in the DT.

*Why:* the bootloader validates DT length and magic early and aborts with a generic message. A rebuilt DTB is a new variable in a path that currently works.

### D7 — Storage: userdata reformatted, unencrypted

`userdata` becomes plain f2fs owned by the Linux side; the rootfs lives on it; `/sdcard` is `/data/media`. No loop image, no second partition.

*Why:* the user has retired Android, so FBE protects nothing that still matters. f2fs is xattr-capable, so overlay2 can sit directly on it — the loop-image workaround was only needed because the recovery ramfs lacks xattrs.

*Alternatives considered:* keep FBE and port `vold` + Keymaster (months, TEE-dependent, no payoff without Android); microSD as root (possible later, slower, and its presence is unverified).

### D8 — Linux userspace: a Debian root with a **real root**, beside the GUI

The Linux root runs in its own PID + mount namespace, obtained with `pivot_root` — not a chroot, and never `switch_root` against the recovery tree. A oneshot init service launches it; systemd runs as init inside that namespace.

*Why a real root:* a chroot is not a root for a container runtime. Demonstrated on device: with the Alpine root chrooted, crun and runc both died at `pivot_root: Invalid argument`; with the pivot_root launcher the same image ran with an address on the container bridge and reached the gateway in 1.1 ms. This is the plan's core insight and it is now the architecture.

*Why not `switch_root`:* busybox `switch_root` deletes the old root, and mount namespaces share the underlying filesystem — running it on the live recovery wiped the recovery's ramfs (`/init` and `/system/bin/sh` disappeared; a cold boot restored it, and userdata survived). `pivot_root` moves the root with no deletion and is per-namespace, so the recovery GUI keeps its own root while the Linux side gets a real one.

*Two mechanics discovered on device:* the recovery's `/` is `rootfs`, which cannot be `pivot_root`ed at all (EINVAL) — the helper binds rootfs elsewhere and chroots into the bind first; and Android marks the whole tree `shared`, so the helper makes it `MS_PRIVATE|MS_REC` first.

*Why Debian (user choice):* familiar tooling, official Docker repo, glibc. The cost is systemd inside a namespace rather than as the sole init, which carries container-semantics caveats; Alpine + OpenRC was proven and is the lower-risk fallback if systemd argues with the namespace.

*Rejected:* the "tiny initramfs replaces the recovery ramdisk" model — it fits a device that boots `boot.img`, and this one does not; it would also discard the GUI.

**Charge gating (measured):** writing 0 to `charging_enabled` moves the pack to Discharging (-142 mA) and 1 resumes it, so that node is the controllable gate. `batt_swelling_control=1` is Samsung's protect-battery mode: it lowers the recharge/termination target (swelling_*_rechg_voltage in sec_battery), a soft cap, not an instant cut - at 85% with the flag set, charging continued. It is set as a gentle backstop; the hard gate is `charging_enabled`, which is the node that was measured. No persistent hardware cap exists, so protection depends on the launcher setting the flag and starting the daemon each boot. Guard: ceiling 80, floor 75, 60 s poll, hysteresis; fails safe (charging on) when the node is unreadable.

**systemd (4.7) did not come up (first attempt):** started as PID 1 in the namespace it printed only `SELinux: Could not open policy file ... policy.33` and exited. The launcher therefore still execs sshd directly; systemd needs the SELinux policy path or a permissive configuration before it is usable here.

**cgroup detail (found on device):** kernel 5.4 has no device controller in cgroup v2 - that arrived in 5.15. Docker's v2 path therefore fails with 'Devices cgroup isn't mounted'. A hybrid works: keep the unified hierarchy for cpuset/cpu/io/memory/pids and mount a v1 `devices` hierarchy alongside it; dockerd then runs with the cgroupfs driver (Cgroup Version 1) and Storage Driver overlayfs. Podman needed none of this and ran without the v1 mount.

**Rootfs location:** `userdata` (105 GB, f2fs, unencrypted, already formatted and in use) — not an SD card. The plan's SD-first advice assumes removable media this device may not have; userdata is proven, larger, and needs no extra hardware. f2fs is xattr-capable, so overlay2 works directly on it.

### D9 — Container runtime: dockerd, overlay2, bridge

`dockerd` with `overlay2` on the f2fs root, `iptables` present, `--iptables=true` once `BRIDGE_NETFILTER` and `addrtype` are compiled in.

*Why:* the ask is Docker, and the kernel delta makes the standard path work instead of the `--network=host` workaround.

*Fallback:* podman with the same storage driver if dockerd trips on a recovery-environment assumption (no systemd, cgroup v1/v2 detection).

### D10 — adb: USB in device role, TCP in host role

`adbd` listens on USB when the port is a device; when the hub forces host mode, `service.adb.tcp.port` makes it reachable over Ethernet.

*Why:* one port, one role. USB adb and a hub are mutually exclusive at the hardware level.

### D11 — Charge guard in userspace

A small daemon reads `capacity` and gates charging at the configured ceiling/floor through the charger's control node.

*Why:* reversible, adjustable, and avoids a kernel patch for a policy that will be tuned. The exact node that actually gates charging (`batt_swelling_control`, the charger's input suspend, or the direct-charger path) is determined on the device, not assumed.

### D12 — Toolchain: the recorded prebuilt clang first

Try the clang revision from the build string (`r563880`, clang 21.0.0) before any other.

*Why:* the build string records it, and a matched toolchain removes one unknown from a kernel that must boot. If unobtainable, fall back to the closest available clang with `LLVM=1` and accept the risk, verified by the same boot gate.

## Risks / Trade-offs

| risk | mitigation |
| --- | --- |
| Toolchain mismatch produces a kernel that builds but does not boot | try the recorded clang first; keep the working LOS image for rollback; boot gate before any GUI work |
| Public HEAD differs from the running build | config comes from the Image; `olddefconfig`; verify drivers and boot, not provenance |
| OrangeFox ramdisk may assume props or a kernel behaviour its own kernel provided | swap only after the LOS candidate passes; keep the stock LOS image as rollback; test touch, adb, storage |
| adb over TCP may not be supported by the LOS adbd | verify early; the OrangeFox adbd supports it, and Wi-Fi (BCM4375) remains a fallback path |
| PD charging while host is unproven on this PMIC | measure idle drain with the hub attached; if it drains, document the duty cycle rather than claim charging |
| f2fs reformat destroys everything on `userdata` | explicit user decision; back up before the first format |
| 5.4.302 is end-of-life (1,539 unfixed CVEs) | LAN-only scope stated in the proposal; no internet-facing exposure without a kernel migration |
| Warm reboot can latch recovery mode | every boot test is a cold boot |
| 24/7 charging on a phone battery | charge guard is delivered in the same change, not later |
| systemd inside a namespace may refuse or degrade | the launcher mounts a fresh cgroup2 and passes a full /dev; Alpine + OpenRC stays a drop-in fallback |
| `switch_root` on the live recovery destroys its ramfs (observed) | never used; the launcher uses `pivot_root`, and the recovery's root is only touched inside its own namespace |
| debootstrap on Alpine may need workarounds | it runs arm64-native on the device (no qemu); if it fails, fall back to extracting a Debian arm64 container image as the rootfs |

## Migration Plan

1. **Prepare** — back up anything wanted from `userdata`; confirm battery above the floor; keep `flash/BL_custom` and the working LOS recovery image as rollback.
2. **Build offline** — kernel and modules; verify config delta and single vermagic. Nothing touches the device yet.
3. **Repack and flash** — LOS container, byte-exact round trip first; flash `recovery` only.
4. **Boot gate** — cold boot; GUI, touch, adb, `unshare --pid`, module log clean. Failure → reflash the saved working image.
5. **Storage** — reformat `userdata`, mount it, install the Alpine root.
6. **Service** — sshd, dockerd, charge guard; verify GUI and service coexist.
7. **GUI** — move the same kernel into the OrangeFox ramdisk; repeat the boot gate.
8. **Hub** — host mode, Ethernet, adb over TCP; measure charging behaviour.

Rollback at any gate: reflash the last verified `recovery` image from download mode. The `boot` slot and the bootloader are never modified by this change.

## Open Questions

- Which clang revision is actually obtainable on this host? Any toolchain that clears the boot gate is acceptable; the choice changes no spec.
- Which sysfs node truly gates charging on this PMIC? Resolved by measurement during D11's implementation.
- Does the LOS adbd expose a TCP listener, or does the console need the OrangeFox adbd first? Verified during phase 3; the fallback is already in the plan.
