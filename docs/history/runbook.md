# S21 FE (SM-G990E, S5E9840) Bootloader Unlock — Verified Runbook

Everything below was **verified working on this device** on 2026-10-09.
Read it top to bottom before retrying anything. Assets live in this
workspace; device state is recoverable at every step (EUB via test point
is always available; nothing is flashed until the IGYI3 downgrade).

> **Change pointer (2026-10-12):** the `repair-bootloader-patch-contracts`
> change cited below and elsewhere in this runbook **does not exist on disk**
> (`openspec list` reports no active changes; `openspec/changes/` holds only
> `archive/`). The active change is now
> **`openspec/changes/ground-up-unlock-state/`** — a pivot away from stubbing
> individual abl gates: materialise a real persistent unlock state so the
> platform's own gates pass, reduce the chain to the patches a fused custom key
> genuinely requires, and validate candidates through the EUB test point before
> any UFS write. The v9 artifact and the leaf-stub history below remain as
> evidence.

> **AGENT MIGRATION (2026-10-12):** read **`HANDOFF.md`** first. It is the
> current-state entry point: device constraints, the on-device state, the
> decompiled DT-stage trace, every falsified attempt (v8-v15), the working
> toolchain invocations, recovery path and prioritised next steps. This runbook
> below is the chronological log behind it.

## Control plane (2026-10-12): pinned serve root, no-fuse variant, session contract

**Pinned serve root.** `eub_session5.py` and `continue_chain.py` both resolve the
chain they serve through `eub_chain.py` — they used to disagree (`igyi3_out/` vs
`output/`), so a transcript could not prove which build was served:

```
python3 -c "import eub_chain; eub_chain.report()"
```

prints the resolved directory and a sha256 per component. `EUB_SERVE_ROOT=<dir>`
overrides it, e.g. to serve a candidate build:

```
EUB_SERVE_ROOT=output python3 -c "import eub_chain; eub_chain.report()"
```

**No-fuse build.** The OTP key-burn is already done, so a new build must be able
to skip it (a RAM-served candidate must not touch OTP at all):

```
PYTHONPATH=Exynos/scripts EUB_SHOULD_FUSE_KEY=0 python3 patch_9840.py <bootload.bin>
```

leaves `check_signature` as a plain `mov w0,#0; ret` with no OTP call; the default
`EUB_SHOULD_FUSE_KEY=1` still builds the fuse payload.

**Download-mode session contract.** A chain that cannot serve a session cannot be
flashed again, so it must never be committed:

```
python3 verify_chain.py session <bootload.bin|sboot.bin|tar.md5>
```

This is the static half only — session command table present, no patch site
overlapping it, and every function-boundary site returning SP-balanced. The
behavioural half (a session actually served) is a device observation made during
RAM validation. Current results: v8 tar `CANNOT serve` (stack imbalance at
`state_switch_app`); v9 tar, v10 tar, `igyi3_out` and stock `can serve`.

**Reduced chain (v10) — `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v10.tar.md5`.**
Built 2026-10-12 from a fresh NHZF5 split with the *reduced* patch set: the three
state-compensating stubs are retired (`patch_read_is_device_unlocked`,
`patch_avbops_state_reader_always_unlocked`, `patch_state_switch_app_noop`) and
the executor's allowed-bit gate is opened instead, so the stock executor performs
the real unlock. The fuse payload is off (`EUB_SHOULD_FUSE_KEY=0`; the fuse is
already burned).

**Tar structure matters.** Our older tars omitted the tar terminator; Samsung's
own tars carry it (body ends with the zero blocks, and their footer is
variable-length — 113 bytes for the NHZF5 BL tar — so footer length is *not* the
constraint). v10 is built to match: members + `2048` zero bytes +
`<md5>  <name>\n`. 24,491,077 bytes (body 24,491,008, footer 69), content-md5
`4189e519eb0ac3df61bf938d24a9bc4d`, whole-file md5
`2b74ffa46fe7f11ecda604c1cd9a28fe`, sha256 `1e424e935f9c61636f768402df43ede47996041c45732091e5fea516dcbac211`.
12 members in the Odin-accepted v8 order. Verified: `image` 17/17, `packed` 17/17
+ region identity, `session` can serve, `confinement` 19 runs / 0 unexpected,
`selftest` rc=0.

**RAM serve confirmed the core fix (2026-10-12 14:54).**
`EUB_SERVE_ROOT=output python3 eub_session5.py` served v10 from the test point;
the device came up in download mode and **Linux flash tool `connect` + `begin odin` both
succeeded** ("Successfully began an Odin session!") — the exact step the v8 chain
could not do. Raw transcript: `flash/los_stage2/eub_v10_serve_2026-10-12.log`.
Caveat learned the hard way: leaving a Linux flash tool session without `end` after a
successful `begin` wedges the download-mode session (`Failed to bulk read:
Connection timed out`); a fresh download-mode entry is then required.

**The UFS chain (v8) still cannot serve a session**, so Odin must talk to the
RAM-served v10 chain: EUB test point -> serve on this host -> move the cable to
the Windows machine (download mode runs from the battery) -> Odin BL slot.

## 2026-10-12 (newest): Secure Download is the real blocker — v13 bypasses it

**The stock AP flash failed at `super.img`, and the device showed
`SECURE CHECK FAIL : (SUPER)`** after Odin had already written the earlier
members. The gate that failed is **not** the OEM-lock gate (v12 opened that one) —
it is **Secure Download**, which the download screen had already reported:
`Secure Download : Enabled`.

- Strings: `SECURE CHECK FAIL : (%s)` @`0x154c80`, `SECUREDOWNLOAD` @`0x154ec0`,
  `DN_FAIL_SECURE_CHECK_FAIL` @`0x155308`, key source `PO_SECURE_CHK` @`0x153440`.
