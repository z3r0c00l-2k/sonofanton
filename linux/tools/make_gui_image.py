#!/usr/bin/env python3
"""Build the GUI image: OrangeFox userspace on our kernel and module set.

Takes the OrangeFox recovery image (already split), keeps its ramdisk, header,
DTB and DTBO, replaces the module set with ours (the OrangeFox one is built for
a different kernel and cannot load), injects the r9s-linux launcher into its
init, swaps in our kernel, signs, and verifies.

  make_gui_image.py --ofox /tmp/ofox --reference /tmp/v3/ramdisk_launcher.gz \
                    --kernel /tmp/v3/parts/kernel --out out/RECOVERY_r9s_gui_v1.img
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ramdisk as rd          # noqa: E402
import recovery_img as ri     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALT = "7d42cb82eb39cdb0c780a44d7fec819502e49959ac10d987020951137ef58b11"
PROP = ("com.android.build.recovery.fingerprint:"
        "samsung/lineage_r9s/r9s:16/BP4A.251205.006/eng.daniel:userdebug/release-keys")


def is_module_entry(name: str) -> bool:
    return name.startswith("lib/modules/") and (name.endswith(".ko") or
                                                name.rsplit("/", 1)[-1].startswith("modules."))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ofox", required=True, help="split OrangeFox image dir")
    ap.add_argument("--reference", required=True, help="our ramdisk (modules + launcher)")
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dtb-from", default=None,
                    help="split dir to take recovery_dtbo/dtb from (default: OrangeFox's)")
    ap.add_argument("--total", type=int, default=67108864)
    args = ap.parse_args()

    meta = json.load(open(os.path.join(args.ofox, "fields.json")))
    parts = {}
    for name in ("kernel", "ramdisk", "second", "recovery_dtbo", "dtb"):
        p = os.path.join(args.ofox, "parts", name)
        if os.path.exists(p):
            parts[name] = open(p, "rb").read()

    if args.dtb_from:
        for name in ("recovery_dtbo", "dtb"):
            p = os.path.join(args.dtb_from, "parts", name)
            if os.path.exists(p):
                parts[name] = open(p, "rb").read()
                print(f"dt payload: {name} taken from {args.dtb_from}")

    ofox = rd.read_cpio(gzip.decompress(parts["ramdisk"]))
    ref = rd.read_cpio(gzip.decompress(open(args.reference, "rb").read()))

    kept = [e for e in ofox if not is_module_entry(e["name"])]
    ref_mods = [e for e in ref if is_module_entry(e["name"])]
    if not ref_mods:
        sys.exit("reference ramdisk carries no modules")
    entries = kept + ref_mods
    print(f"ofox entries {len(ofox)} -> {len(kept)} + {len(ref_mods)} of our modules")

    tmp1 = tempfile.NamedTemporaryFile(suffix=".gz", delete=False).name
    tmp2 = tempfile.NamedTemporaryFile(suffix=".gz", delete=False).name
    try:
        open(tmp1, "wb").write(rd.gz(rd.build_cpio(entries)))
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_launcher_ramdisk.py"),
                        "--ramdisk", tmp1, "--out", tmp2], check=True)
        ramdisk_gz = open(tmp2, "rb").read()
    finally:
        for p in (tmp1, tmp2):
            os.unlink(p)

    parts["kernel"] = open(args.kernel, "rb").read()
    parts["ramdisk"] = ramdisk_gz

    # payload extent, to check it against the partition before signing
    layout = ri.compute_layout(meta, parts)
    end = layout["dtb"] + len(parts["dtb"])
    end = -(-end // meta["page_size"]) * meta["page_size"]
    payload_end = end
    print(f"payload end {end} bytes; partition {args.total} "
          f"({args.total - end} bytes headroom)")
    if end > args.total - 2048:
        sys.exit(f"payload {end} does not fit {args.total}")

    payload = ri.build(meta, parts, total=end, strip_avb=True)
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        tmp = fh.name
        fh.write(payload)
    try:
        subprocess.run([
            sys.executable, os.path.join(ROOT, "..", "third_party", "avbtool", "avbtool.py"), "add_hash_footer",
            "--image", tmp, "--partition_size", str(args.total),
            "--partition_name", "recovery", "--algorithm", "SHA256_RSA4096",
            "--key", os.path.join(ROOT, "keys", "testkey_rsa4096.pem"),  # gitleaks:allow (public AOSP test key path)
            "--rollback_index", "1", "--rollback_index_location", "0",
            "--salt", SALT, "--prop", PROP,
        ], check=True)
        img = open(tmp, "rb").read()
    finally:
        os.unlink(tmp)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "wb").write(img)
    print(f"wrote {args.out}: {len(img)} bytes")

    got = ri.parse(args.out)
    gp = got.pop("_parts")
    checks = [
        ("kernel is ours", gp["kernel"] == parts["kernel"]),
        ("ramdisk is the hybrid", gp["ramdisk"] == ramdisk_gz),
        ("dtb is the one selected", gp["dtb"] == parts["dtb"]),
        ("dtbo is the one selected", gp["recovery_dtbo"] == parts["recovery_dtbo"]),
        ("header name kept", got.get("name") == meta.get("name")),
        ("cmdline kept", got.get("cmdline") == meta.get("cmdline")),
        ("avb signed", bool(got.get("_avb"))),
    ]
    ok = True
    for label, val in checks:
        ok &= bool(val)
        print(f"  {'ok    ' if val else 'FAIL  '} {label}")
    if not ok:
        sys.exit("verification failed")


if __name__ == "__main__":
    main()
