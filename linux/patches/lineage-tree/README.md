# Tree patches

Local changes to the LineageOS tree that the build needs. They are not upstream
fixes; they are what makes this device build and run the server page.

Apply them with `tools/prepare-tree.sh`, which clones the pinned projects,
rebuilds the `hardware/samsung_slsi-linaro` layout and applies everything below
in order. `tools/prepare-tree.sh --verify` checks a tree without changing it.

| patch | repository | what it does |
| --- | --- | --- |
| `0001-kernel-r9s-config-namespaces.patch` | `kernel/samsung/universal2100` | `CONFIG_PID_NS`, `IPC_NS`, `USER_NS`, cgroup device/pids, bridge netfilter, nf_tables, macvlan, POSIX mqueue, tmpfs xattr — the launcher's `unshare --pid` and Docker inside Debian need them. `CONFIG_CFI_PERMISSIVE` is deliberately not added. |
| `0002-recovery-server-menu.patch` | `bootable/recovery` | `MENU_SERVER` and the four server actions in `device.h`/`device.cpp`, `RunServerCommand()` and its switch cases in `recovery.cpp`. The top screen is `Status` / `Advanced` / `Reboot system now`; server control, `Apply update` and `Factory reset` live under `Advanced`. |
| `0003-external-skia-vendor-available.patch` | `external/skia` | `vendor_available` on `libskia_skcms`. |
| `0004-external-highway-vendor-available.patch` | `external/google-highway` | `vendor_available` on `libhwy`. |
| `0005-external-xmp-vendor-available.patch` | `external/XMP-Toolkit-SDK` | `vendor_available` on `xmp_toolkit_sdk` and `zuid_md5`. |
| `0006-universal2100-common-drop-epic-hal.patch` | `device/samsung/universal2100-common` | removes the EPIC HAL from `common.mk` and sepolicy (sources are not in this tree, so the build cannot produce it). |
| `0007-hardware-samsung-disable-lineage-health.patch` | `hardware/samsung` | disables the lineage health AIDL module. |
| `0008-hardware-samsung_slsi-linaro-reduce-android-bp.patch` | `hardware/samsung_slsi-linaro` | reduces `Android.bp` to the Soong namespace root plus `subdirs`; the module definitions it drops come from the split exynos repositories. |
| `0009-recovery-screen-timeout.patch` | `bootable/recovery` | blanks the display after 30 s without input and wakes it on the next touch or key, dropping that input so it cannot also operate the menu. The stock brightness screensaver never arms on this panel (it probes `/sys/class/backlight/panel0-backlight`, r9s exposes `/sys/class/backlight/panel` and the node is inert), so this disables the DRM CRTC the way TWRP's `blanktimer` does, and makes `Flip()` rotate buffers instead of issuing a page flip while blanked. |
| `0010-recovery-status-row.patch` | `bootable/recovery` | draws two extra fields left of the battery: the hub's Ethernet link (`eth0 1G`, `eth0 down`, nothing when the port is a device) and the charger state (`Charging`, `Paused`, `Discharging`, `Full`). Both are read from sysfs by the existing 5 s battery thread, which already redraws on change; `Paused` is the charge guard holding at the ceiling, which the kernel reports as `NOT_CHARGING`. |
| `0011-kernel-cpuset-group-cap.patch` | `kernel/samsung/universal2100` | raises the vendor cpuset-group cap from 20 to 256 (`CS_CGROUP_COUNT`, and the `requested_cs[]` array that is indexed by `css->id - 1`). The counter is never decremented, so a recovery-mode Docker host exhausted 20 allocations and every new cgroup failed with `ENOMEM` — BuildKit surfaced it as `unable to apply cgroup configuration: mkdir /sys/fs/cgroup/docker/buildkit: cannot allocate memory`. Superseded by `0012`; kept so trees that already applied it still reverse-check. |
| `0012-kernel-cpuset-drop-group-cap.patch` | `kernel/samsung/universal2100` | removes the vendor counter and `requested_cs[]` table instead of raising the cap. The table is write-only (the clone-children path already copies `cpus_requested`, as upstream does) and `cs_count` only ever increases, so the limit served no purpose; deleting it restores the upstream 5.4 behaviour and removes 256 boot-time cpumask allocations. A 12-day boot exhausted even the raised 256-slot cap and every `mkdir` under `/sys/fs/cgroup/docker` failed with `ENOMEM`. |

Patches 0003–0005 are one line each and fix the same class of error: a module
reachable from a `vendor_available` library that was never itself marked
`vendor_available`, so Soong refuses to give it a vendor variant.

## Applying by hand

```bash
TREE=/mnt/GGG/BuildGround/lineage
git -C "$TREE/kernel/samsung/universal2100" apply patches/lineage-tree/0001-kernel-r9s-config-namespaces.patch
# ... and so on, one repository per patch, as listed in the table
```

Each patch reverse-applies cleanly to the tree it was captured from, which is
what `--verify` relies on.
