# 07 — DT stage and recovery

The `boot` slot aborts at the bootloader DT stage. The `recovery` slot boots.
This chapter records what the DT stage actually checks, why v3 images fail, and
how the recovery image is selected.

## The check

The validator is at `0x5e9c0` in the bootload. It receives a name (`DTBO` or
`DTB`), copies 0x20 bytes from the pointer to `0xfb400000`, and requires:

- the DTBO table magic `0x1eabb7d7` (byte order `d7 b7 ab 1e`),
- a big-endian size `<= 0x08000000`.

The pointers are set on the scatter path:

| Name | Pointer |
|---|---|
| DTBO | `[0xbeb518]` |
| DTB | `[0xbeb520]` |

Failure prints differ:

```
[UFDT] DTBO LOAD FAIL.
[UFDT] DTB LOAD FAIL.
[UFDT] DT Entry: not found rev 0x...
```

The screen reason is the single `DT Load Fail`, so it cannot distinguish which
sub-check failed.

## Header versions

The loader reads the loaded image at `0x94000000`:

- header version 2 -> the path that boots,
- header version 3 -> the path that fails before display/USB.

Every v2 recovery image boots. Every v3/GKI boot image fails with three
different kernels; the bootloader requests download mode itself
(`force_upload=0`). Panic capture is unavailable (`log_arrdumppanic` disabled;
ramoops is pmsg-only).

## DTBO entry selection

The NHZF5 `dtbo` table declares revision ranges:

| Entry | Revision range |
|---|---|
| 0 | 0–16 |
| 1 | 17 |
| 2 | 18–32 |

The device revision is 18, so entry 2 is correct. The optional
`dt_entry_revision_fallback` patch forces entry 0 when the lookup fails; it was
tested (v15) and did **not** fix the failure, so it is off. The lookup is not the
failing layer.

## Recovery selection

This bootloader has **no Android BCB parser** (`boot-recovery` is absent from
the whole sboot). Recovery is selected by `param[0]`:

- `param[0]` in `{4,5}` reaches the existing Recovery Set block,
- `param[0] == 0` continues to normal boot,
- v28 redirects only the ordinary `0` path to the recovery block, without
  writing `param`.

The `param[0] == 6` restore path and the Download Mode key action (`0x11`) are
unchanged.

## Lineage recovery

The working base is a LineageOS 23.2 recovery image:

- `ANDROID!` header version 2,
- embedded DTBO table (`d7b7ab1e`, FDT at `+0x80`),
- kernel and modules from the same build,
- the project launcher injected into the ramdisk.

v2 is the requirement. A v3/GKI boot image does not reach the display.

## What the recovery slot contains

| Component | Role |
|---|---|
| kernel + modules | rebuilt 5.4.302 with the container delta |
| recovery UI | Lineage recovery with the Server page |
| launcher | `system/bin/linux-launch` |
| helpers | `pivot_root`, `charge-guard`, `net-watch`, `r9s-server` |
| logo | verified project asset |

The Debian root is not in the image; it lives on `userdata`.

## Related

- [Design: DT stage](../design/dt-stage.md)
- [vbmeta](08-vbmeta.md)
- [History: the DT war](../history/runbook.md)
