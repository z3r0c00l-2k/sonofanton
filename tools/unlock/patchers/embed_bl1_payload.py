#!/usr/bin/env python3
"""Embed the EUB bootstrap payload into BL1 at +0x2000.

Why this exists
---------------
Every archived build that boots (v6..v15, and v16) carries this payload; the
stock `input/sboot.bin` has that region zeroed. BL1's exploit path executes it
from 0x02024000 (= BL1 load 0x02022000 + 0x2000), and without it BL1 falls back
to its stock verification of our re-signed chain, fails, and halts: no display,
no download mode, BootROM EUB only. That is what v17 shipped.

`split.py` regenerates output/sboot/bl1.bin from the stock sboot, so this must
run *after* split and *before* build.py signs BL1 (embedding after signing gives
`BL1 Checksum Fail`).

usage: embed_bl1_payload.py <bl1.bin> [payload.bin]
"""
import hashlib
import sys

OFFSET = 0x2000
END = 0x2170
DEFAULT_PAYLOAD = "9840_boot_custom_key_ours.bin"
EXPECTED_ZONE_SHA256 = "49662744279262d05f98b2fd75eddcabcaed7c564797bb2c6539a41c0fc15f65"


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    bl1_path = argv[0]
    payload_path = argv[1] if len(argv) > 1 else DEFAULT_PAYLOAD
    payload = open(payload_path, "rb").read()
    room = END - OFFSET
    if len(payload) > room:
        raise SystemExit(f"error: payload {len(payload)} B does not fit in {room} B")
    want = payload + bytes(room - len(payload))

    d = bytearray(open(bl1_path, "rb").read())
    if len(d) < END:
        raise SystemExit(f"error: {bl1_path}: {len(d)} B, expected >= {END:#x}")
    cur = bytes(d[OFFSET:END])
    if cur == want:
        print(f"{bl1_path}: payload already present (no change)")
    elif all(b == 0 for b in cur):
        d[OFFSET:END] = want
        open(bl1_path, "wb").write(bytes(d))
        print(f"{bl1_path}: payload embedded at {OFFSET:#x} "
              f"({len(payload)} B + {room - len(payload)} pad)")
    else:
        raise SystemExit(
            f"error: {bl1_path}[{OFFSET:#x}:{END:#x}] is neither zero nor our "
            f"payload; refusing to overwrite unknown content")

    zone = bytes(open(bl1_path, "rb").read())[OFFSET:END]
    sha = hashlib.sha256(zone).hexdigest()
    print(f"  zone sha256 {sha}")
    if sha != EXPECTED_ZONE_SHA256:
        print(f"  WARNING: expected {EXPECTED_ZONE_SHA256}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
