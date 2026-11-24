#!/usr/bin/env python3
"""Contract validator for the S5E9840 boot chain.

OpenSpec change: repair-bootloader-patch-contracts
Spec: specs/boot-chain-contract-safety/spec.md (executable replacements
preserve callee contracts; built artifacts receive binary contract verification).

Stages
------
stock   <sboot_stock.bin|bootload_stock.bin>
        Anchor resolution + baseline capture only (an unpatched member is
        expected to fail every patch contract, so contracts are not applied).
image   <bboot_or_bootload_of_a_deployed_image>
        Contract checks against any shipped image (catches historical defects
        such as the two v8 ABI violations).
packed  <final.tar.md5> [--expect-image <signer_output_sboot.bin>]
        Tar structure + md5 footer + member set, contract checks on the
        bootload region of the packed sboot, and identity versus the built
        signed sboot when --expect-image is given.
selftest [--v8-tar <path>]
        Fixtures: the real v8 tar must be REJECTED with both known defects
        named; a stock region with a corrupted anchor must fail anchor
        resolution.

Contract kinds
--------------
ret_const     true-entry detection, net SP delta 0 at every ret reachable
              from the true entry, final w0 == expected constant
reader_store  net SP delta 0; at least one store through the original
              output-pointer argument with the expected value; no store
              through a suspiciously low constant address; final w0 == 0
value_write   replacement words touch neither SP, x29, x30, nor control flow
fuse_payload  balanced custom frame; final x0 == 0

Exit codes: 0 all required checks pass; 1 violations; 2 usage/IO error.
"""

import argparse
import hashlib
import os
import re
import struct
import sys
import tarfile

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

BOOTLOAD_SIZE = 0x2A3000
SBOOT_SIZE = 0x400000
SBOOT_BOOTLOAD_OFFSET = 0xEC000

MD = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)

RET = 0xD65F03C0
UDF = 0x00000000
NOP = 0xD503201F

# BL1's EUB bootstrap payload. Every archived build that boots embeds it at
# +0x2000 (exec'd at 0x02024000 = BL1 load 0x02022000 + 0x2000). Stock has that
# region zeroed, and a build that omits it never runs: BL1 falls back to its
# stock verification of our re-signed chain, fails, and halts - no display, no
# download mode, EUB only. That was the v17 no-boot.
BL1_PAYLOAD_OFFSET = 0x2000
BL1_PAYLOAD_END = 0x2170
BL1_PAYLOAD_FILE = "9840_boot_custom_key_ours.bin"


# --------------------------------------------------------------------------
# low-level helpers
# --------------------------------------------------------------------------

def word(d, o):
    return int.from_bytes(d[o:o + 4], "little")


def signed(v, bits):
    s = 1 << (bits - 1)
    return (v ^ s) - s


def adrp_add(d, o):
    a = word(d, o)
    if a & 0x9F000000 != 0x90000000:
        return None
    imm = ((a >> 29) & 3) | (((a >> 5) & 0x7FFFF) << 2)
    page = (o & ~0xFFF) + (signed(imm, 21) << 12)
    for dist in range(4, 17, 4):
        add = word(d, o + dist)
        if add & 0xFF000000 == 0x91000000 and (add >> 5) & 31 == a & 31:
            return page + (((add >> 10) & 0xFFF) << (12 if add & 0x400000 else 0))
    return None


class ResolveError(Exception):
    pass


def anchor_offset(d, needle, delta):
    off = d.find(needle)
    if off < 0:
        raise ResolveError(f"anchor string missing: {needle!r}")
    if d.find(needle, off + 1) >= 0:
        raise ResolveError(f"anchor string not unique: {needle!r}")
    refs = [o for o in range(0, off & ~3, 4) if adrp_add(d, o) == off]
    if len(refs) != 1:
        raise ResolveError(f"anchor adrp+add not unique: {needle!r} ({len(refs)} refs)")
    return refs[0] + delta


def bl_target(d, off):
    w = word(d, off)
    if w & 0xFC000000 != 0x94000000:
        raise ResolveError(f"expected bl at {off:#x} ({w:#x})")
    return off + (signed(w & 0x03FFFFFF, 26) << 2)


def cbz_target(d, off):
    w = word(d, off)
    if w & 0x7F00001F != 0x34000000:
        raise ResolveError(f"expected CBZ W0 at {off:#x} ({w:#x})")
    return off + (signed((w >> 5) & 0x7FFFF, 19) << 2)


def bcond_target(d, off):
    w = word(d, off)
    if w & 0xFF000010 != 0x54000000:
        raise ResolveError(f"expected B.cond at {off:#x} ({w:#x})")
    return off + (signed((w >> 5) & 0x7FFFF, 19) << 2)


def locate_force_recovery_default_branch(d):
    """Find the param[0] == 0 edge in platform_init, before or after patching."""
    param_get = 0x41C98  # runtime 0xe8041c98 minus base 0xe8000000
    candidates = []
    for call in range(0, len(d) - 40, 4):
        try:
            if bl_target(d, call) != param_get:
                continue
            branch = call + 4
            target = cbz_target(d, branch)
            if (target not in (0x2A48, 0xC624C)
                    or word(d, call + 8) != 0x52800000
                    or bl_target(d, call + 12) != param_get
                    or word(d, call + 16) != 0x2A0003F3
                    or word(d, call + 20) != 0x51001000
                    or word(d, call + 24) != 0x7100041F
                    or word(d, call + 28) != 0x54002229
                    or word(d, call + 32) != 0x71001A7F
                    or word(d, call + 36) != 0x54FFF821
                    or bcond_target(d, call + 28) != 0x2F80
                    or bcond_target(d, call + 36) != 0x2A48):
                continue
            candidates.append(branch)
        except ResolveError:
            continue
    if len(candidates) != 1:
        raise ResolveError(f"expected one forced-recovery selector, found {len(candidates)}")
    return candidates[0]


