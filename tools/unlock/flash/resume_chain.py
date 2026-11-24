#!/usr/bin/env python3
"""Resume serving the chain requests of a booted patched-BL1 session.

Parses 'eub:req:<socid>:<name>' segments properly (acks and requests can
arrive in one read), serves each unserved chain image, then watches for
the download-mode state.
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

REQ_RE = re.compile(rb"eub:req:[0-9a-f]+:([a-z0-9_]+)")


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
    usb.util.claim_interface(dev, 0)
    try:
        dev.ctrl_transfer(0x21, 0x20, 0, 0, bytes([0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08]), timeout=2000)
        dev.ctrl_transfer(0x21, 0x22, 0x0003, 0, None, timeout=2000)
        log("CDC setup OK")
    except usb.core.USBError as e:
        log(f"CDC setup skipped ({e})")
    return dev


def dnw_send(dev, name):
    path = FILES[name]
    file = load_file(path)
    size = len(file)
    write_header(file, size)
    calculate_checksum(file)
    ret = dev.write(2, file, timeout=5000)
    log(f"    -> sent {name} ({path}, {size} bytes): {'OK' if ret == size else 'SHORT WRITE'}")


def main():
    log("claiming device and resuming chain service")
    dev = find_and_claim()
    log(f"device: {dev.idVendor:04x}:{dev.idProduct:04x} (bus {dev.bus} addr {dev.address})")

    served = set(["epbl"])  # already served in the interrupted session
    buf = b""
    deadline = time.time() + 420
    last_data = time.time()
    while time.time() < deadline:
        try:
            chunk = read_bytes(dev)
        except usb.core.USBError as e:
            log(f"USB error: {e}")
            return
        if chunk:
            buf += chunk
            last_data = time.time()
            # log non-request chatter (acks, status lines)
            for line in buf.split(b"\x00"):
                if line and b"eub:req:" not in line and line not in (b"", b"C"):
                    pass  # already visible via raw dumps below
            log(f"  <- {buf!r}")
            # serve every pending request (device may queue several)
            for name in [m.group(1).decode() for m in REQ_RE.finditer(buf)]:
                if name in FILES and name not in served:
                    dnw_send(dev, name)
                    served.add(name)
                elif name in served:
                    log(f"    (already served: {name})")
                else:
                    log(f"    (unknown request name: {name})")
            buf = b""
            if all(n in served for n in CHAIN):
                log("full chain served")
                break
        else:
            # drain anything the device still wants to say
            try:
                data = dev.read(0x81, 511, timeout=250)
                if len(data):
                    buf += bytes(data)
                    continue
            except usb.core.USBError:
                pass
            if time.time() - last_data > 30:
                log(f"30s quiet; served so far: {sorted(served)}")
                last_data = time.time()

    log(f"served: {sorted(served)}")

    log("watching for chain boot / download-mode state (90s)")
    seen = set()
    deadline = time.time() + 90
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
        try:
            chunk = read_bytes(dev)
            if chunk:
                log(f"  <- {chunk!r}")
        except usb.core.USBError:
            pass
        time.sleep(1)
    log("watch done — check lsusb for the download-mode device for the download-mode device")


if __name__ == "__main__":
    main()
