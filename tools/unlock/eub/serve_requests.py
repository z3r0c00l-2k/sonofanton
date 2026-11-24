#!/usr/bin/env python3
"""Serve the pending file requests of an already-exploited EUB device.

Run after eub_session.py's stage 3 (the device is exploited, its USB stack
re-initialized in place, and it is waiting for file requests). The
re-initialized stack answers standard requests but NOT the CDC class
requests, so we claim without houston's SET_LINE_CODING/SET_CONTROL_LINE_STATE.
"""

import sys
import time

sys.path.insert(0, "houston")

import usb.core
import usb.util

from modules.eub import load_file, write_header, calculate_checksum
from modules.usb_helper import read_bytes

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


def find_and_claim(timeout_s=30):
    dev = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for pid in (0x1234, 0x1100):
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
        raise SystemExit("device not found")
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
    usb.util.claim_interface(dev, 0)  # no CDC setup: the re-init stack ignores it
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


def read_request(dev, wait_s=2.0):
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
    log("claiming the exploited device (no CDC setup)")
    dev = find_and_claim()
    log(f"device: {dev.idVendor:04x}:{dev.idProduct:04x} (bus {dev.bus} addr {dev.address})")

    log("serving file requests")
    served = []
    quiet_deadline = time.time() + 20
    overall_deadline = time.time() + 600
    while time.time() < overall_deadline:
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
            quiet_deadline = time.time() + 20
            continue
        if time.time() > quiet_deadline:
            next_name = next(n for n in FILES if n not in served)
            log(f"    no request pending; pushing next in order: {next_name}")
            dnw_send(dev, FILES[next_name])
            served.append(next_name)
            quiet_deadline = time.time() + 20
    log(f"served: {served}")

    log("watching for chain boot / download-mode state change (60s)")
    seen = set()
    deadline = time.time() + 60
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
    log("watch done — check lsusb for the download-mode device for the download-mode device")


if __name__ == "__main__":
    main()