def locate_force_recovery_default_trampoline(d):
    """The two-word, unreachable NOP cave used by the normal-mode branch."""
    off = 0xC624C
    if word(d, off - 4) != 0xD65F03C0:  # preceding instruction is RET
        raise ResolveError("forced-recovery cave is no longer after the verified RET")
    words = [word(d, off), word(d, off + 4)]
    if words not in ([0xD503201F, 0xD503201F], [0x52800013, 0x17FCF34C]):
        raise ResolveError(f"forced-recovery cave has unexpected contents: {[hex(w) for w in words]}")
    return off


def locate_enforcing(d):
    xr = anchor_offset(d, b"[TIMA trusted boot]: SEAndroid MAGIC failure (recovery.img)\n\0", 0)
    return bl_target(d, xr + 0x0C)


def locate_state_cache(d):
    xr = anchor_offset(d, b"PERSISTENT\0", 0)
    fn = xr - 0x64
    return bl_target(d, fn + 0xEC)


def locate_alt(primary, alt):
    def _loc(d):
        # Two anchors point at the same function; either may prove unique.
        try:
            return primary(d)
        except ResolveError:
            return alt(d)
    return _loc


# --------------------------------------------------------------------------
# contract table
# --------------------------------------------------------------------------

def locate_unique_word(d, w):
    """Locate a site by a word that occurs exactly once (self-verifying anchor)."""
    hits = [o for o in range(0, len(d) - 4, 4) if word(d, o) == w]
    if len(hits) != 1:
        raise ResolveError(f"expected one occurrence of {w:#010x}, found {len(hits)}")
    return hits[0]


def locate_bit3_gate(d):
    """The LIVE bit-3 gate in _pit_flash_binary: `cbnz w0, 0x61160` at 0x609ac.

    _pit_flash_binary carries two bit-3 sites and they are one word apart in
    shape, so the window has to tell them apart:
      Gate A  0x604c8  cbz  w0, 0x60e5c - inside the verify#1 (0x67f88) failure
              block, which patch_check_signature makes unreachable (it stubs
              verify#1 to `return 0`, and no branch enters [0x60470,0x604c0)).
              Dead code: patching it was v16's error.
      Gate B  0x609ac  cbnz w0, 0x61160 - inside the verify#2 (0x680a8) block,
              whose predicate FUN_00068b30 whitelists "SUPER".
    Anchored on the four-word window
    [mov w0,#3][bl 0x6dee8 from 0x609a8][?][ldr x5,[x29,#0x80] = the erase path]
    with the site itself wildcarded, so it resolves identically before and after
    patching (the patched word is the wildcard). Gate A's word is asserted stock
    here so the dead gate can never be mistaken for this one again.
    """
    hits = [
        o for o in range(0, len(d) - 16, 4)
        if word(d, o) == 0x52800060
        and word(d, o + 4) == 0x94003550
        and word(d, o + 12) == 0xF94043A5
    ]
    if len(hits) != 1:
        raise ResolveError(f"bit3 gate: expected one window, found {len(hits)}")
    if word(d, 0x604C8) != 0x34004CA0:
        raise ResolveError("bit3 gate: the dead Gate A (0x604c8) is not stock")
    return hits[0] + 8


def locate_keypad_combo(d):
    """The keypad dispatch table's Recovery Mode keycode slot (v23).

    Anchored on set_oneshot_recovery's runtime address, which occurs exactly
    once in the image (as that table entry's action pointer).
    """
    anchor = struct.pack("<Q", 0xE8015118)
    off = d.find(anchor)
    if off < 0 or d.find(anchor, off + 1) >= 0:
        raise ResolveError("keypad combo: set_oneshot_recovery pointer not unique")
    entry = off - 0x18
    try:
        name = struct.unpack_from("<Q", d, entry)[0] - 0xE8000000
    except struct.error:
        raise ResolveError("keypad combo: table entry truncated")
    if d[name:name + 13] != b"Recovery Mode":
        raise ResolveError("keypad combo: entry is not the Recovery Mode record")
    return entry + 8


def _L(needle, delta):
    return lambda d: anchor_offset(d, needle, delta)


