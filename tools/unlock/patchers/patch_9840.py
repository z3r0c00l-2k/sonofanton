#!/usr/bin/env python3
# Project copy of Exynos/scripts/patch_9840.py for the S21 FE (SM-G990E, S5E9840)
# unlock flow. Differences from upstream:
#   - adds patch_check_sw_rev(): kills the rollback (SW REV) flash-time gate in
#     bootload.bin so Odin can flash lower-revision stock firmware
#     (G990EXXSIGYI3, RB 18) through the patched download mode.
#   - adds patch_check_kernel_rev/patch_check_system_rev/patch_check_pit_rev():
#     kills the BOOT-time rollback gates (KERNEL/SYSTEM/PIT REV CHECK, the
#     family that produced "KERNEL REV_CHECK FAIL : DEVICE 23 BINARY 18
#     (VBMETA)" after the IGYI3 flash). Function starts verified via dual
#     string-xref agreement + stp x29,x30 prologues.
#   - should_fuse_key = True (user-approved 2026-10-09): burns our key into the
#     free ROM secure-boot key slot 2 and switches the BootROM selector to it,
#     once, when the patched chain boots download mode. IRREVERSIBLE: after
#     this the device permanently requires our-key-signed images (keys/ is
#     backed up; EUB test-point rescue stays available either way).

import os
import struct
import sys

RETURN_ZERO = bytes.fromhex("00 00 80 D2 C0 03 5F D6")
RETURN_ONE = bytes.fromhex("20 00 80 D2 C0 03 5F D6")

def write_u32(data, offset, value):
    struct.pack_into("<I", data, offset, value)

def word(data, offset):
    return int.from_bytes(data[offset : offset + 4], "little")

def signed(value, bits):
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign

def adrp_add(data, offset):
    adrp = word(data, offset)
    if adrp & 0x9F000000 != 0x90000000:
        return None

    imm = ((adrp >> 29) & 3) | (((adrp >> 5) & 0x7FFFF) << 2)
    page = (offset & ~0xFFF) + (signed(imm, 21) << 12)
    for distance in range(4, 17, 4):
        add = word(data, offset + distance)
        if add & 0xFF000000 == 0x91000000 and (add >> 5) & 31 == adrp & 31:
            return page + (((add >> 10) & 0xFFF) << (12 if add & 0x400000 else 0))
    return None

def find_xref(data, string):
    string_offset = data.find(string)
    if string_offset < 0:
        raise ValueError(f"string not found: {string!r}")
    if data.find(string, string_offset + 1) >= 0:
        raise ValueError(f"expected one copy of {string!r}")

    refs = [
        offset
        for offset in range(0, string_offset & ~3, 4)
        if adrp_add(data, offset) == string_offset
    ]
    if len(refs) != 1:
        raise ValueError(f"expected one xref to {string!r}, found {len(refs)}")
    return refs[0]

def write_words(data, offset, words):
    for i, word_value in enumerate(words):
        write_u32(data, offset + i * 4, word_value)

def jump_to_func_from(from_addr, to_addr):
    return 0x94000000 | (((to_addr - from_addr) >> 2) & 0x03FFFFFF)

# Patch-site registry consumed by verify_chain.py. Every write goes through
# _record() so the validator can (a) confirm the pre-patch bytes match what the
# anchor logic expects, (b) recompute the patched image from stock in memory,
# and (c) evaluate each site's calling contract on any deployed image.
PATCH_SITES = []

def _record(data, offset, new_bytes, name, kind, **contract):
    new = bytes(new_bytes)
    old = bytes(data[offset : offset + len(new)])
    PATCH_SITES.append({
        "name": name, "offset": offset, "old": old, "new": new,
        "kind": kind, "contract": contract,
    })
    data[offset : offset + len(new)] = new

def patch_check_signature(data): # required because PIT will not load on USB boot with custom st2 key
    # Contract: ret_const w0=0 (true entry); verified on the packed sboot by
    # verify_chain.py. Its callers (AVB0/PIT/EDTBO/VDDCAL paths) only test the
    # return for validity.
    #
    # This is also the earliest point that provably runs in the DOWNLOAD flow, so
    # it raises the Secure Download bypass flag here. The flag's own writer
    # (0x6ed28, called only from early init 0x2810) does not run in download mode,
    # which left the per-image secure check active and stopped the stock AP at
    # super.img even with v13 running. See patch_disable_secure_download_check.
    # Payload: [0xbeed28] = 1 ; return 0.
    check_signature = find_xref(data, b"%s: There is no signature\n\0") - 0xDC
    print(f"check_signature: {check_signature:#x} (return 0 + raise secure-download bypass)")
    page = 0xBEED28 & ~0xFFF
    delta = (page - (check_signature & ~0xFFF)) >> 12
    immlo, immhi = delta & 3, (delta >> 2) & 0x7FFFF
    payload = [
        0x90000000 | (immlo << 29) | (immhi << 5),        # adrp x0, #0xbee000
        0x91000000 | ((0xBEED28 & 0xFFF) << 10),          # add  x0, x0, #0xd28
        0x52800021,                                       # mov  w1, #1
        0xB9000001,                                       # str  w1, [x0]
        0x52800000,                                       # mov  w0, #0
        0xD65F03C0,                                       # ret
    ]
    write_words(data, check_signature, payload)
    _record(data, check_signature, struct.pack("<%dI" % len(payload), *payload),
            "check_signature", "ret_const", w0=0)

def patch_prevent_warranty_fuse(data):
    set_warranty_void_bit_reason = find_xref(data, b"%s : invalid value\n\0") + 0x24
    set_warrant_bit = find_xref(data, b"[EFUSE] Set warranty bit(0x%llx)\n\0") - 0x4C
    # Contract: ret_const w0=0 at both sites (true entry / leaf start);
    # verified on the packed sboot.
    print(f"set_warranty_void_bit_reason: {set_warranty_void_bit_reason:#x}")
    print(f"set_warrant_bit: {set_warrant_bit:#x}")
    _record(data, set_warranty_void_bit_reason, RETURN_ZERO,
            "set_warranty_void_bit_reason", "ret_const", w0=0)
    _record(data, set_warrant_bit, RETURN_ZERO, "set_warrant_bit", "ret_const", w0=0)

def patch_check_sw_rev(data):
    check_sw_rev = find_xref(data,
        b"[EFUSE] RB count: device(0x%llx), flash image(0x%llx)\n\0") - 0x2C
    # Contract: ret_const w0=0 (flash-time rollback gate, true prologue entry).
    print(f"check_sw_rev: {check_sw_rev:#x}")
    data[check_sw_rev : check_sw_rev + len(RETURN_ZERO)] = RETURN_ZERO
    _record(data, check_sw_rev, RETURN_ZERO, "check_sw_rev", "ret_const", w0=0)

