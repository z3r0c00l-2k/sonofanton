# 09 — Failures

The expensive part of this project was not the successful path; it was the
attempts that looked correct and were not. Keep this list in front of you when a
new idea feels obvious.

## Falsified unlock attempts

| Attempt | Change | Result |
|---|---|---|
| v8 | leaf-stub chain | boot loop; two ABI defects (state-app stub at wrong entry -> SP imbalance; avb reader `strb` to address `0x1`) |
| v9 | ABI defects fixed | Odin stalled at `File analysis`; the tar had no terminator |
| v10 | reduced chain + unlock gate | flash PASS; boot 1 switched state; boot 2 still DT Load Fail |
| v11 | + decider reader stub `0x96cc8` | same DT Load Fail |
| v12 | + OEM-lock flash gate `0x641d8` | stock AP flash started |
| v13/v14 | + secure-download bypass | `super.img` still `SECURE CHECK FAIL : (SUPER)` |
| v15 | + DT-entry revision fallback | still DT Load Fail; the lookup is not the failing layer |
| v16 | + bit-3 gate at `0x604c8` | dead code; nothing changed |
| v17 | + bit-3 gate at the live site `0x609ac` | built and verified; not flashed |
| v25 | v24 minus state readers | vbmeta `HASH_MISMATCH` |
| v26 | v24 minus unlock gate | executor still ran; superseded |
| IGYI3 v5 | correct lz4 params | device went black (patch-induced) |
| IGYI3 B2 | + `0xa9d8` getter | black; the getter is shared with early init |
| IGYI3 full2 | + `0x6be80` nop | bootloop |

Also falsified:

- Replacing the chain with the IGYI3 generation (same failure; the control was
  already run).
- The idea that the flashed `up_param` supplies the `G990B…` string (it is a tar
  of JPEG splash images with no model/version string).
- The pointer is “never set” (the scatter path sets both pointers; the image
  content or the DT bit is the live candidate).

## Linux-side failures

| Symptom | Cause | Fix |
|---|---|---|
| `switch_root` from recovery wiped `/init` and `/system/bin/sh` | shared filesystem; `switch_root` deletes | never `switch_root` on a live root; use the bind + `mount --move` + `chroot` entry |
| `pivot_root: Invalid argument` from a chroot | a chroot is not a root for a container runtime | enter the root with the namespace-root move |
| `pivot_root` from recovery's `rootfs` | `rootfs` cannot be pivot_root'ed | bind aside, `chroot`, then move |
| container `..` reached the host root | new root mounted at an inner path | attach at the namespace root |
| `unshare(CLONE_NEWUSER)` EPERM | process still in the recovery mount namespace | same root-entry fix |
| dockerd “Devices cgroup isn't mounted” | 5.4 has no cgroup v2 devices controller | hybrid v1 `devices` |
| dockerd `stat /proc/<pid>/ns/pid` | `/proc` mounted before `unshare --pid` | no PID namespace; stack a fresh procfs if needed |
| `iptables-nft` `RULE_APPEND ... No such file` | `CONFIG_NFT_NAT` off | `iptables-legacy` |
| container cannot write data | bind ownership is the image runtime user | Hermes `10000:10000` |
| new containers `mkdir ... cannot allocate memory` | vendor cpuset counter is never decremented | remove cpuset from the Docker subtree, or the kernel 0012 patch |
| `userns-remap` breaks containers | 5.4 cannot mount cgroup2 in a userns | leave remapping off |

## Lessons

- The answer was often in the decompiler, not in another build.
- A patch at the wrong site is indistinguishable from a bad idea until you
  check whether the site is live.
- Packaging defects (tar terminator, md5, lz4) look like bootloader failures.
- A warm reboot can latch the previous mode; always cold boot.
- The EUB path is what makes experimentation affordable; keep it available.

## Related

- [Build ladder](10-build-ladder.md)
- [History: the full chronology](../history/runbook.md)