- With the fused custom key the expected image key is ours, so Samsung-signed
  images cannot pass. The failure path also names `VBMETA_SYSTEM` / `VENDOR_BOOT`
  / `INIT_BOOT` — it covers the **boot images** too, which is the likely cause of
  the DT-stage abort (and why v11's reader stub changed nothing).
- ONE bypass flag, `[0xbeed28]`, is read at ~16 secure-check sites (skipped when
  non-zero) and written in exactly one place (`0x6ed50`), gated by `0xa9e0` and
  valued via `0x668b8`.

**v13** = v12 + that bypass (`0x668b8` and `0xa9e0` stubbed to `mov w0,#1; ret`),
so `[0xbeed28] = 1` at boot and every secure check is skipped.
`flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v13.tar.md5` — 24,491,077 B,
content-md5 `f2dedebb0567d2085d5e0fdf3c72d9fe`, whole-file md5
`9b6592dc8b3a8d625fbbf02aff2e56bf`, sha256 `8009b975…`. Verified: `image` 19/19,
`packed` 19/19 + region identity, `session` can serve, `confinement` 28 runs /
0 unexpected, `selftest` rc=0. **Not yet on the device.**

## 2026-10-12 (latest): v10 FLASHED — Odin PASS; the unlock fires; every boot then aborts at the DT stage

**Flash result: Odin 3.1401, BL slot: `succeed 1 / failed 0`.** Full log saved
verbatim at `flash/los_stage2/odin_v10_flash_2026-10-12.log`. It clears three
separate blockers at once:

- `Checking MD5 finished Sucessfully` + `File analysis..` + `Total Binary size:
  29 M` — past the stall that killed the earlier Odin attempts (the tar
  terminator fix);
- `SetupConnection..` -> `Get PIT for mapping..` -> `NAND Write Start!!` — the
  download mode **served a session** (task 3.3's behavioural half, on-device);
- all 12 members written in order -> `RES OK !!` -> `succeed 1 / failed 0`.

**Boot 1 (plain): `Device state switched (N)`, then `ODIN MODE (DT Load Fail)!`.**
The executor took the unlock branch — the gate patch fired on the device.

**Boot 2 (plain): straight to `ODIN MODE (DT Load Fail)!`, no switch message.**
The state changed (no further switch was needed) and yet the DT stage still
aborts. **The DT-stage abort is therefore not a locked-state effect** — the
decider's stock reader still blocks it. This falsifies the premise behind
retiring the state readers (design.md D2).

**No boot loop** (unlike v8): the chain is deterministic — every boot lands in
download mode.

**The download screen has no lock field.** The full text is recorded verbatim at
`flash/los_stage2/download_screen_v10_2026-10-12.txt`; task 5.2's specified
readout does not exist on this abl revision. Notable lines: `CURRENT BINARY:
Samsung Official`, `WARRANTY VOID: 0 (0x0000)` (the warranty-bit stub held),
`KG STATE: Completed (00)`, `BUILD VERSION : G990BXXSNH?F9` (a G990B string on a
G990E device — to check against the flashed `up_param`), Chip ID
`<chip-id>`.

**Consequence:** the reduced chain was over-reduced. The next candidate restores
the decider's reader stub on top of v10 — the one site the evidence implicates
(`patch_avbops_state_reader_always_unlocked`; NHZF5 site `0x96cc8`, IGYI3
`0x93d40`).

**v11 built (2026-10-12) — `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v11.tar.md5`.**
v10 + that reader stub restored; the unlock gate patch and the running stock
executor are unchanged, and the OEM-lock reader (`0x641f8`) stays retired.
24,491,077 bytes, content-md5 `2093d3feb6873c0e2ee9fda2c916c591`, whole-file md5
`e26d7308066136a2068f3941b5daa29b`, sha256
`3cdaf186191372328ad1f06ea503028af1c5a049979cd929851f5040fab82e40`.
Verified: `image` 17/17, `packed` 17/17 + region identity, `session` can serve,
`confinement` 24 runs / 0 unexpected, `selftest` rc=0. In-tar confirmation:
`avb_state_reader @ 0x96cc8` stubbed, both gate branches patched, app entry stock.
**Not yet on the device.**

## 2026-10-12 (later): v9 contract-correct candidate built + verified — single-variable BL test record

**Artifact:** `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v9.tar.md5`
(24,489,028 bytes; content-md5 `0b6aaf1b1ab8813bab0da75a99140076`;
whole-file md5 `abffa17cb373bf74224a646331d59b9b`; **12 members in the exact
v8 member order** — the first v9 build (11 members, ours-first order, no
vbmeta) hung Windows Odin at `File analysis..`, so the tar was rebuilt as a
byte-faithful clone of the Odin-accepted v8 structure: v8 headers/order
verbatim, the 5 ours members swapped in at identical sizes, and the vbmeta slot
carrying `vbmeta.img` = the 256-byte flags=2 stub **already on the device**
(idempotent — the BL-only test still changes only the bootloader). The stock
`.lz4` members and their headers are byte-copies from the v8 tar.)

Built from a fresh NHZF5 split with the repaired patch set (state-switch no-op
now at the true entry `0x668e8`; AVB reader stores through the original `x1`;
EUB payload embedded in BL1 at +0x2000; `rb_count` 23). Host verification, all
green — reproduce with:

```
python3 verify_chain.py stock  <stock_sboot.bin>        # 14/14 anchors
python3 verify_chain.py image  <built_bootload_or_sboot> # 15/15 contracts
python3 verify_chain.py packed <v9.tar.md5> --expect-image <built_sboot.bin> --expect-members 11
python3 verify_chain.py confinement <stock_sboot.bin> <built_sboot.bin>  # 0 unexpected
python3 verify_chain.py selftest                        # v8 + corrupted-anchor fixtures must be rejected
```

Recorded results: stock 14/14; patched member 15/15; packed 15/15 + md5 footer
+ packed-region identity; confinement 28 diff runs / 0 unexpected (only the
recorded patch sites + the 471-byte signing-trailer tail); selftest rejects the
real v8 tar (stack imbalance + store to `0x1`) and the corrupted-anchor fixture.

### Single-variable device test record (for the V9 BL flash)

**Flash-tool status (2026-10-12):** Linux flash tool `begin odin` currently aborts with
`Failed to bulk write: Connection timed out (110)` against this chain —
reproduced across three fresh download-mode entries (device 009/010/011) and
NOT explained by host state (no `cdc_acm` binding, no `/dev/ttyACM*`, no
process holding the usbfs node). The device's Odin interface is healthy:
Windows Odin connected to this same v8 chain for the v7 and v8 BL flashes.
Conclusion: a Linux flash tool-vs-firmware handshake issue, not a device fault. **Flash the
v9 tar with Windows Odin (BL slot, Auto Reboot OFF).** No bytes were written by
the failed Linux flash tool attempts.

- **Changed variable:** the BL tar only — `..._v9.tar.md5`, Odin **BL slot**,
  Auto Reboot OFF.
- **Explicitly NOT changed in this test:** recovery, vbmeta, MISC, PARAM, and
  every system image. Do not flash anything else in this session.
- **Expected checkpoint:** an observable boot state *different* from the v8
  loop (e.g. the Lineage recovery UI, a fail screen naming a stage, a different
  reboot cadence) **or** the exact same loop quoted verbatim — either outcome
  is informative and must be recorded.
- **Rollback:** EUB test-point rescue (`eub_session5.py` serving the IGYI3
  chain) → re-flash `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v8.tar.md5`
  (or v6). Nothing in this test is irreversible.
- **Evidence to capture:** exact on-screen text, logo timing, reboot pattern,
  and the full Odin session output (save unmodified).

**Provenance (change tasks 4.1/4.2):** see `flash/los_stage2/RECOVERY_MANIFEST.md`.
The on-device recovery is byte-identical to the standalone `flash/recovery.tar`
and is a DIFFERENT build from the LOS zip's `recovery.img`; do not treat the
zip recovery as evidence about the flashed one. Per its own metadata, the ROM
writes `boot`/`dtbo`/`vbmeta`/`vendor_boot` and block-updates the dynamic
partitions on install.

**Read-only console probe (change task 4.3) — DONE 2026-10-12, zero device writes.**
Raw log saved unmodified: `flash/los_stage2/cdc_probe_2026-10-12.log`.
Findings on the current (v8) chain in download mode:
- `ATQ0\r` -> `OKAY` (console alive, as previously verified).
- `DVIF\r` -> 214 bytes: `@#MODEL=SM-G990E;UN=2C07224585CE1AEBB3A6;
  CAPA=128;VENDOR=MICRON  MT128GAXAT2U31  0006;FWVER=0006;PROV=PASS;
  SALES=INS;VER=G990EXXSNHZF5;DID=20<did>;TMU_TEMP=38;
  NAD_TEMP=40;@#`. Confirms device model, INS region, and an abl-reported
  firmware version `G990EXXSNHZF5`.
- `SOD\r` -> no immediate response. The SOD dump path needs its request-block
  framing (SOD then a 0x400-byte block then SODSTART/SODTEST/SODEND), which is
  not yet verified; it was NOT pursued further rather than guessing a block.
- `PROMPT` was deliberately not sent (it exits the console).
- No reset cause / boot log was obtainable from the console in download mode;
  the x7 log-upload path remains the fallback for boot-time evidence.
- **Operational consequence (observed):** after this probe, a following Linux flash tool
  `begin odin` failed with `Failed to bulk write: Connection timed out (110)`.
  The `SOD` command moves the abl's RX pipeline into a receive-wait for its
  0x400-byte request block, so subsequent bulk writes are misparsed/time out.
  A fresh download-mode entry (force restart) clears it. Do NOT send console
  commands (especially `SOD`) in the same download-mode session that will
  serve Odin.

## 2026-10-12: v8 quantified — two ABI defects found in OUR patches; misc tar REJECTED; all claims downgraded to evidence

**Change governance:** this section recorded the verified root-cause
work attributed to OpenSpec change `repair-bootloader-patch-contracts`
(proposal/specs/design/tasks in `openspec/changes/repair-bootloader-patch-contracts/`).
**Correction (2026-10-12):** that change directory does not exist on disk; it is
superseded by `openspec/changes/ground-up-unlock-state/` (see the change pointer
at the top of this runbook). All earlier "root cause" claims in this runbook are
demoted to evidence until re-validated by the binary contract validator + a
controlled test.

### The two verified v8 ABI defects (host-side, byte-exact)

Both were reconstructed from the stock NHZF5 `bootload.bin` and the
packed v8 `sboot.bin` (bootload segment at +0xEC000):

1. **State-switch no-op — stack corruption.** Stock NHZF5 function entry:
   `0x668e8: sub sp, sp, #0x450`; `0x668ec: adrp x0, ...`;
   `0x668f0: stp x29, x30, [sp, #-0x30]!` — and its epilogue
   (`0x66a80/0x66a84`: `ldp x29, x30, [sp], #0x30; add sp, sp, #0x450`)
   restores BOTH allocations. v8 wrote `movn w0,#0; ret` at `0x668f0` —
   so every call through the true entry `0x668e8` first executes
   `sub sp, sp, #0x450` and then returns WITHOUT restoring it. The
   caller resumes with SP off by 0x450 every time the function runs.
   Defect class: ENTRY-OFFSET drift (`xref - 0x12C` landed on the
   `stp` at 0x668f0; the true entry is 0x668e8, i.e. `xref - 0x134`).
2. **AVB unlock-state reader — wrong output target.** Deployment target
   `0x96cc8` is `f("%s handler", ..., out_ptr x1)` shape: the function
   must write the caller's out byte through x1 and return the status in
   w0. Callers at `0x97718`/`0x97764` pass `x1 = &local` and test
   `cbz w0` then `ldrb [local]`. v8's fragment was
   `stp x29, x30, [sp, #-0x10]!; mov w1, #1; strb w1, [x1]; ...; ret` —
   `mov w1, #1` zeroes the upper half of x1, so `x1` becomes
   `0x0000000000000001` and `strb w1, [x1]` writes to address `0x1`,
   NOT to the caller's out byte. Defect class: argument clobbered
   before use.

Both defects existed in the flashed v8 artifact. They are necessary
repairs; neither is claimed sufficient for a successful boot — the
v8 boot loop is exactly the kind of undefined-behavior outcome such
ABI violations produce. The runbook no longer treats the loop as proof
of any specific downstream failure (stale BCB, kernel handoff, DT).

### Odin "Unassigned file" = host artifact failure (no partition write)

The 2026-10-11 misc-clear experiment (AP slot `misc.img`) was rejected
by Odin as `misc.img -> Unassigned file`. That message means Odin could
not map the member name to a PIT partition for this device; nothing was
written to any partition. Do NOT rename the member blindly, and do NOT
flash with Re-Partition enabled. If a partition write is ever needed
beyond BL/AP artifacts already mapped by a verified Odin tar, retrieve
+ parse the device PIT first and cite the proven mapping.

### Quarantined artifacts (evidence/rollback reference only)

- `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v6.tar.md5` — the proven
  download-mode-serving rollback chain (IGYI3-based). EUB rescue
  (`eub_session5.py`) serves the equivalent in RAM.
- `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v8.tar.md5` — includes the
  two ABI defects above. Evidence only; do not flash as a fix.
- `flash/los_stage2/AP_misc_clear.tar.md5` — Odin rejected it
  ("Unassigned file" — no partition mapping verified). Do not flash.
- `flash/los_stage2/recovery_vbmeta.tar` — stays ON the device exactly
  as flashed; its recovery image does NOT match the LOS zip's
  `recovery.img` (byte mismatch observed 2026-10-12) — provenance
  unresolved until the manifest (task 4.1) says otherwise.

### Verified facts kept from the earlier analysis

- Download mode (Vol+ + Vol- + cable) works on the current device chain
  (v8), and Windows Odin flashed the v8 BL tar successfully.
- The BootROM fuse points at our key slot 2 (permanent); keys/ +
  keys_backup_20261009/ are irreplaceable. Never flash stock-signed BL.
- Never take One UI OTAs (their BL components are Samsung-signed).
- The v7-era on-device observation: "Device state switched (11)" before
  the download screen, traced to the state-switch executor printing via
  `0x668f0-`-region code; v8 then suppressed that screen — while
  introducing the entry-offset defect above.
- `exynos_read_is_device_unlocked` mode-0/1 distinction, the
  SEANDROIDENFORCE-vs-enforcing trailer check, the UFDT/DT-bit flow, and
  the download-mode CDC console (`ATQ0` -> "OKAY" verified 2026-10-11;
  dispatcher 0x2add4; commands ODIN/PROMPT(exit!)/DVIF/SOD*/AT+ENGMODES/
  @#AuToTEst@#/FPGM/SECCMD1+2) remain valid static/observed evidence.


**Diagnostic console notes (2026-10-11, mapped from the v8 abl):** the
download-mode CDC-ACM interface (04e8:685d, EP 0x81/0x82 IN, 0x01 OUT)
is the abl's diagnostic console. `ATQ0\r` -> "OKAY" (verified live).
Command set (dispatcher 0x2add4): `ODIN` (binary odin session mode),
`PROMPT` (EXITS the console - do not send casually), `DVIF` (device
info), `SOD`/`SODSTART`/`SODTEST`/`SODEND` (the Storage Offline Dump
protocol: PrObE/PreAmBle/DaTaXfer/PoStAmBlE/AcKnOwLeDgMeNt/PoWeRdOwN,
hex-ASCII offsets, streams storage reads back over EP 0x81),
`AT+ENGMODES=<mode>` (the ESS commands, bl_ess_command),
`@#AuToTEst@#`, `@#AuToTEstRst@#` (reboot 0x4e), `FPGM`, `SECCMD1/2`.
The upload/log-dump path is real in this abl (`cmd_upload`, `do_upload`,
`call_do_upload`, `is_upload_available`, the `Gadget Serial` / `SEC_UPLOAD` USB
gadget), but the trigger previously recorded here as "Vol- + Power x7" was
**never verified** ("still untriggered on this chain"). The binary's own
upload-cause table names the real triggers: cause `5` = `User Press Pwrkey 7s`,
cause `0xc` = `Forced Upload by Key`, cause `0xb` = `CP Crash` — so "x7" is almost
certainly **"Power key held 7 seconds"**, not "7 presses". `is_upload_available()`
(`0x74e70`) gates it, and `FMM Lock is On, upload mode is not Allowed!` /
`fmm_lock_upload` show FMM lock can refuse it outright. A second route is the
abnormal-reset counter (`RESET_COUNT`, `sec_debug.upload_count`, `FORCE_UPLOAD`).

**Permanent caveats (the One UI reality on this phone):**
- The BootROM fuse is burned to OUR key (slot 2), irreversible. The
  bootloader can NEVER be stock again; every future BL change must be
  built + our-key-signed from this workspace (keys/ +
  keys_backup_20261009/ are irreplaceable — keep forever).
- NO One UI OTA updates, ever: OTAs ship Samsung-signed BL components
  which the fused BootROM rejects. An OTA will fail or write an
  unbootable BL (recoverable only via the EUB test-point rescue +
  re-flashing flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v8.tar.md5).
- The recovery partition currently holds the LineageOS recovery (works
  for factory resets); a stock-recovery restore tar can be built from
  flash/NHZF5_rescue's AP tar on request.
- The on-device vbmeta is the flags=2 verification-disabled one;
  harmless on this chain (all verification is stubbed anyway).

## 2026-10-10 (late night): v7 flashed FULL (Windows Odin) -> STILL "(DT Load Fail)" -> TRUE ROOT CAUSE FOUND: the state-switch executor app — v8

The user flashed the full v7 BL tar via Windows Odin (ALL 12 members,
incl. tzsw/keystorage/harx + the stock .lz4 pass-throughs), then
`recovery_vbmeta.tar` (LOS recovery + flags=2 vbmeta) — the device is
now the fully era-matched v7 chain. Result: One UI does not boot,
recovery does not boot, every attempt -> "ODIN MODE (DT Load Fail)".
NEW on-device evidence: a red screen **"Device state switched (11)"**
before the download screen.

That message names the culprit: the abl's unlock/relock **state-switch
executor app** (NHZF5 `0x668f0`; the IGYI3 0x65a70-family). Full static
decode (disassembly, IGYI3 + NHZF5 identical flow):

- The app (invoked from the boot app table, no bl callers) compares the
  **cached device state** (the `0x1f7b0`/`0x1f7f0` state-cache reader —
  **the function the v5 patch force-returns "unlocked"**) with config
  bit 3 ("OEM unlock allowed", bit table @0xbeee30):
  locked+bit3 -> executes the UNLOCK; **unlocked+!bit3 -> executes the
  RELOCK**; else returns -1 (no-op).
- An execution: writes the BCB
  `recovery\n--wipe_data\n--reason=bootloader_unlock\n--locale=en_US`,
  **sets the DT-error bit 0x80000 via the accumulator setter
  (NHZF5 0x5d878 / IGYI3 0x5bd18)**, reports the stage abort, writes the
  TRUE state, and displays "Device state switched (%d)" with a
  persistent switch counter (global 0xbed838 -> param +0xa84 via
  0x629d8). **(11) = the 11th execution** — one per boot attempt since
  the v5 flash. The set DT bit makes the UFDT main skip the whole DTBO
  phase -> "(DT Load Fail)" -> download mode — for ANY image, ANY abl
  generation, ANY AVB state. That is exactly why v5/v6/v7 all behaved
  identically: the v5 state-cache patch created a permanent
  "unlocked-but-OEM-unlock-disallowed" mismatch -> a RELOCK every boot.
  (The v5 load-address + v6 enforcing analyses remain correct — they
  were real gates — but this app re-aborted the boot after them.)
- The BCB now in MISC says recovery+wipe (written 11x, idempotent), so
  the next successful boot goes to the recovery — which is the goal
  anyway; the LOS recovery will offer/perform the data wipe (required
  for LOS regardless).

**v8 = v7 with TWO state-machinery changes (the 11-patch set becomes:
minus the v5 state-cache patch, plus the app neutralizer):**

1. The `0x1f7b0` state-cache reader restored to STOCK. Its remaining
   live consumers are harmless: the 0x641e0 state-diff getter (stock
   values), 0x96d2c (dead code behind the head-patched ops variant).
   Every boot gate is independently forced by its own patch (the
   `0x641d8` mode-0 wrapper, the `0x96cc8` avbops head).
2. `patch_state_switch_app_noop`: the app returns -1 immediately —
   the exact value the stock app returns in every non-switch case (the
   app-table runner provably handles it: every stock-locked device hits
   it on every boot). No executor can ever run -> the DT bit is never
   set by it -> the DTBO phase finally runs.

Build proven + reproducible: `patch_9840.py` (updated) applied to the
stock NHZF5 bootload == the v8 member byte-identically (code region);
rebuilt via `build.py s5e9840 ../keys <split_dir> 23`; v8 sboot verified
in-tar (reader stock / app `movn w0,#-1; ret` / avbops head / enforcing
off / OEM wrapper / rev checks / fuse payload all present).

Artifact: `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v8.tar.md5`
(24,494,148 bytes; content-md5 16169062732d169e2451c466801ba0f2; built by
in-place sboot.bin replacement of the v7 tar + fresh md5 footer; diff vs
v7 confined to the sboot member: the two edits + re-randomized ECDSA
sigs). Staged `flash/BL_custom/sboot.bin` refreshed. **v7 kept as
rollback** (it IS the on-device chain now).

**Flash flow (v8) — Windows Odin, BL slot ONLY (the AP slot is already
correct on the device: LOS recovery + flags=2 vbmeta):**

1. Download mode (Vol+ + Vol- + cable) -> Odin, Auto Reboot OFF:
   BL slot `BL_G990E_CUSTOM_KEY_UNLOCK_v8.tar.md5` -> Start -> PASS.
2. Power off. Then EITHER plain power-on OR hold Vol+ + plug the cable:
   the pending BCB makes the first boot go to the recovery either way —
   expect the **LineageOS recovery** (it may perform the data wipe the
   BCB requests — expected and required for LOS).
3. `adb sideload flash/lineage-23.2-20260904-UNOFFICIAL-r9s.zip` ->
   wipe data (if not already done) -> reboot -> LineageOS ->
   Magisk-patch the LOS boot.img.

Rollback: re-flash `BL_G990E_CUSTOM_KEY_UNLOCK_v7.tar.md5` (or v6) —
the EUB test-point rescue remains available at every step.
Diagnostic if v8 still fails: flash the NHZF5's own stock recovery.img
as the AP-slot tar (build on request; source
flash/NHZF5_rescue/BL...tar.md5) — if even that fails with the
executor dead, the remaining suspect is the genuine image-load path
and the failure finally means something new (report the exact screen).

## 2026-10-10 (night): v6 flashed, NO change -> the generation-gap pivot: v7 (NHZF5-based chain)

The v6 flash PASSED and changed nothing: every recovery combo still fell
back to "ODIN MODE (DT Load Fail)". Three verified patch sets (v4 state
gates, v5 cache/ops state readers, v6 SEAndroid/TIMA enforcing) with
zero behavioral change is the systematic signal that the failing path is
none of them — and one variable remained untouched: **the abl itself is
one firmware generation older than everything else on the device**
(IGYI3 / One UI 7 abl vs NHZF5 / One UI 8 images + the One UI 8-era
LOS). Confirmed hard evidence of the gap: the NHZF5 boot.img is header
v3 (no in-image DTB — unparseable by the IGYI3 DT flow), the param
table layout shifted (the DT-bit recovery marker's only live setter is
the param-0 poll, and the recovery image load at 0xf7f0 is gated on
that bit — if the marker never sets, EVERY boot attempt takes the
normal path and dies identically on the v3 boot.img).

**PIVOT: build the chain from the NHZF5 BL tar** (the device's own
firmware generation — the same abl generation the community's working
flow runs). The full toolchain works on it:

- NHZF5 BL tar -> lz4 -d the 12 members -> split.py s5e9840 (same
  segment layout, bootload segment at +0xEC000, same sizes).
- The 11-patch set dry-run: 8 of 10 string-anchored patches apply
  DIRECTLY (identical strings + function structures). Two
  derived-address patches needed tolerant asserts (the functions moved:
  state-cache reader 0x1f7f0 -> 0x1f7b0, enforcing query 0x618d0 ->
  0x63430; inner instructions byte-identical, asserts now check the
  inner words: 0xAA0003E2 mov x2,x0 / 0x6B1F001F cmp w0,wzr).
- Fuse payload anchors resolve on the NHZF5 (cm_otp fns at 0xb468 /
  0xb7d8, +8 vs IGYI3) — both verified as real functions by
  disassembly before use. The fuse is already burned (our key, slot
  2) so the re-burn is a no-op; the payload doubles as the dead
  check_signature.
- bl1: our EUB payload (9840_boot_custom_key_ours.bin, 367 B) embedded
  at +0x2000 (region verified zeros) -> build.py s5e9840 ../keys
  /tmp/opencode/nhzf5_out 23 (rb_count 23 = the NHZF5's own, matches
  the device efuse) -> all patches verified in the packed sboot at
  +0xEC000 offsets.

Artifact: `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v7.tar.md5`
(24,494,148 bytes; content-md5 f527749a240bc46d111b1c6c414f3084; built
from scratch: 5 ours-raw (the NHZF5 chain, our-key-signed) + the
NHZF5's 7 stock .lz4 pass-throughs, ustar, Samsung md5 footer as the
last 68 bytes; round-trip verified). **v6 is KEPT as the rollback**
(the IGYI3-based chain that reliably serves download mode).

**Flash flow (v7)** — download mode (Vol+ + Vol- + cable) -> Odin, Auto
Reboot OFF: Start 1 BL slot `BL_G990E_CUSTOM_KEY_UNLOCK_v7.tar.md5`
-> PASS. Start 2 AP slot `flash/los_stage2/recovery_vbmeta.tar` ->
PASS (REQUIRED: the v7 tar's vbmeta member restores the stock NHZF5
vbmeta flags=0 whose BL descriptors hash the Samsung images, not ours
— the flags=2 no-descriptor vbmeta removes all hash checks; it also
re-affirms the LOS recovery). Then:

1. Plain power-on -> expect One UI 8 (the NHZF5 abl natively parses
   the v3 boot.img).
2. Power off -> hold Vol+ + plug the cable -> expect the LineageOS
   recovery -> `adb sideload` the LOS zip -> wipe data -> LineageOS ->
   Magisk-patch the LOS boot.img.

Rollback: if v7 does not boot at all, EUB test-point rescue
(eub_session5.py serves igyi3_out = the v6 chain over USB) -> download
mode -> re-flash `BL_G990E_CUSTOM_KEY_UNLOCK_v6.tar.md5`.
Diagnostic (only if the recovery still fails on v7): flash the NHZF5's
own stock recovery.img (extracted at /tmp/opencode/nhzf5/recovery.img;
a tar can be built on request) — the exact image the v7 abl ships with;
if even that fails the recovery-request path (the DT-bit marker /
param-0) is the remaining suspect and the ×7-log / param-trace becomes
the next step.

## 2026-10-10 (later): BOTH DT-fail root causes found (byte-exact) — v6 chain

The v5 flash PASSED but changed nothing: plain boot and all Vol+ recovery
combos still fell back to "ODIN MODE (DT Load Fail)". That killed the
lock-state hypothesis and forced a full re-trace with corrected decodes.
Eliminated with hard evidence: the AVB/SVB (reason 11 has its own
"ODIN MODE (SVB Fail)" screen — never shown), the header-version
rejection (the abl dispatches v2 -> 0xfb80 AND v3 -> 0xfb90), the DTBH
rev match (LOS and factory tables encode identical ranges, both byte
orders handled), the DPM mismatch (IGYI3 vs NHZF5 dpm.img have IDENTICAL
node/prop structures — only long property values differ, harmless to a
structural merge), and the vbmeta (flags@0x7C = 2 confirmed byte-exact
on the flashed image).

**Plain boot root cause:** the NHZF5 (One UI 8) boot.img is header v3
(GKI layout — no DTB in the boot image; verified: header_version=3 at
+0x28, header_size=1580). Our IGYI3-era abl loads it (v3 path at 0xfb90
also pulls VENDOR_BOOT to 0x98000000) but its DT flow needs the DTB the
v2 images carry in-image; the DTB blob global stays unset -> 0x5ce60
("DTB") fails the magic check -> "DTB LOAD FAIL" -> reason 12. The
stock NHZF5 recovery.img and IGYI3 recovery.img are v2 — only the BOOT
image moved to v3. Fix for One UI boots: flash the IGYI3 AP (v2
images, matched to our abl — now unblocked since all flash gates are
dead in our chain). NOT required for the LOS goal: the LOS recovery
and LOS system boot images are the v2 family.

**Recovery root cause (THE goal blocker):** the boot-image loader
(0x42028 v2 scatter_load) calls 0x65850 at 0x422ac, which validates
the Samsung trailer: 16 bytes at [image + cumulative page-aligned
section end] must be "SEANDROIDENFORCE". Byte-exact verification:

- IGYI3 stock recovery: trailer at 0x356e000 == computed end — PASS
- NHZF5 stock recovery: trailer at 0x329b000 == computed end — PASS
- LOS 23.2 recovery: NO "SEANDROIDENFORCE" anywhere; an AVB0 blob
  sits at the computed 0x3649000 — the community build used the
  AOSP/avbtool layout, not the Samsung trailer layout.

On mismatch the abl prints "[TIMA trusted boot]: SEAndroid MAGIC
failure (recovery.img)" (0x153f98) and queries the SEAndroid/TIMA
enforcing flag ([0xbea63c], static data — Samsung ships enforcing)
via 0x618d0. Enforcing routes both the match AND mismatch paths to
0xaaa8 -> the TIMA SMC (0xC200101D) -> TZ-side trailer signature
verification -> reject -> the DT-fail abort. That is exactly why the
community flow works: truly-unlocked devices run the "orange" state
(enforcing off) and take the lenient path. v5's state patches never
touched this flag. (The enforcing path is equally fatal for STOCK
images on our chain: the TZ would verify Samsung signatures against
our custom-key TrustZone.)

v6 = v5 + one surgical patch (2 words), `patch_seandroid_enforcing_off`
in patch_9840.py (now the 11-patch set): 0x618d0 -> `mov w0,#0; ret`
("not enforcing"). Scope verified: 0x618d0's ONLY two callers are the
trailer-check paths (0x658ac/0x65928). Effect: both paths take the
lenient continuation — identical to an unlocked device — for stock
and custom images alike.

Applied to the proven v5 bootload (diff = exactly 2 words), rebuilt
(`build.py s5e9840 ../keys ../igyi3_out 23`), verified in the packed
sboot.bin at +0xEC000+0x618d0 with all v4/v5 patches intact.

Artifact: `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v6.tar.md5`
(24,504,388 bytes; content-md5 fbbef5995ac6c1863e8e909806e05e95;
in-place member replacement of the v5 tar, 5 ours == rebuilt
byte-for-byte, 7 stock pass-throughs unchanged, Odin md5 footer
identical). **v5 removed — flash v6 only.** Staged member copies in
flash/BL_custom/ refreshed.

**Flash flow (v6)** — power off -> download mode (Vol+ + Vol- + cable)
-> Odin BL slot: `BL_G990E_CUSTOM_KEY_UNLOCK_v6.tar.md5` -> Start ->
power off -> hold Vol+ + plug the cable -> LineageOS recovery ->
`adb sideload flash/lineage-23.2-20260904-UNOFFICIAL-r9s.zip` -> wipe
data -> LineageOS -> Magisk-patch the LOS boot.img. (No re-flash of
recovery_vbmeta.tar needed — the recovery partition and the flags=2
vbmeta are already in place.)

Note: the PLAIN power-on will still show "DT Load Fail" until the
NHZF5 v3 boot.img is replaced — that is the separate v3-image issue
above, expected, and irrelevant to the LOS flow (the LOS images are
v2-family and the trailer check is now lenient).

## 2026-10-10: "ODIN MODE (DT Load Fail)" root-caused from the binary — v5 chain

Both the LOS recovery boot (Vol+) AND a plain power-on (the stock NHZF5
boot.img + the stock NHZF5 dtbo — a factory-matched pair that boots on
every stock device with this abl) fell back to download mode with
"ODIN MODE (DT Load Fail)". A factory pair cannot fail on content, so
the failure was environmental. Full static trace (no device needed):

- The screen = reason 12: the boot flow at 0xfa34 masks the DT-error
  bit (0x80000) from the accumulator (getter 0x5bd08 / setter 0x5bd18)
  and calls the UFDT main (0x5d010), which SKIPS the whole DTBO phase
  (`cbnz w19, 0x5d268` -> the "DTBO LOAD FAIL" block) when that bit is
  pre-set. Image-load aborts are reported through the boot stage
  machine (0x41ba8; stages 4/5 = the image/DT stage) as "(DT Load
  Fail)".
- The bit has only three setters: the stage-4/5 abort report (0x2f78),
  Samsung's own unlock/relock state-switch executor (0x65b18 — gated
  on a request flag, not running on plain boots; it writes the BCB
  "recovery\n--wipe_data\n--reason=bootloader_unlock" and the TRUE
  state via 0x1f828), and a dead-code FOTA check (0x1512c — zero
  callers). So the plain-boot failure was a real image-load abort.
- **ROOT CAUSE**: the boot/vendor_boot image load-address decider at
  0x94740 (compares the partition name against "boot" -> 0x94000000 /
  "vendor_boot" -> 0x98000000) calls a SECOND
  exynos_read_is_device_unlocked implementation at 0x93d40 (self-named
  in its "%s : RPMB is not initialized yet" print; fail-closed to
  locked). It reads the CACHED TRUE state via 0x1f7f0 (global
  [0x7baf3c]: 1=locked, 0=unlocked) — a path NO v4 patch touched,
  because the decider never calls the 0x621c0 wrapper we patched.
  LOCKED -> the 0x945c0 validation path, which with the flags=2
  no-descriptor vbmeta returns NO load address for ANY image (stock
  boot.img and LOS recovery alike) -> the DT stage aborts -> the
  screen. This is also exactly why the community flow works: on
  truly-unlocked devices 0x93d40 reports unlocked and the validation
  is skipped.

v5 = v4 + 2 surgical patches (9 words), verified by disassembly;
`patch_9840.py` now carries the full 10-patch set:

1. `patch_state_cache_read_always_unlocked`: 0x1f7f0 ->
   `str wzr,[x0]; mov w0,#0; ret` (always unlocked + success; covers
   mode-0's raw read at 0x622ac, the state-switch UI at 0x65a70/0x65b48,
   and the 0x93da4 path).
2. `patch_avbops_state_reader_always_unlocked`: 0x93d40 ->
   `stp; mov w1,#1; strb w1,[x1]; mov w0,#0; ldp; ret` (always
   unlocked; opens the boot/vendor_boot load gating directly).

Applied surgically to the proven v4 bootload (the two sites were
original/unpatched; diff = exactly 9 words), then rebuilt:
`cd Exynos && python3 scripts/build.py s5e9840 ../keys ../igyi3_out 23`.
Verified on the packed sboot.bin: the 9 words at +0xEC000+0x1f7f0 /
+0xEC000+0x93d40, the v4 patches intact (+0x14e1e0/+0x14e2b8).

Artifact: `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v5.tar.md5`
(24,504,388 bytes; content-md5 9542d5985038db0066f4d88b4588bbae; built
by in-place member replacement of the v4 tar: the 5 our-images == the
rebuilt igyi3_out chain byte-for-byte, the 7 stock pass-throughs
unchanged, Odin md5 footer format identical; round-trip verified). The
staged member copies in flash/BL_custom/ refreshed to the v5 chain.
**v4 removed — flash v5 only.** (The v4 chain is reproducible by
reverting the two patches and rebuilding.)

**Flash flow (v5)** — power off -> download mode (Vol+ + Vol- + cable;
the on-UFS v4 chain serves it, gates open) -> Odin, Auto Reboot OFF:

1. BL slot: `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v5.tar.md5`
   -> Start (wait for PASS).
2. Same session, AP slot: `flash/los_stage2/recovery_vbmeta.tar`
   -> Start (idempotent; re-affirms the flags=2 vbmeta + the LOS
   recovery and removes the never-explicitly-confirmed PASS
   uncertainty. If it sticks at SetupConnection: power off, re-enter
   download mode, flash it alone).
3. Plain power-on (no keys): the stock NHZF5 boot.img should finally
   load -> One UI (the factory-matched dtbo pair gets used; an
   unlocked-state boot warning splash is possible).
4. Power off -> hold Vol+ + plug the cable: LineageOS recovery ->
   `adb sideload flash/lineage-23.2-20260904-UNOFFICIAL-r9s.zip` ->
   wipe data -> LineageOS -> Magisk-patch the LOS boot.img.

EUB test-point rescue unchanged and available at every step.

## 2026-10-09 (evening): v2 BL FLASHED — OEM-lock gate patched, v4 chain

The Windows Odin flash of `BL_G990E_CUSTOM_KEY_UNLOCK_v2.tar.md5` (BL slot)
SUCCEEDED — the custom-key chain is on UFS and the fused BootROM verifies
it. Consequences confirmed on-device:

- Stock firmware flashes (IGYI3 / NHZF5_rescue dirs) are now blocked with
  "Custom Binary (SUPER) Blocked By OEM Lock" — EXPECTED: with the ROM key
  selector on our key slot 2, Samsung-signed images fail verification and
  count as "custom"; the device's OEMLOCK state is still LOCKED, and
  custom AP-class flashes (super/recovery/vbmeta/...) are rejected. The
  stock-restore path is dead by design; OUR chain is the only way forward
  (and it is already on UFS).
- The `recovery_vbmeta.tar` AP flash stuck at Odin "SetupConnection.." —
  a session-state issue after a BL flash (the RAM bootload's post-BL-write
  state), NOT a format issue; the stock attempts after it DID connect
  (the rejects came from the running bootload). Fresh download-mode entry
  fixes it (see the flow below).

Root cause of the rejects: the OEM-lock flash gate in `_pit_flash_binary`
@ bootload 0x5f6b8-0x5f6c0: `bl 0x621c0(0)` then `cbz w0 -> 0x5f7a8` ->
the "Custom Binary(%s) Blocked By OEM Lock" reject print. 0x621c0 =
`exynos_read_is_device_unlocked` (mode 0 = unlock-state read, fail-closed
default 0 = locked; mode 1 = PERSISTENT-partition state-byte read). The
sibling erase/format gate at 0x5e9f8 shares the reject block, and the
BOOT-time gates read the same function (0x6562c/0x6582c lowercase
"Custom binary blocked by OEM Lock" + 0x66304/0x6634c/0x663e0 locked ->
verify-fail) — that was the runbook's "remaining known risk" for the LOS
recovery boot. One patch kills all of them.

**Fallback ladder step 1 APPLIED** — `patch_read_is_device_unlocked` in
`patch_9840.py` (the documented fallback): 2 instructions in mode 0,
both `mov w19, #1` (always report UNLOCKED):

- 0x621e0: `mov w19,#0` (fail-closed default) -> `mov w19,#1`
- 0x622b8: `sub w19,w20,w19` (= 1 - stored) -> `mov w19,#1`

Mode 1 (the PERSISTENT byte read, the OEMLOCK machinery) is UNTOUCHED —
fallback ladder step 2 (flashing the OEMLOCK partition) stays available.
Anchor: the mode-1 "PERSISTENT" PIT-entry lookup adrp+add @0x62224
(string @0x152ae0, unique, single xref); asserts on the prologue
(0xd10843ff) and both original instruction words.

Rebuild (verified): surgical apply on the proven bootload.bin (import
patch_9840; patch_read_is_device_unlocked) — diff exactly the 2 words;
then `cd Exynos && python3 scripts/build.py s5e9840 ../keys ../igyi3_out
23`. Verified on the built sboot.bin: patched words present at
+0xEC000+0x621e0 / +0x622b8 (the bootload segment base is +0xEC000),
prologue + mode-1 path intact, bl1 payload intact at +0x2000, SLSI
sign-header (rb_count 23 = 0x17, type 4, fresh timestamp). All other
new-vs-old diffs are the re-randomized ECDSA (P-384) signatures — each
valid over its content — plus the updated header checksums. The full
from-scratch rebuild path now includes this patch (8-patch set in
patch_9840.py __main__).

Artifact: `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v4.tar.md5`
(24,504,388 bytes; content-md5 e1b37a0602a7310106dde3f1cece79e7; raw
members + Samsung-style `.tar` footer, round-trip verified: 5 ours ==
igyi3_out, 7 stock pass-throughs unchanged). v3 removed; **flash v4 only**.

**Flash flow (v4)** — the OEM patch only takes effect when the NEW
bootload RUNS, so the EUB session serves the v4 chain over USB and the
same Odin session gets both flashes:

1. EUB session (test point; `eub_session5.py` serves igyi3_out = the v4
   chain now) -> download mode.
2. ONE Odin session, Auto Reboot OFF: Start 1: `BL_G990E_CUSTOM_KEY_
   UNLOCK_v4.tar.md5` -> BL slot (writes the v4 chain to UFS). Start 2:
   `recovery_vbmeta.tar` -> AP slot (the RAM v4 bootload's OEM gate is
   open -> allowed).
3. If Start 2 sticks at "SetupConnection..": power off -> re-enter
   download mode (Vol+ + Vol- + cable — the UFS v4 chain serves it, its
   gate is open) -> flash `recovery_vbmeta.tar` alone. Another EUB
   session is the fallback for getting download mode.
4. Power off -> hold Vol+ while plugging in -> LineageOS recovery boots
   (every boot-time OEM gate now reads "unlocked").
5. `adb sideload flash/lineage-23.2-20260904-UNOFFICIAL-r9s.zip` -> wipe
   data -> reboot -> LineageOS; then Magisk-patch the LOS boot.img and
   flash it back for root.



## 2026-10-09 (later): Odin lz4 dialect — flash RAW members

Odin failed our first BL tar with "FAIL! LZ4 invalid": our `lz4 -9`
members used the modern frame dialect (no content-size field, 4MB
blocks), while Samsung's firmware lz4 uses their own dialect
(content-size field present, legacy byte order, BD=0x60 1MB blocks).
Rather than replicate Samsung's lz4 writer, our 5 built images
(sboot.bin, keystorage.bin, ldfw.img, tzsw.img, harx.bin) go into the
tar RAW (uncompressed) — Odin only decompresses `.lz4`-suffixed member
names; raw members are flashed as-is (the same way the community
recovery.tar/vbmeta_disabled.tar work). The 7 stock pass-through
members keep their original Samsung `.lz4` files (the exact bytes Odin
already wrote fine in the stuck session).

Artifact: `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v2.tar.md5`
(round-trip verified: raw members == igyi3_out build byte-for-byte).
The v1 compressed tar was removed.



The user clarified: the Windows Odin flash of the IGYI3 stock package was
STUCK at tzar.img with "KERNEL REV_CHECK FAIL : DEVICE 23 BINARY 18
(VBMETA)" shown on the device DURING the flash — it was not a post-flash
boot error. Revised understanding:

- The flash-time KERNEL REV check (same function as the boot-time one,
  anchored `KERNEL REV. CHECK FAIL. DEVICE:%d, BINARY:%d (%s)`) runs in
  the download-mode flash path on the tar's vbmeta member (its Samsung
  trailer RB 18 vs efuse 23) — the OLD RAM chain (4 patches) did not
  have it patched, so the BL-tar flash aborted around the vbmeta/tzar
  members. The BL members up to harx were written (incl. the stock
  IGYI3 sboot and the stock IGYI3 vbmeta); tzar/vddcal_fw/ssp were not;
  the AP/CP/HOME_CSC were NEVER flashed (device AP/CP = NHZF5 still).
