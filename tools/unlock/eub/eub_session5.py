#!/usr/bin/env python3
"""EUB session driver v5 (definitive) for the S21 FE (S5E9840) permanent unlock.

Everything proven in the 2026-10-09 sessions, baked in:

  Exploit phase (one handle):
    1. find 04e8:1100, claim, CDC setup (DTR) - requests only flow after DTR
    2. houston send_payload(bl1) (+512 declared-size trick)
    3. overwrite_iram(exec 0x02024000) - timeout on final ctrl write expected
    4. IMMEDIATELY write 512 zero bytes to ep 0x2 on the SAME handle

  Re-enumeration (~1s later):
    5. detect stale handle via (bus, addr) compare with a fresh find
       (houston's read_bytes swallows ENODEV), re-find + claim + CDC FAST

  Chain service (per request, the 'C' protocol):
    6. request arrives on 0x81 as 'eub:req:e9840000:<name>' (acks and
       requests can share one read)
    7. WAIT for the 'C' readiness byte before writing (a write started
       before 'C' gets only its first 512 bytes buffered)
    8. send the file as ONE single full write (chunked writes break the
       DNW state machine)
    9. if a write returns SHORT (512 accepted), send the remaining bytes
       as one single continuation write (recovered epbl and bl2 this way)

  Chain order: epbl, bl2, bootload, el3_mon, ldfw, tzsw -> [USB Booting
  Done] -> device re-enumerates as 04e8:685d (Odin download mode).

THIS BUILD IS THE FUSE BUILD: bootload.bin carries the key-fusing payload
at check_signature (efuse value identical to the EUB payload's at +0x130).
When the chain's bootload runs during THIS session, it burns our key into
ROM secure-boot key slot 2 and switches the selector — irreversible.
Keep keys/ safe (backed up at keys_backup_20261009/).
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

from eub_chain import CHAIN, files_for, report as report_serve_root, resolve_serve_root

SOC = {"rx_address": 0x02024000, "usb_struct_offset": 0x0480}

# The served chain is resolved in ONE place (eub_chain.py): EUB_SERVE_ROOT
# overrides, the default is the proven download-mode-serving IGYI3-based
# patched chain (rb_count 23, our keys, EUB payload in bl1).
SERVE_ROOT = resolve_serve_root()
FILES = files_for(SERVE_ROOT)

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


def dnw_packet(name):
    file = load_file(FILES[name])
    size = len(file)
    write_header(file, size)
    calculate_checksum(file)
    return bytes(file)


def dnw_send(dev, name):
    """Single full write; SHORT (partial) writes are completed with one
    continuation write (proven recovery: first 512 accepted then 'C')."""
    pkt = dnw_packet(name)
    ret = dev.write(2, pkt, timeout=15000)
    if ret == len(pkt):
        log(f"    -> sent {name} ({len(pkt)} bytes): OK")
        return True
    log(f"    -> sent {name}: SHORT ({ret} of {len(pkt)}) — sending continuation")
    rest = pkt[ret:]
    ret2 = dev.write(2, rest, timeout=15000)
    if ret2 == len(rest):
        log(f"    -> {name} continuation ({len(rest)} bytes): OK — packet complete")
        return True
    log(f"    -> {name} continuation SHORT ({ret2} of {len(rest)}) — giving up on {name}")
    return False


def wait_for_C(dev, timeout_s=10):
    """Wait for the device's 'C' readiness byte after a request."""
    deadline = time.time() + timeout_s
    buf = b""
    while time.time() < deadline:
        chunk = read_bytes(dev)
        if chunk:
            buf += chunk
            if b"C" in chunk:
                if buf.strip(b"C"):
                    log(f"  <- {buf!r}")
                return True
    if buf:
        log(f"  <- {buf!r}")
    return False


def handle_requests(dev, chunk, served):
    """Serve any requests found in a read chunk. Returns list of served names."""
    newly = []
    for m in REQ_RE.finditer(chunk):
        name = m.group(1).decode().split(".")[0]
        if name not in FILES:
            log(f"    (unknown request name: {name})")
            continue
        if name == "bootload":
            log("    NOTE: bootload upload begins — serving itself writes no UFS, "
                "but a fuse-carrying bootload burns the OTP when the chain runs "
                "(check the build's fuse state before serving)")
        if name in served and name != "bl1":
            log(f"    device re-requests {name} — sending again (its state machine asked)")
        if b"C" in chunk:
            if dnw_send(dev, name):
                served.add(name)
                newly.append(name)
        else:
            log(f"    request for {name}: waiting for 'C' readiness byte")
            if wait_for_C(dev):
                if dnw_send(dev, name):
                    served.add(name)
                    newly.append(name)
            else:
                log(f"    no 'C' for {name} — trying the write anyway")
                if dnw_send(dev, name):
                    served.add(name)
                    newly.append(name)
    return newly


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
            try:
                handle_requests(dev, chunk, served)
            except usb.core.USBError as e:
                log(f"send failed: {e} — re-finding")
                drop(dev)
                dev = find_and_claim(timeout_s=30)
                if dev is None:
                    return dev, "gone"
            continue
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