def _expect_prologue(data, offset, name):
    w = word(data, offset)
    if not ((w >> 24) == 0xA9 and (w & 0x7FFF) == 0x7BFD):
        raise ValueError(f"{name}: no stp x29,x30 prologue at {offset:#x} ({w:#x})")
    return w

def patch_check_kernel_rev(data):
    # boot-time gate; fail msg "KERNEL REV. CHECK FAIL. DEVICE:%d, BINARY:%d (%s)"
    # Contract: ret_const w0=0 at the true prologue entry.
    check = find_xref(data,
        b"KERNEL REV. CHECK FAIL. DEVICE:%d, BINARY:%d (%s)\n\0") - 0x114
    _expect_prologue(data, check, "check_kernel_rev")
    print(f"check_kernel_rev: {check:#x}")
    data[check : check + len(RETURN_ZERO)] = RETURN_ZERO
    _record(data, check, RETURN_ZERO, "check_kernel_rev", "ret_const", w0=0)

def patch_check_system_rev(data):
    # boot-time gate; fail msg "SYSTEM REV. CHECK FAIL. DEVICE:%d, BINARY:%d (%s)"
    # Contract: ret_const w0=0 at the true prologue entry.
    check = find_xref(data,
        b"SYSTEM REV. CHECK FAIL. DEVICE:%d, BINARY:%d (%s)\n\0") - 0xC4
    _expect_prologue(data, check, "check_system_rev")
    print(f"check_system_rev: {check:#x}")
    data[check : check + len(RETURN_ZERO)] = RETURN_ZERO
    _record(data, check, RETURN_ZERO, "check_system_rev", "ret_const", w0=0)

def patch_check_pit_rev(data):
    # boot-time gate; the fail msg "\nPIT REV. CHECK FAIL. BINARY:%d" is only
    # reachable from this function's b.eq branch (ref resolves to the leading
    # newline), so anchor on the "PIT RB count" print in the same function.
    # Contract: ret_const w0=0 at the true prologue entry.
    check = find_xref(data, b"PIT RB count: BINARY:%d\n\0") - 0x60
    _expect_prologue(data, check, "check_pit_rev")
    print(f"check_pit_rev: {check:#x}")
    data[check : check + len(RETURN_ZERO)] = RETURN_ZERO
    _record(data, check, RETURN_ZERO, "check_pit_rev", "ret_const", w0=0)

def patch_read_is_device_unlocked(data):
    # exynos_read_is_device_unlocked @ 0x621c0 (mode 0 = unlock-state read,
    # fail-closed default 0 = locked; mode 1 = PERSISTENT-partition byte
    # read used by the OEMLOCK machinery - NOT touched). Mode-0 consumers:
    # pit_flash_binary's OEM-lock flash gate (cbz w0 -> "Custom Binary(%s)
    # Blocked By OEM Lock" - the gate that rejected the AP-slot flash of
    # SUPER/recovery/vbmeta on the fused chain), its sibling erase/format
    # gate at 0x5e9fc (same reject block), and the boot-time locked ->
    # verify-fail paths (0x6562c/0x6582c "Custom binary blocked by OEM
    # Lock" + 0x66304/0x6634c/0x663e0). Make mode 0 always report 1
    # (unlocked) - the runbook's documented fallback ladder step 1.
    # Anchor: mode-1's "PERSISTENT" PIT-entry lookup adrp+add at +0x64.
    xref = find_xref(data, b"PERSISTENT\0")
    fn = xref - 0x64
    if word(data, fn) != 0xD10843FF: # sub sp, sp, #0x210 prologue
        raise ValueError(f"read_is_device_unlocked: bad prologue at {fn:#x}")
    default_ret = xref - 0x44  # mov w19, #0x0 (default return: locked)
    computed_ret = xref + 0x94 # sub w19, w20, w19 (1 - stored state)
    if word(data, default_ret) != 0x52800013:
        raise ValueError(f"read_is_device_unlocked: no mov w19,#0 at {default_ret:#x}")
    if word(data, computed_ret) != 0x4B130293:
        raise ValueError(f"read_is_device_unlocked: no sub w19,w20,w19 at {computed_ret:#x}")
    # Contract: value_write (SP/branch-neutral); both return paths forced to
    # w19 = 1 (unlocked); mode-1 (PERSISTENT byte read) deliberately untouched.
    print(f"read_is_device_unlocked: {fn:#x} (always reports unlocked)")
    write_u32(data, default_ret, 0x52800033)  # mov w19, #0x1
    write_u32(data, computed_ret, 0x52800033) # mov w19, #0x1
    _record(data, default_ret, struct.pack("<I", 0x52800033),
            "read_is_device_unlocked/default_ret", "value_write")
    _record(data, computed_ret, struct.pack("<I", 0x52800033),
            "read_is_device_unlocked/computed_ret", "value_write")

def patch_state_cache_read_always_unlocked(data):
    # 0x1f7f0: the shared unlock-state cache reader used by every boot-time
    # *** DO NOT USE (v8 finding, 2026-10-10): this patch made the abl's
    # state-switch executor app (0x668f0/IGYI3 0x65a70) read "unlocked",
    # which with config bit 3 ("OEM unlock allowed") CLEAR makes it execute
    # a RELOCK on EVERY boot: it sets the DT-error bit 0x80000 (the
    # accumulator setter, NHZF5 0x5d878/IGYI3 0x5bd18), so the UFDT main
    # skips the DTBO phase and every boot aborts as "ODIN MODE (DT Load
    # Fail)" - observed on-device as "Device state switched (11)" (the
    # 11th execution). That is why v5/v6/v7 all behaved identically.
    # v8 keeps this reader STOCK and neutralizes the app instead
    # (patch_state_switch_app_noop). Kept for history/ladder completeness.
    # Consumer that does NOT go through exynos_read_is_device_unlocked:
    # mode-0's raw read (fn+0xEC), the state-switch UI (0x65a70/0x65b48) and
    # the image-load ops reader (0x93da4, covered by the patch below once its
    # head is replaced). Reads the cached state global [0x7baf3c]
    # (1=locked, 0=unlocked), gated by the ready flag [0x7bb364]; the raw
    # value bypassed every v4 patch. Force: *out = 0 (unlocked), status 0.
    xref = find_xref(data, b"PERSISTENT\0")
    fn = xref - 0x64
    bl_offset = fn + 0xEC  # mode-0's raw read: add x0,x29,#0x2c; bl <cache_read>
    bl_word = word(data, bl_offset)
    if bl_word & 0xFC000000 != 0x94000000:
        raise ValueError(f"state_cache_read: no bl at {bl_offset:#x} ({bl_word:#x})")
    cache_read = bl_offset + (signed(bl_word & 0x03FFFFFF, 26) << 2)
    if word(data, cache_read + 4) != 0xAA0003E2:  # mov x2, x0 (identical in IGYI3+NHZF5)
        raise ValueError(f"state_cache_read: bad head at {cache_read:#x}")
    # Contract (if ever re-enabled): reader_store out_arg=0 value=0, w0=0.
    # v8 keeps the reader STOCK; see the DO NOT USE note above.
    print(f"state_cache_read: {cache_read:#x} (always reports unlocked)")
    write_words(data, cache_read, [
        0xB900001F,  # str wzr, [x0]   -> *out = 0 (unlocked)
        0x52800000,  # mov w0, #0      -> status 0 (success)
        0xD65F03C0,  # ret
    ])
    _record(data, cache_read, struct.pack("<3I",
            0xB900001F, 0x52800000, 0xD65F03C0),
            "state_cache_read", "reader_store", out_arg=0, out_value=0, w0=0)

