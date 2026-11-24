#!/usr/bin/env bash
# Turn a plain LineageOS 23.2 sync into the tree this project builds.
#
# The manifest does not carry the Samsung projects, and the exynos HAL arrives
# as eight split repositories that have to sit inside
# hardware/samsung_slsi-linaro (whose umbrella checkout then loses the duplicate
# flat directories it ships for older trees). Eight local patches follow.
#
#   tools/prepare-tree.sh              # apply: clone, pin, layout, patch
#   tools/prepare-tree.sh --verify     # report state, change nothing
#
# Existing clones are reused; HEADs are moved to the pinned commit. Nothing is
# deleted outside hardware/samsung_slsi-linaro.
#
# TREE defaults to /mnt/GGG/BuildGround/lineage.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TREE="${TREE:-/mnt/GGG/BuildGround/lineage}"
PATCHES="$ROOT/patches/lineage-tree"

verify=0
case "${1:-}" in
    --verify) verify=1 ;;
    "") ;;
    *) echo "usage: $0 [--verify]" >&2; exit 2 ;;
esac

[ -d "$TREE/.repo" ] || [ -d "$TREE/build" ] || {
    echo "$TREE does not look like a LineageOS tree" >&2; exit 1; }

fail=0
say()  { printf '%s\n' "$*"; }
good() { printf '  ok    %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; fail=1; }

# path  url  commit
PROJECTS="
device/samsung/r9s|https://github.com/Daubfy/android_device_samsung_r9s.git|67a2063ab578867eddddc3a6b76fc13d32469e1c
device/samsung/universal2100-common|https://github.com/exy2100/android_device_samsung_universal2100-common.git|e12db82376c851d2cbfbcb4b6e8ec258c86ee236
vendor/samsung/r9s|https://github.com/Daubfy/proprietary_vendor_samsung_r9s.git|d78b3b7657c63339fe01b6f4788e64474227e635
vendor/samsung/universal2100-common|https://github.com/exy2100/proprietary_vendor_samsung_universal2100-common.git|42057ecebddd52babebacb55a9a221a1ba333926
kernel/samsung/universal2100|https://github.com/exy2100/android_kernel_samsung_universal2100.git|34237952ad8c476c274856c997f7c6e4e92a9946
hardware/samsung|https://github.com/exy2100/android_hardware_samsung.git|94174bf7c798492408bd51b918193d97461e7540
hardware/samsung_slsi-linaro|https://github.com/exy2100/android_hardware_samsung_slsi-linaro_exynos.git|031b49f4c83814590ad3107a99ec23dc156f1562
hardware/samsung_slsi-linaro/codec2|https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_codec2.git|11c7da92a458d6e50e8e95c40d90fd2ec475b3d5
hardware/samsung_slsi-linaro/config|https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_config.git|3626ce714e847cae429883a612d4ec9de79389e7
hardware/samsung_slsi-linaro/exynos|https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_exynos.git|11fa20fdd7fa165ab82fb903a14198f2e67e9691
hardware/samsung_slsi-linaro/exynos5|https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_exynos5.git|7a7c982313e0821898ef9c696d3e12da95cfe037
hardware/samsung_slsi-linaro/graphics|https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_graphics.git|7434937774ed0515758acd5a8109b9dfb3898025
hardware/samsung_slsi-linaro/interfaces|https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_interfaces.git|a23ed82b3f3859aa9e0207036b0d0e98119b959b
hardware/samsung_slsi-linaro/openmax|https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_openmax.git|15ab30812af9fe39fff2ae3cd867d7e954c73881
hardware/samsung_slsi-linaro/sgpu|https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_sgpu.git|3c9e33b7723ed5b3ff4c68a03ce5f22b4575a1c4
"

say "== projects"
while IFS='|' read -r path url sha; do
    [ -n "$path" ] || continue
    dir="$TREE/$path"
    if [ ! -d "$dir/.git" ] && [ ! -f "$dir/.git" ]; then
        if [ "$verify" -eq 1 ]; then
            bad "$path missing"
            continue
        fi
        say "  clone $path"
        git clone --quiet "$url" "$dir"
    fi
    if [ "$verify" -eq 1 ]; then
        head="$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)"
        if [ "$head" = "$sha" ]; then
            good "$path @ ${sha:0:12}"
        else
            bad "$path at ${head:0:12}, want ${sha:0:12}"
        fi
    else
        git -C "$dir" fetch --quiet --all --tags || true
        git -C "$dir" checkout --quiet "$sha"
        good "$path -> ${sha:0:12}"
    fi
done <<EOF
$PROJECTS
EOF

# The umbrella checkout duplicates, file for file, what the split repositories
# provide; leaving both in place makes Soong define the same modules twice.
say "== layout (hardware/samsung_slsi-linaro)"
um="$TREE/hardware/samsung_slsi-linaro"
keep=".gitignore Android.bp NOTICE epic include libsbwcdecomp ssp codec2 config exynos exynos5 graphics interfaces openmax sgpu"
for entry in "$um"/* "$um"/.gitignore; do
    [ -e "$entry" ] || continue
    name="$(basename "$entry")"
    case " $keep " in
        *" $name "*) ;;
        *)
            if [ "$verify" -eq 1 ]; then
                bad "duplicate $name still present"
            else
                rm -rf "$entry"
                say "  removed $name"
            fi
            ;;
    esac
done
[ "$verify" -eq 1 ] || good "flat duplicates removed"

say "== patches"
seen=0
while IFS='|' read -r patch repo; do
    [ -n "$patch" ] || continue
    seen=$((seen + 1))
    file="$PATCHES/$patch"
    [ -f "$file" ] || { bad "$patch missing from patches/lineage-tree"; continue; }
    if [ "$verify" -eq 1 ]; then
        if git -C "$TREE/$repo" apply --check --reverse "$file" 2>/dev/null; then
            good "$patch"
        else
            bad "$patch not applied to $repo"
        fi
    else
        if git -C "$TREE/$repo" apply --check --reverse "$file" 2>/dev/null; then
            good "$patch (already applied)"
        else
            git -C "$TREE/$repo" apply "$file"
            good "$patch"
        fi
    fi
done <<'EOF'
0001-kernel-r9s-config-namespaces.patch|kernel/samsung/universal2100
0002-recovery-server-menu.patch|bootable/recovery
0003-external-skia-vendor-available.patch|external/skia
0004-external-highway-vendor-available.patch|external/google-highway
0005-external-xmp-vendor-available.patch|external/XMP-Toolkit-SDK
0006-universal2100-common-drop-epic-hal.patch|device/samsung/universal2100-common
0007-hardware-samsung-disable-lineage-health.patch|hardware/samsung
0008-hardware-samsung_slsi-linaro-reduce-android-bp.patch|hardware/samsung_slsi-linaro
0009-recovery-screen-timeout.patch|bootable/recovery
0010-recovery-status-row.patch|bootable/recovery
0011-kernel-cpuset-group-cap.patch|kernel/samsung/universal2100
0012-kernel-cpuset-drop-group-cap.patch|kernel/samsung/universal2100
EOF

# A patch file that is not in the list above is never applied, and --verify
# would not notice. Refuse the mismatch instead of building without it.
files=$(find "$PATCHES" -maxdepth 1 -name '*.patch' | wc -l | tr -d ' ')
[ "$seen" -eq "$files" ] || bad "patch list covers $seen of $files files in patches/lineage-tree"

if [ "$fail" -ne 0 ]; then
    say
    say "tree does not match the build state"
    exit 1
fi
say
say "tree ready: $TREE"
