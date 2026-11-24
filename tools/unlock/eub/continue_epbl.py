#!/usr/bin/env python3
"""Continue the interrupted epbl DNW packet and serve the rest of the chain.

The device accepted the first 512 bytes of the epbl DNW packet (the
single-write protocol was broken by a chunked send). Send the remaining
bytes as ONE single write, then serve any further chain requests.
"""

import re
import sys
import time

sys.path.insert(0, "houston")

import usb.core
import usb.util

from modules.eub import load_file, write_header, calculate_checksum
from modules.usb_helper import read_bytes

REQ_RE = re.compile(rb"eub:req:[0-9a-f]+:([a-z0-9_.]+)")
FILES = {
    "bl1": "output/sboot/bl1.bin",
    "epbl": "output/sboot/epbl.bin",
    "bl2": "output/sboot/bl2.bin",
    "bootload": "output/sboot/bootload.bin",
    "el3_mon": "output/sboot/el3_mon.bin",
    "ldfw": "output/ldfw/ldfw.bin",
    "tzsw": "output/tzsw/tzsw.bin",
}
CHAIN = ["epbl", "bl2", "bootload", "el3_mon", "ldfw", "tzsw"]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def claim(dev):
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
    usb.util.claim_interface(dev, 0)
    try:
        dev.ctrl_transfer(0x21, 0x20, 0, 0, bytes([0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08]), timeout=2000)
        dev.ctrl_transfer(0x21, 0x22, 0x0003, 0, None, timeout=2000)
        log("CDC setup OK")
    except usb.core.USBError as e:
        log(f"CDC setup skipped ({e})")


def dnw_send(dev, name):
    path = FILES[name]
    file = load_file(path)
    size = len(file)
    write_header(file, size)
    calculate_checksum(file)
    ret = dev.write(2, bytes(file), timeout=8000)
    log(f"    -> sent {name} ({size} bytes): {ret} {'OK' if ret == size else 'SHORT'}")


def main():
    dev = usb.core.find(idVendor=0x04e8, idProduct=0x1100)
    if dev is None:
        log("device gone")
        return
    claim(dev)
    log(f"device: bus {dev.bus} addr {dev.address}")

    file = load_file(FILES["epbl"])
    size = len(file)
    write_header(file, size)
    calculate_checksum(file)
    continuation = bytes(file[512:])
    log(f"sending epbl continuation: {len(continuation)} of {size} bytes (single write)")
    try:
        ret = dev.write(2, continuation, timeout=8000)
        log(f"continuation write returned {ret} of {len(continuation)}")
    except usb.core.USBError as e:
        log(f"continuation write FAILED: {e}")

    served = set(["epbl"])
    deadline = time.time() + 300
    while time.time() < deadline:
        if all(n in served for n in CHAIN):
            log("full chain served")
            break
        chunk = read_bytes(dev)
        if chunk:
            log(f"  <- {chunk!r}")
            for m in REQ_RE.finditer(chunk):
                name = m.group(1).decode().split(".")[0]
                if name in FILES and name not in served:
                    try:
                        dnw_send(dev, name)
                        served.add(name)
                    except usb.core.USBError as e:
                        log(f"send {name} failed: {e}")
                else:
                    log(f"    (skip: {name})")
        time.sleep(0.2)
    log(f"served: {sorted(served)}")

    log("watching for download-mode state (120s)")
    seen = set()
    deadline = time.time() + 120
    while time.time() < deadline:
        for pid in (0x685D, 0x1234, 0x1100):
            try:
                d = usb.core.find(idVendor=0x04e8, idProduct=pid)
            except Exception:
                d = None
            if d is not None:
                key = (d.bus, d.address, pid)
                if key not in seen:
                    seen.add(key)
                    log(f"    USB device present: 04e8:{pid:04x} bus {d.bus} addr {d.address}")
                    if pid == 0x685D:
                        log("download mode (Odin PID 04e8:685d) is up — session complete")
                        return
        chunk = read_bytes(dev)
        if chunk:
            log(f"  <- {chunk!r}")
        time.sleep(1)
    log("watch done — check lsusb for the download-mode device")


if __name__ == "__main__":
    main()
