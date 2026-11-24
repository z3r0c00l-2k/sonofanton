#!/usr/bin/env python3
"""Check that every shipped module can pass the kernel's CFI check.

Two different things live in a module:

  __cfi_check        the module's own type-id table and checker. Every module
                     built with CONFIG_CFI_CLANG must export it; a module
                     without one already failed to link.
  init_module.cfi_jt a jump-table stub for the init call. Its absence is
                     *not* fatal: the loader falls back to __cfi_slowpath and
                     the module's __cfi_check. Measured on r9s, the stock LOS
                     build ships 26 of 271 modules without it, runs an
                     enforcing kernel (CONFIG_CFI_PERMISSIVE unset) and boots:
                     "init: Loaded 271 modules from /lib/modules", no CFI
                     failure in dmesg.

The failure this guards against is a module built by a toolchain that
disagrees with the kernel's, where the type-id hashes do not match and
__cfi_check fails at load (seen once as a panic in s3c2410_wdt when kernel and
modules came from different clang versions).

  tools/check_cfi_jt.py [--build DIR] [--ramdisk PATH] [--strict]

Exit code 0 unless a shipped module is missing __cfi_check or was not built.
--strict additionally fails when the init jump-table stub is absent.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ramdisk as rd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def names_in_ramdisk(path: str) -> list[str]:
    entries = rd.read_cpio(gzip.decompress(open(path, "rb").read()))
    return sorted(
        e["name"].rsplit("/", 1)[-1][:-3]
        for e in entries
        if e["name"].startswith("lib/modules/") and e["name"].endswith(".ko")
    )


def symbols(path: str) -> str:
    return subprocess.run(["llvm-nm", path], capture_output=True, text=True).stdout


def has_self_check(path: str) -> bool:
    """__cfi_check is defined by the module itself, not imported."""
    for line in symbols(path).splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == "__cfi_check" and parts[1] in "TtWw":
            return True
    return False


def has_jt(path: str) -> bool:
    return "init_module.cfi_jt" in symbols(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default=os.path.join(ROOT, "build"))
    ap.add_argument("--ramdisk", default=os.path.join(ROOT, "baseline/parts/ramdisk"))
    ap.add_argument("--strict", action="store_true",
                    help="also fail when init_module.cfi_jt is absent")
    args = ap.parse_args()

    want = names_in_ramdisk(args.ramdisk)
    index = {}
    for p in glob.glob(os.path.join(args.build, "**", "*.ko"), recursive=True):
        index.setdefault(os.path.basename(p)[:-3], p)

    absent, no_check, no_jt = [], [], []
    for name in want:
        p = index.get(name)
        if not p:
            absent.append(name)
            continue
        if not has_self_check(p):
            no_check.append(name)
        if not has_jt(p):
            no_jt.append(name)

    print(f"shipped modules: {len(want)}   built: {len(index)}")
    if absent:
        print(f"  not built: {len(absent)}: {', '.join(absent)}")
    if no_check:
        print(f"  missing __cfi_check: {len(no_check)}")
        for m in no_check:
            print(f"    {m}")
    if no_jt:
        print(f"  no init_module.cfi_jt (informational): {len(no_jt)}")
        for m in no_jt:
            print(f"    {m}")

    if absent:
        sys.exit("some shipped modules were not built")
    if no_check:
        sys.exit("modules without __cfi_check cannot pass an enforcing kernel")
    if no_jt and args.strict:
        sys.exit("init_module.cfi_jt missing (--strict)")
    print("PASS: every shipped module exports __cfi_check"
          + ("" if not no_jt else f"; {len(no_jt)} rely on __cfi_slowpath"))


if __name__ == "__main__":
    main()
