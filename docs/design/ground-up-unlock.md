> Exported from the project's OpenSpec design record and sanitized for publication.

# Design

## Context

See `proposal.md` - Why. The technical state that shapes this design:

- Device: SM-G990E (S5E9840). The custom-key fuse is **burned** and irreversible;
  the BootROM selector points at our key slot. Stock-signed bootloader images can
  never be accepted again. `keys/` and `keys_backup_20261009/` are irreplaceable.
- On-UFS chain today: v8 (11 stubs). It boot-loops. Download mode runs, but a
  flash session can no longer be established: Odin stalls around file analysis
  and Linux flash tool's first odin write times out. Both tools run *inside* the on-UFS abl.
- The EUB test-point path runs from `igyi3_out/` via `eub_session5.py` +
  `continue_chain.py`, and is independent of the installed chain.
- Known machinery (`patch_9840.py`, bootload-relative):

```
  exynos_read_is_device_unlocked @ 0x621c0   (prologue: sub sp,sp,#0x210)
    mode 0  -> w19 = 0 (default, LOCKED)  |  w19 = 1 - stored (stored=0 -> UNLOCKED)
    mode 1  -> PIT lookup "PERSISTENT" (xref @ 0x62224) -> persistent state byte
                    |
                    v
       persistent state byte on UFS        <== the ROOT
                    |
                    v
       boot cache [0x1f7f0] / global [0x7baf3c]
                    |
   +----------------+----------------+-------------------+------------------+
   v                v                v                   v                  v
 avbops reader   load-addr      pit_flash_binary   boot-time locked    state-switch
 @0x93d40        decider        OEM gate           verify-fail gates   executor app
 (v5 stub)       @0x94740       @0x5f6b8           (0x6562c/0x6582c/   @0x668f0
                 (v5 stub)      (v2 stub)          0x66304...)         (v8 stub)
```

- `openspec/changes/repair-bootloader-patch-contracts/` is cited throughout
  `UNLOCK_RUNBOOK.md` but does not exist on disk; `openspec list --specs` is empty.
- Local `capstone` 5.0.7 is available. REA cannot open the raw headerless
  segment (`bootload_pristine.bin`, 2,756,480 bytes) as a binary artifact.

## Goals / Non-Goals

**Goals:**

- A device that reports unlocked from recorded state, with the unlock performed
  by the platform's own unlock path.
- A flashed chain whose only patches are the ones the fused custom key and the
  platform image format genuinely require.
- A control plane that can always replace the installed chain, and a way to prove
  a candidate before it is committed.

**Non-Goals:**

- Preserving the leaf-stub architecture, or adding further leaf stubs.
- Any write to non-volatile storage before in-memory validation.
- Restoring stock firmware (impossible with the burned fuse) or modifying fuses.
- Booting LineageOS itself; that is the acceptance test *after* unlock, not part
  of this change.
- Explaining the v8 boot loop with certainty; it is replaced rather than fixed.

## Decisions

### D1 - Materialise the unlock through the platform's own unlock operation

Preference order, best first:

1. Let the stock state-switch executor perform the unlock, opening only its
   allowed-bit gate (there is no request flag — see the write-path finding).
   The action is the platform's own: wipe BCB + DT bit + `rpmb_set_lock(0)` +
   switch counter.
2. Only if (1) proves insufficient: call the platform's own storage writer
   `rpmb_set_lock(0)` directly at boot (still not a hand-crafted partition
   image), with the same observable outcome.

Rationale: the executor writes the state, the wipe and the transition
accounting consistently, which is what every unpatched consumer expects.
Alternatives considered: (a) crafting and flashing a PERSISTENT-partition image
— rejected as primary because it can leave the accounting inconsistent with the
rest of the state machinery; (b) continuing to stub leaves — rejected, that is
the architecture this change exists to stop.

The `device-unlock` spec states the executor mechanism and it **stands
unamended**: group 4 shows the spec's "bootloader's own unlock operation" is
reachable by opening the allowed-bit gate, so no direct state write is needed by
default. The gate's backing token is not forgeable, so option 1 is reachable only
by opening the branch, not by raising the bit itself; if that proves
insufficient, option 2 uses the platform's own `rpmb_set_lock` writer rather than
a crafted image, and the spec's "direct byte writes are not used" scenario still
holds.

