> Exported from the project's OpenSpec design record and sanitized for publication.

# Design

## Context

See `proposal.md` - Why. The traced state of the abl's DT stage (NHZF5 segment,
`bootload_pristine.bin`, md5 `727e6047be7e044d461397d45be8fef4`, reproducible with
`re_unlock_state.py`):

```
  0x5eb70  "[UFDT] BOOT IMG HDR V%d.. FINDING DTB ENTRY"
             bl 0x43988            boot-image header version
             0x5eb9c  x0 = "DTB"
             0x5eba4  bl 0x5e9c0    the validator, name="DTB"
             0x5eba8  cbz x0, 0x5ef80   NULL => failure path
             0x5ebb0  "[UFDT] FINDING DTBO ENTRY"

  0x5e9c0  validator
             strncmp(name,"DTBO") -> 0x5ea68:  x19 = [0xbeb518]   (DTBO pointer)
             strncmp(name,"DTB")  -> 0x5ea00:  x19 = [0xbeb520]   (DTB pointer)
             memcpy(0xfb400000, x19, 0x20)
             magic 0x1eabb7d7 (= DTBO table magic 0xd7b7ab1e)  else "[DTH] dt table
               header check Fail" (-9)
             BE size <= 0x08000000                              else same (-0xc)
             returns NULL on failure

  writers:  0x5eb28 sets [0xbeb518]        readers: 0x5ea68 (validator),
            0x5eb18 sets [0xbeb520]                  0x5eb58 (getter, gated by a
            0x5eb38 getter: bit from 0x5d868 selects [0xbeb518] vs 0xfb400000)
```

Content is **not** the fault — host-side bytes:

| artefact | evidence |
| --- | --- |
| stock `dtbo.img` (AP tar) | 8388608 B, `d7 b7 ab 1e 00 0a d0 78 …`, FDT at `+0x80` — exactly the required header |
| LOS recovery | 67108864 B, `ANDROID!`, DTBO table at `0x353a000`, FDT at `0x353a080` |
| TWRP recovery | 55341072 B, `ANDROID!`, DTBO table at `0x33ba000`, FDT at `0x33ba080` |

Also relevant: the AP tar's member order puts `misc.bin` **after** `super`, so the
failed AP flash never reset MISC; and the download screen reports
`BUILD VERSION : G990BXXSNH?F9` on a G990E device, which is unexplained.

## Goals / Non-Goals

**Goals:**

- Identify who sets `[0xbeb518]`/`[0xbeb520]` and the condition that leaves it unset.
- Establish whether the DT lookup fails on a model/revision mismatch, and where the
  reported identity actually comes from.
- Fix the responsible layer, proven host-side first, then by one device test.

**Non-Goals:**

- Building or flashing another candidate before the layer is identified (five
  attempts — v10 to v14 — produced no change because they targeted downstream gates).
- Re-signing the stock AP, or the secure-download check: separate concerns, already
  captured elsewhere or recorded as falsified.
- Changing the bootloader's key posture: the fused key is not in question here.

## Decisions

### D1 - Treat the DT stage as the gate, and the pointer as the subject

The check reads pointers, so the question "which image?" is the wrong one. The
subject is the pointer-setting step. This is the correction that reframes the
whole investigation.

### D2 - Prove host-side before any device write

Every one of the trace's inputs is readable from the binary and from artefacts on
disk. A device write is proposed only once the responsible layer is named.

### D3 - Keep the change separate from the other two

`ground-up-unlock-state` owns the unlock state and `restore-stock-boot` the stock
AP. This change owns the DT/recovery gate; mixing them made earlier attribution
harder than it needed to be.

## Risks / Trade-offs

- [The pointer is set correctly and the failure is elsewhere in the chain] -> the
  reads in task group 1 answer this directly; if so, the trace above is refined
  rather than discarded.
- [The identity string is a red herring] -> task 1.2 identifies its source before
  anything depends on it.
- [Reading `0x5ef80` shows the NULL path is not what prints `DTBO LOAD FAIL`] ->
  that is a cheap correction; the task records the actual path.
- [The fix needs a device write after all] -> that write is proposed explicitly,
  after the layer is named, with the EUB path unchanged as rollback.

## Migration Plan

1. Host-side reads: pointer setters (`0x5eb18`/`0x5eb28`) and their callers; the
   `0x5ef80` failure path; the `up_param.bin` model string we flash.
2. Name the responsible layer and record it here.
3. Fix it, verify host-side, then one device test of recovery.
4. Only then revisit TWRP and LineageOS, which this change unblocks rather than
   performs.

Rollback: nothing in this change replaces our BL or the fused state; the EUB test
point remains the recovery path throughout.

## Responsible layer (group 1 complete)

The DT stage fails in the **revision-keyed DT-entry lookup**. Every input is now read
end to end:

```
  device side:  0x1a48  memoised getter ([0x1b3000]) -> 0x19b0 -> OTP/SMC id 0x10730103
  image side:   0xfb400000 + BE32(image[8]) = the DT table
                entry count = BE32(image[0x10])
  lookup:       0x5e6f8  load_fdt_from_dt_table(revision, "DTBO" / "EDTBO")
                  0x5e734  count <= 0        -> "DT Entry: not found rev 0x%x"
                  loop                       -> no entry matching the revision
                  NULL                       -> the DTB/DTBO pointer is never set
                  -> validator magic check -> "DTB LOAD FAIL" / "DTBO LOAD FAIL"
                  -> stage-4/5 abort -> "DT Load Fail"
```

Supporting reads: the setters `0x5eb18`/`0x5eb28` are **unconditional** on their
paths (`0x43d70`, `0x0441f0`, `0x43d78`), and `0x43db8` does not skip them. The two
failure messages are distinct paths (`0x5ede0` DTBO, `0x5ef80` DTB) — the earlier
design text conflated them, which task 1.2 refuted. Header versions: stock `boot`
is **v3**, while all three recoveries (stock, LOS, TWRP) are **v2**, and the NHZF5
abl accepts both. The IGYI3 abl predates v3, and the IGYI3-era chain already
produced this same failure on this device, so the generation swap is a control that
has been run, not a fix.

**Chosen fix: make the lookup succeed** — fall back to an entry when no revision
match is found — rather than "supply a matching DT table". Reason: the revision is a
hardware/OTP value (`0x10730103`) that is not readable from the host, so a
matching-table fix cannot be verified here, whereas the lookup is an ordinary patch
site the validator can check.

**Host-side check that proves it (before any device write):** the built bootload
must carry the stubbed lookup site at `0x5e6f8`, `verify_chain.py image`/`packed`/
`session`/`confinement`/`selftest` must all still pass, and the DT-table lookup must
be shown to return non-NULL for a table whose entry count is > 0 and whose entries
do not match the revision. This runs entirely on artefacts.

## Open Questions

- None blocking. `0x1a48`'s value is hardware-derived and not host-readable, which
  is precisely why the fix is defined on the lookup rather than on the table.
