#!/usr/bin/env bash
# Package a recovery image for Odin: ustar archive holding one file, with at
# least a 2048-byte zero terminator, plus a .tar.md5 companion whose footer is
# a full md5sum line ("<hash>  <name>.tar\n") - the form Odin accepts on this
# device. A bare hash is rejected as "md5 is invalid".
#
#   tools/package_odin.sh <image> <out.tar> [inner-name]
set -euo pipefail

img="$1"
out="$2"
inner="${3:-recovery.img}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp "$img" "$work/$inner"

tar --format=ustar --mtime=@0 --owner=0 --group=0 --numeric-owner -C "$work" -cf "$out" "$inner"

python3 - "$out" <<'PY'
import sys
p = sys.argv[1]
d = open(p, "rb").read()
n = len(d) - len(d.rstrip(b"\0"))
if n < 2048:
    with open(p, "ab") as f:
        f.write(b"\0" * (2048 - n))
    print(f"trailing zeros {n} -> padded to 2048")
else:
    print(f"trailing zeros {n} (>= 2048 ok)")
PY

cp "$out" "$out.md5"
md5="$(md5sum "$out" | cut -d' ' -f1)"
footer="$(printf '%s  %s\n' "$md5" "$(basename "$out")")"
printf '%s\n' "$footer" >> "$out.md5"
echo "footer: $footer"

# verify the footer the way Odin will
python3 - "$out.md5" <<'PY'
import hashlib, re, sys
p = sys.argv[1]
d = open(p, "rb").read()
m = re.search(rb"([0-9a-f]{32})  (\S+\.tar)\n$", d[-120:])
assert m, "footer is not in md5sum form"
content = d[:len(d) - (m.end() - m.start())]
ok = m.group(1).decode() == hashlib.md5(content).hexdigest()
print(f"footer verified: {ok}  (content {len(content)} bytes)")
sys.exit(0 if ok else 1)
PY

sha256sum "$out"