CONTRACTS = [
    {
        # RETIRED (ground-up-unlock-state group 6): the executor must run, so
        # this site is stock again and the contract is informational.
        "name": "state_switch_app", "kind": "ret_const", "optional": True,
        # true entry = the `sub sp, sp, #0x450` that v8 overshot by 0x8
        "locate": _L(b"Device state switched (%d)\n\0", -0x134),
        "w0": 0xFFFFFFFF,
    },
    {
        # RESTORED (group 9): the v10 device result showed the DT-stage abort is
        # not a locked-state effect, so this reader stub is required again.
        "name": "avb_state_reader", "optional": True, "kind": "reader_store",
        "locate": locate_alt(_L(b"exynos_read_is_device_unlocked\0", -0x28),
                             _L(b"%s : RPMB is not initialized yet\n\0", -0x2C)),
        "out_arg": 1, "out_value": 1, "w0": 0,
    },
    {
        "name": "open_oem_unlock_gate/unlock_branch", "optional": True, "kind": "branch_redirect",
        "locate": _L(b"Device state switched (%d)\n\0", -0x134 + 0x48),
        "words": [0x14000001],
    },
    {
        "name": "open_oem_unlock_gate/relock_skip", "optional": True, "kind": "branch_redirect",
        "locate": _L(b"Device state switched (%d)\n\0", -0x134 + 0x70),
        "words": [0x14000047],
    },
    {
        "name": "secure_download_bypass/value_source", "kind": "ret_const",
        "locate": _L(b"Device state switched (%d)\n\0", -0x134 - 0x30),
        "w0": 1,
    },
    {
        "name": "secure_download_bypass/gate", "kind": "ret_const",
        "locate": _L(b"[CM] set publick_key: start\n\0", -0x14),
        "w0": 1,
    },
    {
        # v24: the DT entry fallback is disabled (the stock NHZF5 dtbo covers rev 18
        # in entry 2; forcing entry 0 supplied a rev 0..16 DTB). Optional so a
        # build without it still verifies.
        "name": "dt_entry_fallback/le_hi", "kind": "branch_redirect", "optional": True,
        "locate": _L(b"[UFDT] DT Entry: not found rev 0x%x.\n\0", -0x17C),
        "words": [0xD503201F],
    },
    {
        # v24: the DT entry fallback is disabled (the stock NHZF5 dtbo covers rev 18
        # in entry 2; forcing entry 0 supplied a rev 0..16 DTB). Optional so a
        # build without it still verifies.
        "name": "dt_entry_fallback/le_match", "kind": "branch_redirect", "optional": True,
        "locate": _L(b"[UFDT] DT Entry: not found rev 0x%x.\n\0", -0x16C),
        "words": [0x14000010],
    },
    {
        # v24: the DT entry fallback is disabled (the stock NHZF5 dtbo covers rev 18
        # in entry 2; forcing entry 0 supplied a rev 0..16 DTB). Optional so a
        # build without it still verifies.
        "name": "dt_entry_fallback/range_hi", "kind": "branch_redirect", "optional": True,
        "locate": _L(b"[UFDT] DT Entry: not found rev 0x%x.\n\0", -0x138),
        "words": [0xD503201F],
    },
    {
        # v24: the DT entry fallback is disabled (the stock NHZF5 dtbo covers rev 18
        # in entry 2; forcing entry 0 supplied a rev 0..16 DTB). Optional so a
        # build without it still verifies.
        "name": "dt_entry_fallback/range_lo", "kind": "branch_redirect", "optional": True,
        "locate": _L(b"[UFDT] DT Entry: not found rev 0x%x.\n\0", -0x130),
        "words": [0xD503201F],
    },
    {
        # bit-3 gate in _pit_flash_binary, Gate B (the live one):
        # cbnz w0, 0x61160 -> b 0x61160, so a failed verification is not refused
        # there. Anchored on the surrounding window so it also resolves once
        # patched; Gate A (0x604c8) is dead code and must stay stock.
        "name": "secure_check_bit3_gate", "kind": "branch_redirect",
        "locate": locate_bit3_gate,
        "words": [0x140001ED],
    },
    # NOTE: BL1 lives in the sboot, not in the bootload region this table operates
    # on, so the BL1 payload invariant is checked separately against the sboot -
    # see bl1_payload_ok(), used by stage_packed/stage_image.
    {
        "name": "check_signature_fuse_payload", "kind": "fuse_payload",
        "locate": _L(b"%s: There is no signature\n\0", -0xDC),
        "w0": 0,
    },
    {
        "name": "set_warranty_void_bit_reason", "kind": "ret_const",
        "locate": _L(b"%s : invalid value\n\0", +0x24), "w0": 0,
    },
    {
        "name": "set_warrant_bit", "kind": "ret_const",
        "locate": _L(b"[EFUSE] Set warranty bit(0x%llx)\n\0", -0x4C), "w0": 0,
    },
    {
        "name": "check_sw_rev", "kind": "ret_const",
        "locate": _L(b"[EFUSE] RB count: device(0x%llx), flash image(0x%llx)\n\0", -0x2C), "w0": 0,
    },
    {
        "name": "check_kernel_rev", "kind": "ret_const",
        "locate": _L(b"KERNEL REV. CHECK FAIL. DEVICE:%d, BINARY:%d (%s)\n\0", -0x114), "w0": 0,
    },
    {
        "name": "check_system_rev", "kind": "ret_const",
        "locate": _L(b"SYSTEM REV. CHECK FAIL. DEVICE:%d, BINARY:%d (%s)\n\0", -0xC4), "w0": 0,
    },
    {
        "name": "check_pit_rev", "kind": "ret_const",
        "locate": _L(b"PIT RB count: BINARY:%d\n\0", -0x60), "w0": 0,
    },
    {
        "name": "seandroid_enforcing_query", "kind": "ret_const",
        "locate": locate_enforcing, "w0": 0,
    },
    {
        "name": "read_is_device_unlocked/default_ret", "optional": True, "kind": "value_write",
        "locate": _L(b"PERSISTENT\0", -0x44), "size": 4,
    },
    {
        "name": "read_is_device_unlocked/computed_ret", "optional": True, "kind": "value_write",
        "locate": _L(b"PERSISTENT\0", +0x94), "size": 4,
    },
    {
        "name": "cm_otp_rom_key_selector", "kind": "value_write",
        "locate": _L(b"[OTP] ROM_SECURE_BOOT_KEY program start\n\0", +0x88), "size": 4,
    },
    {
        "name": "cm_otp_use_key_selector", "kind": "value_write",
        "locate": _L(b"[OTP] USE_ROM_SEC_BOOT_KEY program start\n\0", +0x18), "size": 4,
    },
    {
        "name": "state_cache_read", "kind": "reader_store", "optional": True,
        "locate": locate_state_cache, "out_arg": 0, "out_value": 0, "w0": 0,
    },
    {
        # Captured logs show 0x101 dispatching "Recovery Mode"; warm-reboot
        # PMIC latching means this does not prove a keyless cold boot scans 0x101.
        # The optional patch remaps only that entry; Download Mode (0x11) stays.
        "name": "keypad_recovery_combo", "kind": "branch_redirect", "optional": True,
        "locate": locate_keypad_combo, "words": [0x102, 0],
    },
    {
        # The normal param[0] == 0 path must enter the existing Recovery Set
        # block; nonzero modes retain the original 4/5 recovery and 6 restore
        # logic. The CBZ lands in the verified two-word cave, which sets the
        # logged mode to 0 before branching to 0x2f80.
        "name": "force_recovery_default/branch", "kind": "branch_redirect",
        "locate": locate_force_recovery_default_branch, "words": [0x3461B940],
    },
    {
        "name": "force_recovery_default/trampoline", "kind": "branch_redirect",
        "locate": locate_force_recovery_default_trampoline,
        "words": [0x52800013, 0x17FCF34C],
    },
]


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------

