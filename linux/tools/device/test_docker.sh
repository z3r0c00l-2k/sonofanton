#!/bin/bash
mount -t proc proc /proc
update-alternatives --set iptables /usr/sbin/iptables-legacy 2>/dev/null
update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null
mkdir -p /sys/fs/cgroup/devices
mount -t cgroup -o devices devices /sys/fs/cgroup/devices 2>/dev/null
echo "devices-cgroup mounts: $(mount | grep -c 'cgroup/devices')"
mkdir -p /var/log
dockerd --data-root=/var/lib/docker > /var/log/dockerd.log 2>&1 &
for i in $(seq 1 40); do docker info >/dev/null 2>&1 && break; sleep 1; done
docker info 2>/dev/null | grep -E "Server Version|Storage Driver|Cgroup" || { echo FAILED; tail -12 /var/log/dockerd.log; exit 1; }
docker run --rm alpine /bin/sh -c "echo DOCKER-CONTAINER-OK; ip -o addr show | head -3; cat /etc/alpine-release"
