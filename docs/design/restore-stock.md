> Exported from the project's OpenSpec design record and sanitized for publication.

# Design

## Context

See `proposal.md` - Why. The technical state that shapes this design:

- The fuse is burned, so the BL can only ever be ours. v12 is the current chain:
  the unlock gate patch, both state readers stubbed, and the OEM-lock flash gate.
- **v10 and v11 both end every boot in `ODIN MODE (DT Load Fail)!`.** v11 restored
  the decider's reader stub and changed nothing, so the DT-stage abort is not that
  reader and not a locked-state effect.
- **The abl's boot log is not readable.** Upload mode is gated by
  `is_upload_available()` (`0x74e70`): a debug register magic or `param[0x11] == 5`,
  plus an FMM lock refusal. The console's command table (`0x141b70`-`0x141d00` —
  `SOD/SODSTART/SODTEST/SODEND`, `DVIF`, `ODIN`, `PROMPT`, `FPGM`, `AT+ENGMODES`,
  `SECCMD`, `@#AuToTEst@#`, `upload`, `download`, `host_reset`) has no log or
  reset-reason command. So the failure must be resolved by experiment.
- **AVB root of trust** (`0x979e8`..`0x97ab4`): a 16-byte expected pubkey is read
  via `SMC 0xC200101D` and `memcmp`'d against the vbmeta's key; failure prints
  `AVB pubkey is not matched with vbmeta`. Our fuse payload writes only
  `cm_otp_write_rom_sec_boot_key`, `cm_otp_write_use_rom_sec_boot_key` and the two
  selectors, so the AVB entry is untouched and a Samsung-signed `vbmeta` should
  validate.
- The DT stage scatters kernel/ramdisk/dtb/recovery-dtbo from the boot/recovery
  image (`scatter_load_boot`), and has named failure points: `DT Entry: not found
  rev`, `FDT Header Check Fail`, `DTB LOAD FAIL`, `DTBO LOAD FAIL`, `DT Overlay
  FAIL`, plus the pre-set-bit skip.

## Goals / Non-Goals

**Goals:**

- A bootable stock system under our custom-key BL.
- The AVB question answered on-device, not inferred.
- A known-good base before any LineageOS attempt.

**Non-Goals:**

- Restoring a Samsung-signed bootloader (impossible with the burned fuse).
- A genuinely unlocked platform state (`ground-up-unlock-state` owns that, and is
  not a prerequisite here — the gate stub is the deterministic path).
- Diagnosing the DT-stage abort by reading the abl log (proven unavailable).

## Decisions

### D1 - Restore the OEM-lock flash gate, as v12

Stock images fail **our** fused key's check and therefore present as
custom-class, and the gate at `_pit_flash_binary` refuses custom AP flashes while
the device is locked. Alternative considered: achieving a genuine unlock first
(`ground-up-unlock-state`) — not achieved, and the gate stub is deterministic and
already verified in the chain. v12 changes exactly one thing over v11.

### D2 - Keep our BL; replace only AP and CSC

The BL cannot be stock, so the flash is deliberately partial: our BL tar is not
included, and the stock AP + HOME_CSC provide everything above it.

### D3 - Answer the AVB question by the flash itself

The SMC key-store contents cannot be read statically, so the stock AP's
`vbmeta` (flags=0, verification enabled) is the test. A success prints
`[AVB 2.0] authentication success`; a mismatch prints
`AVB pubkey is not matched with vbmeta`.

### D4 - Stock first, LineageOS second

One variable at a time: a LOS failure over a known-good stock base is a
different, narrower problem than a LOS failure on an unproven base.

## Risks / Trade-offs

- [AVB rejects Samsung's signed `vbmeta`] -> that is a named, recorded outcome;
  the fallback is a permissive `vbmeta` or continuing with LOS.
- [The DT-stage abort persists even with stock DT/DTBO] -> then image content is
  not the cause, and this change's premise is falsified; record it and re-scope
  rather than patching around it.
- [The AP flash is large and can fail part-way] -> our BL is untouched, HOME_CSC
  (not CSC) avoids a wipe, and the EUB test point remains the recovery path.
- [Rollback / OS-version gates on the stock AP] -> our chain already carries the
  revision-gate stubs, so a matching-revision AP is acceptable.
- [The stock AP overwrites `vbmeta` with verification enabled] -> expected; that
  is the test.

## Migration Plan

1. Build v12 with the flash gate restored. **Done** — `image` 17/17, `packed`
   17/17, `session` can serve, `confinement` 25 runs / 0 unexpected, `selftest` rc=0.
2. Flash v12 (BL slot, Auto Reboot OFF).
3. Odin the stock NHZF5 AP + HOME_CSC.
4. Boot and record, explicitly watching for the AVB line and for `DT Load Fail`.
5. If the stock system is usable, attempt LineageOS over it.

Rollback: our BL is never replaced; EUB serves a known-good chain regardless;
`keys/` and the fused state are never touched.

## Open Questions

- Whether `SMC 0xC200101D`'s contents are derived from the fused key (static
  analysis cannot see into the SMC). Impact: none on the plan — step 3 answers it.