def find_entry(d, off, max_back=64):
    """True function entry: the first instruction after the nearest preceding
    ret (skipping udf/nop padding) or after a backward unconditional branch."""
    thr = max(0, off - max_back * 4)
    i = off
    while i > thr:
        w = word(d, i - 4)
        if w == RET:
            e = i
            while e < off and word(d, e) in (UDF, NOP):
                e += 4
            return e
        if (w & 0xFC000000) == 0x14000000:  # b
            tgt = (i - 4) + (signed(w & 0x03FFFFFF, 26) << 2)
            if tgt < (i - 4):  # backward tail-jump = end of previous function
                e = i
                while e < off and word(d, e) in (UDF, NOP):
                    e += 4
                return e
        i -= 4
    return None


_SP_PRE = re.compile(r"\[sp, #(-?0x[0-9a-fA-F]+|-?\d+)\]!")
_SP_POST = re.compile(r"\[sp\], #(0x[0-9a-fA-F]+|\d+)")
_SP_SUB = re.compile(r"^sub\s+sp, sp, #(0x[0-9a-fA-F]+|\d+)$")
_SP_ADD = re.compile(r"^add\s+sp, sp, #(0x[0-9a-fA-F]+|\d+)$")
_MOV_IMM = re.compile(r"^(?:mov|movz)\s+(x|w)(\d+), #(-?0x[0-9a-fA-F]+|-?\d+)$")
_MOVN = re.compile(r"^movn\s+(x|w)(\d+), #(0x[0-9a-fA-F]+|\d+)$")
_MOV_REG = re.compile(r"^mov\s+(x|w)(\d+), (x|w)(\d+)$")
_MEM_BASE = re.compile(r"\[(x\d+|w\d+|sp)")
_STORE = re.compile(r"^(str|strb|stur|sturb|strh)\s+(.*)")


def sp_delta_of(ins):
    """Signed SP change for one instruction (0 when it does not move SP)."""
    text = f"{ins.mnemonic} {ins.op_str}".strip()
    m = _SP_SUB.match(text)
    if m:
        return -int(m.group(1), 0)
    m = _SP_ADD.match(text)
    if m:
        return +int(m.group(1), 0)
    if ins.mnemonic in ("stp", "ldp", "str", "ldr", "stur", "ldur", "sttr", "ldtr"):
        m = _SP_PRE.search(ins.op_str)
        if m:
            return int(m.group(1), 0)
        m = _SP_POST.search(ins.op_str)
        if m:
            return +int(m.group(1), 0)
    return 0


def simulate(d, start, limit=80):
    """Linear symbolic run from `start`.

    Returns dict(sp=net SP delta at ret, x0=provenance at ret, ret=ret addr or
    None, stores=[(addr, base_prov, value_prov), ...]).
    """
    sp = 0
    prov = {i: ("arg", i) for i in range(8)}
    stores = []
    ret = None
    n = 0
    for ins in MD.disasm(d[start:start + limit * 4], start):
        n += 1
        if n > limit:
            break
        m, ops, text = ins.mnemonic, ins.op_str, f"{ins.mnemonic} {ins.op_str}".strip()
        if m == "ret":
            ret = ins.address
            break
        if m in ("bl", "blr"):
            for r in range(0, 19):
                prov[r] = ("unk",)
            continue
        if m == "b":
            break  # control leaves the linear window
        sp += sp_delta_of(ins)
        if m == "movz":
            mm = _MOV_IMM.match(text)
            if mm:
                prov[int(mm.group(2))] = ("const", int(mm.group(3), 0))
                continue
        mm = _MOVN.match(text)
        if mm:
            width = 32 if mm.group(1) == "w" else 64
            prov[int(mm.group(2))] = ("const", (~int(mm.group(3), 0)) & ((1 << width) - 1))
            continue
        mm = _MOV_IMM.match(text)
        if mm:
            width = 32 if mm.group(1) == "w" else 64
            prov[int(mm.group(2))] = ("const", int(mm.group(3), 0) & ((1 << width) - 1))
            continue
        mm = _MOV_REG.match(text)
        if mm:
            src = int(mm.group(4))
            prov[int(mm.group(2))] = prov.get(src, ("unk",))
            continue
        if m in ("adr", "adrp"):
            rd = re.match(r"^(x|w)(\d+)", ops)
            if rd:
                prov[int(rd.group(2))] = ("addr",)
            continue
        sm = _STORE.match(text)
        if sm:
            base = _MEM_BASE.search(ops)
            if base:
                bn = base.group(1)
                bi = 31 if bn == "sp" else int(bn[1:])
                val = ops.split(",", 1)[0].split()[-1]
                if val in ("wzr", "xzr"):
                    vp = ("const", 0)
                else:
                    vi = int(val[1:]) if val[1:].isdigit() else None
                    vp = prov.get(vi, ("unk",)) if vi is not None else ("unk",)
                stores.append((ins.address, prov.get(bi, ("unk",)), vp))
            continue
        if m in ("ldr", "ldrb", "ldrh", "ldrsb", "ldur", "ldurb", "ldrsw"):
            rd = re.match(r"^(x|w)(\d+)", ops)
            if rd:
                prov[int(rd.group(2))] = ("unk",)
            continue
        # any other writing mnemonic: clobber its first operand register
        rd = re.match(r"^(x|w)(\d+)", ops)
        if rd and m not in ("cmp", "cmn", "tst", "strb"):
            prov[int(rd.group(2))] = ("unk",)
    return {"sp": sp, "x0": prov.get(0, ("unk",)), "ret": ret, "stores": stores}


