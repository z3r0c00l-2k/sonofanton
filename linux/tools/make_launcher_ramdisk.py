#!/usr/bin/env python3
"""Inject the r9s-linux launcher into a recovery ramdisk.

Adds:
  system/bin/pivot_root      static helper (tools/device/pivot_root)
  system/bin/linux-launch    launcher script (tools/device/linux-launch)
  system/bin/charge-guard    charge guard (tools/device/charge-guard)
  system/bin/net-watch       Ethernet watcher (tools/device/net-watch)
  system/bin/r9s-server      server status/control (tools/device/r9s-server)
  an init service             appended to init.recovery.exynos2100.rc
  res/images/logo_image*.png  project branding (assets/logo_sonofanton.png)

The ramdisk is one cpio archive. Entries must be inserted before its
TRAILER!!! record: an earlier version of this script appended a second archive
after the trailer, which the kernel happens to unpack but which ramdisk.py (and
anyone reading the image) cannot see.

Idempotent: replaces the four files and the service block if present.

  make_launcher_ramdisk.py --ramdisk IN.gz --out OUT.gz
"""
from __future__ import annotations

import argparse
import gzip
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ramdisk as rd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV = os.path.join(ROOT, "tools", "device")

SERVICE_MARKER = "# r9s-linux: start the Linux root"
SERVICE_BLOCK = f"""
{SERVICE_MARKER} in its own namespace (see /system/bin/linux-launch)
service r9slinux /system/bin/linux-launch
    class core
    user root
    oneshot
    disabled
    seclabel u:r:recovery:s0

on late-init
    start r9slinux
"""


def first_archive_end(data: bytes) -> int:
    """Offset just past the first archive's TRAILER!!! record."""
    off = 0
    while off + 110 <= len(data):
        if data[off:off + 6] != rd.MAGIC:
            sys.exit(f"bad cpio magic at {off}")
        fields = [int(data[off + 6 + i * 8: off + 6 + (i + 1) * 8], 16) for i in range(13)]
        namesz = fields[11]
        name = data[off + 110: off + 110 + namesz - 1]
        end = (off + 110 + namesz + 3) & ~3
        if name == b"TRAILER!!!":
            return end
        off = (end + fields[6] + 3) & ~3
    sys.exit("no TRAILER!!! in the first archive")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ramdisk", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    data = gzip.decompress(open(args.ramdisk, "rb").read())
    end = first_archive_end(data)
    head, rest = data[:end], data[end:]

    entries = [e for e in rd.read_cpio(head) if e["name"] != "TRAILER!!!"]
    by_name = {e["name"]: i for i, e in enumerate(entries)}

    injected = {
        "system/bin/pivot_root": open(os.path.join(DEV, "pivot_root"), "rb").read(),
        "system/bin/linux-launch": open(os.path.join(DEV, "linux-launch"), "rb").read(),
        "system/bin/charge-guard": open(os.path.join(DEV, "charge-guard"), "rb").read(),
        "system/bin/net-watch": open(os.path.join(DEV, "net-watch"), "rb").read(),
        "system/bin/r9s-server": open(os.path.join(DEV, "r9s-server"), "rb").read(),
    }

    # mtime 0, like the rest of the ramdisk: keeps the gzipped cpio byte-stable
    # across runs, so a rebuild of the same sources hashes identically.
    for name, blob in injected.items():
        if name in by_name:
            entries[by_name[name]]["data"] = blob
            entries[by_name[name]]["mode"] = 0o100755
        else:
            entries.append(dict(name=name, mode=0o100755, uid=0, gid=0, nlink=1,
                                mtime=0, data=blob))

    # Branding: the menu header is a bitmap, so the project name replaces the
    # stock wordmark here instead of in recovery's source. logo_image_switch is
    # the one this device loads (ro.boot.dynamic_partitions is set); both are
    # replaced so the paths cannot disagree.
    logo = open(os.path.join(ROOT, "assets", "logo_sonofanton.png"), "rb").read()
    for name in ("res/images/logo_image.png", "res/images/logo_image_switch.png"):
        if name not in by_name:
            sys.exit(f"{name} not found in the first archive")
        entries[by_name[name]]["data"] = logo
        entries[by_name[name]]["mode"] = 0o100644
        injected[name] = logo

    init_name = "init.recovery.exynos2100.rc"
    if init_name not in by_name:
        sys.exit(f"{init_name} not found in the first archive")
    init = entries[by_name[init_name]]["data"].decode()

    # Recovery adbd requires host-key authorisation unless this is cleared, and
    # a keyless ramdisk otherwise leaves adb unusable after a cold boot. This is
    # the same property the "Enable ADB" menu item sets at runtime.
    prop_name = "prop.default"
    if prop_name in by_name:
        props = entries[by_name[prop_name]]["data"].decode()
        if "ro.adb.secure.recovery=" not in props:
            props = (props.rstrip("\n") + "\n"
                     "# r9s-linux: adb in recovery needs no host-key authorisation\n"
                     "ro.adb.secure.recovery=0\n")
            entries[by_name[prop_name]]["data"] = props.encode()
            print(f"{prop_name}: ro.adb.secure.recovery=0 added")
        else:
            print(f"{prop_name}: ro.adb.secure.recovery already present")

    if SERVICE_MARKER in init:
        head_text = init[: init.index(SERVICE_MARKER)]
        # drop the line before the marker that carried the block too
        init = head_text.rsplit("\nservice r9slinux", 1)[0].rstrip("\n") + "\n"
    init = init.rstrip("\n") + "\n" + SERVICE_BLOCK
    entries[by_name[init_name]]["data"] = init.encode()

    # The first archive's trailing zero padding is replaced by build_cpio's own
    # 512-byte padding; the remaining archives follow unchanged.
    packed = rd.build_cpio(entries) + rest
    open(args.out, "wb").write(rd.gz(packed))

    print(f"injected: {', '.join(injected)}")
    print(f"service written to {init_name}")
    print(f"first archive {len(entries)} entries, {len(rest)} bytes of further archives preserved")
    print(f"wrote {args.out}: {os.path.getsize(args.out)} bytes")


if __name__ == "__main__":
    main()
