#!/usr/bin/env bash
# SSH into the Debian root running on the device.
#
# The phone has no network of its own yet: the only path in is the adb tunnel
# (adb forward tcp:2222 -> device port 22, forwarded into the Linux namespace).
# Once the USB-C hub lands, this becomes a direct network login.
#
#   tools/ssh-r9s.sh                  interactive shell
#   tools/ssh-r9s.sh 'uname -a'       run one command
#   KEY=... PORT=2223 tools/ssh-r9s.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY="${KEY:-$ROOT/keys/r9s-linux_ed25519}"
PORT="${PORT:-2222}"

if [ ! -f "$KEY" ]; then
    echo "missing key: $KEY" >&2
    exit 1
fi
chmod 600 "$KEY" 2>/dev/null || true

adb forward "tcp:$PORT" tcp:22 >/dev/null

exec ssh -i "$KEY" -p "$PORT" \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="${KNOWN_HOSTS:-$ROOT/.ssh-known-hosts}" \
    root@127.0.0.1 "$@"
