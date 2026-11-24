#!/usr/bin/env bash
# Pull crash and boot evidence from the device. Run while the recovery is up;
# the pstore copy is the *previous* boot, which is the one that failed.
#
#   tools/fetch_crashlog.sh [outdir]
set -uo pipefail

out="${1:-/tmp/opencode/crash}"
mkdir -p "$out"

adb pull /sys/fs/pstore "$out/pstore"        >/dev/null 2>&1
adb pull /cache/recovery/last_kmsg "$out/"   >/dev/null 2>&1
adb pull /cache/recovery/last_log "$out/"    >/dev/null 2>&1
adb shell 'dmesg'                            > "$out/dmesg-current.log" 2>/dev/null
adb shell 'cat /proc/version'                > "$out/version.txt" 2>/dev/null
adb shell 'ls /sys/fs/pstore'                > "$out/pstore-list.txt" 2>/dev/null

echo "== captured in $out"
ls -l "$out" | tail -n +2

echo
echo "== current kernel"
head -c 130 "$out/version.txt" 2>/dev/null; echo

echo
echo "== previous boot (pstore)"
if ls "$out"/pstore/* >/dev/null 2>&1; then
  grep -m1 "Linux version" "$out"/pstore/* | cut -c1-140
  grep -nE "Kernel panic|Internal error|Oops|__cfi_check_fail|Unable to handle" "$out"/pstore/* | head -5
else
  echo "(no pstore entries)"
fi

echo
echo "== CFI violations this boot (expected: logged, not fatal)"
adb shell 'dmesg | grep -iE "cfi" | head -10' 2>/dev/null