def patch_avbops_state_reader_always_unlocked(data):
    # 0x93d40: exynos_read_is_device_unlocked, the image-load ops variant
    # (self-named in its "%s : RPMB is not initialized yet" print; fail-closed
    # to 0 = locked when RPMB is not up). Its only callers, 0x94790/0x947dc in
    # the boot/vendor_boot image load-address decider at 0x94740, gate the
    # image load: unlocked -> load address 0x94000000/0x98000000; locked ->
    # the 0x945c0 validation path, which with the flags=2 no-descriptor
    # vbmeta yields NO load address for ANY image (stock NHZF5 boot.img and
    # LOS recovery alike) -> the DT stage aborts -> "ODIN MODE (DT Load
    # Fail)". This path bypassed all v4 patches.
    # v8 bug: the stub did `mov w1, #1` BEFORE `strb w1, [x1]`, which
    # overwrote the caller's out pointer with 1 and stored to address 0x1.
    # Fixed: the value goes through a scratch (w2) and x1 is untouched.
    # Caller branches (load-address decider): 0x97718 "boot" -> fixed
    # address 0x94000000 and 0x97764 "vendor_boot" -> 0x98000000; both do
    # `cbz w0` (0 = success) then `ldrb` the out byte (0 = locked/validate,
    # 1 = unlocked/fixed-address path).
    # Contract: reader_store via out_arg=1 value=1, w0=0, SP delta 0
    # (enforced by verify_chain.py).
    # Anchor: the function-name string's adrp/add; fallback: the RPMB
    # print format (same site, different delta).
    try:
        xref = find_xref(data, b"exynos_read_is_device_unlocked\0")
        fn = xref - 0x28
    except ValueError:
        xref = find_xref(data, b"%s : RPMB is not initialized yet\n\0")
        fn = xref - 0x2C
    if word(data, fn) != 0xA9BD7BFD:  # stp x29, x30, [sp, #-0x30]!
        raise ValueError(f"avbops_state_reader: bad prologue at {fn:#x}")
    print(f"avbops_state_reader: {fn:#x} (always reports unlocked)")
    write_words(data, fn, [
        0x52800022,  # mov w2, #1     (scratch: x1 is the caller's out pointer)
        0x39000022,  # strb w2, [x1]  -> *out = 1 (unlocked) via the ORIGINAL pointer
        0x52800000,  # mov w0, #0     -> status 0
        0xD65F03C0,  # ret            (no frame needed: nothing touches SP/x29/x30)
    ])
    _record(data, fn, struct.pack("<4I",
            0x52800022, 0x39000022, 0x52800000, 0xD65F03C0),
            "avbops_state_reader", "reader_store", out_arg=1, out_value=1, w0=0)

def patch_seandroid_enforcing_off(data):
    # 0x618d0: the "is SEAndroid/TIMA enforcing" query (reads the static flag
    # [0xbea63c]; Samsung ships it set = enforcing). Its ONLY two callers are
    # the boot/recovery image trailer-check function 0x65850 (called from
    # inside the v2 scatter loader at 0x422ac): the "SEANDROIDENFORCE"-magic
    # match path (0x658ac) and the "[TIMA trusted boot]: SEAndroid MAGIC
    # failure" path (0x65928). Enforcing=1 routes BOTH to 0xaaa8 -> the TIMA
    # SMC (0xC200101D) -> the TZ-side signature verification of the image's
    # Samsung trailer. The LOS 23.2 recovery has NO Samsung trailer (an AVB0
    # blob sits where stock images carry "SEANDROIDENFORCE" + SignerV3 -
    # verified byte-exact on the images), so enforcing kills the recovery
    # boot with the "DT Load Fail" abort. Stock images would equally fail
    # the TZ verify against our custom-key TrustZone. Force "not enforcing"
    # -> both paths take the lenient continuation = exactly what a truly
    # unlocked (orange-state) device does. Anchor: the recovery MAGIC-failure
    # string xref (+0x0C = the query bl in the mismatch path).
    xref = find_xref(data, b"[TIMA trusted boot]: SEAndroid MAGIC failure (recovery.img)\n\0")
    bl_offset = xref + 0x0C
    bl_word = word(data, bl_offset)
    if bl_word & 0xFC000000 != 0x94000000:
        raise ValueError(f"seandroid_enforcing: no bl at {bl_offset:#x} ({bl_word:#x})")
    fn = bl_offset + (signed(bl_word & 0x03FFFFFF, 26) << 2)
    if word(data, fn + 8) != 0x6B1F001F:  # cmp w0, wzr (identical in IGYI3+NHZF5)
        raise ValueError(f"seandroid_enforcing: bad head at {fn:#x}")
    # Contract: ret_const w0=0 (leaf function, no frame involved).
    print(f"seandroid_enforcing_query: {fn:#x} (always reports NOT enforcing)")
    write_words(data, fn, [
        0x52800000,  # mov w0, #0     -> not enforcing
        0xD65F03C0,  # ret
    ])
    _record(data, fn, struct.pack("<2I", 0x52800000, 0xD65F03C0),
            "seandroid_enforcing_query", "ret_const", w0=0)