- The fuse never burned (all sessions used the should_fuse_key=False
  build) — the BootROM still trusts Samsung's key, which is why the
  partially-flashed IGYI3 sboot boots far enough to show the KERNEL REV
  error at boot (same check, boot path).
- Our fuse-build chain patches this check family at BOTH flash time
  and boot — the plan is unchanged and now also explains the stuck
  flash.

**The IGYI3 vbmeta hashes the BL partitions** (parsed descriptors:
recovery, dtbo, prism, optics, boot, bootloader(=sboot), harx,
keystorage, ldfw, tzsw, vendor_boot, product, system, vendor —
BL-tar and AP-tar vbmeta.img are byte-identical). Our modified
our-signed BL images would fail the (UNPATCHED) AVB hash verification
at boot while a stock vbmeta is in the vbmeta partition.

=> FLOW REFINEMENT: flash the BL tar AND recovery_vbmeta.tar (the
flags=2 no-descriptor disabled vbmeta) in the SAME download-mode
session (Odin Auto Reboot OFF), with NO intermediate reboot. The
disabled vbmeta removes all descriptors -> no hash verification of
any partition -> our BL images and the LOS recovery boot clean.
The LOS recovery screen after Vol+ + cable is the single checkpoint
(burn + chain + AVB state all proven at once).



