#!/usr/bin/env python3
"""Repack the recovery image with a rebuilt kernel and module set.

Works on the cpio entries directly (no filesystem round trip), so ownership,
modes and symlinks are preserved exactly. Refuses to produce an image when the
module set does not match the baseline list or when any vermagic disagrees with
the new kernel.

  repack.py --baseline baseline --build build \
            --kernel build/arch/arm64/boot/Image \
            --out out/RECOVERY_r9s_kernel.img [--keep-avb]
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ramdisk as rd          # noqa: E402
import recovery_img as ri     # noqa: E402

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AVBTOOL = os.path.normpath(os.path.join(ROOT_DIR, "..", "third_party", "avbtool", "avbtool.py"))

# Recovered from the baseline recovery image (avbtool info_image) and verified
# by re-signing the baseline payload to a byte-identical image.
AVB_SALT = "7d42cb82eb39cdb0c780a44d7fec819502e49959ac10d987020951137ef58b11"
AVB_PROP = ("com.android.build.recovery.fingerprint:"
            "samsung/lineage_r9s/r9s:16/BP4A.251205.006/eng.daniel:userdebug/release-keys")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def ustar_release(image: bytes) -> str:
    m = re.search(rb"Linux version (\S+)", image)
    if not m:
        sys.exit("could not read a version string from the new Image")
    return m.group(1).decode()


def strip_module(path: str) -> bytes:
    """Strip debug info the way Kbuild's INSTALL_MOD_STRIP=1 does for ramdisks."""
    with tempfile.NamedTemporaryFile(suffix=".ko", delete=False) as fh:
        tmp = fh.name
        fh.write(open(path, "rb").read())
    try:
        for cmd in (["llvm-strip", "--strip-debug", tmp],
                    ["llvm-objcopy", "--strip-debug", tmp]):
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return open(tmp, "rb").read()
            except FileNotFoundError:
                continue
            except subprocess.CalledProcessError:
                continue
        sys.exit(f"could not strip {path}: no working strip tool")
    finally:
        os.unlink(tmp)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--build", default=None,
                    help="module build tree; omit when supplying --ramdisk")
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--ramdisk", default=None,
                    help="use this ramdisk verbatim and skip module replacement")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-avb", action="store_true")
    ap.add_argument("--sign", action="store_true",
                    help="sign with the recovered LOS AVB parameters (recommended)")
    ap.add_argument("--total", type=int, default=67108864)
    args = ap.parse_args()

    meta = json.load(open(os.path.join(args.baseline, "fields.json")))
    base_parts = {}
    for name in ("kernel", "ramdisk", "second", "recovery_dtbo", "dtb"):
        p = os.path.join(args.baseline, "parts", name)
        if os.path.exists(p):
            base_parts[name] = open(p, "rb").read()

    kernel = open(args.kernel, "rb").read()
    release = ustar_release(kernel)
    print(f"new kernel: {len(kernel)} bytes, release {release}")

    # index built modules by basename
    built = {}
    if args.build:
        for p in glob.glob(os.path.join(args.build, "**", "*.ko"), recursive=True):
            b = os.path.basename(p)
            if b in built:
                sys.exit(f"duplicate module basename in build: {b}")
            built[b] = p
    print(f"built modules: {len(built)}")

    if args.ramdisk:
        ramdisk_gz = open(args.ramdisk, "rb").read()
        print(f"ramdisk: supplied {len(ramdisk_gz)} bytes; module replacement skipped")
    else:
        # rewrite the ramdisk
        entries = rd.read_cpio(gzip.decompress(base_parts["ramdisk"]))
        replaced, missing = 0, []
        load_names = []
        for e in entries:
            n = e["name"]
            if n == "lib/modules/modules.load":
                load_names = [l for l in e["data"].decode().splitlines() if l.strip()]
            if n.startswith("lib/modules/") and n.endswith(".ko"):
                base = n.rsplit("/", 1)[-1]
                if base not in built:
                    missing.append(base)
                    continue
                data = strip_module(built[base])
                i = data.find(b"vermagic=")
                vm = data[i + 9:i + 9 + 200].split(b"\0")[0].decode(errors="replace") if i >= 0 else "(none)"
                if not vm.startswith(release + " "):
                    sys.exit(f"{base}: vermagic {vm!r} does not match release {release!r}")
                e["data"] = data
                replaced += 1

        if missing:
            sys.exit(f"modules in the ramdisk but not in this build ({len(missing)}): {', '.join(missing[:8])}")

        shipped = {e["name"].rsplit("/", 1)[-1][:-3] for e in entries
                   if e["name"].startswith("lib/modules/") and e["name"].endswith(".ko")}
        if load_names and set(load_names) != shipped:
            sys.exit(f"modules.load does not list exactly the shipped modules "
                     f"(load-only {sorted(set(load_names) - shipped)[:5]}, "
                     f"shipped-only {sorted(shipped - set(load_names))[:5]})")
        print(f"modules replaced: {replaced}; modules.load entries: {len(load_names)}")

        packed = rd.build_cpio(entries)
        ramdisk_gz = rd.gz(packed)
        print(f"ramdisk: {len(packed)} packed, {len(ramdisk_gz)} gzipped "
              f"(baseline {len(base_parts['ramdisk'])})")

    parts = dict(base_parts)
    parts["kernel"] = kernel
    parts["ramdisk"] = ramdisk_gz

    trailer = b""
    if args.keep_avb:
        trailer = open(os.path.join(args.baseline, "trailer.bin"), "rb").read()

    if args.sign:
        # Sign with the exact parameters the LOS build used, so the image is
        # structurally identical to the one that boots. Salt, prop, algorithm,
        # rollback index/location and key were all recovered from the baseline
        # image; reproducing them re-signs the *original* payload byte-for-byte.
        layout = ri.compute_layout(meta, parts)
        end = layout["dtb"] + len(parts["dtb"])
        end = -(-end // meta["page_size"]) * meta["page_size"]
        payload = ri.build(meta, parts, total=end, strip_avb=True)

        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
            tmp = fh.name
            fh.write(payload)
        try:
            subprocess.run([
                sys.executable, AVBTOOL,
                "add_hash_footer",
                "--image", tmp,
                "--partition_size", str(args.total),
                "--partition_name", "recovery",
                "--algorithm", "SHA256_RSA4096",
                "--key", os.path.join(ROOT_DIR, "keys", "testkey_rsa4096.pem"),  # gitleaks:allow (public AOSP test key path)
                "--rollback_index", "1",
                "--rollback_index_location", "0",
                "--salt", AVB_SALT,
                "--prop", AVB_PROP,
            ], check=True)
            img = open(tmp, "rb").read()
        finally:
            os.unlink(tmp)
    else:
        img = ri.build(meta, parts, args.total, trailer, strip_avb=not args.keep_avb)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "wb").write(img)
    print(f"wrote {args.out}: {len(img)} bytes sha256 {sha(img)}")

    # --- self-verification against the written file ---
    print("verify:")
    got = ri.parse(args.out)
    gp = got.pop("_parts")
    ok = True
    for name in ("recovery_dtbo", "dtb"):
        same = sha(gp.get(name, b"")) == sha(base_parts.get(name, b""))
        ok &= same
        print(f"  {'ok    ' if same else 'FAIL  '} {name} identical to baseline")
    same = sha(gp["kernel"]) == sha(kernel)
    ok &= same
    print(f"  {'ok    ' if same else 'FAIL  '} kernel is the rebuilt Image")
    same = sha(gp["ramdisk"]) == sha(ramdisk_gz)
    ok &= same
    print(f"  {'ok    ' if same else 'FAIL  '} ramdisk is the repacked one")
    same = got.get("name") == meta.get("name") and got.get("cmdline") == meta.get("cmdline")
    ok &= same
    print(f"  {'ok    ' if same else 'FAIL  '} header name/cmdline preserved")
    id_ok = got.get("id", "")[:40] == ri.image_id(gp, got["header_version"]).hex()
    ok &= id_ok
    print(f"  {'ok    ' if id_ok else 'FAIL  '} header id recomputed matches stored")
    avb = got.get("_avb")
    if args.sign:
        avb_ok = bool(avb) and avb.get("vbmeta_size") == 2240
        label = (f"signed, vbmeta@{avb['vbmeta_offset']} size={avb['vbmeta_size']}"
                 if avb else "MISSING after signing")
    else:
        avb_ok = avb is None or args.keep_avb
        label = "kept (stale)" if avb else "stripped"
    ok &= avb_ok
    print(f"  {'ok    ' if avb_ok else 'FAIL  '} avb: {label}")

    if args.sign:
        info = subprocess.run(
            [sys.executable, AVBTOOL,
             "info_image", "--image", args.out],
            capture_output=True, text=True).stdout
        m = re.search(r"Digest:\s+([0-9a-f]{64})", info)
        want = hashlib.sha256(bytes.fromhex(AVB_SALT) + payload).hexdigest()
        same = bool(m) and m.group(1) == want
        ok &= same
        print(f"  {'ok    ' if same else 'FAIL  '} avb digest covers the new payload")

    if not ok:
        sys.exit("verification failed")


if __name__ == "__main__":
    main()