def patch_state_switch_app_noop(data):
    # 0x668f0 (NHZF5; the IGYI3 equivalent sits in the 0x65a70-family):
    # Samsung's unlock/relock
    # state-switch executor APP (no bl callers - invoked from the boot
    # app table). Verified by disassembly (string/flow identical in
    # IGYI3 + NHZF5): with the request field set it reads the cached
    # state via the 0x1f7b0/0x1f7f0 cache reader and compares it with
    # config bit 3 ("OEM unlock allowed", bit table @0xbeee30):
    #   locked + bit3    -> executes the UNLOCK
    #   unlocked + !bit3 -> executes the RELOCK
    # An execution: writes the BCB "recovery\n--wipe_data\n
    # --reason=bootloader_unlock", SETS the DT-error bit 0x80000 via the
    # accumulator setter (NHZF5 0x5d878 / IGYI3 0x5bd18) - which makes
    # the UFDT main skip the whole DTBO phase -> every boot aborts as
    # "(DT Load Fail)" - writes the TRUE state, and displays
    # "Device state switched (%d)" with a persistent switch counter
    # (global 0xbed838, persisted to param +0xa84 via 0x629d8).
    # Neutralize: return -1 immediately - the exact value the stock app
    # returns in every non-switch case (so the boot app table runner
    # already handles it on every stock device).
    # Anchor: the display string's adrp+add (xref - 0x134 = the TRUE
    # function entry `sub sp, sp, #0x450`) + that entry-word assert.
    # v8 landed on xref-0x12C (the `stp` INSIDE the frame) and returned
    # without restoring the outstanding 0x450-byte allocation, corrupting
    # the caller stack; the entry assert makes that drift impossible.
    # Contract: ret_const w0=0xFFFFFFFF, net SP delta 0 from the true
    # entry (checked by verify_chain.py).
    xref = find_xref(data, b"Device state switched (%d)\n\0")
    app = xref - 0x134
    if word(data, app) != 0xD11143FF:  # sub sp, sp, #0x450 (true entry)
        raise ValueError(f"state_switch_app: bad entry at {app:#x} ({word(data, app):#x})")
    print(f"state_switch_app: {app:#x} (neutralized: return -1)")
    write_words(data, app, [
        0x12800000,  # movn w0, #0    -> w0 = -1 (stock no-op return)
        0xD65F03C0,  # ret
    ])
    _record(data, app, struct.pack("<2I", 0x12800000, 0xD65F03C0),
            "state_switch_app", "ret_const", w0=0xFFFFFFFF)

def patch_open_oem_unlock_gate(data):
    # The state-switch executor's unlock decision (change task 4.3). The stock
    # app unlocks only when the STEADY-token "OEM unlock allowed" bit is set:
    #   0x66928  mov w0,#3; bl 0x6dee8   ; bit 3 = allowed?
    #   0x66930  cbz w0, 0x66940         ; not allowed -> the "no change" path
    #   0x66934  ldr state; cmp #1; b.eq 0x66ac0   ; locked -> w20 = 0 = UNLOCK
    #   0x66958  mov w20, #1             ; the relock target -> the write below
    # The allowed bit is a signature-verified, single-use STEADY-token mode bit,
    # so it cannot be raised; open the gate instead and let the platform perform
    # its own unlock (wipe BCB + DT bit + rpmb_set_lock(0) + switch counter):
    #   S1 0x66930  cbz -> `b .+4`     always evaluate the state
    #   S2 0x66958  mov w20,#1 -> `b 0x66a74`
    #      an already-unlocked device exits the stock "no change" path (w20 is
    #      already -1 there from 0x66944), so no spurious relock
    # Contract: two branch redirects, verified by the recorded words.
    app = find_xref(data, b"Device state switched (%d)\n\0") - 0x134
    if word(data, app) != 0xD11143FF:  # sub sp, sp, #0x450 (true entry)
        raise ValueError(f"open_oem_unlock_gate: bad entry at {app:#x} ({word(data, app):#x})")
    s1 = app + 0x48
    s2 = app + 0x70
    if word(data, s1) != 0x34000080:  # cbz w0, 0x66940
        raise ValueError(f"open_oem_unlock_gate: expected cbz at {s1:#x} ({word(data, s1):#x})")
    if word(data, s2) != 0x52800034:  # mov w20, #1
        raise ValueError(f"open_oem_unlock_gate: expected mov w20,#1 at {s2:#x} ({word(data, s2):#x})")
    print(f"open_oem_unlock_gate: {app:#x} (gate {s1:#x}, relock {s2:#x})")
    write_u32(data, s1, 0x14000001)  # b .+4      -> always evaluate the state
    write_u32(data, s2, 0x14000047)  # b 0x66a74  -> exit (already unlocked)
    _record(data, s1, struct.pack("<I", 0x14000001),
            "open_oem_unlock_gate/unlock_branch", "branch_redirect", words=[0x14000001])
    _record(data, s2, struct.pack("<I", 0x14000047),
            "open_oem_unlock_gate/relock_skip", "branch_redirect", words=[0x14000047])

def patch_executor_skip_recovery(data):
    # v27. The state-switch executor (sync_lockstate_custtoken, raw 0x668e8) runs
    # on every boot on this device and each time it:
    #   writes "recovery --wipe_data --reason=bootloader_unlock" into the misc BCB,
    #   sets sys_bootm |= 0x80000 (recovery) and param[0] = 4,
    #   performs the RPMB lock-state switch, then reboots.
    # The switch never persists here (RPMB is blocked at boot: "RPMB: key blocking:
    # success"), so the next boot repeats it -> an endless recovery/wipe loop
    # (unlock_count is already 15). Keep the switch logic, drop its three
    # side effects: the BCB wipe, the recovery boot bit and the param boot mode.
    app = find_xref(data, b"Device state switched (%d)\n\0") - 0x134
    want = {app + 0xE8: 0x2F2F0, app + 0xF4: 0x5D878, app + 0x108: 0x41698}
    for off, target in want.items():
        w = word(data, off)
        if (w & 0xFC000000) != 0x94000000:
            raise ValueError(f"executor: {off:#x} is not a bl ({w:#x})")
        imm = w & 0x3FFFFFF
        if imm & 0x2000000:
            imm -= 0x4000000
        if off + imm * 4 != target:
            raise ValueError(f"executor: {off:#x} does not call {target:#x}")
    for off in want:
        write_u32(data, off, 0xD503201F)
        _record(data, off, struct.pack("<I", 0xD503201F),
                f"executor_skip/{off:#x}", "branch_redirect", words=[0xD503201F])
    print(f"executor_skip_recovery: nop BCB/recovery/param calls at "
          f"{', '.join(hex(o) for o in want)}")

