#!/usr/bin/env python3
"""EUB session driver v2 for the S21 FE (S5E9840) unlock flow.

Findings baked in from the failed sessions:

  1. houston's send_payload leaves the "bl1" upload exactly 512 bytes
     incomplete on purpose (+512 declared size). The hijacked EP0
     XferComplete handler jumps into that not-yet-finished upload (our
     payload embedded at bl1+0x2000, exec 0x02024000).

  2. The custom_key payload's first action is a blocking receive of up to
     300 bytes from the host via the BootROM's USB receive fn — the host
     must immediately complete the upload by sending 512 bytes (padding;
     the BL1 inner header num_of_sector=24 delimits the real image).

  3. The payload then loads BL1 "normally" (header, checksum, key-ptr
     swap, verify, check — with OUR efuse patched into the payload at
     +0x130), resets the USB/DNW state, and continues into the BootROM's
     load path, which requests the remaining chain images on 0x81.

  4. All of this happens WITHOUT a USB bus re-enumeration (the stack
     re-initializes in place), so houston's post-exploit find_device
     (which also spins on its stale claim) never gets anywhere. We keep
     driving the SAME handle and only re-find if the controller actually
     re-enumerates.
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


def try_claim(dev, with_cdc):
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
    usb.util.claim_interface(dev, 0)
    if with_cdc and dev.idProduct == 0x1100:
        try:
            dev.ctrl_transfer(0x21, 0x20, 0, 0, bytes([0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08]), timeout=1000)
            dev.ctrl_transfer(0x21, 0x22, 0x0003, 0, None, timeout=1000)
        except usb.core.USBError as e:
            log(f"    CDC setup skipped ({e})")


def find_and_claim(timeout_s=60, with_cdc=True, expect_pids=(0x1234, 0x1100)):
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
    try_claim(dev, with_cdc)
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


def complete_upload(dev):
    """Send the 512 padding bytes that finish the deliberately-incomplete
    bl1 upload; the payload's blocking receive(300) picks them up."""
    for size in (512, 300):
        try:
            ret = dev.write(2, b"\x00" * size, timeout=3000)
            log(f"    -> wrote {size} completion bytes: {ret} accepted")
            if ret == size:
                return True
        except usb.core.USBError as e:
            log(f"    -> {size} completion bytes failed: {e}")
    return False


def serve(dev, served, quiet_s=25, overall_s=600):
    quiet_deadline = time.time() + quiet_s
    overall_deadline = time.time() + overall_s
    while time.time() < overall_deadline:
        if len(served) >= len(FILES):
            log("all chain images served")
            return "done"
        try:
            req = read_request(dev, wait_s=2.0)
        except usb.core.USBError as e:
            log(f"USB error while reading: {e}")
            return "usb_error"
        if req:
            log(f"  <- {req!r}")
            name = next((n for n in FILES if n.encode() in req), None)
            if name is None:
                try:
                    parsed = req.decode()[18:-1]
                except Exception:
                    parsed = "?"
                log(f"    unrecognized request (houston parse: {parsed!r}) — stopping")
                return "unknown_request"
            if name in served:
                log(f"    duplicate request for {name} — stopping")
                return "duplicate"
            dnw_send(dev, FILES[name])
            served.append(name)
            quiet_deadline = time.time() + quiet_s
            continue
        if time.time() > quiet_deadline:
            next_name = next(n for n in FILES if n not in served)
            log(f"    no request pending; pushing next in order: {next_name}")
            try:
                dnw_send(dev, FILES[next_name])
            except usb.core.USBError as e:
                log(f"    push failed: {e}")
                return "usb_error"
            served.append(next_name)
            quiet_deadline = time.time() + quiet_s
    return "timeout"


def main():
    log("stage 1: waiting for EUB device (04e8:1100)")
    dev = find_and_claim(with_cdc=True)
    log(f"device: {dev.idVendor:04x}:{dev.idProduct:04x} (bus {dev.bus} addr {dev.address})")

    log("stage 2: exploit (payload = bl1 with our efuse + embedded custom_key)")
    send_payload(dev, FILES["bl1"])
    overwrite_iram(dev, False, SOC["rx_address"], SOC["usb_struct_offset"])
    log("exploit done (ACE) — payload is blocking in its receive(300)")

    log("stage 3: completing the upload (512 padding bytes on ep 0x2, same handle)")
    if not complete_upload(dev):
        log("could not complete the upload — device may need a fresh EUB entry; stopping")
        return
    log("upload completion accepted")

    log("stage 4: serving file requests (same handle; re-find only if re-enumerated)")
    served = []
    result = serve(dev, served)
    log(f"serve result: {result}; served: {served}")

    if result == "usb_error":
        log("device may have re-enumerated — re-finding")
        try:
            usb.util.release_interface(dev, 0)
        except Exception:
            pass
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass
        time.sleep(2)
        try:
            # fresh post-re-init states accept the CDC setup and only send
            # requests after DTR — try with CDC first, fall back without
            try:
                dev = find_and_claim(timeout_s=30, with_cdc=True)
            except SystemExit:
                dev = find_and_claim(timeout_s=10, with_cdc=False)
        except SystemExit:
            log("device gone after re-find — see lsusb")
            return
        served = []
        result = serve(dev, served)
        log(f"second serve result: {result}; served: {served}")

    log("stage 5: watching for chain boot / download-mode state (60s)")
    seen = set()
    deadline = time.time() + 60
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
        time.sleep(1)
    log("watch done — check lsusb for the download-mode device for the download-mode device")


if __name__ == "__main__":
    main()