### D2 - Reduce the patch set instead of extending it

Drop the stubs that exist only to compensate for a locked state: the v2 unlock
reader, the v5 state-cache/avbops readers, the v8 state-switch app neutraliser.
Keep only what the fused custom key and the platform image format require.

**Partially falsified on the device (2026-10-12, v10).** The v10 boot sequence
was: boot 1 `Device state switched (N)` (the unlock fired, so the state changed),
boot 2 no switch message but **still `ODIN MODE (DT Load Fail)!`** — every time.
The DT-stage abort therefore persists independently of the unlock state: the
decider takes the validation path and, with the flags=2 no-descriptor `vbmeta`,
that path yields no load address for any image. The decider's reader stub
(`0x93d40`) is load-bearing on its own. The next candidate restores
`patch_avbops_state_reader_always_unlocked` on top of v10, and the
`device-unlock` spec's "state-compensating stubs are absent" scenario is amended
rather than silently kept.

### D3 - EUB-first control plane

Serve and RAM-boot candidates through the test point, then flash. Odin and Linux flash tool
are conveniences, not the primary path, because both execute inside the chain
under test — the exact coupling that made the v9 flash untestable.

### D4 - Download-mode session behaviour is a chain contract

Add "a flashed chain can serve a download-mode session" as a validated contract
alongside the existing byte-level patch contracts. This is the behavior that
gated everything and was never checked.

### D5 - One serve directory, and a no-fuse serve variant

Pin the serve directory to one identified build output (`eub_session5.py` uses
`igyi3_out/`, `continue_chain.py` uses `output/` — a real divergence) and report
it. Build a `should_fuse_key=False` variant so validation cannot re-run the OTP
key-burn payload.

### D6 - RE with local capstone on the raw segment

Analyse `bootload_pristine.bin` in place at its bootload-relative addresses with
capstone. Wrapping the segment in a minimal ELF would let REA open it, but that
is a derived artifact with no analytical benefit here; not doing it keeps the
whole investigation read-only.

## Reverse-engineering findings (group 1)

All addresses are bootload-relative in the **NHZF5** segment
(`bootload_pristine.bin`, md5 `727e6047be7e044d461397d45be8fef4`, 0x2A3000 bytes),
reproducible with `re_unlock_state.py`. The addresses carried in the runbook and
in `patch_9840.py`'s comments are **IGYI3's**: NHZF5's `get_oem_unlock_val` is at
`0x641d8`, not `0x621c0` (IGYI3 still has `0xD10843FF` at `0x621c0`; NHZF5 has
`0x2a1303e1` there). Every NFZF5 site below is the generation-correct one.

### The state reader: `get_oem_unlock_val` @ 0x641d8 (task 1.1)

```
0x641d8  sub   sp, sp, #0x210          ; prologue (0xD10843FF)
0x641f0  cbnz  w0, 0x64220             ; mode != 0 -> mode-1 path
0x641f8  mov   w19, #0                 ; default: LOCKED (fail-closed)
0x641fc  ldr   w20, [x0, #0x368]       ; w20 = [0x7be368]  (RPMB usable flag)
0x64200  cmp   w20, w1                 ; w1 = 1
0x64204  b.eq  0x642c0                 ; usable -> do the real read
0x642d0  sub   w19, w20, w19           ; w19 = 1 - cached   <== reproduced
```

Mode 0 returns `1 - cached`, so **cached 0 = unlocked, cached 1 = locked**. The
state-switch app corroborates the polarity: cached `== 1` makes it print
`OEM Lock in RPMB`, the fall-through prints `OEM Unlock in RPMB`.