def patch_disable_secure_download_check(data):
    # The Secure Download verification ("SECURE CHECK FAIL : (%s)",
    # "SECUREDOWNLOAD"). With the fused custom key the expected image key is
    # OURS, so Samsung-signed images fail it: the stock AP's super.img died with
    # "SECURE CHECK FAIL : (SUPER)". The same check covers the boot images (its
    # failure path names VBMETA_SYSTEM / VENDOR_BOOT / INIT_BOOT), which is the
    # likely cause of the DT-stage abort.
    #
    # ~16 sites read ONE bypass flag, [0xbeed28], and skip the check when it is
    # non-zero. It is written in exactly one place (0x6ed50), and only when that
    # path's gate passes:
    #   flag value source  0x668b8  (single caller: the flag writer)
    #   its gate           0xa9e0   (true when [0x39fc88] == 1)
    # Stub both to return 1, so [0xbeed28] = 1 at boot and every secure check is
    # skipped - for the flash path and for the boot image load alike.
    app = find_xref(data, b"Device state switched (%d)\n\0") - 0x134
    value_src = app - 0x30
    gate = find_xref(data, b"[CM] set publick_key: start\n\0") - 0x4 - 0x10
    if word(data, value_src) != 0xA9BF7BFD:  # stp x29, x30, [sp, #-0x10]!
        raise ValueError(f"secure_download: bad value-source prologue at {value_src:#x}")
    if word(data, gate) != 0xB0001CA0:       # adrp x0, #0x39f000
        raise ValueError(f"secure_download: bad gate adrp at {gate:#x}")
    if word(data, gate + 4) != 0xB94C8800:   # ldr w0, [x0, #0xc88]
        raise ValueError(f"secure_download: bad gate load at {gate + 4:#x}")
    print(f"disable_secure_download: value_src {value_src:#x}, gate {gate:#x}")
    write_words(data, value_src, [0x52800020, 0xD65F03C0])  # mov w0, #1 ; ret
    write_words(data, gate, [0x52800020, 0xD65F03C0])       # mov w0, #1 ; ret
    _record(data, value_src, struct.pack("<2I", 0x52800020, 0xD65F03C0),
            "secure_download_bypass/value_source", "ret_const", w0=1)
    _record(data, gate, struct.pack("<2I", 0x52800020, 0xD65F03C0),
            "secure_download_bypass/gate", "ret_const", w0=1)

def patch_dt_entry_revision_fallback(data):
    # The DT-entry lookup load_fdt_from_dt_table (0x5e6f8) picks an entry by a
    # revision RANGE: entry[i].start <= device_rev <= entry[i].end, compared at
    # 0x5e794/0x5e79c (and the entry_rev <= 0xff path at 0x5e748). The device's
    # revision comes from OTP (id 0x10730103 via 0x19b0) and cannot be read from
    # the host, so when no range covers it the lookup returns NULL, the DTB/DTBO
    # pointer is never set, and the DT stage aborts ("DT Load Fail") on every boot
    # path - which is why no key combo, image swap or abl generation changed it.
    # Fix: fall back to the first entry by neutralising the four comparisons so the
    # first iteration reaches the match at 0x5e7a4.
    # Contract: branch redirects, verified by the recorded words.
    xref = find_xref(data, b"[UFDT] DT Entry: not found rev 0x%x.\n\0")
    fn = xref - 0x1D8
    _expect_prologue(data, fn, "dt_entry_lookup")
    loop = xref - 0x190
    sites = [
        (loop + 0x14, 0x540000A8, 0xD503201F),  # entry<=0xff: b.hi -> nop (keep entry)
        (loop + 0x24, 0x54000202, 0x14000010),  # entry<=0xff: b.hs -> b 0x5e7a4 (match)
        (loop + 0x58, 0x54FFFE88, 0xD503201F),  # range:        b.hi -> nop
        (loop + 0x60, 0x54FFFE43, 0xD503201F),  # range:        b.lo -> nop
    ]
    print(f"dt_entry_revision_fallback: fn {fn:#x}, loop {loop:#x}")
    for off, want, new in sites:
        if word(data, off) != want:
            raise ValueError(f"dt_entry_revision_fallback: unexpected word at {off:#x} ({word(data, off):#x})")
        write_u32(data, off, new)
        _record(data, off, struct.pack("<I", new),
                f"dt_entry_revision_fallback/{off:#x}", "branch_redirect", words=[new])

def patch_secure_check_bit3_gate(data):
    # _pit_flash_binary has TWO bit-3 sites, and only ONE of them is live:
    #
    #   Gate A  0x604c0  mov w0,#3 / bl 0x6dee8 / cbz w0,0x60e5c   -- DEAD
    #     sits inside the `verify #1 (0x67f88) < 0` block. verify #1 is the
    #     function patch_check_signature stubs to `return 0`, and no branch in
    #     _pit_flash_binary enters [0x60470,0x604c0), so that whole block - Gate A
    #     with it - is unreachable in every build we make. (v16 patched this
    #     word: inert dead-code, which is why v16 could not have moved super.img.)
    #
    #   Gate B  0x609a4  mov w0,#3 / bl 0x6dee8 / cbnz w0,0x61160  -- LIVE
    #     sits inside `if (FUN_00068b30(name) != 0 && FUN_000690a8(...) < 0)`.
    #     FUN_00068b30 is a name whitelist that CONTAINS "SUPER" (0x149980); and
    #     verify #2 (0x680a8) reads [0xbee250], NOT the secure-download bypass
    #     flag [0xbeed28] this build raises - which is exactly why the boot images
    #     verify through and only super.img reaches this block:
    #       bit 3 clear -> erase + "SECURE CHECK FAIL : (%s)" + return 0xffffff91
    #       bit 3 set   -> 0x61160: KG-state check, then the SUPER marker
    #                      (FUN_00064380(0x400)) and the ordinary write path
    #
    # Bit 3 is STEADY-token backed and clear on this device, so the clear side is
    # what stopped the stock AP at super.img. Make the bit-3-set route
    # unconditional (cbnz -> b) so a failed verification is not refused here;
    # verify #2 (0x680a8) itself is untouched.
    #
    # Anchors: the live site is identified by its own branch word (0x35003da0, two
    # occurrences image-wide) plus the unique preceding `bl 0x6dee8` from 0x609a8
    # (0x94003550, one occurrence). Gate A is asserted stock so the dead gate can
    # never again be mistaken for the live one.
    CAND = 0x35003DA0                       # cbnz w0, 0x61160
    hits = [o for o in range(0, len(data) - 4, 4) if word(data, o) == CAND]
    if len(hits) != 2:
        raise ValueError(f"secure_check_bit3_gate: expected two {CAND:#x}, found {[hex(h) for h in hits]}")
    site = [o for o in hits if word(data, o - 4) == 0x94003550]
    if len(site) != 1:
        raise ValueError(f"secure_check_bit3_gate: gate B not identified, found {[hex(o) for o in site]}")
    site = site[0]
    if word(data, site - 8) != 0x52800060:               # mov w0, #3
        raise ValueError(f"secure_check_bit3_gate: unexpected mov at {site - 8:#x}")
    if word(data, site + 4) != 0xF94043A5:               # ldr x5,[x29,#0x80]: the erase path
        raise ValueError(f"secure_check_bit3_gate: unexpected fallthrough at {site + 4:#x}")
    imm = (CAND >> 5) & 0x7FFFF
    if imm & 0x40000:
        imm -= 0x80000
    if site + imm * 4 != 0x61160:
        raise ValueError(f"secure_check_bit3_gate: cbnz target {site + imm*4:#x} != 0x61160")
    if word(data, 0x604C8) != 0x34004CA0:               # the dead gate must stay stock
        raise ValueError("secure_check_bit3_gate: gate A is not stock; leave the dead gate alone")
    new = 0x14000000 | (((0x61160 - site) >> 2) & 0x03FFFFFF)   # b 0x61160
    print(f"secure_check_bit3_gate: {site:#x} (cbnz w0, 0x61160 -> b 0x61160)")
    write_u32(data, site, new)
    _record(data, site, struct.pack("<I", new),
            "secure_check_bit3_gate", "branch_redirect", words=[new])

