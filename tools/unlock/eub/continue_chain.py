#!/usr/bin/env python3
"""Continue the interrupted bl2 packet and serve the rest of the chain.

Protocol (learned empirically):
  - device: 'eub:req:<socid>:<name>' ... then a 'C' readiness byte
  - host:  wait for the 'C', then send the file's DNW packet as ONE write
  - a write started before 'C' gets only its first 512 bytes buffered;
    the device then sends 'C' and waits for the remaining bytes as a
    single continuation write (recovered epbl this way at 14:08)
"""

import re
import sys
import time

sys.path.insert(0, "houston")

import usb.core
import usb.util

from modules.eub import load_file, write_header, calculate_checksum
from modules.usb_helper import read_bytes

from eub_chain import CHAIN, files_for, report as report_serve_root, resolve_serve_root

REQ_RE = re.compile(rb"eub:req:[0-9a-f]+:([a-z0-9_.]+)")

# Same single source of truth as eub_session5.py (eub_chain.py). These two
# tools used to disagree about the chain root; a serve transcript must identify
# one build.
SERVE_ROOT = resolve_serve_root()
FILES = files_for(SERVE_ROOT)


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


def dnw_packet(name):
    file = load_file(FILES[name])
    size = len(file)
    write_header(file, size)
    calculate_checksum(file)
    return bytes(file)


def wait_for_C(dev, timeout_s=10):
    """Read until the device's 'C' readiness byte arrives."""
    deadline = time.time() + timeout_s
    buf = b""
    while time.time() < deadline:
        chunk = read_bytes(dev)
        if chunk:
            buf += chunk
            if b"C" in chunk:
                if buf != b"C":
                    log(f"  <- {buf!r}")
                return True
    if buf:
        log(f"  <- {buf!r}")
    return False


def send_full(dev, name):
    pkt = dnw_packet(name)
    ret = dev.write(2, pkt, timeout=15000)
    log(f"    -> sent {name} ({len(pkt)} bytes): {ret} {'OK' if ret == len(pkt) else 'SHORT'}")
    return ret == len(pkt)


def send_rest(dev, name, already):
    pkt = dnw_packet(name)
    rest = pkt[already:]
    ret = dev.write(2, rest, timeout=15000)
    log(f"    -> sent {name} continuation ({len(rest)} of {len(pkt)} bytes): {ret} {'OK' if ret == len(rest) else 'SHORT'}")
    return ret == len(rest)


def main():
    dev = usb.core.find(idVendor=0x04e8, idProduct=0x1100)
    if dev is None:
        log("device gone")
        return
    claim(dev)
    log(f"device: bus {dev.bus} addr {dev.address}")
    report_serve_root(SERVE_ROOT, stream=log)

    # bl2 already had its first 512 bytes accepted; device sent 'C' and waits
    log("sending bl2 continuation (first 512 bytes were already accepted)")
    try:
        if not send_rest(dev, "bl2", 512):
            log("bl2 continuation incomplete — stop")
            return
    except usb.core.USBError as e:
        log(f"bl2 continuation failed: {e} — stop")
        return
    served = set(["epbl", "bl2"])

    deadline = time.time() + 420
    while time.time() < deadline:
        if all(n in served for n in CHAIN):
            log("full chain served")
            break
        chunk = read_bytes(dev)
        if chunk:
            log(f"  <- {chunk!r}")
            reqs = [m.group(1).decode().split(".")[0] for m in REQ_RE.finditer(chunk)]
            for name in reqs:
                if name in FILES and name not in served:
                    # protocol: wait for the 'C' readiness byte before writing
                    if b"C" in chunk:
                        try:
                            send_full(dev, name)
                            served.add(name)
                        except usb.core.USBError as e:
                            log(f"send {name} failed: {e}")
                    else:
                        log(f"    request for {name}: waiting for 'C' readiness")
                        if wait_for_C(dev):
                            try:
                                send_full(dev, name)
                                served.add(name)
                            except usb.core.USBError as e:
                                log(f"send {name} failed: {e}")
                        else:
                            log(f"    no 'C' for {name} — trying anyway")
                            try:
                                send_full(dev, name)
                                served.add(name)
                            except usb.core.USBError as e:
                                log(f"send {name} failed: {e}")
                else:
                    log(f"    (skip: {name})")
    log(f"served: {sorted(served)}")

    log("watching for download-mode state (180s)")
    seen = set()
    deadline = time.time() + 180
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
            m = REQ_RE.search(chunk)
            if m:
                name = m.group(1).decode().split(".")[0]
                if name in FILES and name not in served and (b"C" in chunk or wait_for_C(dev, 5)):
                    try:
                        send_full(dev, name)
                        served.add(name)
                    except usb.core.USBError as e:
                        log(f"late send {name} failed: {e}")
        time.sleep(1)
    log("watch done — check lsusb for the download-mode device")


if __name__ == "__main__":
    main()
