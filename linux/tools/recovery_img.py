#!/usr/bin/env python3
"""Split and rebuild header v1/v2 Android boot/recovery images, byte-exactly.

The packer's contract: given the parts and the recorded header fields, the
rebuilt image must hash identically to the source. Only after that proof is a
modified payload allowed through this tool.

  recovery_img.py info   <img>
  recovery_img.py split  <img> <outdir>
  recovery_img.py build  <partsdir> <outimg> [--total N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys

MAGIC = b"ANDROID!"
# v1 adds three fields after extra_cmdline (608..1631), v2 adds two more.
OFF_DTBO_SIZE = 1632
OFF_DTBO_OFFSET = 1636
OFF_HEADER_SIZE = 1644
OFF_DTB_SIZE = 1648
OFF_DTB_ADDR = 1652
HEADER_SIZE_V1 = 1648
HEADER_SIZE_V2 = 1660


def align(n: int, page: int) -> int:
    return (n + page - 1) // page * page


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def avb_info(d: bytes) -> dict | None:
    """Decode the AVB footer (all integers big-endian) if one is present."""
    if len(d) < 64 or d[-64:-60] != b"AVBf":
        return None
    f = d[-64:]
    vmaj, vmin = struct.unpack_from(">II", f, 4)
    ois, voff, vsize = struct.unpack_from(">QQQ", f, 12)
    info = {
        "footer_offset": len(d) - 64,
        "version": f"{vmaj}.{vmin}",
        "original_image_size": ois,
        "vbmeta_offset": voff,
        "vbmeta_size": vsize,
    }
    if d[voff:voff + 4] == b"AVB0":
        ma, mi = struct.unpack_from(">II", d, voff + 4)
        auth, aux = struct.unpack_from(">QQ", d, voff + 12)
        alg = struct.unpack_from(">I", d, voff + 28)[0]
        # layout includes the public_key_metadata offset/size pair before the
        # descriptors, so rollback_index sits at +112, flags at +120.
        rb = struct.unpack_from(">Q", d, voff + 112)[0]
        flags = struct.unpack_from(">I", d, voff + 120)[0]
        rbloc = struct.unpack_from(">I", d, voff + 124)[0]
        info.update(
            header_version=f"{ma}.{mi}", auth_block_size=auth, aux_block_size=aux,
            algorithm_type=alg, rollback_index=rb, flags=flags,
            rollback_index_location=rbloc,
            structure_size=256 + auth + aux,
        )
    return info


def parse(path: str) -> dict:
    d = open(path, "rb").read()
    if d[:8] != MAGIC:
        sys.exit(f"{path}: not an Android boot image")

    (ks, ka, rs, ra, ss, sa, tags, ps) = struct.unpack_from("<8I", d, 8)
    hv = struct.unpack_from("<I", d, 40)[0]

    f = {
        "kernel_size": ks, "kernel_addr": ka,
        "ramdisk_size": rs, "ramdisk_addr": ra,
        "second_size": ss, "second_addr": sa,
        "tags_addr": tags, "page_size": ps,
        "header_version": hv,
        "total_size": len(d),
    }

    if hv >= 1:
        f["os_version"] = struct.unpack_from("<I", d, 44)[0]
        f["name"] = d[48:64].rstrip(b"\0").decode("latin1")
        f["cmdline"] = d[64:576].rstrip(b"\0").decode("latin1")
        f["id"] = d[576:608].hex()
        f["extra_cmdline"] = d[608:1120].rstrip(b"\0").decode("latin1")
        f["recovery_dtbo_size"], f["recovery_dtbo_offset"] = struct.unpack_from("<IQ", d, OFF_DTBO_SIZE)
        f["header_size"] = struct.unpack_from("<I", d, OFF_HEADER_SIZE)[0]
    if hv >= 2:
        f["dtb_size"] = struct.unpack_from("<I", d, OFF_DTB_SIZE)[0]
        f["dtb_addr"] = struct.unpack_from("<Q", d, OFF_DTB_ADDR)[0]

    off = ps
    parts = {}

    def take(name: str, size: int) -> bytes:
        nonlocal off
        b = d[off:off + size]
        if len(b) != size:
            sys.exit(f"truncated: wanted {size} bytes for {name} at {off:#x}")
        off = align(off + size, ps)
        return b

    parts["kernel"] = take("kernel", ks)
    parts["ramdisk"] = take("ramdisk", rs)
    parts["second"] = take("second", ss)
    if hv >= 1 and f.get("recovery_dtbo_size"):
        parts["recovery_dtbo"] = take("recovery_dtbo", f["recovery_dtbo_size"])
    if hv >= 2 and f.get("dtb_size"):
        parts["dtb"] = take("dtb", f["dtb_size"])

    f["_parts"] = parts
    f["_payload_end"] = off
    f["_pad"] = len(d) - off
    f["_trailer"] = d[off:]
    f["_avb"] = avb_info(d)
    return f


def image_id(parts: dict, hv: int) -> bytes:
    """mkbootimg's id: sha1 over (data, size) for each part in load order."""
    sha = hashlib.sha1()
    order = ["kernel", "ramdisk", "second"]
    if hv >= 1:
        order.append("recovery_dtbo")
    if hv >= 2:
        order.append("dtb")
    for name in order:
        b = parts.get(name, b"")
        sha.update(b)
        sha.update(struct.pack("<I", len(b)))
    return sha.digest()