def word_is_neutral(w):
    """True when a single word can replace its original without touching
    SP/x29/x30 or control flow (value_write contract)."""
    try:
        ins = next(MD.disasm(struct.pack("<I", w), 0))
    except StopIteration:
        return False, "undecodable"
    text = f"{ins.mnemonic} {ins.op_str}"
    if ins.mnemonic in ("ret", "b", "bl", "br", "blr", "cbz", "cbnz",
                        "tbz", "tbnz", "b.eq", "b.ne", "b.hi", "b.ls", "b.gt",
                        "b.le", "b.hs", "b.lo", "b.ge", "b.lt"):
        return False, f"control flow ({ins.mnemonic})"
    if re.search(r"\bsp\b", text):
        return False, "touches sp"
    if re.search(r"^\s*(x29|x30)\b", ins.op_str) or ", x29" in ins.op_str or ", x30" in ins.op_str:
        return False, "writes x29/x30"
    return True, "ok"


def check_contract(d, c, tag):
    """Returns (ok, lines)."""
    name = c["name"]
    kind = c["kind"]
    lines = []
    try:
        off = c["locate"](d)
    except ResolveError as e:
        return False, [f"[FAIL] {tag} {name}: {e}"]

    if kind == "value_write":
        size = c.get("size", 4)
        for i in range(0, size, 4):
            ok, why = word_is_neutral(word(d, off + i))
            if not ok:
                return False, [f"[FAIL] {tag} {name} @ {off + i:#x}: non-neutral word ({why})"]
        return True, [f"[PASS] {tag} {name} @ {off:#x} (value_write, SP/branch-neutral)"]

    if kind == "branch_redirect":
        want = c["words"]
        got = [word(d, off + 4 * i) for i in range(len(want))]
        if got != want:
            return False, [f"[FAIL] {tag} {name} @ {off:#x}: "
                           f"{[hex(x) for x in got]} != {[hex(x) for x in want]}"]
        return True, [f"[PASS] {tag} {name} @ {off:#x} (branch_redirect)"]

    entry = find_entry(d, off)
    start = entry if entry is not None else off
    sim = simulate(d, start)
    who = f"entry={entry:#x}" if entry is not None else "entry=unresolved(site)"

    if sim["ret"] is None:
        return False, [f"[FAIL] {tag} {name} @ {off:#x} ({who}): no ret within window"]

    reasons = []
    if sim["sp"] != 0:
        reasons.append(f"stack imbalance: SP delta {sim['sp']:+#x} at ret")
    x0 = sim["x0"]
    if x0 != ("const", c["w0"]):
        reasons.append(f"return w0={x0!r} expected const {c['w0']:#x}")

    if kind == "reader_store":
        want_arg, want_val = c["out_arg"], c["out_value"]
        through_out = any(
            base == ("arg", want_arg) and (val == ("const", want_val))
            for _, base, val in sim["stores"])
        if not through_out:
            reasons.append(f"no store through out-arg x{want_arg} with value {want_val}")
        for addr, base, val in sim["stores"]:
            if base[0] == "const" and 0 < base[1] < 0x10000:
                reasons.append(f"store to suspicious constant address {base[1]:#x} at {addr:#x}")

    if reasons:
        return False, [f"[FAIL] {tag} {name} @ {off:#x} ({who}): " + "; ".join(reasons)]
    return True, [f"[PASS] {tag} {name} @ {off:#x} ({who}, sp=+0x0, w0=const {c['w0']:#x})"]


def check_contracts(d, tag, required_only=False):
    results = []
    for c in CONTRACTS:
        if required_only and c.get("optional"):
            continue
        ok, lines = check_contract(d, c, tag)
        if c.get("optional") and not ok:
            # An optional site that is simply not patched is informational.
            lines = ["[INFO] optional site not applied: " + lines[0].replace("[FAIL] ", "")]
            ok = True
        results.append((c["name"], ok, lines))
    return results


def check_anchors(d, tag):
    results = []
    for c in CONTRACTS:
        if c.get("optional"):
            continue
        try:
            off = c["locate"](d)
            results.append((c["name"], True, [f"[OK] {tag} {c['name']} resolves @ {off:#x}"]))
        except ResolveError as e:
            results.append((c["name"], False, [f"[FAIL] {tag} {c['name']}: {e}"]))
    return results


