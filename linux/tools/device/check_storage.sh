#!/bin/bash
mount -t proc proc /proc 2>/dev/null
mkdir -p /sys/fs/cgroup/devices
mount -t cgroup -o devices devices /sys/fs/cgroup/devices 2>/dev/null
dockerd --data-root=/var/lib/docker > /var/log/dockerd.log 2>&1 &
for i in $(seq 1 40); do docker info >/dev/null 2>&1 && break; sleep 1; done
docker info 2>/dev/null | grep -iE "storage driver|backing filesystem|cgroup (driver|version)|server version"