def watch_download_mode(dev, seconds=300):
    seen = set()
    deadline = time.time() + seconds
    served = set(CHAIN)
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
                        log("download mode (Odin PID 04e8:685d) is up — "
                            "the fuse is burned and the patched chain is running")
                        log("NEXT: flash flash/BL_custom/BL_G990E_CUSTOM_KEY_UNLOCK.tar.md5 "
                            "via Odin in THIS download mode, then let the device reboot")
                        return True
        try:
            chunk = read_bytes(dev)
        except Exception:
            chunk = b""
        if chunk:
            log(f"  <- {chunk!r}")
            m = REQ_RE.search(chunk)
            if m:
                name = m.group(1).decode().split(".")[0]
                if name in FILES:
                    try:
                        dnw_send(dev, name)
                        served.add(name)
                    except usb.core.USBError as e:
                        log(f"late send {name} failed: {e}")
        time.sleep(1)
    return False


def complete_upload(dev):
    """Stage 3 with race recovery. The completion write must land on ep 0x2
    before the payload's USB re-init (the ~1s re-enumeration). Observed once
    (22:49 session): the device re-enumerated FIRST -> ENODEV. Recovery: the
    payload polls the device-side endpoint FIFO, so the completion can still
    land via the NEW enumeration — re-find, claim, and retry once. Harmless
    on a fresh BootROM (no ctrl handshake -> a bare bulk write is dropped)."""
    for size in (512, 300):
        try:
            ret = dev.write(2, b"\x00" * size, timeout=3000)
            log(f"    -> wrote {size} completion bytes: {ret} accepted")
            if ret == size:
                return dev, True
        except usb.core.USBError as e:
            log(f"    -> {size} completion bytes failed: {e}")
    log("    handle stale — re-finding for the completion retry")
    drop(dev)
    dev = find_and_claim(timeout_s=10)
    if dev is None:
        return None, False
    log(f"    re-found: bus {dev.bus} addr {dev.address}")
    for size in (512, 300):
        try:
            ret = dev.write(2, b"\x00" * size, timeout=3000)
            log(f"    -> wrote {size} completion bytes (fresh handle): {ret} accepted")
            if ret == size:
                return dev, True
        except usb.core.USBError as e:
            log(f"    -> {size} completion bytes failed (fresh handle): {e}")
    return dev, False


def main():
    log("stage 1: waiting for EUB device (04e8:1100)")
    report_serve_root(SERVE_ROOT, stream=log)
    dev = find_and_claim(timeout_s=90)
    if dev is None:
        log("device not found")
        return
    log(f"device: {dev.idVendor:04x}:{dev.idProduct:04x} (bus {dev.bus} addr {dev.address})")

    log("stage 2: exploit (IGYI3 chain, fuse build)")
    send_payload(dev, FILES["bl1"])
    overwrite_iram(dev, False, SOC["rx_address"], SOC["usb_struct_offset"])
    log("exploit done (ACE) — payload blocking in its receive(300)")

    log("stage 3: completing the upload (512 padding bytes on ep 0x2)")
    dev, wrote = complete_upload(dev)
    if dev is None:
        log("device gone — needs a fresh EUB entry")
        return
    if not wrote:
        log("could not complete the upload — needs a fresh EUB entry")
        return
    log("upload completion accepted — expect re-enumeration within ~1s")

    log("stage 3b: bounded request watch (30s) — bail early on a dead state")
    served = set()
    deadline = time.time() + 30
    alive = False
    while time.time() < deadline:
        if stale(dev):
            log("device re-enumerated — re-finding immediately")
            drop(dev)
            dev = find_and_claim(timeout_s=30)
            if dev is None:
                log("device gone — needs a fresh EUB entry")
                return
            log(f"re-claimed: bus {dev.bus} addr {dev.address}")
        chunk = read_bytes(dev)
        if chunk:
            log(f"  <- {chunk!r}")
            handle_requests(dev, chunk, served)
            alive = True
            break
        time.sleep(0.2)
    if not alive:
        log("no requests within 30s — the state is dead; needs a fresh EUB entry")
        return

    log("stage 4: serving chain requests ('C' protocol, single writes)")
    dev, result = serve_chain(dev, served)
    log(f"serve result: {result}; served: {sorted(served)}")
    if dev is None:
        return

    log("stage 5: watching for chain boot / download-mode state")
    watch_download_mode(dev, 300)


if __name__ == "__main__":
    main()