def compute_layout(f: dict, parts: dict) -> dict:
    """Payload positions, page-aligned, in the order the image stores them."""
    ps = f["page_size"]
    hv = f["header_version"]
    pos = ps
    pos_map = {}
    for name in ("kernel", "ramdisk", "second"):
        pos_map[name] = pos
        pos = align(pos + len(parts.get(name, b"")), ps)
    if hv >= 1:
        pos_map["recovery_dtbo"] = pos
        pos = align(pos + len(parts.get("recovery_dtbo", b"")), ps)
    if hv >= 2:
        pos_map["dtb"] = pos
    return pos_map


def build_header(f: dict, parts: dict, layout: dict) -> bytes:
    ps = f["page_size"]
    hv = f["header_version"]
    h = bytearray(HEADER_SIZE_V2 if hv >= 2 else HEADER_SIZE_V1)

    struct.pack_into(
        "<8s8I", h, 0, MAGIC,
        len(parts.get("kernel", b"")), f["kernel_addr"],
        len(parts.get("ramdisk", b"")), f["ramdisk_addr"],
        len(parts.get("second", b"")), f["second_addr"],
        f["tags_addr"], ps,
    )
    struct.pack_into("<I", h, 40, hv)

    if hv >= 1:
        struct.pack_into("<I", h, 44, f["os_version"])
        name = f["name"].encode("latin1")[:15]
        h[48:48 + len(name)] = name
        cmd = f["cmdline"].encode("latin1")[:511]
        h[64:64 + len(cmd)] = cmd
        h[576:608] = image_id(parts, hv) + b"\0" * 12
        extra = f["extra_cmdline"].encode("latin1")[:511]
        h[608:608 + len(extra)] = extra
        struct.pack_into("<I", h, OFF_DTBO_SIZE, len(parts.get("recovery_dtbo", b"")))
        dtbo_off = layout.get("recovery_dtbo", 0) if f.get("recovery_dtbo_offset") else 0
        struct.pack_into("<Q", h, OFF_DTBO_OFFSET, dtbo_off)
        struct.pack_into("<I", h, OFF_HEADER_SIZE, HEADER_SIZE_V2 if hv >= 2 else HEADER_SIZE_V1)
    if hv >= 2:
        struct.pack_into("<I", h, OFF_DTB_SIZE, len(parts.get("dtb", b"")))
        struct.pack_into("<Q", h, OFF_DTB_ADDR, f.get("dtb_addr", 0))

    return bytes(h) + b"\0" * (ps - len(h))


