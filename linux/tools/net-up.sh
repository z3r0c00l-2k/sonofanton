#!/usr/bin/env bash
# r9s-linux: network for development mode, when the phone is a USB device.
#
# The phone is a USB host while a hub is attached: it gets its own Ethernet and
# /system/bin/net-watch configures it (static address from /data/linux/net.conf
# or DHCP) and sets the clock. With a plain cable the port is a device again and
# there is no uplink, so a userspace HTTP/CONNECT proxy on the host plus
# `adb reverse` gives the device a 127.0.0.1:PORT that tunnels to the host.
#
#   tools/net-up.sh            bring it up (idempotent)
#   PORT=3129 tools/net-up.sh  use another device-side port
#
# Then, on the device:
#   export http_proxy=http://127.0.0.1:3128 https_proxy=http://127.0.0.1:3128
# apt is pre-configured via /etc/apt/apt.conf.d/99proxy, so it needs nothing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-3128}"
PROXY_LOG="${PROXY_LOG:-/tmp/r9s-proxy.log}"
ROOTFS="${ROOTFS:-/data/linux/data/debian}"

# 1. host proxy
if ! pgrep -f "tools/adbproxy.py|/adbproxy.py" >/dev/null 2>&1; then
    setsid nohup python3 "$ROOT/tools/adbproxy.py" >"$PROXY_LOG" 2>&1 </dev/null &
    sleep 1
fi
grep -m1 "proxy listening" "$PROXY_LOG" 2>/dev/null || echo "proxy: started"

# 2. device-side listener tunnelled to the host
adb reverse "tcp:$PORT" tcp:3128 >/dev/null
echo "reverse: device 127.0.0.1:$PORT -> host 3128"

# 3. clock, for when the hub path has not run yet (host time, written to the RTC)
HOSTDATE=$(date -u '+%Y-%m-%d %H:%M:%S')
adb shell "chroot $ROOTFS /bin/date -u -s \"$HOSTDATE\" >/dev/null 2>&1 &&
           chroot $ROOTFS /usr/sbin/hwclock -w >/dev/null 2>&1" || true
echo "clock: $HOSTDATE"

# 4. apt proxy config, idempotent
adb shell "chroot $ROOTFS /bin/sh -c 'printf \"Acquire::http::Proxy \\\"http://127.0.0.1:$PORT\\\";\\nAcquire::https::Proxy \\\"http://127.0.0.1:$PORT\\\";\\n\" > /etc/apt/apt.conf.d/99proxy'" 2>/dev/null
echo "apt: /etc/apt/apt.conf.d/99proxy -> http://127.0.0.1:$PORT"

echo
echo "ready. on the device:"
echo "  export http_proxy=http://127.0.0.1:$PORT https_proxy=http://127.0.0.1:$PORT"
echo "  apt-get update && apt-get install -y curl"
