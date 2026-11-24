#!/usr/bin/env bash
# Task 3.4 gate: run against the device after flashing the candidate and
# cold-booting. Read-only except for a scratch overlay under /tmp.
set -uo pipefail

say() { printf '\n== %s\n' "$1"; }

say "device"
adb devices -l | tail -2

say "kernel"
adb shell 'uname -a' 2>&1
adb shell 'cut -c1-110 /proc/version' 2>&1

say "namespaces"
for ns in pid ipc user; do
  printf '  %-5s ' "$ns"
  adb shell "unshare --$ns true 2>&1 && echo ok" 2>&1 | tail -1
done

say "config delta present in the running kernel"
adb shell 'zcat /proc/config.gz | grep -E "CONFIG_(PID_NS|IPC_NS|USER_NS|CGROUP_DEVICE|CGROUP_PIDS|BRIDGE_NETFILTER|NETFILTER_XT_MATCH_ADDRTYPE|NF_TABLES|NFT_COMPAT|MACVLAN|POSIX_MQUEUE|TMPFS_XATTR)="' 2>&1

say "module load failures"
adb shell 'dmesg | grep -iE "version magic|vermagic|disagrees" | head -5' 2>&1
printf '  loaded modules: '; adb shell 'lsmod | tail -n +2 | wc -l' 2>&1

say "cfi (permissive: violations logged, must not panic)"
adb shell 'dmesg | grep -iE "cfi" | head -8' 2>&1
printf '  kernel still alive: '; adb shell 'echo yes' 2>&1

say "overlay on tmpfs (TMPFS_XATTR)"
adb shell 'rm -rf /tmp/ovt; mkdir -p /tmp/ovt/l /tmp/ovt/u /tmp/ovt/w /tmp/ovt/m && echo lower > /tmp/ovt/l/f && mount -t overlay overlay -o lowerdir=/tmp/ovt/l,upperdir=/tmp/ovt/u,workdir=/tmp/ovt/w /tmp/ovt/m && cat /tmp/ovt/m/f && echo overlay-tmpfs-ok' 2>&1
adb shell 'umount /tmp/ovt/m 2>/dev/null; rm -rf /tmp/ovt' 2>&1

say "gui and adb"
adb shell 'pidof recovery; getprop sys.usb.config; getprop init.svc.adbd' 2>&1
