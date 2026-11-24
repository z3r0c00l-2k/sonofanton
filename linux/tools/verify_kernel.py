#!/usr/bin/env python3
"""Verify a built kernel against its own config and module set.

Checks:
  1. the Image's UTS release is readable
  2. the config embedded in the Image contains every delta option
  3. every built module carries exactly one vermagic, matching that release

Exit code 0 only if all checks pass.
"""
from __future__ import annotations

import glob
import gzip
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build")
IMAGE = os.path.join(OUT, "arch/arm64/boot/Image")
FRAGMENT = os.path.join(ROOT, "configs/docker.config")

fails = []


def check(ok: bool, msg: str) -> None:
    print(("  ok    " if ok else "  FAIL  ") + msg)
    if not ok:
        fails.append(msg)


def main() -> None:
    print(f"image: {IMAGE}")
    data = open(IMAGE, "rb").read()
    print(f"size:  {len(data)} bytes")

    m = re.search(rb"Linux version (\S+)", data)
    check(m is not None, "UTS release present in Image")
    if not m:
        sys.exit(1)
    release = m.group(1).decode()
    print(f"release: {release}")

    # embedded config
    a, b = data.find(b"IKCFG_ST"), data.find(b"IKCFG_ED")
    check(a >= 0 and b > a, "IKCFG present in Image")
    if a < 0 or b <= a:
        sys.exit(1)
    cfg = gzip.decompress(data[a + 8:b]).decode(errors="replace").splitlines()
    print(f"embedded config: {len(cfg)} lines")

    wanted = [l.strip() for l in open(FRAGMENT) if l.strip() and not l.lstrip().startswith("#")]
    if os.environ.get("CFI_PERMISSIVE") == "0":
        wanted = [w for w in wanted if w != "CONFIG_CFI_PERMISSIVE=y"]
    for line in wanted:
        check(line in cfg, f"delta option in Image config: {line}")

    # module vermagic
    kos = sorted(glob.glob(os.path.join(OUT, "**", "*.ko"), recursive=True))
    check(len(kos) > 0, f"modules built ({len(kos)} found)")
    vermagics = {}
    for p in kos:
        blob = open(p, "rb").read()
        i = blob.find(b"vermagic=")
        if i < 0:
            vermagics.setdefault("(none)", []).append(p)
            continue
        v = blob[i + 9:i + 9 + 200].split(b"\0")[0].decode(errors="replace")
        vermagics.setdefault(v, []).append(p)

    check(len(vermagics) == 1, f"exactly one vermagic across {len(kos)} modules")
    for v, paths in vermagics.items():
        print(f"  vermagic: {v}  ({len(paths)} modules)")
        check(v.startswith(release + " "), "module vermagic starts with the Image release")
        for flag in ("SMP", "preempt", "mod_unload", "modversions", "aarch64"):
            check(flag in v.split(), f"vermagic carries {flag}")

    print()
    if fails:
        print(f"FAILED: {len(fails)} check(s)")
        sys.exit(1)
    print("PASS: kernel and module set are coherent")


if __name__ == "__main__":
    main()
