# Cheatsheet

Run Linux commands from `linux/` unless stated otherwise. Replace `<phone-ip>`
with the DHCP lease your router assigned.

## Device access

```bash
# SSH (key from your own provisioning, not from this repo)
ssh -i ~/.ssh/r9s-linux_ed25519 root@<phone-ip>

# Server control on the device
/system/bin/r9s-server status
/system/bin/r9s-server start
/system/bin/r9s-server stop
```

## Linux host

```bash
ip -br addr
cat /etc/resolv.conf
docker ps
docker logs --tail 50 <container>
tail -n 50 /var/log/dockerd.log
```

## Build

```bash
cd linux
tools/prepare-tree.sh
tools/build-recovery.sh server_vN
```

## Flash

Use Odin with the custom BL/recovery tar. Battery above the floor,
AP slot, recovery only, then **cold boot**.

## Verify before flashing

```bash
sha256sum -c out/SHA256SUMS
python3 tools/verify_kernel.py
python3 tools/check_cfi_jt.py
```

## Emergencies

| Symptom | First action |
|---|---|
| No display, no download mode | EUB test point; see [Recovery first](recovery-first.md) |
| Download mode works, recovery does not | reflash the recovery image or custom BL |
| Docker cannot create containers | check the cgroup state; see [Operations](linux/operations.md) |
| Container cannot write its data | fix ownership to the image runtime user |

## Do not

- Flash a stock Samsung BL.
- Take a One UI OTA.
- Commit `keys/`, `hmac.bin`, firmware, or signed images.
- Flash at a low charge.
- Warm-reboot after a flash; cold boot.