def patch_recovery_rp_gate(data):
    # check_samsung_secure_info (0x957c8) verifies each boot image, then calls
    # FUN_00067378 - the rollback-protection check - and HALTS on failure:
    #   * RECOVERY image -> an infinite `do { } while (true)` (0x95ae4 / 0x95f94)
    #   * anything else  -> 5 s delay + FUN_0005e0c0(0xf)
    # On this device the ESI-backed counter no longer matches the flashed images,
    # so every boot lands in that halt. That is the "stuck on the Samsung splash,
    # no adb" state, and it is also why recovery has never come up.
    # Same class as the existing check_sw_rev / check_kernel_rev / check_system_rev
    # / check_pit_rev stubs: keep the check and its logging, make the verdict
    # advisory.
    #
    #   0x958f4  bl   0x66378
    #   0x958f8  tbnz w0,#0x1f,0x95f38   -> nop          (green branch)
    #   0x95a80  bl   0x66378
    #   0x95a84  tbz  w0,#0x1f,0x958fc   -> b 0x958fc    (orange branch, this device)
    sites = [
        (0x958F8, 0xD503201F, "nop"),
        (0x95A84, 0x17FFFF9E, "b 0x958fc"),
    ]
    for off, new, what in sites:
        w = word(data, off)
        if word(data, off - 4) & 0xFC000000 != 0x94000000:
            raise ValueError(f"recovery_rp: no bl before {off:#x}")
        imm = word(data, off - 4) & 0x3FFFFFF
        if imm & (1 << 25):
            imm -= 1 << 26
        if off - 4 + imm * 4 != 0x66378:
            raise ValueError(f"recovery_rp: {off - 4:#x} is not a call to the RP check")
        want = 0x37000000 if off == 0x958F8 else 0x36000000   # TBNZ / TBZ
        if (w & 0x7F000000) != want:
            raise ValueError(f"recovery_rp: {off:#x} is not {'tbnz' if off == 0x958F8 else 'tbz'} ({w:#x})")
        print(f"recovery_rp_gate: {off:#x} {w:#010x} -> {new:#010x} ({what})")
        write_u32(data, off, new)
        _record(data, off, struct.pack("<I", new),
                f"recovery_rp_gate/{off:#x}", "branch_redirect", words=[new])

def patch_recovery_secure_check_gate(data):
    # The THIRD bit-3 gate, in a separate function (entry 0x671d8) - not
    # _pit_flash_binary. This is the one that refuses RECOVERY: bit 3 is clear on
    # this device, so any image reaching it prints "SECURE CHECK FAIL : (%s)".
    # The _pit_flash_binary whitelist does not contain RECOVERY, which is why the
    # Gate-B patch let SUPER through and did nothing here.
    #   0x6720c  mov w0,#3
    #   0x67210  bl  0x6dee8          <- same bit-3 accessor as the unlock executor
    #   0x67214  cbnz w0,0x67298      <- bit 3 set -> skip the refusal
    # Patch: unconditional b 0x67298, same shape as secure_check_bit3_gate.
    SITE = 0x67214
    w = word(data, SITE)
    if word(data, SITE - 8) != 0x52800060:
        raise ValueError(f"recovery_secure_check: bad mov at {SITE - 8:#x}")
    if word(data, SITE - 4) != 0x94001B36:          # bl 0x6dee8 from 0x67210
        raise ValueError(f"recovery_secure_check: {SITE - 4:#x} is not bl 0x6dee8")
    if (w & 0x7F000000) != 0x35000000:
        raise ValueError(f"recovery_secure_check: {SITE:#x} is not cbnz ({w:#x})")
    imm = (w >> 5) & 0x7FFFF
    if imm & 0x40000:
        imm -= 0x80000
    if SITE + imm * 4 != 0x67298:
        raise ValueError(f"recovery_secure_check: branch target {SITE + imm * 4:#x} != 0x67298")
    new = 0x14000000 | (((0x67298 - SITE) >> 2) & 0x03FFFFFF)
    print(f"recovery_secure_check_gate: {SITE:#x} cbnz 0x67298 -> b 0x67298 ({new:#010x})")
    write_u32(data, SITE, new)
    _record(data, SITE, struct.pack("<I", new),
            "recovery_secure_check_gate", "branch_redirect", words=[new])


# set_oneshot_recovery's runtime address. It occurs exactly once in the image:
# in the keypad dispatch table (entry at -0x18), so it doubles as the anchor.
SET_ONESHOT_RECOVERY = 0xE8015118
# The dispatch table's shared "is this boot mode allowed" test (leaf, same for
# the Download and Recovery entries) - used to prove we found the right record.
KEYPAD_DISPATCH_TEST = 0xE80A1BC8


def patch_keypad_recovery_combo(data):
    # Optional v23 patch. Captured boot logs show the scanner returning 0x101
    # and dispatching "Recovery Mode"; later analysis found the PMIC power-on
    # key state can be latched across warm reboots, so those logs alone do not
    # prove that a keyless cold boot produces 0x101. This patch remaps only that
    # explicit Recovery table entry. It does not control the normal boot
    # default; patch_force_recovery_boot owns that behavior.
    #
    # Move the entry's keycode 0x101 -> 0x102. The scan values are built from
    # 0x1|0x10|0x100, so 0x102 does not match. Download mode 0x11 is untouched.
    # Do not claim recovery remains available through BCB: this sboot has no
    # Android BCB parser; Download/EUB are the preserved escape routes.
    anchor = struct.pack("<Q", SET_ONESHOT_RECOVERY)
    off = data.find(anchor)
    if off < 0:
        raise ValueError("keypad_recovery: set_oneshot_recovery pointer not found")
    if data.find(anchor, off + 1) >= 0:
        raise ValueError("keypad_recovery: set_oneshot_recovery pointer is not unique")
    entry = off - 0x18
    if word(data, entry + 8) != 0x101 or word(data, entry + 12) != 0:
        raise ValueError(f"keypad_recovery: entry {entry:#x} keycode is not 0x101")
    if word(data, entry + 16) != KEYPAD_DISPATCH_TEST:
        raise ValueError(f"keypad_recovery: entry {entry:#x} test ptr is not {KEYPAD_DISPATCH_TEST:#x}")
    if word(data, entry + 32) != 0:
        raise ValueError(f"keypad_recovery: entry {entry:#x} terminator flag is set")
    name = struct.unpack_from("<Q", data, entry)[0] - 0xE8000000
    if data[name:name + 13] != b"Recovery Mode":
        raise ValueError(f"keypad_recovery: entry {entry:#x} is not the Recovery Mode record")
    print(f"keypad_recovery_combo: {entry + 8:#x} keycode 0x101 -> 0x102 "
          f"(action {SET_ONESHOT_RECOVERY:#x})")
    _record(data, entry + 8, struct.pack("<Q", 0x102),
            "keypad_recovery_combo", "branch_redirect", words=[0x102, 0])


