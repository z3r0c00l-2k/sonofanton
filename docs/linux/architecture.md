# Architecture

## 2. The device

| item | value |
| --- | --- |
| model | SM-G990E ("r9s"), Exynos 2100, 8 GB, 128 GB UFS |
| bootloader | custom-key fused; **never flash a stock or OTA bootloader** |
| partitions | `recovery` boots; `boot` dies at the DT stage (`FDT_ERR_BADMAGIC`) |
| recovery image | header v2, 64 MiB partition, `SRPUG16A018KU` |
| userdata | `/dev/block/sda34`, reformatted f2fs, unencrypted |
| keys | `keys/` holds `testkey_rsa4096.pem` (AOSP test key used by the LOS build) |

Recovery is the reliable slot. Every experiment in this project targets it.

---

## 3. Boot chain

```
 bootloader (custom key)
        |
        v
 recovery.img = kernel + ramdisk + DTBO + DTB + AVB footer        (header v2)
        |
        v
 LOS recovery ramdisk: init -> GUI + adb
        |
        |  (4.3, planned) oneshot service:
        |    make mount tree private, bind rootfs aside, chroot into the bind,
        |    pivot_root into the Linux root, exec its init
        v
 Linux root on userdata  (/data/linux for Alpine, /data/linux/data/debian for Debian)
        |
        +-- sshd
        +-- dockerd / podman        (real root required - see section 6)
        +-- charge guard (planned)
```

The GUI and the Linux side coexist because `pivot_root` is per mount namespace:
the recovery keeps its own root, the Linux side gets a real one.

---

## 4. Kernel

**Source** — `exy2100/android_kernel_samsung_universal2100` at `lineage-23.2`
(5.4.302). The ROM's exact commit (`51d63cf4924c`) is not in the public tree;
HEAD `34237952` is one day newer and builds the same drivers.

**Configuration** — recovered from the booting image, not guessed:

```
baseline/kernel.config        7,600 lines, extracted from IKCFG_ST..IKCFG_ED
olddefconfig on the public tree accepts it; 37 lines resolve
delta: sources/.../arch/arm64/configs/samsung/docker.config
```

The delta (14 options, each justified in the file):

```
PID_NS IPC_NS USER_NS CGROUP_DEVICE CGROUP_PIDS
BRIDGE_NETFILTER NETFILTER_XT_MATCH_ADDRTYPE NF_TABLES NF_TABLES_INET
NF_TABLES_NETDEV NFT_COMPAT MACVLAN POSIX_MQUEUE TMPFS_XATTR
CONFIG_CFI_PERMISSIVE                        (build workaround, see below)
```

`CONFIG_NFT` does not exist in 5.4; the core is `NF_TABLES`, and `NFT_COMPAT`
lives inside its `if` block, so it is invisible when the core is off. The build
script asserts every delta line against the resolved config — that gate is what
caught this.

**Toolchain** — the LOS kernel was built with Android clang **r563880 (21.0.0)**,
LLD 21.0.0 (from the kernel banner). That exact prebuilt is not published on
`prebuilts/clang/host/linux-x86` `main` (404; main tops out at r547379).

**The CFI finding.** With clang 23 the kernel panicked at 5.9 s, in
`s3c2410_wdt`, at `__cfi_check_fail`. 30 of 272 modules lacked
`init_module.cfi_jt`, and that symbol was taken as the cause; the shipped
kernel therefore sets `CONFIG_CFI_PERMISSIVE=y`.

Building LOS 23.2 from its own tree corrects that reading. One tree, one pinned
toolchain (`clang-r563880c`): 271 modules ship, **26 of them also lack
`init_module.cfi_jt`**, and the kernel boots with CFI **enforcing**
(`# CONFIG_CFI_PERMISSIVE is not set`):

```
init: Loaded 271 modules from /lib/modules        (no CFI failure in dmesg)
```

The absent stub is survivable — the loader falls back to `__cfi_slowpath` and
the module's own `__cfi_check`. What matters is that every module exports
`__cfi_check` (all 271 do) and that kernel and modules are built by the same
toolchain. The earlier panic fits a kernel/module type-id mismatch, not the
absent stub. `tools/check_cfi_jt.py` now checks the invariant that matters.

**Build**

```
TOOLCHAIN=<toolchain dir> JOBS=6 tools/build-kernel.sh
vendor patches: patches/0001-vendor-drivers-allow-warnings.patch (7 Makefiles
re-add -Werror after the globals; bare -Werror removed, -Werror=... kept)
patches/0002-kernel-cpuset-drop-group-cap.patch   removes the vendor per-boot
                                                  cpuset counter (mkdir ENOMEM)
KCFLAGS=-Wno-error                      vendor Makefile:496 adds blanket -Werror
bc built locally into tools/host/bin    distro image lacks it
```

---

## 5. Image packaging

**Packer** — `tools/recovery_img.py` splits and rebuilds header-v2 images. The
contract: an unmodified repack must reproduce the original **byte for byte**.
It does (`06bb5c2a…`), and the header `id` is *recomputed*, so the match proves
synthesis rather than copying.

Correct v2 field offsets, verified against the live image (the reference table
in the skill was wrong and has been fixed):

```
1632 recovery_dtbo_size    1636 recovery_dtbo_offset
1644 header_size (1660)    1648 dtb_size        1652 dtb_addr
```

**AVB** — the LOS image is signed. The full recipe was recovered and
**reproduces the original bit-for-bit**:

```
algorithm SHA256_RSA4096, key testkey_rsa4096.pem, rollback index 1, location 0,
salt  7d42cb82…8b11,
prop  com.android.build.recovery.fingerprint:samsung/lineage_r9s/r9s:16/BP4A.251205.006/eng.daniel:userdebug/release-keys
```

`tools/repack.py --sign` signs new payloads with those parameters.
Stripping the trailer instead was **not** the cause of a boot failure (the
kernel booted fine, see section 9) — but a stale trailer is worse than none,
so candidates are signed, never carried over.

**Odin packaging** — `tools/package_odin.sh`. A `.tar.md5` must be the tar plus
a full `md5sum` line (`<hash>  <name>.tar\n`); a bare hash is rejected as
"md5 is invalid". The tar is deterministic (`--mtime=@0`).

**Current candidate** — `out/RECOVERY_r9s_kernel_v3.tar.md5`
(image sha256 `02bfb818…`, tar.md5 sha256 `361e6bbf…`), flashed and running.

---

