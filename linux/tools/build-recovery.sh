#!/usr/bin/env bash
# Produce a flashable recovery image: build (optional), inject the launcher,
# sign, verify, package.
#
#   tools/build-recovery.sh server_v4              # build, then package
#   tools/build-recovery.sh --no-build server_v4   # package what is already built
#
# The LineageOS build alone is not enough: it produces the recovery UI but no
# launcher, no server helper, no init service and no ro.adb.secure.recovery=0,
# because injection is a post-build step into the packed ramdisk. This script is
# that whole chain, and it refuses to ship an image whose ramdisk is missing any
# of the pieces, so a stale helper cannot be flashed again.
#
# Environment overrides: LINEAGE_DIR, LUNCH, JOBS, OUTDIR, BUILD_LOG.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LINEAGE="${LINEAGE_DIR:-/mnt/GGG/BuildGround/lineage}"
PRODUCT="${PRODUCT:-r9s}"
JOBS="${JOBS:-8}"
OUTDIR="${OUTDIR:-$ROOT/out}"
BUILD_LOG="${BUILD_LOG:-$LINEAGE/../build-raw.log}"
LUNCH="${LUNCH:-lineage_${PRODUCT}-trunk_staging-userdebug}"

build=1
args=()
for a in "$@"; do
    case "$a" in
        --no-build) build=0 ;;
        -h|--help) awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "$0"; exit 0 ;;
        *) args+=("$a") ;;
    esac
done
if [ "${#args[@]}" -ne 1 ]; then
    echo "usage: $0 [--no-build] TAG      (e.g. server_v4)" >&2
    exit 2
fi
tag="${args[0]}"
case "$tag" in
    *[!A-Za-z0-9._-]*) echo "tag may only contain letters, digits, dot, dash, underscore" >&2; exit 2 ;;
esac

built="$LINEAGE/out/target/product/$PRODUCT/recovery.img"
work="$OUTDIR/work-$tag"
img="$OUTDIR/RECOVERY_r9s_$tag.img"
tar="$OUTDIR/RECOVERY_r9s_$tag.tar"

step() { printf '\n== %s\n' "$*"; }

if [ "$build" -eq 1 ]; then
    step "building recovery in $LINEAGE ($LUNCH, -j$JOBS)"
    (
        # envsetup.sh and lunch are not `set -u` clean: _gettop_once() reads
        # $TOP before assigning it, so this script's `set -u` aborts at
        # build/envsetup.sh:21. Keep nounset off for the build shell only.
        set +u
        cd "$LINEAGE"
        source build/envsetup.sh
        lunch "$LUNCH" >/dev/null
        m -j"$JOBS" recoveryimage
    ) 2>&1 | tee -a "$BUILD_LOG"
fi

[ -f "$built" ] || { echo "no built image at $built" >&2; exit 1; }

step "splitting $built"
rm -rf "$work"
mkdir -p "$work"
python3 "$ROOT/tools/recovery_img.py" split "$built" "$work" >/dev/null

step "injecting the launcher"
python3 "$ROOT/tools/make_launcher_ramdisk.py" \
    --ramdisk "$work/parts/ramdisk" --out "$work/ramdisk.gz"

step "repacking and signing"
python3 "$ROOT/tools/repack.py" \
    --baseline "$work" --kernel "$work/parts/kernel" \
    --ramdisk "$work/ramdisk.gz" --sign --out "$img"

step "verifying the shipped ramdisk"
python3 - "$img" "$ROOT" <<'PY'
import gzip, re, sys
sys.path.insert(0, sys.argv[2] + "/tools")
import recovery_img as ri, ramdisk as rd

img = sys.argv[1]
meta = ri.parse(img)
parts = meta["_parts"]
entries = rd.read_cpio(gzip.decompress(parts["ramdisk"]))
by = {e["name"]: e for e in entries}

fail = []
need = ("system/bin/pivot_root", "system/bin/linux-launch",
        "system/bin/charge-guard", "system/bin/net-watch",
        "system/bin/r9s-server")
for n in need:
    e = by.get(n)
    if not e:
        fail.append(f"{n} missing")
    elif not e["mode"] & 0o111:
        fail.append(f"{n} not executable")
    else:
        print(f"  ok    {n} ({len(e['data'])} bytes, {oct(e['mode'])[-3:]})")

