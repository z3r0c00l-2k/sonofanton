#!/usr/bin/env python3
"""cpio (newc) ramdisk: list, extract, pack. Handles symlinks and directories.

  ramdisk.py list    <ramdisk.gz> [--modules]
  ramdisk.py extract <ramdisk.gz> <outdir>
  ramdisk.py pack    <indir> <out.gz>
"""
from __future__ import annotations

import argparse
import gzip
import io
import os
import stat
import sys

MAGIC = b"070701"
FIELDS = 13


def decompress(path: str) -> bytes:
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    return raw


def read_cpio(data: bytes) -> list[dict]:
    off = 0
    out = []
    while off + 110 <= len(data):
        if data[off:off + 6] != MAGIC:
            break
        f = [int(data[off + 6 + i * 8: off + 6 + (i + 1) * 8], 16) for i in range(FIELDS)]
        ino, mode, uid, gid, nlink, mtime, fsize = f[0:7]
        namesz = f[11]
        name = data[off + 110: off + 110 + namesz - 1].decode("utf-8", "replace")
        pos = (off + 110 + namesz + 3) & ~3
        payload = data[pos:pos + fsize]
        out.append(dict(name=name, mode=mode, uid=uid, gid=gid, nlink=nlink,
                        mtime=mtime, data=payload))
        if name == "TRAILER!!!":
            break
        off = (pos + fsize + 3) & ~3
    return out


def gz(data: bytes) -> bytes:
    b = io.BytesIO()
    with gzip.GzipFile(fileobj=b, mode="wb", mtime=0, compresslevel=9) as f:
        f.write(data)
    return b.getvalue()


def cmd_list(args) -> None:
    entries = read_cpio(decompress(args.ramdisk))
    print(f"{args.ramdisk}: {len(entries)} entries")
    if args.modules:
        mods = [e for e in entries if e["name"].startswith("lib/modules/") and e["name"].endswith(".ko")]
        load = next((e for e in entries if e["name"] == "lib/modules/modules.load.recovery"), None)
        print(f"  .ko files: {len(mods)}")
        if load:
            lines = [l for l in load["data"].decode(errors="replace").splitlines() if l.strip()]
            print(f"  modules.load.recovery: {len(lines)} lines")
        return
    for e in entries[: args.head]:
        kind = "d" if stat.S_ISDIR(e["mode"]) else ("l" if stat.S_ISLNK(e["mode"]) else "-")
        print(f"  {kind} {e['mode']:07o} {len(e['data']):>9} {e['name']}")


def cmd_extract(args) -> None:
    entries = read_cpio(decompress(args.ramdisk))
    os.makedirs(args.outdir, exist_ok=True)
    for e in entries:
        if e["name"] == "TRAILER!!!":
            continue
        p = os.path.join(args.outdir, e["name"].lstrip("/"))
        mode = e["mode"]
        if stat.S_ISDIR(mode):
            os.makedirs(p, exist_ok=True)
        elif stat.S_ISLNK(mode):
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            if os.path.lexists(p):
                os.unlink(p)
            os.symlink(e["data"].decode(), p)
        else:
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(e["data"])
            os.chmod(p, stat.S_IMODE(mode))
    print(f"extracted {len(entries)} entries -> {args.outdir}")


def cmd_pack(args) -> None:
    entries = []
    base = os.path.abspath(args.indir)
    paths = []
    for root, dirs, files in os.walk(base, followlinks=False):
        dirs.sort()
        for name in sorted(dirs) + sorted(files):
            paths.append(os.path.join(root, name))
    paths.sort(key=lambda p: os.path.relpath(p, base))
    for p in paths:
        rel = os.path.relpath(p, base)
        st = os.lstat(p)
        data = b""
        if stat.S_ISLNK(st.st_mode):
            data = os.readlink(p).encode()
        elif stat.S_ISREG(st.st_mode):
            data = open(p, "rb").read()
        entries.append(dict(name=rel, mode=st.st_mode, uid=st.st_uid, gid=st.st_gid,
                            nlink=st.st_nlink, mtime=int(st.st_mtime), data=data))
    blob = build_cpio(entries)
    open(args.out, "wb").write(gz(blob))
    print(f"packed {len(entries)} entries -> {args.out} ({len(gz(blob))} bytes)")


def build_cpio(entries: list[dict]) -> bytes:
    out = bytearray()
    ino = 1
    for e in entries:
        name = e["name"].encode() + b"\0"
        hdr = MAGIC + b"".join(b"%08X" % v for v in (
            ino, e["mode"], e["uid"], e["gid"], e["nlink"], e["mtime"],
            len(e["data"]), 0, 0, 0, 0, len(name), 0))
        out += hdr + name
        out += b"\0" * ((4 - (len(hdr) + len(name)) % 4) % 4)
        out += e["data"]
        out += b"\0" * ((4 - len(e["data"]) % 4) % 4)
        ino += 1
    name = b"TRAILER!!!\0"
    hdr = MAGIC + b"".join(b"%08X" % v for v in (0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name), 0))
    out += hdr + name
    out += b"\0" * ((4 - (len(hdr) + len(name)) % 4) % 4)
    out += b"\0" * ((512 - len(out) % 512) % 512)
    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("list"); a.add_argument("ramdisk"); a.add_argument("--modules", action="store_true")
    a.add_argument("--head", type=int, default=20); a.set_defaults(fn=cmd_list)
    b = sub.add_parser("extract"); b.add_argument("ramdisk"); b.add_argument("outdir"); b.set_defaults(fn=cmd_extract)
    c = sub.add_parser("pack"); c.add_argument("indir"); c.add_argument("out"); c.set_defaults(fn=cmd_pack)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