Question: do the LOS recovery/vbmeta need signing with our keys
(sign_android.py) before flashing them on the custom-key chain?

**Answer: no — flash the unmodified community images.** Evidence:

- The stock recovery.img/vbmeta.img trailer is Samsung's **SignerV3**
  format (the 0x100 "sig" slot holds UTF-8-encoded cert/text, not a raw
  signature) — not replicable without Samsung's signer.
- `Exynos/scripts/sign_android.py` was written for older RSA-type SoCs:
  its bootimg size parse reads `dtb_size` at +0x28, but this device's
  images are **AOSP v2 headers** (`header_version` at +0x28 — stock
  IGYI3 recovery.img included, SEANDROIDENFORCE confirmed at the true
  v2 content end 0x356e000). Running it would truncate the LOS
  recovery's recovery_dtbo (0xad800) and dtb sections.
- The gate that rejects unsigned REE images is `check_signature` (the
  st2r trailer check, `%s: There is no signature` / DN_FAIL_BLOCK_
  CUSTOM_BIN_OEM) — which our patch replaces with burn+`return 0`
  ("valid", unconditionally). With the trailer check dead, the flags=2
  vbmeta_disabled is the trust-root-passed vbmeta -> verification
  disabled -> custom boot/recovery accepted.
- Stock reference extraction: `flash/los_signed/stockref/` (recovery,
  vbmeta, vbmeta_system from the IGYI3 AP tar) for future analysis.