def _relative_branch_target(data, offset, mask, opcode_mask, imm_bits):
    instruction = word(data, offset)
    if instruction & mask != opcode_mask:
        return None
    return offset + (signed((instruction >> 5) & ((1 << imm_bits) - 1), imm_bits) << 2)


def _bl_target(data, offset):
    instruction = word(data, offset)
    if instruction & 0xFC000000 != 0x94000000:
        return None
    return offset + (signed(instruction & 0x03FFFFFF, 26) << 2)


def _encode_cbz_w0(offset, target):
    delta = target - offset
    if delta % 4 or not -(1 << 20) <= delta < (1 << 20):
        raise ValueError(f"force_recovery_boot: CBZ target out of range: {target:#x}")
    return 0x34000000 | (((delta >> 2) & 0x7FFFF) << 5)


def _encode_b(offset, target):
    delta = target - offset
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise ValueError(f"force_recovery_boot: B target out of range: {target:#x}")
    return 0x14000000 | ((delta >> 2) & 0x03FFFFFF)


def locate_default_recovery_branch(data):
    """Locate platform_init's param[0] == 0 normal-boot edge.

    The full surrounding instruction window is checked so a similar getter
    elsewhere cannot be mistaken for this branch. Offsets are bootload-relative.
    """
    param_get = 0x41C98  # runtime 0xe8041c98 minus the image base 0xe8000000
    candidates = []
    for call in range(0, len(data) - 40, 4):
        if _bl_target(data, call) != param_get:
            continue
        site = call + 4
        if (_relative_branch_target(data, site, 0x7F00001F, 0x34000000, 19) != 0x2A48
                or word(data, call + 8) != 0x52800000
                or _bl_target(data, call + 12) != param_get
                or word(data, call + 16) != 0x2A0003F3
                or word(data, call + 20) != 0x51001000
                or word(data, call + 24) != 0x7100041F
                or word(data, call + 28) != 0x54002229
                or word(data, call + 32) != 0x71001A7F
                or word(data, call + 36) != 0x54FFF821):
            continue
        if (_relative_branch_target(data, call + 28, 0xFF000010, 0x54000000, 19) != 0x2F80
                or _relative_branch_target(data, call + 36, 0xFF000010, 0x54000000, 19) != 0x2A48):
            continue
        candidates.append(site)
    if len(candidates) != 1:
        raise ValueError(f"force_recovery_boot: expected one normal-mode selector, found {len(candidates)}")
    return candidates[0]


def patch_force_recovery_boot(data):
    # platform_init's param[0] == 0 edge normally continues to Android. Route
    # only that default case to the existing Recovery Set block. param[0] 4/5
    # and the special 6 path keep their original logic; the separate Download
    # Mode action and upload/EUB paths are untouched.
    #
    # The trampoline occupies two Ghidra-verified NOP words after a RET at
    # 0xc6248. No code or data references enter the cave. It zeros w19 so the
    # existing Recovery Set log reports mode 0 accurately, then branches to the
    # existing recovery setup at 0x2f80. No param/UFS write is introduced.
    site = locate_default_recovery_branch(data)
    expected_cave = 0xC624C
    recovery_block = 0x2F80
    if word(data, 0xC6248) != 0xD65F03C0:  # ret immediately before the cave
        raise ValueError("force_recovery_boot: code-cave predecessor is not RET")
    if word(data, expected_cave) != 0xD503201F or word(data, expected_cave + 4) != 0xD503201F:
        raise ValueError("force_recovery_boot: expected two unused NOP words at 0xc624c")

    branch = _encode_cbz_w0(site, expected_cave)
    trampoline = [0x52800013, _encode_b(expected_cave + 4, recovery_block)]  # mov w19,#0; b recovery
    print(f"force_recovery_boot: {site:#x} param[0]==0 -> cave {expected_cave:#x} -> {recovery_block:#x}")
    _record(data, site, struct.pack("<I", branch),
            "force_recovery_default/branch", "branch_redirect", words=[branch])
    _record(data, expected_cave, struct.pack("<2I", *trampoline),
            "force_recovery_default/trampoline", "branch_redirect", words=trampoline)

def get_efuse_data():
    import hmac
    from sign import load_private_key, pubkey_blob
    with open("keys/hmac.bin", "rb") as f:
        hmac_key = f.read()
    if len(hmac_key) != 32:
        raise ValueError("hmac.bin should be 32 bytes")
    key = load_private_key("keys/4/st1.pem")
    public_blob = pubkey_blob(key.public_key(), 4)
    return bytes(a ^ b for a, b in zip(hmac.digest(hmac_key, public_blob[:136], "sha512")[:32], hmac_key))

def patch_sbl_check_upload(data):
    sbl_check_upload = find_xref(data, b"sbl_check_upload\0") - 0x24
    print(f"sbl_check_upload: {sbl_check_upload:#x}")
    data[sbl_check_upload : sbl_check_upload + len(RETURN_ONE)] = RETURN_ONE

def patch_fuse_boot_key(data):
    check_signature = find_xref(data, b"%s: There is no signature\n\0") - 0xDC

    rom_key_start_xref = find_xref(data, b"[OTP] ROM_SECURE_BOOT_KEY program start\n\0")
    cm_otp_write_rom_sec_boot_key = rom_key_start_xref - 0x58
    rom_key_selector = rom_key_start_xref + 0x88

    use_key_start_xref = find_xref(data, b"[OTP] USE_ROM_SEC_BOOT_KEY program start\n\0")
    cm_otp_write_use_rom_sec_boot_key = use_key_start_xref - 0x4
    use_key_selector = use_key_start_xref + 0x18

    print(f"check_signature: {check_signature:#x}")
    print(f"cm_otp_write_rom_sec_boot_key: {cm_otp_write_rom_sec_boot_key:#x}")
    print("cm_otp_write_use_rom_sec_boot_key: " f"{cm_otp_write_use_rom_sec_boot_key:#x}")
    # Contract: fuse_payload performs the key burn with a balanced custom
    # frame and returns x0=0 (its callers only test validity); the two
    # selector words are value_write (SP/branch-neutral).
    print("WARNING: patching for burning BOOT_KEY!")

    payload = [
        0xA9BF7BFD,
        0x100000E0,
        0x52800401,
        jump_to_func_from(check_signature + 12, cm_otp_write_rom_sec_boot_key),
        jump_to_func_from(check_signature + 16, cm_otp_write_use_rom_sec_boot_key),
        0xD2800000,
        0xA8C17BFD,
        0xD65F03C0,
    ]

    write_u32(data, rom_key_selector, 0xD28002C1) # write key2
    write_u32(data, use_key_selector, 0xD28002E1) # write use key2

    payload.extend(struct.unpack("<8I", get_efuse_data()))
    write_words(data, check_signature, payload)
    _record(data, rom_key_selector, struct.pack("<I", 0xD28002C1),
            "cm_otp_rom_key_selector", "value_write")   # write key2
    _record(data, use_key_selector, struct.pack("<I", 0xD28002E1),
            "cm_otp_use_key_selector", "value_write")   # write use key2
    _record(data, check_signature, struct.pack("<%dI" % len(payload), *payload),
            "check_signature_fuse_payload", "fuse_payload", w0=0)

