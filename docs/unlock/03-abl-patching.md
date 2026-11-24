# 03 — ABL patching

The bootloader is Samsung's ABL (`bootload.bin` inside `sboot`). The patches
below are applied by `tools/unlock/patchers/patch_9840.py` (NHZF5 lineage) and
`patch_9840_igyi3.py` (IGYI3 variant). Offsets are raw offsets in the extracted
`bootload.bin`.

## Build order is load-bearing

```
split.py s5e9840 <indir> <workdir>
tools/unlock/patchers/embed_bl1_payload.py <workdir>/sboot/bl1.bin
EUB_SHOULD_FUSE_KEY=0 python3 patch_9840.py <workdir>/sboot/bootload.bin
python3 patch_9840_igyi3.py <workdir>/sboot/bootload.bin
Exynos: scripts/build.py s5e9840 ../keys <workdir> [RB]
splice stock dpm.img into <workdir>/sboot.bin at 0xea000   # after signing
pack tar (member names/order as the stock package)
```

The BL1 payload must be embedded **before** BL1 is signed. Embedding after
signing produces `BL1 Checksum Fail`.

## NHZF5 lineage patches

| # | Patch | Site(s) | Effect | Default |
|---|---|---|---|---|
| 1 | `check_signature` | `0x67f88` | stub the no-signature check and set the secure-download bypass flag `[0xbeed28]=1` | ON |
| 2 | `prevent_warranty_fuse` | `0x63380`, `0x65c00` | never write the irreversible warranty-void bit | ON |
| 3 | `check_sw_rev` | `0x650d0` | SW-REV flash gate returns 0 | ON |
| 4 | `check_kernel_rev` | `0x66378` | kernel rollback check returns 0 | ON |
| 5 | `check_system_rev` | `0x65e88` | system rollback check returns 0 | ON |
| 6 | `check_pit_rev` | `0x66500` | PIT rollback check returns 0 | ON |
| 7 | `seandroid_enforcing_off` | `0x63430` | SEAndroid/TIMA enforcing query returns 0 | ON |
| 8 | `avbops_state_reader_always_unlocked` | `0x96cc8` | AVB ops reader always reports unlocked | ON |
| 9 | `read_is_device_unlocked` | `0x641d8` | reports unlocked | ON |
| 10 | `disable_secure_download_check` | value `0x668b8`, gate `0xa9e0` | sets the bypass flag for Samsung-signed images under a fused key | ON |
| 11 | `dt_entry_revision_fallback` | `0x5e754`, `0x5e764`, `0x5e798`, `0x5e7a0` | forces DTBO entry 0 on lookup failure | **OFF** |
| 12 | `secure_check_bit3_gate` | `0x609ac` | `cbnz` -> `b`; routes the live SUPER refusal to the write path | ON |
| 13 | `recovery_rp_gate` | `0x958f8`, `0x95a84` | removes the rollback halt | ON |
| 14 | `recovery_secure_check_gate` | `0x67214` | removes the RECOVERY bit-3 refusal | ON |
| 15 | `keypad_recovery_combo` | `0x207588` | disables key-triggered recovery | **OFF** |
| 16 | `open_oem_unlock_gate` | `0x66930`, `0x66958` | lets the stock unlock executor run | **OFF** |
| 17 | `executor_skip_recovery` | `0x669d0`, `0x669dc`, `0x669f0` | stops the executor's BCB wipe / `sys_bootm` / `param[0]` loop | ON |
| 18 | `fuse_boot_key` | overwrites `0x67f88` | burns the custom key into ROM slot 2 | **OFF with `EUB_SHOULD_FUSE_KEY=0`** |
| 19 | `force_recovery_boot` | `0x2b24` -> cave `0xc624c` -> `0x2f80` | ordinary `param[0] == 0` selects recovery | ON |

Environment flags: `EUB_SHOULD_FUSE_KEY`, `EUB_DT_FALLBACK`,
`EUB_KEYPAD_RECOVERY_COMBO`, `EUB_OEM_UNLOCK_GATE`, `EUB_EXECUTOR_RECOVERY`.

## The two bit-3 gates

The per-image secure check has two gates; only one is live:

| Gate | Site | Live? |
|---|---|---|
| A | `0x604c8` | no — dead code after `check_signature` returns 0 |
| B | `0x609ac` | **yes** — the whitelist contains `SUPER`; verify #2 reads `[0xbee250]`, not the bypass flag |

This is why v16 (gate A) did nothing and v17 (gate B) moved the SUPER refusal.

## IGYI3 variant

IGYI3 differs structurally. The verified patches are signature, warranty fuse,
SW/kernel/system/PIT rollback, SEAndroid, AVB reader, unlock reader, the
rollback consumer nops, and the executor. The secure-download *getter* at
`0xa9d8` is shared with early init and must stay stock; patching it blacked the
device. The value half at `0x6be84` is the verified route.

## Verification

```bash
python3 tools/unlock/verify/verify_chain.py image   <sboot.bin>
python3 tools/unlock/verify/verify_chain.py packed  <tar.md5> --expect-image <sboot.bin>
python3 tools/unlock/verify/verify_chain.py confinement <stock_bootload> <built_bootload>
python3 tools/unlock/verify/verify_chain.py session <sboot.bin>
```

The `image` check covers the patch contracts, BL1 payload, and ST2 key index.
The full patch history and the falsified attempts are in
[history/runbook.md](../history/runbook.md) and
[Failures](09-failures.md).