**Remaining known risk (accept + fallback):** ~~if the AVB result path
still enforces...~~ RESOLVED 2026-10-09 (evening): the flash-time gate
FIRED ("Custom Binary (SUPER) Blocked By OEM Lock" on the stock dirs
after the v2 BL flash) and the boot-time gates read the same function —
fallback ladder step 1 was APPLIED (`patch_read_is_device_unlocked`,
see the evening section above). Step 2 remains available:
2. Flash the `OEMLOCK` partition directly (it IS a partition — the
   name sits in the partition table alongside KNOXGUARD/SUPER/OMR/
   PRISM) with the unlocked state (format TBD via the OEMLOCK xref at
   0x5f7cc if needed); the mode-1 PERSISTENT byte read that this
   machinery uses was deliberately left unpatched.

Flash artifacts for the LOS stage stay as-is:
`flash/recovery.tar`, `flash/vbmeta_disabled.tar` (unsigned community
images), `flash/lineage-23.2-20260904-UNOFFICIAL-r9s.zip`.



The IGYI3 flash (task 4.2, done via Windows Odin) succeeded — no flash-time
`SW REV. CHECK FAIL` — but the device failed to BOOT One UI 7 with:

    KERNEL REV_CHECK FAIL : DEVICE 23 BINARY 18 (VBMETA)