# The fuse is already burned (2026-10-09, user-approved; keys backed up at
# keys_backup_20261009/), so every build made from now on must be able to skip
# the burn: `EUB_SHOULD_FUSE_KEY=0` produces the no-fuse variant, which is what
# a RAM-served candidate uses (it must not touch OTP at all). The default stays
# True so the historical build path is unchanged.
should_fuse_key = os.environ.get("EUB_SHOULD_FUSE_KEY", "1").lower() not in (
    "0", "false", "no", "")

if __name__ == "__main__":
    with open(sys.argv[1], "rb") as f:
        data = bytearray(f.read())

    patch_check_signature(data)
    patch_prevent_warranty_fuse(data)
    patch_check_sw_rev(data)
    patch_check_kernel_rev(data)
    patch_check_system_rev(data)
    patch_check_pit_rev(data)
    patch_seandroid_enforcing_off(data)               # v6: the SEAndroid/TIMA
    #   enforcing query -> always off; unblocks the boot/recovery image
    #   trailer check (the LOS recovery has no Samsung trailer)
    # RETIRED (change ground-up-unlock-state, group 6): the unlock state is now
    # materialised instead of stubbed, so the patches that only compensated for
    # a locked device state are gone from the build:
    #   patch_state_switch_app_noop               (v8) - the executor must RUN
    #     now: it is the thing that performs the real unlock.
    # patch_state_cache_read_always_unlocked stays retired from v8 (it made the
    # executor relock on every boot).
    # RESTORED (group 9): the decider's ops-variant reader is load-bearing on its
    # own - the DT-stage abort is not a locked-state effect (v10: boot 1 switched
    # the state, boot 2 still aborted).
    # v25 experiment (removed, prove): without these two the bootloader enforces
    # the vbmeta hash, and our vbmeta is a stock image with only its flags word
    # changed -> "Error verifying vbmeta image: HASH_MISMATCH (3)" + Security
    # Error. They are load-bearing, not lock-state compensation.
    patch_avbops_state_reader_always_unlocked(data)
    # RESTORED (restore-stock-boot): the OEM-lock flash gate. Stock images fail
    # OUR fused key's check and therefore count as "custom", and the gate blocks
    # custom-class AP flashes while the device is locked - so this has to be open
    # to flash a stock AP under our BL.
    patch_read_is_device_unlocked(data)
    # RESTORED/ADDED (restore-stock-boot): the Secure Download check refuses
    # Samsung-signed images under our fused key - it stopped the stock AP at
    # super.img, and it covers the boot images too.
    patch_disable_secure_download_check(data)
    # ADDED (fix-recovery-dt-stage): the DT stage aborts because the revision-keyed
    # DT-entry lookup returns NULL for this device's OTP revision, so no image
    # loads. Fall back to the first entry.
    #
    # v24: DISABLED by default. The NHZF5 dtbo declares its ranges in the table's
    # custom words: entry0 0x00..0x10, entry1 0x11..0x11, entry2 0x12..0x20. This
    # device's revision is 18 (0x12), so entry2 - not entry0 - is the correct DTB.
    # Forcing the first entry handed the kernel a revision 0..16 DTB on a rev-18
    # board, which is consistent with a hang before display/USB. The original
    # abort was diagnosed before the stock dtbo was in place.
    # Set EUB_DT_FALLBACK=1 to restore the historical behaviour.
    if os.environ.get("EUB_DT_FALLBACK", "0") != "0":
        patch_dt_entry_revision_fallback(data)
    # ADDED (restore-stock-boot group 6): the per-image secure-check refusal is
    # gated by bit 3 (STEADY-token backed and clear on this device), which is what
    # refused the stock AP's super.img. Retargeted from Gate A (0x604c8, dead
    # code) to Gate B (0x609ac, the live site that sees SUPER) - see the
    # function's own comment.
    patch_secure_check_bit3_gate(data)
    # ADDED (v21): the recovery/kernel rollback-protection gate in
    # check_samsung_secure_info halts - infinite loop for a RECOVERY image, 5 s +
    # FUN_0005e0c0(0xf) for anything else - when FUN_00067378 fails. On this
    # device that failure is why every boot parks on the splash with no adb, and
    # why recovery has never come up.
    patch_recovery_rp_gate(data)
    # ADDED (v22): the third bit-3 gate (separate function, entry 0x671d8). This
    # is the one that refuses RECOVERY on a device with bit 3 clear, which is the
    # "SECURE CHECK FAIL : (RECOVERY)" seen when flashing TWRP.
    patch_recovery_secure_check_gate(data)
    # The optional v23 key-table patch disables the explicit Vol-Up+Power
    # Recovery Mode entry (keycode 0x101 -> unreachable 0x102); it is unrelated
    # to the forced default path above and remains off by default.
    if os.environ.get("EUB_KEYPAD_RECOVERY_COMBO", "0") != "0":
        patch_keypad_recovery_combo(data)
    # v26: OFF. With the no-descriptor vbmeta the stock unlock executor runs at
    # boot ("Device state switched"), switches state and reboots -> bootloop.
    # EUB_OEM_UNLOCK_GATE=1 restores it.
    if os.environ.get("EUB_OEM_UNLOCK_GATE", "0") != "0":
        patch_open_oem_unlock_gate(data)
    # v27: stop the executor's forced recovery + data wipe (the bootloop).
    if os.environ.get("EUB_EXECUTOR_RECOVERY", "0") == "0":
        patch_executor_skip_recovery(data)                  # opens only the allowed-
    #   bit gate so the STOCK executor performs its own unlock (wipe BCB + DT
    #   bit + rpmb_set_lock(0) + switch counter). The bit itself is a
    #   signature-verified STEADY-token mode bit and cannot be raised.
    if should_fuse_key:
        patch_fuse_boot_key(data)
    # v28: force only platform_init's ordinary param[0]==0 path to its existing
    # recovery block. The explicit Download Mode action, upload/EUB route,
    # param[0] 4/5 recovery route, and param[0]==6 restore path are preserved.
    patch_force_recovery_boot(data)
    #patch_sbl_check_upload(data)

    with open(sys.argv[1], "wb") as f:
        f.write(data)
