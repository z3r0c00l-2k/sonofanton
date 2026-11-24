# 10 — Build ladder

The chain was not designed once; it was reduced until the device booted. This is
the map of what each build carried and which one is current.

## NHZF5 lineage

| Build | Base | Patch set | Notes |
|---|---|---|---|
| v15 | NHZF5 | core + fuse | last known-good before the v16+ rework |
| v16/v17/v18 | NHZF5 | + gates | do not flash; v17 omitted the BL1 payload |
| v19/v20 | NHZF5 | + bit-3 gate | fixed the SUPER refusal |
| v21 | NHZF5 | + rp gate | fixed the recovery rollback halt |
| v22 | NHZF5 | + recovery gate | **known-good**; TWRP boots; previous running chain |
| v23 | NHZF5 | v22 + keypad recovery combo | removed the key route into recovery; superseded |
| v24 | NHZF5 | v22, DT fallback off | correct DTBO entry 2 (rev 18) |
| v25 | NHZF5 | v24 minus state readers | do not use; vbmeta `HASH_MISMATCH` |
| v26 | NHZF5 | v24 minus unlock gate | executor still ran; superseded |
| v27 | NHZF5 | v24 + executor nops | current best NHZF5 build before v28 |
| v28 | NHZF5 | v27 + `force_recovery_boot` | ordinary power-on selects recovery; flashed and running |

v28: `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v28.tar.md5`, md5
`f5adad3532017704f4db9bc0d4d9745d`, sha256 `56170b77…39b5f`;
`output/sboot_v28.bin` sha256 `4172ae38…a847`.

## IGYI3 variant

| Build | Base | Patch set | Notes |
|---|---|---|---|
| v1–v3 | IGYI3 | 15 sites | do not flash; wrong lz4 container |
| v4 | IGYI3 | 15 sites | lz4 frame, wrong block size |
| v5 | IGYI3 | 15 sites | correct lz4 params; device went black (patch-induced) |
| minimal | IGYI3 | none | boots; reports `Invalid PPI` (needs the IGYI3 PIT) |
| A | IGYI3 | 9 stubs | boots |
| B1 | IGYI3 | A + rp gates | boots |
| B2 | IGYI3 | A + rp + `0xa9d8` getter | black (patch-induced) |
| full2 | IGYI3 | B1 + `0x6be80` nop + value + executor | boots to download mode; device bootlooped |
| core v1 | IGYI3 | 12 functions / 17 sites: stubs + rp gates + `0x6be84` value + executor nops | current candidate; differs from full2 only at `0x6be80`/`0x6be84`/`0x64e28` |

IGYI3 is structurally different. The shared secure-download getter at `0xa9d8`
must stay stock; the value half at `0x6be84` is the verified route.

## What each family proved

- **NHZF5**: the stock chain can be reduced to a small set of gates; the DT
  stage is not fixed by the revision fallback; the SUPER refusal is the live
  bit-3 gate.
- **IGYI3**: the same failure mode recurs; a correct lz4 container is not
  enough if a shared function is patched; the executor and the secure-download
  value are the load-bearing pieces.

## Current state

- Running: v28 (NHZF5), with the server image v9 and Debian 13.7.
- Previous: v22 (known-good fallback).
- The Linux host is on the recovery slot; the bootloader is only touched when a
  new chain is built and verified.

## Related

- [ABL patching](03-abl-patching.md)
- [Failures](09-failures.md)
- [History: the full chronology](../history/runbook.md)
