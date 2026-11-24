# Device record

> Status and procedures: see the [Linux guide](README.md). This file holds device facts only.

Ground truth for this project. Every claim here was measured on the device or
read out of a shipped image. Anything unverified is marked **(unverified)**.
This file holds only facts about this phone; the method lives in the guide.

---

## 1. Device

| item | value |
| --- | --- |
| model | SM-G990E, codename **r9s**, SoC S5E9840 (Exynos 2100), 8 GB, UFS |
| serial | <device-serial> |
| bootloader revision | 18, rollback `rp=23` |
| running BL | NHZF5-based **v28**, custom-key signed (`androidboot.bootloader=G990EXXSNHZF5`) |
| fused key | project key `0x3e96f623` (slot 2) |
| verified boot | `verifiedbootstate=orange`, `other.locked=1` |

**Hard constraint:** the fuse is burned. Only BL images signed with `keys/` can
run. A stock Samsung BL or a stock OTA BL can never be restored. `keys/` and
`keys_backup_20261009/` are irreplaceable. Rescue path is the EUB test point
(`eub_session5.py`).

**Boot reality:** the `recovery` slot boots reliably; the `boot` slot aborts at
the bootloader DT stage (`[DTH] dt table header check fail: FDT_ERR_BADMAGIC`,
`[UFDT] DTB_LOAD_FAIL`). All Linux work targets the **recovery** slot.

Warm reboots can stay latched in recovery (PMIC key state survives). Any
normal-boot test needs a cold boot — power key only.

---

## 2. Kernel as shipped (LineageOS recovery)

```
Linux version 5.4.302-g51d63cf4924c
  <builder>@<host>, Android clang 21.0.0 (r563880c), LLD 21.0.0
  #5 SMP PREEMPT Mon Jul 13 13:46:01 UTC 2026
aarch64, SELinux Enforcing in recovery
```

- Source tree: **not yet obtained**. The ROM is an unofficial r9s build
  (`lineage-23.2-20260904-UNOFFICIAL-r9s.zip`) so the public LineageOS repos
  `android_kernel_samsung_exynos2100` and `android_device_samsung_r9s` do not
  exist. Public 5.4.302 Exynos 2100 trees that do exist:
  `ProtonKernel/Proton`, `haridhayal11/android_kernel_samsung_exynos2100`,
  `FlopKernel-Series/flop_exynos2100_kernel`.
- 5.4.302 is the final 5.4.y release (EOL, no further security patches).

### Config delta needed for containers

Recovered from the image via `IKCFG_ST`/`IKCFG_ED` (7600 lines).

```
MISSING  PID_NS  IPC_NS  USER_NS  CGROUP_DEVICE  CGROUP_PIDS
         BRIDGE_NETFILTER  NETFILTER_XT_MATCH_ADDRTYPE  NFT  NFT_COMPAT
         MACVLAN  IPVLAN  POSIX_MQUEUE  TMPFS_XATTR

PRESENT  NAMESPACES  UTS_NS  NET_NS  CGROUPS  MEMCG  CGROUP_FREEZER  CGROUP_BPF
         SECCOMP  SECCOMP_FILTER  OVERLAY_FS  FUSE  F2FS  EXT4  VETH  BRIDGE
         NF_CONNTRACK  NF_NAT  NF_NAT_MASQUERADE  IP_NF_IPTABLES  IP_NF_FILTER
         IP_NF_NAT  IP_NF_TARGET_MASQUERADE  XT_MATCH_CONNTRACK  TUN  DUMMY
         KEYS  USB_DWC3_HOST  USB_RTL8152  USB_USBNET  USB_NET_CDCETHER
```

`CONFIG_TMPFS_XATTR=n` is why overlayfs refuses the recovery ramfs but works on
ext4.

---

## 3. Image inventory

All three are `ANDROID!` header **v2**. Sizes are in bytes; the files live in
the recovery work directory, not in this repository.

| file | sha256 (outer tar/zip) | recovery.img size |
| --- | --- | --- |
| `LOS_recovery.tar` | `071c9918…d535` | 67,108,864 |
| `twrp-3.6.1_11-1_afaneh92-r9s.tar` | `b5e4a068…5d4` | 55,341,072 |
| `OrangeFox-R11.3-Unofficial-r9s.img.tar` | `51fdd3b5…18e` | 64,266,272 |
| `OrangeFox-R11.3-Unofficial-r9s.zip` | `8dc08d75…54e` | (contains the tar above) |

Extracted images:

```
los.img  sha256 06bb5c2a…
twrp.img sha256 473efe75…
ofox.img sha256 4d4b0288…
```

### Structure

| | kernel | ramdisk (gz cpio) | tail | modules | kernel string |
| --- | --- | --- | --- | --- | --- |
| LOS | 30,673,408 | 25,129,330 → 78,316,032 | 11,300,864 (DTBO table) | 275 | `5.4.302-g51d63cf4924c` |
| TWRP | 28,738,048 | 25,492,195 → 88,917,760 | 1,105,936 | 285 | `5.4.129-afaneh92-g2b4fc089a02d` |
| OrangeFox | 28,738,048 | 34,416,795 → 104,416,768 | 1,105,936 | 288 | same as TWRP |

LOS header: `kernel_addr 0x80080000`, `ramdisk_addr 0x84000000`,
`tags 0x80000000`, page 4096, cmdline `loop.max_part=7`, name `SRPUG16A018KU`.

TWRP/OrangeFox header: `kernel_addr 0x80008000`, cmdline includes
`androidboot.hardware=exynos2100 androidboot.selinux=permissive`.

### Two defects worth remembering

1. **TWRP and OrangeFox are internally inconsistent.** Their Image is
   `5.4.129-afaneh92-…` but every module in their ramdisk is
   `5.4.129-23339874-abG990EXXS1BVB8` (a stock Samsung build). vermagic mismatch;
   only built-in drivers work. LOS is the only coherent pair.
2. **None of the three can decrypt FBE.** No `system/bin/vold`, no keymaster
   HAL, `init.recovery.vold_decrypt.rc` not present (it is imported by init.rc but
   missing). `/data` is unreadable, which is why it was never mounted.

---

## 4. Superseded status (kept for history)

This file is now the **device record** only. Current state, procedures and the
failure log live in the [Linux guide](README.md).

The three "blocked" items from the earlier phase are all closed:

| then | now |
| --- | --- |
| containers blocked, `crun: clone: Invalid argument` | fixed: `PID_NS`/`IPC_NS`/`USER_NS` compiled in; podman and docker both run containers |
| persistence impossible (`/data` encrypted) | `userdata` reformatted unencrypted f2fs; Debian rootfs on it |
| kernel namespaces missing | custom kernel `5.4.302-g34237952ad8c-dirty` built and booting from the recovery slot |

The four open decisions were resolved: Android retired (user choice); LOS
recovery kept as the base (OrangeFox pending); repack-with-rebuilt-kernel chosen
over an AOSP source build; storage on userdata, no SD card.

## 5. Host capacity (current)

Ryzen 7 5700, 16 threads, 15 GB RAM, 55 GB free on `/home`.
On disk: `toolchains/` 18 GB (upstream LLVM 21.1.0 and Android clang r547379,
kept for a future CFI-enforcement build), `build/` 3.9 GB (regenerable),
`out/` 897 MB, `baseline/` 193 MB, `sources/` 1.4 GB.