def build(f: dict, parts: dict, total: int | None, trailer: bytes = b"", strip_avb: bool = False) -> bytes:
    ps = f["page_size"]
    hv = f["header_version"]
    out = bytearray(build_header(f, parts, compute_layout(f, parts)))

    for name in ("kernel", "ramdisk", "second"):
        b = parts.get(name, b"")
        out += b
        out += b"\0" * (align(len(out), ps) - len(out))
    if hv >= 1:
        b = parts.get("recovery_dtbo", b"")
        if b:
            out += b
            out += b"\0" * (align(len(out), ps) - len(out))
    if hv >= 2:
        b = parts.get("dtb", b"")
        if b:
            out += b
            out += b"\0" * (align(len(out), ps) - len(out))

    if trailer and not strip_avb:
        out += trailer
        if total is not None and len(out) != total:
            sys.exit(f"trailer ends at {len(out)}, requested total {total}")
        return bytes(out)

    size = total if total is not None else f["total_size"]
    if len(out) > size:
        sys.exit(f"payload {len(out)} exceeds requested total {size}")
    out += b"\0" * (size - len(out))
    return bytes(out)


def cmd_info(args) -> None:
    f = parse(args.img)
    parts = f.pop("_parts")
    print(f"{args.img}: {f['total_size']} bytes, header v{f['header_version']}, page {f['page_size']}")
    print(f"  name={f.get('name')!r} board_size_cmdline={f.get('cmdline')!r}")
    for k, v in parts.items():
        print(f"  {k:14s} {len(v):>10}  sha256 {sha256(v)[:16]}")
    print(f"  pad after payload: {f['_pad']} bytes")
    avb = f["_avb"]
    if avb:
        print(f"  avb: v{avb['version']} vbmeta@{avb['vbmeta_offset']} size={avb['vbmeta_size']} "
              f"alg={avb['algorithm_type']} image_size={avb['original_image_size']} "
              f"rollback={avb['rollback_index']} flags={avb['flags']}")
    computed = image_id(parts, f["header_version"]).hex()
    stored = f.get("id", "")[:40]
    print(f"  id stored={stored}")
    print(f"  id computed={computed}  {'MATCH' if stored == computed else 'MISMATCH'}")


def cmd_split(args) -> None:
    f = parse(args.img)
    parts = f.pop("_parts")
    os.makedirs(args.outdir, exist_ok=True)
    pdir = os.path.join(args.outdir, "parts")
    os.makedirs(pdir, exist_ok=True)

    meta = {"source": os.path.abspath(args.img), "image_sha256": sha256(open(args.img, "rb").read())}
    meta.update({k: v for k, v in f.items() if not k.startswith("_")})

    entries = {}
    for name, b in parts.items():
        with open(os.path.join(pdir, name), "wb") as fh:
            fh.write(b)
        entries[name] = {"size": len(b), "sha256": sha256(b)}
    meta["parts"] = entries
    meta["pad"] = f["_pad"]
    meta["payload_end"] = f["_payload_end"]
    meta["avb"] = f["_avb"]
    meta["trailer_size"] = len(f["_trailer"])

    with open(os.path.join(args.outdir, "trailer.bin"), "wb") as fh:
        fh.write(f["_trailer"])

    with open(os.path.join(args.outdir, "fields.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    print(f"split -> {args.outdir}  ({len(parts)} parts)")


def cmd_build(args) -> None:
    with open(os.path.join(args.partsdir, "fields.json")) as fh:
        meta = json.load(fh)
    parts = {}
    for name in ("kernel", "ramdisk", "second", "recovery_dtbo", "dtb"):
        p = os.path.join(args.partsdir, "parts", name)
        if os.path.exists(p):
            parts[name] = open(p, "rb").read()

    trailer = b""
    tp = os.path.join(args.partsdir, "trailer.bin")
    if os.path.exists(tp) and not args.strip_avb:
        trailer = open(tp, "rb").read()

    img = build(meta, parts, args.total, trailer, args.strip_avb)
    with open(args.out, "wb") as fh:
        fh.write(img)
    print(f"built {args.out}: {len(img)} bytes sha256 {sha256(img)} "
          f"avb={'stripped' if args.strip_avb else ('kept' if trailer else 'none')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("info"); a.add_argument("img"); a.set_defaults(fn=cmd_info)
    b = sub.add_parser("split"); b.add_argument("img"); b.add_argument("outdir"); b.set_defaults(fn=cmd_split)
    c = sub.add_parser("build"); c.add_argument("partsdir"); c.add_argument("out")
    c.add_argument("--total", type=int, default=None)
    c.add_argument("--strip-avb", action="store_true")
    c.set_defaults(fn=cmd_build)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