def bl1_payload_ok(sboot):
    """(ok, line): BL1 must carry the EUB bootstrap payload at +0x2000.

    Checked against the *sboot*, not the bootload region: bl1 only exists in a
    full sboot, and this omission is what produced the v17 no-boot (BL1 with an
    empty payload region falls back to stock verification, fails our re-signed
    chain, and halts - no display, no download mode, EUB only). Deliberately not
    diff-based: confinement compares stock -> built, and stock has the region
    zeroed too, so an omission is invisible to it.
    """
    if len(sboot) < BL1_PAYLOAD_END:
        return False, f"sboot too small ({len(sboot)} B) to hold BL1"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), BL1_PAYLOAD_FILE)
    if not os.path.exists(path):
        return False, f"{BL1_PAYLOAD_FILE} missing; cannot prove the invariant"
    payload = open(path, "rb").read()
    want = payload + bytes(BL1_PAYLOAD_END - BL1_PAYLOAD_OFFSET - len(payload))
    got = bytes(sboot[BL1_PAYLOAD_OFFSET:BL1_PAYLOAD_END])
    if got != want:
        why = ("region is ALL ZERO (payload never embedded)"
               if all(b == 0 for b in got) else "region content mismatch")
        return False, (f"{why} (got {hashlib.sha256(got).hexdigest()[:16]}, "
                       f"want {hashlib.sha256(want).hexdigest()[:16]})")
    return True, f"BL1 payload present (sha256 {hashlib.sha256(got).hexdigest()[:16]})"


# The ST2 key index the device trusts for this BL chain, read from the record in
# the bootload's signature footer (bootload + 0x2a2dfc). v10..v16 all carry
# 0x3e96f623, the index of the *project* keys/4/*.pem. Signing with the
# repository keys (Exynos/keys) instead yields 0x3fbd5ba3, which this fused
# device does not trust - the ROM/BL1 reject the chain and halt: no display, no
# download mode, EUB only. That is what v17 and v18 shipped.
BOOTLOAD_KEY_INDEX_OFFSET = 0x2A2DFC
BOOTLOAD_KEY_INDEX = 0x3E96F623


def key_index_ok(sboot):
    """(ok, line): the bootload signature must be made by the trusted key."""
    off = SBOOT_BOOTLOAD_OFFSET + BOOTLOAD_KEY_INDEX_OFFSET
    if len(sboot) < off + 4:
        return False, f"sboot too small ({len(sboot)} B) to hold the bootload signature"
    got = int.from_bytes(sboot[off:off + 4], "little")
    if got != BOOTLOAD_KEY_INDEX:
        return False, (f"ST2 key index {got:#010x} != {BOOTLOAD_KEY_INDEX:#010x} - "
                       f"wrong signing key; the device does not trust this chain")
    return True, f"ST2 key index {got:#010x} (trusted key)"


# --------------------------------------------------------------------------
# image loading
# --------------------------------------------------------------------------

def load_region(path):
    """Accepts a signed sboot (4 MiB) or a raw bootload member (0x2A3000)."""
    d = open(path, "rb").read()
    if len(d) == SBOOT_SIZE:
        return d[SBOOT_BOOTLOAD_OFFSET:SBOOT_BOOTLOAD_OFFSET + BOOTLOAD_SIZE], "sboot"
    if len(d) >= BOOTLOAD_SIZE:
        return d[:BOOTLOAD_SIZE], "bootload"
    raise SystemExit(f"error: {path}: unexpected size {len(d)}")


