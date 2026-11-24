#!/usr/bin/env python3
"""Capture the abl's boot-log dump.

The upload-mode gadget re-enumerates the phone as 04e8:685d and streams the boot
log immediately. Two traps, both learned the hard way:

  1. 04e8:685d is ALSO the ordinary download-mode console, which shares the PID
     and (on this abl) reports the product string "Gadget Serial". Latching it
     yields zero bytes, not an error.
  2. usb.ids renders the PID as "GT-I9100 Phone [Galaxy S II] (Download mode)",
     which is a database label, not anything the device said.

So this tool reports the *device-reported* product string and whether bytes
arrived unprompted. An upload dump streams by itself; the download console stays
silent until a command is sent. Upload mode also refuses outright under FMM lock
("FMM Lock is On, upload mode is not Allowed!").

The dump fires at (re-)enumeration with no DTR handshake (SET_LINE_CODING and
SET_CONTROL_LINE_STATE both STALL on this gadget; plain bulk reads return
ETIMEDOUT once the dump is gone). So: poll for every (re-)enumeration, claim
FAST, and read continuously."""

import sys
import time

sys.path.insert(0, "houston")
import usb.core
import usb.util

LOG_PATH = "flash/los_stage2/abl_boot_log.bin"  # in-repo; /tmp is cleared between sessions
DEADLINE_S = int(sys.argv[1]) if len(sys.argv) > 1 else 300

# Device-reported product strings. "UPLOAD" implies the upload gadget;
# "Gadget Serial" alone is the download-mode console.
UPLOAD_MARK = "UPLOAD"
DOWNLOAD_MARK = "GADGET SERIAL"


def product_of(dev):
    try:
        return usb.util.get_string(dev, dev.iProduct) or ""
    except Exception:
        return "(unavailable)"


def classify(product):
    p = product.upper()
    if UPLOAD_MARK in p:
        return "UPLOAD gadget (expected)"
    if DOWNLOAD_MARK in p:
        return "download-mode console (will stay silent)"
    return "unknown gadget"


def in_endpoints(dev):
    """IN endpoints of the active configuration, with the known-good fallback."""
    eps = []
    try:
        for iface in dev.get_active_configuration():
            for ep in iface:
                if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
                    eps.append(ep.bEndpointAddress)
    except Exception:
        pass
    return sorted(set(eps)) or [0x81, 0x82]


def main():
    log = b""
    seen = {}
    first_byte_at = None
    start = time.time()
    deadline = start + DEADLINE_S
    dev = None
    eps = [0x81, 0x82]

    while time.time() < deadline:
        try:
            d = usb.core.find(idVendor=0x04e8, idProduct=0x685d)
        except Exception:
            d = None
        if d is not None and (d.bus, d.address) not in seen:
            seen[(d.bus, d.address)] = True
            product = product_of(d)
            print(f"[{time.strftime('%H:%M:%S')}] enumerated: bus {d.bus} addr {d.address} "
                  f"product={product!r} -> {classify(product)}", flush=True)
            dev = None
            try:
                for ifnum in (0, 1):
                    try:
                        if d.is_kernel_driver_active(ifnum):
                            d.detach_kernel_driver(ifnum)
                        usb.util.claim_interface(d, ifnum)
                    except Exception:
                        pass
                dev = d
                eps = in_endpoints(d)
                print(f"    reading endpoints {[hex(e) for e in eps]}", flush=True)
            except Exception as e:
                print(f"    claim failed: {e}", flush=True)
        if dev is not None:
            got = False
            for ep in eps:
                try:
                    chunk = dev.read(ep, 512, timeout=100)
                    if chunk:
                        if first_byte_at is None:
                            first_byte_at = time.time()
                            print(f"    first bytes arrived {first_byte_at - start:.1f}s "
                                  f"after start (unprompted stream)", flush=True)
                        log += bytes(chunk)
                        sys.stdout.write(bytes(chunk).decode(errors="replace"))
                        sys.stdout.flush()
                        got = True
                except usb.core.USBError:
                    pass
                except Exception:
                    try:
                        usb.util.release_interface(dev, 0)
                    except Exception:
                        pass
                    try:
                        usb.util.dispose_resources(dev)
                    except Exception:
                        pass
                    dev = None
                    break
            if not got:
                time.sleep(0.02)
        else:
            time.sleep(0.05)

    with open(LOG_PATH, "wb") as fh:
        fh.write(log)

    # Release cleanly so we never leave the interface claimed for the next tool.
    if dev is not None:
        for ifnum in (0, 1):
            try:
                usb.util.release_interface(dev, ifnum)
            except Exception:
                pass
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass

    print(f"\n-- summary --")
    print(f"enumerations seen: {len(seen)}: "
          f"{sorted((b, a) for (b, a) in seen)}")
    print(f"captured {len(log)} bytes -> {LOG_PATH}")
    if log:
        print("RESULT: bytes streamed unprompted -> this is an abl log dump; read the "
              "[UFDT] / image-load lines above.")
    else:
        print("RESULT: NO bytes. Upload mode did not engage (or FMM refused it), or only "
              "the download-mode console was present - which stays silent until commanded. "
              "A retry with the trigger, not a tool failure.")
    return 0 if log else 1


if __name__ == "__main__":
    sys.exit(main())