That answers the design's boot-time open question: the flashed IGYI3
bootloader enforces the rollback count at boot (device efuse RB 23, burned
by One UI 8 — permanent silicon — vs IGYI3 vbmeta RB 18). The stock chain
cannot boot below RB 23, and the IGYI3 abl's official unlock path needs
server-delivered "unlock keys" (`ul_keys` via SMC), so no stock-based
path to an unlocked bootloader exists.

PIVOT (user-approved, irreversible): the toolchain's own "Optional key
fusing" flow. Built a NEW chain from the IGYI3 BL tar:

- `igyi3_in/` (decompressed IGYI3 BL images) -> `split.py` -> `igyi3_out/`
- `patch_9840.py` (project copy) now additionally patches the three
  BOOT-time rev gates, all starts verified by dual xref + stp prologue:
    - check_kernel_rev @ 0x648e8 (anchor `KERNEL REV. CHECK FAIL...` -0x114)
    - check_system_rev @ 0x643f8 (anchor `SYSTEM REV. CHECK FAIL...` -0xC4)
    - check_pit_rev    @ 0x64a70 (anchor `PIT RB count: BINARY:%d` -0x60;
      the FAIL string is referenced with its leading \n -> 0x153a80)
- `should_fuse_key = True`: check_signature @ 0x66538 is replaced by the
  fuse payload (adr -> our 32-byte efuse at +0x20, movz w1,#0x20,
  bl cm_otp_write_rom_sec_boot_key @ 0xb460, bl cm_otp_write_use_rom_
  sec_boot_key @ 0xb7d0, return 0) + both key-slot selectors patched to
  key slot 2. The fused value is byte-identical to the EUB payload's
  efuse at +0x130 (one key commitment; verified).