Mode 1 (`0x64220`) does a PIT lookup for `"PERSISTENT"` (`0x6423c` -> `0x5fb40`),
assembles three `u32` PIT fields read from the entry at `+0x14/+0x18/+0x1c`,
computes `offset = field14 + field18 - 1` (the partition's **last block**), calls
the block-read wrapper `0x2f1f8`, and returns `buffer[0x1ff]` (`0x642b4`) — i.e.
**the last byte of the last 0x200-byte block of the `PERSISTENT` partition**,
width 1 byte (task 1.2).

### The boot cache (task 1.4)

`0x1f7b0` is the cache reader: returns `[0x7bdf3c]`, or error `0x00040300` when
the RPMB-usable flag `[0x7be364]` is clear. It is **repopulated every boot** by
the RPMB lock-state init `0x1efb0`: it reads the RPMB header block, and if the
magic matches caches the state word from header `+0x13c` into `[0x7bdf3c]`
(`0x1f158`..`0x1f174`); on a magic mismatch it **defaults to `1` (locked)**
(`0x1f028`). So the authoritative source is RPMB, cached at boot; nothing
persists only in RAM.

Consumers of `get_oem_unlock_val`, all **mode 0** (no in-segment caller uses
mode 1):

| site | context |
| --- | --- |
| `0xfed4` | image path (`0x63448` verify tail) |
| `0x67d50` | `Binaryname has changed (%s) -> (%s)` — signinfo path |
| `0x67d98` | `No signinfo : (%s)` |
| `0x67e2c` | `Unable to get partinfo (%s)` |

### The "OEM unlock allowed" bit (task 1.3)

`0xbeee30` is a 256-bit array (0x20 bytes, 8-byte words):

- **read**: `0x6dee8(i)` returns bit `i` (`ldr x3,[base, w1, uxtw #3]`, `lsr`, `and #1`); `0x6e230(i)` returns whole word `i`.
- **written**: `0x6df28` clears all 0x20 bytes; the table is **populated** at
  `0x6e08c`..`0x6e098` by `memcpy(0xbeee30, [0xbeee28] + 0x120, 0x20)`.
- **backing store**: `[0xbeee28]` is a buffer allocated by `preparePayload`
  (`0x6d8b8`) and filled by **`read_token` (`0x6db50`), which PIT-looks-up the
  `STEADY` partition** (`0x153ec8`). The allowed bits are therefore
  **partition-backed (STEADY), not OTP** — which is what makes D1 option 1
  potentially reachable.

The app tests it directly: `0x66928 mov w0,#3; bl 0x6dee8` = "is bit 3 allowed?".

### The state-switch executor (task 1.5)

`0x668e8` (the app, prologue `0xD11143FF` = `sub sp,sp,#0x450`) has exactly one
call path:

```
0x67744  bl  0x676e8          ; single caller of the wrapper
0x676e8  bl  0x1ea28          ; "is RPMB accessible?" probe
0x676f4  cbnz w0, 0x67700     ; not accessible -> print "...Not able to access RPMB"
0x676fc  b   0x668e8          ; tail-call the app
```

and internally gates on `[0x7be368] == 1` (RPMB initialized, `0x66908`). There is
**no request flag**: the executor is a per-boot reconciliation, which is exactly
why v7 produced `Device state switched (11)` — one execution per boot. It reads
the cached state via `0x1f7b0` (`0x66a94`), tests allowed-bit 3, and on the switch
path looks up `MISC` (`0x66964`) and writes the BCB, failing out through
`Failed to switch device state.` / `Fail_to_switch_device_state`.

### Patch classification (task 1.6)

| patch | class | reason |
| --- | --- | --- |
| `patch_check_signature` | required | chain/PIT load on the fused-key device |
| `patch_prevent_warranty_fuse` | required | irreversible warranty-bit side effect |
| `patch_check_sw_rev` | required | rollback gate |
| `patch_check_kernel_rev` | required | boot-time rollback gate |
| `patch_check_system_rev` | required | boot-time rollback gate |
| `patch_check_pit_rev` | required | boot-time rollback gate |
| `patch_seandroid_enforcing_off` | required | platform trailer check (LOS has no Samsung trailer) |
| `patch_read_is_device_unlocked` | **state-dependent -> retire** | compensates for locked state |
| `patch_avbops_state_reader_always_unlocked` | **state-dependent -> retire** | compensates for locked state |
| `patch_state_switch_app_noop` | **state-dependent -> retire** | D1 needs this app to run |
| `patch_state_cache_read_always_unlocked` | **retired already (v8)** | compensates for locked state |
| `patch_fuse_boot_key` | one-shot | already burned; off for every new build |

### The persistent write path (group 4)

The executor's unlock action is fully decoded and it is the platform's own
unlock end to end (`0x6695c`..`0x66a74`):

```
0x6695c  PIT lookup "MISC"
0x66980  strcpy(buf, "recovery\n--wipe_data\n--reason=bootloader_unlock\n--locale=en_US\n")
0x669d0  blk_bwrite(MISC, buf, ...)        ; the wipe BCB
0x669dc  set DT-error bit 0x80000 (0x5d878)
0x66a10  rpmb_set_lock(w20) @ 0x1f7e8      ; THE PERSISTENT STATE WRITE
0x66a18  read the switch counter -> "Device state switched (%d)"
```

`rpmb_set_lock(v)` (`0x1f7e8`) sets the boot cache `[0x7bdf3c] = (v != 0)` and
writes the RPMB header block through `0x1f1d8`, so `w20 = 0` is the persistent
unlock.

**The gate is the allowed bit, and it is not directly raisable.** The branch is
`0x66930 cbz w0, 0x66940` over `0x6dee8(3)`: `w20` becomes `0` only on
`allowed && state == 1` (unlock) and `1` on `!allowed && state == 0` (relock);
every other combination exits at `0x66a74`. The allowed bit lives in the
`STEADY` token (`read_token` `0x6db50` -> `[0xBEEE28]+0x120`), and that subsystem
is signature-verified and single-use (`Failed to verify token signature`,
`Installed token isn't for this device`, `token is expired`, `USED token. Please
issue a new token`). There is no forgeable path to set it — and the v5-era
evidence points the other way: forcing the cached state to "unlocked" made the
executor take the RELOCK branch, which exists only when the allowed bit is
**clear**.

**Chosen mechanism.** Keep the stock executor and open its allowed-bit gate, so
the platform performs the whole unlock itself (wipe BCB + DT bit +
`rpmb_set_lock(0)` + counter). That remains "the bootloader's own unlock
operation" in the `device-unlock` spec's sense, so the spec stands unamended; a
direct `rpmb_set_lock(0)` call is the fallback if the gate patch proves
insufficient.

## Risks / Trade-offs

- [The unlock request cannot be raised from a state we can reach] -> D1's fallback
  is the recorded-state write; the `device-unlock` spec is amended in this change
  if RE proves it necessary, before any implementation.
- [A remaining gate we did not enumerate re-closes after stubs are dropped] ->
  the RE consumer sweep (mode-0 callers, the cache, the executor) is a required
  task, and RAM validation plus the download-screen lock readout catch a
  regression before the UFS write.
- [RAM validation cannot reproduce a cold-boot path exactly] -> validation is
  explicitly a pre-commit gate, not proof; a residual difference is recorded,
  and the installed chain remains replaceable via the same EUB path.
- [The unlock wipe destroys user data] -> expected and required for LineageOS;
  no user data of value remains on this device.
- [Served chain differs from validated chain] -> D5 pins and reports the serve
  directory; the "served chain matches the validated chain" scenario covers it.
- [Fuse safety] -> no-fuse variant (D5); no task in this change writes OTP.

## Migration Plan

No deployed consumers; this is a device procedure, ordered so the device is
always recoverable:

1. RE sweep: state byte, allowed-bit store, request mechanism, cache
   repopulation, full mode-0 consumer list, and the still-required patch set.
2. Decide the mechanism (D1) and amend the `device-unlock` spec if needed.
3. Rebuild the reduced chain; verify the patches that remain.
4. RAM-validate: serve the candidate via EUB, confirm it runs and can serve a
   download-mode session, without touching UFS.
5. Single UFS write, then the boot observation.

Rollback at every step: the EUB path serves the known-good chain regardless of
the installed one; the previous chain's tar remains on the host; nothing in this
change writes fuses.

## Open Questions

- **State-byte polarity for mode 1.** Mode 0 returns `1 - cached` (so `0 =
  unlocked`), and the app's `OEM Lock/Unlock in RPMB` strings confirm that
  polarity for the cached value. Mode 1 returns the raw `PERSISTENT` byte, and
  the segment does not prove its polarity in isolation; assume `0 = unlocked`
  only after an on-device read confirms it. Impact: one validation observation,
  no spec or approach change.
