#!/usr/bin/env python3
"""Read or set the bootloader's boot-mode word in the param partition.

Why this exists
---------------
This bootloader has no Android BCB parser ("boot-recovery" does not appear
anywhere in the 4 MB sboot), so recovery is *only* reachable through its own env
store and the boot-mode selector: `platform_init` reads param int 0 and, when it
is 4 or 5, sets `sys_bootm |= 0x80000` and loads the recovery partition. The
v28 candidate also redirects the ordinary value 0 to that same recovery block
without changing the stored word.

The env structure is serialised by `save_env_file` (bootload 0x42528):
0x200 bytes of header, 0x40 int slots, then 0x1e string slots of 0x800 bytes.
On the param partition it starts at 0x700000, so:

    param[0]        = partition offset 0x700200   (u32, boot mode)
    param str 0x47  = partition offset 0x703b00   ("BL:Recovery Mode Set by key")

Stored values: 4 = recovery request, 0 = default/system mode. On the v28 BL,
the default/system mode is forced to recovery, so setting 0 is not an Android
boot escape.

Captured logs show the keypad scanner returning 0x101 and dispatching recovery;
later analysis found the PMIC power-on key state may be latched across warm
reboots. Do not treat those logs as proof of what a keyless cold boot reports.

usage: param_bootmode.py get
       param_bootmode.py set {0|4}
Set requires a device booted to TWRP (adb root shell, block device writable).
"""
import subprocess
import sys

PART = "/dev/block/by-name/param"
BASE = 0x700000
MODE_OFF = BASE + 0x200
MAGIC = bytes.fromhex("0300feca")


def adb(*args, serial=None, binary=False):
    cmd = ["adb"] + (["-s", serial] if serial else []) + list(args)
    return subprocess.run(cmd, check=True, capture_output=True, text=not binary).stdout


def device():
    out = adb("devices")
    for line in out.splitlines()[1:]:
        if line.strip() and "\t" in line:
            return line.split("\t")[0].strip()
    raise SystemExit("error: no adb device")


def read_head(serial, length=0x40):
    return adb("exec-out", f"dd if={PART} bs=512 skip={BASE // 512} count=1 2>/dev/null",
               serial=serial, binary=True)[:length]


def main(argv):
    if not argv or argv[0] not in ("get", "set"):
        print(__doc__)
        return 2
    serial = device()
    head = read_head(serial)
    if head[:4] != MAGIC:
        raise SystemExit(f"error: param env magic {head[:4].hex()} != {MAGIC.hex()} "
                         f"at {BASE:#x}; refusing to touch it")
    base = BASE
    mode = int.from_bytes(adb("exec-out",
                              f"dd if={PART} bs=1 skip={base + 0x200} count=4 2>/dev/null",
                              serial=serial, binary=True)[:4], "little")
    if argv[0] == "get":
        label = ("recovery request" if mode in (4, 5) else
                 "default/system mode (v28 candidate redirects to recovery)" if mode == 0 else
                 "special mode")
        print(f"device {serial}: param[0] = {mode} ({label})")
        return 0
    if len(argv) != 2 or argv[1] not in ("0", "4"):
        raise SystemExit("usage: param_bootmode.py set {0|4}")
    want = int(argv[1])
    hexbyte = f"{want:02x}"
    adb("shell", f"printf '\\x{hexbyte}\\x00\\x00\\x00' | "
                 f"dd of={PART} bs=1 seek={base + 0x200} conv=notrunc 2>&1; sync",
        serial=serial)
    got = int.from_bytes(adb("exec-out",
                             f"dd if={PART} bs=1 skip={base + 0x200} count=4 2>/dev/null",
                             serial=serial, binary=True)[:4], "little")
    if got != want:
        raise SystemExit(f"error: write did not take (read back {got})")
    label = ("recovery request" if got == 4 else
             "default/system mode (v28 candidate redirects to recovery)")
    print(f"device {serial}: param[0] {mode} -> {got} ({label})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