def tar_members(path):
    """Return (names, md5_ok, footer, sboot) for a Samsung .tar[.md5].

    The md5 footer is `<32 hex>  <filename>\\n` and its length varies with the
    filename (Samsung's own tars carry long names), so locate it from the
    512-aligned body end instead of assuming the 68 bytes a single-digit
    version name happens to produce."""
    with open(path, "rb") as f:
        raw = f.read()
    body_len = (len(raw) // 512) * 512
    body = raw[:body_len]
    footer = raw[body_len:]
    md5_ok = footer.split(b"  ")[0].decode(errors="replace") == hashlib.md5(body).hexdigest()
    with tarfile.open(path) as tf:
        names = [(m.name, m.size) for m in tf.getmembers()]
        sboot = tf.extractfile("sboot.bin").read() if any(n == "sboot.bin" for n, _ in names) else None
    return names, md5_ok, footer, sboot


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------

def stage_stock(path):
    d, kind = load_region(path)
    print(f"== stage stock: {path} ({kind})")
    results = check_anchors(d, "stock")
    return report(results, "stock")


def stage_image(path):
    d, kind = load_region(path)
    print(f"== stage image: {path} ({kind})")
    rc = 0
    raw = open(path, "rb").read()
    if len(raw) == SBOOT_SIZE:
        ok_pl, line_pl = bl1_payload_ok(raw)
        print(f"   [{'PASS' if ok_pl else 'FAIL'}] image bl1_eub_payload: {line_pl}")
        ok_ki, line_ki = key_index_ok(raw)
        print(f"   [{'PASS' if ok_ki else 'FAIL'}] image signing_key: {line_ki}")
        if not (ok_pl and ok_ki):
            rc = 1
    results = check_contracts(d, "image")
    return 1 if (rc or report(results, "image")) else 0


def stage_packed(path, expect_image=None, expect_members=None):
    print(f"== stage packed: {path}")
    names, md5_ok, footer, sboot = tar_members(path)
    hard_fail = False
    print(f"   members: {len(names)}")
    for n, s in names:
        print(f"     - {n} ({s} bytes)")
    if expect_members is not None and len(names) != expect_members:
        print(f"[FAIL] packed member count {len(names)} != expected {expect_members}")
        hard_fail = True
    if md5_ok:
        print(f"[PASS] packed md5 footer verified ({footer.split(b'  ')[0].decode()})")
    else:
        print("[FAIL] packed md5 footer mismatch")
        hard_fail = True
    if sboot is None:
        print("[FAIL] packed tar has no sboot.bin member")
        return 1
    ok_pl, line_pl = bl1_payload_ok(sboot)
    print(f"   [{'PASS' if ok_pl else 'FAIL'}] packed bl1_eub_payload: {line_pl}")
    ok_ki, line_ki = key_index_ok(sboot)
    print(f"   [{'PASS' if ok_ki else 'FAIL'}] packed signing_key: {line_ki}")
    if not (ok_pl and ok_ki):
        hard_fail = True
    region = sboot[SBOOT_BOOTLOAD_OFFSET:SBOOT_BOOTLOAD_OFFSET + BOOTLOAD_SIZE]
    if expect_image is not None:
        built = open(expect_image, "rb").read()
        region_built = built[SBOOT_BOOTLOAD_OFFSET:SBOOT_BOOTLOAD_OFFSET + BOOTLOAD_SIZE]
        if region == region_built:
            print("[PASS] packed bootload region == built signed sboot region")
        else:
            print("[FAIL] packed bootload region differs from the built signed sboot")
            hard_fail = True
    results = check_contracts(region, "packed")
    rc = report(results, "packed")
    return 1 if (hard_fail or rc != 0) else 0


# --------------------------------------------------------------------------
# download-mode session contract
# --------------------------------------------------------------------------

# The abl's download-mode/ODIN console command table (NHZF5 bootload, ~0x141b7x).
# A chain that cannot serve a session cannot be flashed again, so this machinery
# must be present and must not sit under a patch.
SESSION_COMMANDS = (b"ODIN\0", b"PROMPT\0", b"DVIF\0", b"SOD\0",
                    b"SODSTART\0", b"AT+ENGMODES", b"@#AuToTEst@#\0")

# The stock state-switch app does not reach its `ret` inside the 80-instruction
# window the patch contracts use; the session check asks only for stack
# discipline, so it needs a longer window.
SESSION_SIM_LIMIT = 400


def session_site_discipline(d, c):
    """(ok, reason): the function at a recorded site must return with a balanced
    stack. Return-value and store-through-out-arg correctness stay in the patch
    contracts (`image`/`packed`): the served igyi3 chain carries the same
    wild-store defect as v8 and still serves download mode, so that defect class
    demonstrably does not gate a session."""
    if c.get("kind") in ("value_write", "bl1_payload"):
        return None, f"{c.get('kind')} site (not a function boundary)"
    try:
        off = c["locate"](d)
    except ResolveError as e:
        return None, f"anchor absent in this generation ({e})"
    entry = find_entry(d, off)
    sim = simulate(d, entry if entry is not None else off, limit=SESSION_SIM_LIMIT)
    if sim["ret"] is None:
        return None, f"no ret within {SESSION_SIM_LIMIT} instructions"
    if sim["sp"] != 0:
        return False, f"stack imbalance: SP delta {sim['sp']:+#x} at ret"
    return True, "SP-balanced at ret"


def stage_session(path):
    """Static preconditions of the download-mode session contract:
      S1 the session command table is present in the image;
      S2 no recorded patch site overlaps the session machinery;
      S3 every recorded site that resolves returns with a balanced stack.

    The behavioural half - a session actually being served - is a device
    observation (RAM validation), not something the image alone can prove."""
    if path.endswith((".tar", ".tar.md5")):
        _, _, _, sboot = tar_members(path)
        if sboot is None:
            print(f"[FAIL] {path}: no sboot.bin member")
            return 1
        d = sboot[SBOOT_BOOTLOAD_OFFSET:SBOOT_BOOTLOAD_OFFSET + BOOTLOAD_SIZE]
        kind = "tar"
    else:
        d, kind = load_region(path)
    print(f"== stage session: {path} ({kind})")
    bad = 0
    offsets = [(c, d.find(c)) for c in SESSION_COMMANDS]
    missing = [c for c, o in offsets if o < 0]
    if missing:
        print("[FAIL] session command table incomplete: "
              + ", ".join(c.decode(errors="replace") for c in missing) + " missing")
        bad += 1
    else:
        lo = min(o for _, o in offsets)
        hi = max(o for _, o in offsets) + 32
        print(f"[PASS] session command table present @ {lo:#x}..{hi:#x}")
        clashes = []
        for c in CONTRACTS:
            try:
                off = c["locate"](d)
            except ResolveError:
                continue
            if lo <= off < hi:
                clashes.append(f"{c['name']}@{off:#x}")
        if clashes:
            print("[FAIL] patch site(s) overlap the session machinery: " + ", ".join(clashes))
            bad += 1
        else:
            print("[PASS] no recorded patch site overlaps the session machinery")
    for c in CONTRACTS:
        ok, why = session_site_discipline(d, c)
        if ok is None:
            print(f"   [INFO] session {c['name']}: {why}")
        elif ok:
            print(f"   [PASS] session {c['name']}: {why}")
        else:
            print(f"   [FAIL] session {c['name']}: {why}")
            bad += 1
    verdict = ("can serve a download-mode session (static preconditions hold)"
               if not bad else "CANNOT serve a download-mode session")
    print(f"== session: {verdict}")
    return 1 if bad else 0


def report(results, tag):
    bad = 0
    for _, ok, lines in results:
        for line in lines:
            print("   " + line)
        if not ok:
            bad += 1
    print(f"== {tag}: {len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


def selftest(v8_tar):
    rc = 0
    print("== selftest 1: real v8 tar must be rejected with both known defects")
    names, md5_ok, _, sboot = tar_members(v8_tar)
    region = sboot[SBOOT_BOOTLOAD_OFFSET:SBOOT_BOOTLOAD_OFFSET + BOOTLOAD_SIZE]
    by_name = {c["name"]: c for c in CONTRACTS}
    # The two v8 defects are owned by different checks now: the stack imbalance
    # by the session discipline check (the state contracts are optional, since a
    # genuinely unlocked chain leaves those sites stock), and the wild store by
    # the avb reader's own contract.
    ok_app, why_app = session_site_discipline(region, by_name["state_switch_app"])
    ok_avb, lines_avb = check_contract(region, by_name["avb_state_reader"], "v8")
    print(f"   [{'FAIL' if ok_app is False else 'PASS'}] v8 state_switch_app: {why_app}")
    for line in lines_avb:
        print("   " + line)
    if ok_app is False and not ok_avb:
        print("[PASS] v8 fixture: both ABI defects detected")
    else:
        print("[FAIL] v8 fixture: expected state_switch_app + avb_state_reader to fail")
        rc = 1
    print("== selftest 2: corrupted anchor must fail resolution")
    d = bytearray(region)
    o = d.find(b"PERSISTENT\0")
    d[o:o + 4] = b"XBRS"
    anchor_results = check_anchors(bytes(d), "corrupt")
    any_fail = any(not ok for _, ok, _ in anchor_results)
    for _, _, lines in anchor_results:
        for line in lines:
            print("   " + line)
    if any_fail:
        print("[PASS] corrupted-anchor fixture rejected")
    else:
        print("[FAIL] corrupted-anchor fixture was accepted")
        rc = 1
    return rc


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def stage_confinement(stock_path, built_path):
    """Every byte differing between a stock image and the built image must lie
    inside a recorded patch site or the member's trailing signing-trailer zone
    (the last 0x800 bytes, which the signing step rewrites)."""
    stock_d, _ = load_region(stock_path)
    built_d, _ = load_region(built_path)
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, root)                      # project patch_9840.py wins
        sys.path.append(os.path.join(root, "Exynos", "scripts"))  # `sign` for the fuse payload
        import patch_9840 as P
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] cannot import patch_9840 ({e}); run from the repo root with keys/ present")
        return 2
    tmp = bytearray(stock_d)
    # Populate the patch-site registry for this generation. Optional patch sites
    # are included as allowed regions, whether or not this particular build used
    # their environment flags.
    fns = [P.patch_check_signature, P.patch_prevent_warranty_fuse, P.patch_check_sw_rev,
           P.patch_check_kernel_rev, P.patch_check_system_rev, P.patch_check_pit_rev,
           P.patch_seandroid_enforcing_off, P.patch_avbops_state_reader_always_unlocked,
           P.patch_read_is_device_unlocked, P.patch_disable_secure_download_check,
           P.patch_dt_entry_revision_fallback, P.patch_secure_check_bit3_gate,
           P.patch_recovery_rp_gate,
            P.patch_recovery_secure_check_gate,
            P.patch_keypad_recovery_combo,
            P.patch_open_oem_unlock_gate]
    if os.environ.get("EUB_EXECUTOR_RECOVERY", "0") == "0":
        fns.append(P.patch_executor_skip_recovery)
    if P.should_fuse_key:
        fns.append(P.patch_fuse_boot_key)
    fns.append(P.patch_force_recovery_boot)
    for fn in fns:
        fn(tmp)
    sites = [(s["offset"], s["offset"] + len(s["new"])) for s in P.PATCH_SITES]
    n = len(stock_d)
    trailer = n - 0x800
    runs = []
    i = 0
    while i < n:
        if stock_d[i] != built_d[i]:
            j = i
            while j < n and stock_d[j] != built_d[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    bad = 0
    for a, b in runs:
        if any(s <= a and b <= e for s, e in sites):
            kind = "site"
        elif a >= trailer:
            kind = "signing-trailer"
        else:
            kind = "UNEXPECTED"
            bad += 1
        print(f"   {a:#08x}..{b:#08x} ({b - a:4}B) {kind}")
    print(f"== confinement: {len(runs)} diff runs, {bad} unexpected")
    return 1 if bad else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--key-index",
                   default=os.environ.get("R9S_KEY_INDEX", "0x3e96f623"),
                   help="expected ST2 key index (hex; env R9S_KEY_INDEX)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stock"); s.add_argument("path")
    s = sub.add_parser("image"); s.add_argument("path")
    s = sub.add_parser("packed"); s.add_argument("path")
    s.add_argument("--expect-image")
    s.add_argument("--expect-members", type=int)
    s = sub.add_parser("selftest"); s.add_argument("--v8-tar", default="flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK_v8.tar.md5")
    s = sub.add_parser("confinement"); s.add_argument("stock"); s.add_argument("built")
    s = sub.add_parser("session"); s.add_argument("path")
    a = p.parse_args(argv)
    global BOOTLOAD_KEY_INDEX
    BOOTLOAD_KEY_INDEX = int(a.key_index, 0)
    try:
        if a.cmd == "stock":
            return stage_stock(a.path)
        if a.cmd == "image":
            return stage_image(a.path)
        if a.cmd == "packed":
            return stage_packed(a.path, a.expect_image, a.expect_members)
        if a.cmd == "selftest":
            return selftest(a.v8_tar)
        if a.cmd == "confinement":
            return stage_confinement(a.stock, a.built)
        if a.cmd == "session":
            return stage_session(a.path)
    except (OSError, KeyError, tarfile.TarError) as e:
        print(f"error: {e}")
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