logo = by.get("res/images/logo_image_switch.png", {}).get("data", b"")
want = open(sys.argv[2] + "/assets/logo_sonofanton.png", "rb").read()
if logo != want:
    fail.append("res/images/logo_image_switch.png is not the project logo")
else:
    print(f"  ok    res/images/logo_image_switch.png ({len(logo)} bytes)")

helper = by.get("system/bin/r9s-server", {}).get("data", b"").decode()
if "pgrep -x sshd" not in helper:
    fail.append("r9s-server does not detect sshd by command name (stale helper?)")

launch = by.get("system/bin/linux-launch", {}).get("data", b"").decode()
if "net-watch" not in launch:
    fail.append("linux-launch does not start net-watch")

watch = by.get("system/bin/net-watch", {}).get("data", b"").decode()
if "dhclient" not in watch:
    fail.append("net-watch does not drive dhclient")
if "chronyd" not in watch:
    fail.append("net-watch does not set the clock from ntp")
if "hwclock" not in watch:
    fail.append("net-watch does not commit the clock to the rtc")
if '"$ROOT$p"' in watch or '"$ROOT$p" ]' in watch:
    fail.append("net-watch tests executables from outside the chroot (absolute symlinks look dangling)")
if "chroot \"$ROOT\" \"$p\"" not in watch:
    fail.append("net-watch does not probe tools inside the chroot")

props = by.get("prop.default", {}).get("data", b"").decode()
if "ro.adb.secure.recovery=0" not in props:
    fail.append("prop.default lacks ro.adb.secure.recovery=0")

rc = by.get("init.recovery.exynos2100.rc", {}).get("data", b"").decode()
if "service r9slinux /system/bin/linux-launch" not in rc:
    fail.append("init rc lacks the r9slinux service")
if not re.search(r"on late-init\n\s+start r9slinux", rc):
    fail.append("init rc does not start r9slinux on late-init")

kos = [e for e in entries if e["name"].startswith("lib/modules/") and e["name"].endswith(".ko")]
load = [l for l in by.get("lib/modules/modules.load", {}).get("data", b"").decode().splitlines() if l.strip()]
if not kos:
    fail.append("ramdisk ships no modules")
if set(load) != {e["name"].rsplit("/", 1)[-1][:-3] for e in kos}:
    fail.append("modules.load does not list exactly the shipped modules")

rel = re.search(rb"Linux version (\S+)", parts["kernel"]).group(1).decode()
bad = []
for e in kos:
    d = e["data"]
    i = d.find(b"vermagic=")
    vm = d[i + 9:i + 9 + 200].split(b"\0")[0].decode(errors="replace") if i >= 0 else ""
    if not vm.startswith(rel + " "):
        bad.append(e["name"])
if bad:
    fail.append(f"{len(bad)} modules disagree with kernel release {rel}")

print(f"  ok    {len(kos)} modules, all vermagic {rel}")
print("  ok    ro.adb.secure.recovery=0, r9slinux service, sshd detection")

if fail:
    print("\nFAILED:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
PY

step "verifying AVB"
avbdir="$work/avb"
mkdir -p "$avbdir"
cp "$img" "$avbdir/recovery.img"
python3 "$ROOT/../third_party/avbtool/avbtool.py" verify_image \
    --image "$avbdir/recovery.img" --key "$ROOT/keys/testkey_rsa4096.pem"

step "packaging for Odin"
"$ROOT/tools/package_odin.sh" "$img" "$tar"
cp "$tar" "$OUTDIR/FLASH_r9s_$tag.tar"

step "recording hashes"
# relative to the repo root when the artifacts live under it, like the rest of
# the manifest, so the file stays portable
(
    cd "$ROOT"
    sha256sum "${img#"$ROOT"/}" "${tar#"$ROOT"/}" "${tar#"$ROOT"/}.md5"
) >> "$OUTDIR/SHA256SUMS"

[ "${KEEP_WORK:-0}" = "1" ] || rm -rf "$work"

step "done"
echo "image   $img"
echo "flash   $OUTDIR/FLASH_r9s_$tag.tar"