- bl1: EUB payload embedded at +0x2000 (region verified zero), then
  `build.py s5e9840 ../keys ../igyi3_out 23` — **rb_count 23** (matches
  the device efuse; the stock IGYI3 header says 18 which the payload/
  BootROM checks could reject). bl1 verified: rb_count 23, checksum,
  our st1/st2t/st2r pubkeys, hmac, efuse, payload intact.
- Flash artifact: `flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK.tar.md5`
  (original BL tar structure, our sboot.bin.lz4/keystorage/ldfw/tzsw/harx
  + stock pass-throughs; Odin md5 footer format replicated exactly —
  content padded to 512, md5, `<md5>  <name>.tar\n`). Round-trip verified
  byte-for-byte against the built chain and stock inputs.
- Session driver: `eub_session5.py` (full proven protocol + 'C' readiness
  + single writes + short-write continuation recovery, pointed at
  igyi3_out/).

THE BURN happens during the EUB session itself: the RAM chain's bootload
runs the fuse payload when it boots (seconds after the bootload upload).
After the burn the BootROM only trusts our key — flash our BL tar in the
SAME download-mode session, then reboot: our chain boots from UFS with
every gate patched off -> One UI 7 -> LOS recovery + vbmeta_disabled ->
sideload -> Magisk. Keys backed up (`keys_backup_20261009/`) — keep them
forever; EUB test-point rescue stays available regardless.



- Host workspace ready: `input/` (split inputs), `output/` (patched,
  our-key-signed chain), `flash/` (verified firmware assets), `keys/`
  (fresh signing keys), project copies `patch_9840.py`,
  `9840_boot_custom_key_ours.bin`.
- The EUB → patched-download-mode session is **proven end-to-end**
  (see `continue_chain.py` transcript: EPBL/BL2/Bootloader/EL3_MON/LDFW/
  TZSW all loaded, `[USB Booting Done]`, device in download mode
  `04e8:685d`).
- Next step: **flash IGYI3 (BL+AP+CP+HOME_CSC) via Odin** (task 4.2),
  then reboot → One UI 7, OEM unlock, recovery, ROM, Magisk.

## Host prerequisites (done once)

