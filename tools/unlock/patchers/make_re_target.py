#!/usr/bin/env python3
"""Wrap a raw AArch64 segment in a minimal ELF so container-only tools (REA's
native provider) can load it.

`bootload_pristine.bin` is a headerless segment, which REA rejects with
"unsupported binary format". This produces a valid ELF64/AArch64 executable with
one PT_LOAD (R+X) so the provider can open it and decompile.

The segment is mapped at vaddr 0x1000 (p_vaddr must be congruent to p_offset),
so an analysis address is (bootload file offset + 0x1000). The segment bytes are
unmodified.
"""

import os
import struct

SEG = "bootload_pristine.bin"
OUT = "/tmp/opencode/bootload_seg.elf"
BASE = 0x1000  # 1 page; keeps p_vaddr == p_offset for strict loaders

EM_AARCH64 = 183
ET_EXEC = 2
EV_CURRENT = 1
PT_LOAD = 1
PF_R, PF_X = 4, 1


def main():
    seg = open(SEG, "rb").read()

    ehdr = bytearray(64)
    ehdr[0:4] = b"\x7fELF"
    ehdr[4] = 2  # ELFCLASS64
    ehdr[5] = 1  # ELFDATA2LSB
    ehdr[6] = EV_CURRENT
    ehdr[7] = 0  # ELFOSABI_SYSV
    struct.pack_into(
        "<HHIQQQIHHHHHH", ehdr, 16,
        ET_EXEC,        # e_type
        EM_AARCH64,     # e_machine
        EV_CURRENT,     # e_version
        BASE,           # e_entry
        64,             # e_phoff
        0,              # e_shoff
        0,              # e_flags
        64,             # e_ehsize
        56,             # e_phentsize
        1,              # e_phnum
        0,              # e_shentsize
        0,              # e_shnum
        0,              # e_shstrndx
    )

    phdr = struct.pack(
        "<IIQQQQQQ",
        PT_LOAD,            # p_type
        PF_R | PF_X,        # p_flags
        BASE,               # p_offset
        BASE,               # p_vaddr
        BASE,               # p_paddr
        len(seg),           # p_filesz
        len(seg),           # p_memsz
        BASE,               # p_align
    )

    pad = BASE - len(ehdr) - len(phdr)
    assert pad >= 0, "BASE too small for the headers"

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as fh:
        fh.write(ehdr)
        fh.write(phdr)
        fh.write(b"\x00" * pad)
        fh.write(seg)

    total = os.path.getsize(OUT)
    print(f"wrote {OUT}")
    print(f"  size      {total} bytes (segment {len(seg)})")
    print(f"  machine   EM_AARCH64 ({EM_AARCH64}), ET_EXEC, R+X")
    print(f"  mapping   vaddr = file offset + {BASE:#x}")
    print(f"  check     0x5e6f8 -> {0x5e6f8 + BASE:#x}, "
          f"0x43d70 -> {0x43d70 + BASE:#x}, 0x5d878 -> {0x5d878 + BASE:#x}")


if __name__ == "__main__":
    main()
