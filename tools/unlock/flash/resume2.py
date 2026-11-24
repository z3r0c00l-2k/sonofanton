#!/usr/bin/env python3
"""Resume chain service on the current post-payload device state.

Fixes vs the interrupted attempts:
  - served starts EMPTY (this session has served nothing yet)
  - detects a stale handle (houston's read_bytes swallows ENODEV): when
    reads stay empty, compare our handle's (bus, addr) with a fresh find;
    re-find + re-claim + CDC when the device re-enumerated
"""

import re
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
CHAIN = ["epbl", "bl2", "bootload", "el3_mon", "ldfw", "tzsw"]

REQ_RE = re.compile(rb"eub:req:[0-9a-f]+:([a-z0-9_.]+)")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


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


def find_and_claim(timeout_s=30):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for pid in (0x1234, 0x1100):
            try:
                dev = usb.core.find(idVendor=0x04e8, idProduct=pid)
            except Exception:
                dev = None
            if dev is not None:
                try:
                    dev.get_active_configuration()
                    claim(dev)
                    return dev
                except usb.core.USBError as e:
                    log(f"claim failed on addr {dev.address}: {e} — retrying")
                except Exception:
                    pass
        time.sleep(0.5)
    return None


def dnw_send(dev, name):
    path = FILES[name]
    file = load_file(path)
    size = len(file)
    write_header(file, size)
    calculate_checksum(file)
    ret = dev.write(2, file, timeout=5000)
    log(f"    -> sent {name} ({path}, {size} bytes): {'OK' if ret == size else 'SHORT WRITE'}")


def stale_handle(dev):
    """True if our handle's device is no longer the live one."""
    try:
        fresh = usb.core.find(idVendor=0x04e8, idProduct=dev.idProduct)
    except Exception:
        return False
    return fresh is not None and (fresh.bus, fresh.address) != (dev.bus, dev.address)


def main():
    log("claiming the current device state and resuming chain service")
    dev = find_and_claim(timeout_s=30)
    if dev is None:
        log("no device found")
        return
    log(f"device: {dev.idVendor:04x}:{dev.idProduct:04x} (bus {dev.bus} addr {dev.address})")

    served = set()
    deadline = time.time() + 600
    last_progress = time.time()
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
                        last_progress = time.time()
                    except usb.core.USBError as e:
                        log(f"send {name} failed: {e}")
                else:
                    log(f"    (skip: {name}, served={name in served})")
            continue
        # no data: detect a re-enumerated (stale) handle every few seconds
        if time.time() - last_progress > 5:
            if stale_handle(dev):
                log("device re-enumerated — re-finding")
                try:
                    usb.util.release_interface(dev, 0)
                except Exception:
                    pass
                try:
                    usb.util.dispose_resources(dev)
                except Exception:
                    pass
                dev = find_and_claim(timeout_s=15)
                if dev is None:
                    log("device gone during re-find")
                    return
                log(f"re-claimed: bus {dev.bus} addr {dev.address}")
                last_progress = time.time()
                continue
            if time.time() - last_progress > 45:
                log(f"45s quiet; served so far: {sorted(served)}")
                last_progress = time.time()
    log(f"served: {sorted(served)}")

    log("watching for chain boot / download-mode state (120s)")
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
    log("watch done — check lsusb for the download-mode device for the download-mode device")


if __name__ == "__main__":
    main()