- udev rules in `/etc/udev/rules.d/51-android.rules` must give the
  `users` group access to **all three** Samsung modes:
  `04e8:1100` (EUB), `04e8:1234` (old DNW), `04e8:685d` (download mode).
  CachyOS has NO `dialout` group — use `GROUP="users"`.
- houston python deps (`coloredlogs`, `pyusb`, `pygments`, `libusb`)
  installed user-level; `cryptography` system package.
- Linux flash tool: `tools/flash-tool-linux-0.4.0-alpha/Linux flash tool/linux-x64/flash-tool shell`
  (CLI shell; GUI needs system `tk` package, not installed).

## Build (already done — only redo if rebuilding the chain)

1. `lz4`-decompress the 12 BL images into `input/` (11 are consumed by
   the splitter; `vbmeta.img` is extra).
2. `cd Exynos && python3 scripts/split.py s5e9840 ../input ../output`
3. `EUB_SHOULD_FUSE_KEY=0 python3 patch_9840.py ../output/sboot/bootload.bin` — project copy;
   the custom-key fuse is already burned, so never enable the fuse payload again
   with the extra `patch_check_sw_rev` (anchor `[EFUSE] RB count:
   device(0x%llx), flash image(0x%llx)\n\0`, delta -0x2C → resolves to
   `0x650d0`). `should_fuse_key` stays **False**.
4. **Patch the payload's efuse for OUR keys** (the shipped
   `9840_boot_custom_key.bin` embeds the REPO keys' efuse_4.bin at
   payload offset +0x130): `9840_boot_custom_key_ours.bin` = shipped
   payload with our 32-byte efuse
   (`hmac(our hmac.bin, our st1 pubkey[:136], sha512)[:32] XOR hmac key`)
   at +0x130. Embed it into BL1 at offset **+0x2000** (zero padding,
   code ends at +0x1643).
5. `cd Exynos && python3 scripts/build.py s5e9840 ../keys ../output`
   **BUT: bl1 must be (re-)signed AFTER embedding the payload** —
   `python3 scripts/sign.py ../output/sboot/bl1.bin ../keys st1
   --signing-type 4` — because BL1's inner header checksum
   (`sha512(bl1[0x10:])[:4]`) and st1 signature cover the payload
   bytes at +0x2000. Embedding after signing ⇒ `BL1 Checksum Fail`
   (observed, diagnosed).

## EUB session — the verified protocol

**Race + hardening (22:49 session, first failure):** the stage-3 completion
write raced the payload's USB re-init — the device re-enumerated BEFORE the
write landed (ENODEV, then the device dropped off entirely ~minutes later).
`eub_session5.py` is hardened: on a stale handle it re-finds + retries the
completion on the fresh handle (the payload polls the device-side endpoint
FIFO, so the completion can still land via the new enumeration), and a
30s bounded request watch bails early on a dead state. The five successful
sessions were on bus 1; the failure was on bus 5 (a different port, all
xhci) — prefer the same port used all day.


Two-phase. Tools: `eub_session3.py` (phase A+B) and `continue_chain.py`
(phase C; also recovers partial writes). Run as the normal user.

### Phase A: exploit (all on one handle)

1. Find `04e8:1100`, claim interface 0, **CDC setup**
   (SET_LINE_CODING 115200 8N1 + SET_CONTROL_LINE_STATE DTR|RTS).
   Requests only flow after DTR.
2. houston `send_payload(output/sboot/bl1.bin)` — the device asks
   `\neub:req:e9840000:bl1`; houston replies with the +512-declared-size
   DNW packet (deliberately leaves the upload 512 bytes incomplete).
3. houston `overwrite_iram` — exec pointer → `0x02024000`
   (= bl1@0x02022000 + payload@+0x2000). The ctrl write "doesn't return"
   (expected): the hijacked EP0 XferComplete handler runs our payload,
   which blocks in a `receive(300)`.
4. **Immediately write 512 zero bytes to ep 0x2 on the SAME handle.**
   This completes the interrupted upload; the payload receives its 300,
   runs its checks (header → checksum → verify → check, all consistent
   with our keys), resets the USB/DNW state and loads BL1 "normally".

### Phase B: survive the in-place re-enumeration

Within ~1s the USB stack **re-enumerates** (new device address; strings
come back; CDC setup is accepted again). CRITICAL: houston's
`read_bytes` swallows ALL exceptions — a stale handle reads `b''`
forever with no error. Detect it by comparing the handle's
`(bus, address)` with a fresh `usb.core.find` and **re-find +
re-claim + CDC setup immediately**. Every second of delay risks a
degraded device state (an 11-minute-late epbl send got a SHORT WRITE).

### Phase C: serve the chain (request-driven)

- Requests arrive on 0x81 as `\neub:req:e9840000:<name>` with
  status chatter (`eub:ack:...`, `Ready to rx EPBL`, `[BL2] USB
  Loading Done`, `BL2 Pass`, ...) — acks and the next request often
  arrive in ONE read. Parse with a regex on `eub:req:` segments; never
  treat an ack as a duplicate request.
- **After each request, wait for the `C` readiness byte** before
  writing. Writing before `C` gets only the first 512 bytes buffered,
  then the device NAKs and sends `C`.
- **Send each file as ONE single full write** (`\x1BDNW` header +
  u32 size + file + u16 checksum — houston's `eub.load_file` +
  `write_header(file, size)` + `calculate_checksum`). Chunked writes
  BREAK the protocol (only the first 512-byte chunk is taken).
- Order: epbl, bl2, bootload, el3_mon, ldfw, tzsw.
- If a write went partial anyway (512 accepted, then timeout + `C`):
  send the REMAINING bytes of that file's DNW packet
  (`file[512:]`) as one single write — the packet completes and the
  chain continues (recovered epbl and bl2 this way, twice verified).

End state: `[USB Booting Done]`, then the device re-enumerates as
**`04e8:685d` (Samsung download mode)** — the patched chain is running
from RAM with the signature, rollback (SW REV) and warranty-fuse gates
disabled.

## Flash the IGYI3 downgrade (download mode)

The patched download mode is a stock-equivalent Odin mode:

- Files: `flash/IGYI3_flash/` — BL, AP, CP, **HOME_CSC**
  (CSC_ODM is intentionally EXCLUDED — it wipes; the wipe happens at
  ROM install instead).
- Linux CLI: `python3 flash helper` (pexpect driver for Linux flash tool; note:
  `connect` shows a device-selection menu — press Enter on the only
  device; driver handles it).
- Linux GUI: needs the system `tk` package (`sudo pacman -S tk`) plus
  `pip install --user sv_ttk tktooltip tkinterdnd2`.
- **Windows + Odin also works** — flash BL/AP/CP/HOME_CSC, one
  uninterrupted session. Success = no `SW REV. CHECK FAIL`
  (that rejection is exactly what the rollback patch removes).
- Download mode runs from the battery — unplugging does not exit it.
  If it reboots anyway, the phone just boots stock One UI 8 (intact);
  redo the EUB session.

After the flash: reboot → verify One UI 7 boots (`G990EXXSIGYI3`).
If it does NOT boot: EUB + test point + re-flash the NHZF5 rescue
package (`flash/NHZF5_rescue/`), then revisit the design's boot-time
rollback open question.

## Remaining flow (after the downgrade boots)

1. Developer options → **OEM unlock toggle** → confirm in download mode.
2. Odin: `flash/recovery.tar` + `flash/vbmeta_disabled.tar`
   (ROM-thread flow) → Lineage recovery.
3. `adb sideload flash/lineage-23.2-20260904-UNOFFICIAL-r9s.zip`,
   wipe `/data`, reboot → LineageOS 23.2.
4. Magisk-patch the LOS `boot.img` (Magisk-v30.7.apk is in Downloads)
   and flash via recovery → root.
5. Verify: unlocked + LOS + root + Knox intact + EUB rescue still
   enumerates (`lsusb` shows `04e8:1100` from EUB entry).

## Known-good session transcripts

- `continue_chain.py` output (14:12:12–14:12:21): the full chain served
  and `[USB Booting Done]` → `04e8:685d`.
- Earlier failures and their causes (all fixed):
  `BL1 Checksum Fail` (payload embedded after signing), silent post-
  exploit hang (missing 512-byte upload completion), stale-handle spin
  (houston's read_bytes swallows ENODEV; in-place re-enumeration),
  SHORT WRITE (write before `C` / degraded state), 512-then-NAK
  (chunked writes instead of one single write).
