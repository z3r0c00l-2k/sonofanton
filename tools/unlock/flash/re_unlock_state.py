#!/usr/bin/env python3
"""Read-only reverse-engineering helper for the S21 FE unlock-state machinery.

Disassembles the raw (headerless) bootload segment at bootload-relative
addresses with capstone and answers the questions OpenSpec change
`ground-up-unlock-state` group 1 asks. The input segment is opened read-only
and never modified; nothing is written.

Usage:
    re_unlock_state.py func    <addr> [len]   annotated disassembly
    re_unlock_state.py refs    <addr>         code referencing a data address
    re_unlock_state.py callers <addr>         bl/b sites reaching a function
    re_unlock_state.py str     <addr>         print a C string at an address

Addresses are hexadecimal, bootload-relative (the stage treats the segment as
base 0, which is how patch_9840.py's anchors are expressed).
"""

import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

DEFAULT_SEGMENT = "bootload_pristine.bin"

_DATA = None
_MD = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)


def load(path=DEFAULT_SEGMENT):
    global _DATA
    with open(path, "rb") as fh:
        _DATA = fh.read()
    return _DATA


def word(off):
    return struct.unpack_from("<I", _DATA, off)[0]


def _adrp_page(off):
    """Page target of an ADRP at off, or None."""
    adrp = word(off)
    if adrp & 0x9F000000 != 0x90000000:
        return None
    imm = ((adrp >> 29) & 3) | (((adrp >> 5) & 0x7FFFF) << 2)
    if imm & (1 << 20):
        imm -= 1 << 21
    return (off & ~0xFFF) + (imm << 12)


def _add_of(off):
    """(Rn, imm) of an ADD-immediate at off, or None."""
    w = word(off)
    if w & 0xFF000000 != 0x91000000:
        return None
    return ((w >> 5) & 31, (w >> 10) & 0xFFF)


def _ldst_of(off):
    """(kind, Rn, byte_offset) of a scalar LDR/STR-unsigned-immediate, or None."""
    w = word(off)
    if w & 0x3B000000 != 0x39000000:
        return None
    kind = "str" if (w >> 22) & 3 == 0 else "ldr"
    shift = (w >> 30) & 3
    return (kind, (w >> 5) & 31, ((w >> 10) & 0xFFF) << shift)


def adrp_add(off):
    """Target of an ADRP+ADD pointer materialisation at off, or None."""
    page = _adrp_page(off)
    if page is None:
        return None
    adrp = word(off)
    for dist in range(4, 17, 4):
        add = _add_of(off + dist)
        if add and add[0] == adrp & 31:
            return page + (add[1] << (12 if word(off + dist) & 0x400000 else 0))
    return None


def cstr(off):
    end = _DATA.find(b"\x00", off)
    return _DATA[off:end].decode("latin1")


def _branch(off):
    """(kind, target) for bl/b at off, or None."""
    w = word(off)
    if w & 0xFC000000 == 0x94000000:
        kind = "bl"
    elif w & 0xFC000000 == 0x14000000:
        kind = "b"
    else:
        return None
    imm = w & 0x03FFFFFF
    if imm & 0x02000000:
        imm -= 0x04000000
    return (kind, off + imm * 4)


def cmd_func(addr, n=0x120):
    end = min(addr + n, len(_DATA))
    for ins in _MD.disasm(_DATA[addr:end], addr):
        note = ""
        page = _adrp_page(ins.address)
        if page is not None:
            tgt = adrp_add(ins.address)
            if tgt is not None and 0 <= tgt < len(_DATA):
                note = f"   ; -> {tgt:#x} {cstr(tgt)!r}"
            else:
                note = f"   ; page {page:#x}"
        br = _branch(ins.address)
        if br:
            note = f"   ; {br[0]} -> {br[1]:#x}"
        print(f"{ins.address:#08x}: {ins.mnemonic:<8} {ins.op_str}{note}")


def cmd_refs(addr):
    page, off = addr & ~0xFFF, addr & 0xFFF
    hits = []
    for at in range(0, len(_DATA) - 20, 4):
        if _adrp_page(at) != page:
            continue
        adrp = word(at)
        for dist in range(4, 21, 4):
            a = _add_of(at + dist)
            if a and a[0] == adrp & 31 and a[1] == off:
                hits.append((at, "adrp+add"))
                break
            ls = _ldst_of(at + dist)
            if ls and ls[1] == adrp & 31 and ls[2] == off:
                hits.append((at, f"adrp+{ls[0]}"))
                break
    print(f"refs to {addr:#x} (page {page:#x} + {off:#x}):")
    for at, kind in hits:
        print(f"  {at:#08x}  {kind}")
    if not hits:
        print("  (none)")


def cmd_callers(addr):
    print(f"callers of {addr:#x}:")
    found = False
    for at in range(0, len(_DATA) - 4, 4):
        br = _branch(at)
        if br and br[1] == addr:
            print(f"  {at:#08x}  {br[0]}")
            found = True
    if not found:
        print("  (none)")


def cmd_str(addr):
    print(f"{addr:#x}: {cstr(addr)!r}")


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    load()
    cmd, arg = argv[1], argv[2]
    addr = int(arg, 16)
    if cmd == "func":
        cmd_func(addr, int(argv[3], 0) if len(argv) > 3 else 0x120)
    elif cmd == "refs":
        cmd_refs(addr)
    elif cmd == "callers":
        cmd_callers(addr)
    elif cmd == "str":
        cmd_str(addr)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
