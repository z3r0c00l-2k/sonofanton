#!/usr/bin/env python3
"""Clean-room IGYI3 (G990EXXSIGYI3) patch set.

Nothing here is copied from patch_9840.py / patch_9840_igyi3.py. Every patch is
derived from the stock IGYI3 bootload (sboot sha256 3fec2671...), asserts the
exact instruction it expects, and records the word it writes.

usage: EUB_CLEAN_PATCHES=p1[,p2...] python3 patch_igyi3_clean.py <bootload.bin>
       (default: every patch defined below)
"""
import os
import struct
import sys

PATCHED = []


def word(d, off):
    return struct.unpack_from("<I", d, off)[0]


def write_word(d, off, expect, new, name, note):
    got = word(d, off)
    if got != expect:
        raise ValueError(f"{name}: {off:#x} holds {got:#08x}, expected {expect:#08x}")
    struct.pack_into("<I", d, off, new)
    PATCHED.append((name, off, expect, new, note))
    print(f"{name}: {off:#x} {expect:08x} -> {new:08x}   {note}")


# ---------------------------------------------------------------------------
# p1 — accept a failed Samsung image signature in the Odin flash path
#
# The bootloader verifies the Samsung SignerVer03 trailer of every image with
# check_signature (0x66538). Under the fused custom key that verdict is always
# "invalid", so the two places that turn the verdict into a refusal must be
# neutralised. Both are in the Odin write path; neither runs at boot.
#
# (a) PIT-specific gate, 0x66c88 (called from pit_check_integrity 0x5dd30):
#
#   0x66cb0  mov x0,"PIT"
#   0x66cb4  bl 0x66538              check_signature("PIT", image, size)
#   0x66cb8  tbnz w0,#0x1f, 0x66d90  fail -> "SECURE CHECK FAIL : (PIT)" + halt
#   0x66cc8  bl 0x64a70             CheckPitRP(trailer)
#   0x66ccc  tbnz w0,#0x1f, 0x66de8
#   0x66cf8  strncmp(trailer+0x98,"mrk",3)  -> "mrk" returns success
#
# This is the gate that produced the reported failure. With it ignored the
# continuation is safe: the shipped PIT's rollback field at trailer+0x88 is
# "018", so CheckPitRP (which only refuses 0) passes, and its signer field at
# trailer+0x98 is "mrk", which returns success before the factory-binary check.
#
# (b) generic per-partition gate, _pit_flash_binary 0x5e370:
#
#   0x5e59c  bl 0x66538               check_signature(name, image, size)
#   0x5e5a0  tbnz w0,#0x1f, 0x5e930   fail -> 0x5e930
#   0x5e5a4  bl 0x660e0               signed path continues here
#
# 0x5e930 whitelists only BOOT / RECOVERY / DTBO / VBMETA / VBMETA_SAMSUNG /
# VBMETA_SYSTEM / VENDOR_BOOT / INIT_BOOT. Everything else (SUPER, modem, ...)
# is refused with the same message, so this site must carry the same decision.
#
# check_signature is a pure verifier (table at 0x1532e8, table hit -> 0, missing
# trailer or bad signature -> -1, logs "check_signature (<name>) valid|invalid.")
# and has no side effects the callers depend on.
# ---------------------------------------------------------------------------
def p1_flash_signature(d):
    write_word(d, 0x66CB8, 0x37F806C0, 0xD503201F, "p1_flash_signature/pit",
               "PIT gate: tbnz w0,#0x1f,0x66d90 -> nop")
    write_word(d, 0x5E5A0, 0x37F81C80, 0xD503201F, "p1_flash_signature/generic",
               "per-partition: tbnz w0,#0x1f,0x5e930 -> nop")


# ---------------------------------------------------------------------------
# p2 — do not let the rollback counters refuse an older image
#
# Every IGYI3 image carries rollback 018 in its SignerVer03 trailer (verified in
# the stock AP: trailer+0x88 reads "018" for boot.img, vendor_boot.img and the
# PIT). The device fuse reports bootloader_rp = 0x17 (23), so each of these
# functions takes its "image < device" branch, prints ...REV. CHECK FAIL, calls
# 0x94f88 and returns -1. During a flash that stops Odin with no further output.
#
#   0x63640  CheckSwRev      SW-versioned images (BOOTLOADER/LDFW/KEYSTORAGE/TZSW/BLCMD)
#   0x648e8  CheckKernelRP   kernel images (BOOT/RECOVERY/DTBO/VENDOR_BOOT/INIT_BOOT/VBMETA)
#   0x643f8  CheckSystemRP   filesystem images (CACHE/HIDDEN/USERDATA/OMR/EFS/...)
#   0x64a70  CheckPitRP      PIT (only refuses rollback 0)
#
# All four return 0 on the pass path and -1 after the halt on the fail path, so
# the stub is the pass value at the true prologue. Returning early also skips
# CheckKernelRP's device < image branch, which would otherwise write the new
# rollback value; nothing here needs that write.
# ---------------------------------------------------------------------------
REV_CHECKS = {
    0x63640: ("CheckSwRev", 0xA9BC7BFD),
    0x648E8: ("CheckKernelRP", 0xA9BC7BFD),
    0x643F8: ("CheckSystemRP", 0xA9BD7BFD),
    0x64A70: ("CheckPitRP", 0xA9BE7BFD),
}


def p2_rollback(d):
    for off, (name, anchor) in REV_CHECKS.items():
        got = word(d, off)
        if got != anchor:
            raise ValueError(f"{name}: {off:#x} holds {got:08x}, expected {anchor:08x}")
        struct.pack_into("<II", d, off, 0xD2800000, 0xD65F03C0)  # mov x0,#0 ; ret
        PATCHED.append((f"p2_rollback/{name}", off, anchor, 0xD2800000, "mov x0,#0; ret"))
        print(f"p2_rollback/{name}: {off:#x} {anchor:08x} -> 0xd2800000 d65f03c0")


# ---------------------------------------------------------------------------
# p3 — load the on-device PIT table even though its Samsung signature fails
#
# This is the cause of "Could not do Narmal Boot (Invalid PPI)" and of the
# flash stopping at the first image.
#
# load_boot_images (0xf7f0) does:
#   0xfa74  x0 = "BOOT"
#   0xfa7c  bl 0x5dfe0            find_partition()  -> scans the table at 0xbe96b8
#   0xfa84  cbnz x19, 0xf8d4      NULL -> 0xfa88 "Invalid PPI", 0xfaa8 stop
#
# The table is filled only by the stored-PIT loader 0x5e178, called from early
# init (0x27cc) and after a PIT write (0x8fda0):
#
#   0x5e178  read the PIT from storage (0x5ee38)
#   0x5e220  bl 0x66538           check_signature("PIT", pit, size)
#   0x5e224  tbnz w0,#0x1f,0x5e354  <0 -> free and return -1, table NOT filled
#   0x5e228  ... copy entries into 0xbe96b8/0xbe96d4
#
# Under the fused custom key the PIT's SignerVer03 verdict is always "invalid",
# so the table stays empty: find_partition("BOOT") returns NULL and the boot
# aborts with Invalid PPI. The same table is what _pit_flash_binary looks up
# (0xbe96f8 / 0xbe96d4), so a download also cannot map its partition and the
# protocol simply stops.
#
# Patch: do not abort the table load on the signature verdict. The PIT is read
# from the device's own PIT partition; the verdict only asserted Samsung
# authorship, which cannot apply to a device keyed by us.
# ---------------------------------------------------------------------------
def p3_pit_table(d):
    write_word(d, 0x5E224, 0x37F80980, 0xD503201F, "p3_pit_table",
               "stored-PIT loader: tbnz w0,#0x1f,0x5e354 -> nop (fill table)")


# ---------------------------------------------------------------------------
# p4 — report the device as OEM-unlocked
#
# The SUPER refusal is the OEM-lock branch in _pit_flash_binary:
#
#   0x...    bl 0x621c0            exynos_read_is_device_unlocked(0)
#            cbz w0, <OEMLOCK>     locked -> FUN_00030428 (knox guard) -> "OEMLOCK"
#                                  -> "Custom Binary(%s) Blocked By OEM Lock"
#
# A persistent stock unlock is not reachable on this device: the state is
# RPMB-backed and the bootloader blocks the RPMB keys on every boot
# ("RPMB: key blocking: success"), so the stock unlock executor can never make
# the state stick. What is reachable is the state itself: every consumer in the
# bootloader asks one of two readers, and both currently answer "locked".
#
# 0x621c0 exynos_read_is_device_unlocked(mode 0):
#   0x621e0  mov w19,#0                 fail-closed default = locked
#   0x621e4  ldr w20,[0x7bb368]         state source ready?
#   0x621ec  b.eq 0x622a8               yes -> 0x1f7f0 cached state
#   0x622b8  sub w19,w20,w19            1 - state  (state 0 = unlocked)
#   returns w19
#
# 0x93d40 the image-load ops reader ("%s : RPMB is not initialized yet"):
#   writes 0 to the caller's out byte and returns success, i.e. "locked".
#   Its two callers in the load-address decider pick the fixed load addresses
#   (0x94000000 boot / 0x98000000 vendor_boot) only when that byte is 1.
#
# Both are patched to the unlocked value. The cached-state reader 0x1f7f0 is
# deliberately left stock: the state-switch executor reads that one, and with
# the real (locked) state plus config bit 3 clear it takes its "no change"
# branch — patching it is what caused the relock loop in earlier work.
# ---------------------------------------------------------------------------
def p4_unlock_state(d):
    write_word(d, 0x621E0, 0x52800013, 0x52800033, "p4_unlock/mode0_default",
               "mov w19,#0 -> mov w19,#1")
    write_word(d, 0x622B8, 0x4B130293, 0x52800033, "p4_unlock/mode0_computed",
               "sub w19,w20,w19 -> mov w19,#1")
    got = d[0x93D40:0x93D40 + 4]
    if got != bytes.fromhex("fd7bbda9"):
        raise ValueError(f"avbops reader: bad prologue {got.hex()}")
    for i, w in enumerate((0x52800022, 0x39000022, 0x52800000, 0xD65F03C0)):
        struct.pack_into("<I", d, 0x93D40 + 4 * i, w)
    PATCHED.append(("p4_unlock/avbops_reader", 0x93D40, 0xA9BD7BFD, 0x52800022,
                    "mov w2,#1; strb w2,[x1]; mov w0,#0; ret"))
    print("p4_unlock/avbops_reader: 0x93d40 -> *out=1, w0=0 (unlocked)")


# ---------------------------------------------------------------------------
# p5 — do not let the bootloader revoke RPMB access
#
# The OEM unlock state is an RPMB record (magic "BOOT", read through 0x1ecd8 at
# early init into [0x7baf3c]). The stock unlock executor writes it with
# rpmb_set_lock; it ran 20 times without the state changing because access was
# revoked first, in load_boot_images, before every boot:
#
#   0xfd00  bl 0xa070        SMC 0xB2000105   "disable handler execution"
#   0xfd14  bl 0x1dc60       TEEGRIS 0xC2001018 w1=2   "RPMB: key blocking"
#   0xfd2c  bl 0x1e918       TEEGRIS 0xC2001018 w1=4   "RPMB: hmac blocking"
#   0xfe24  bl 0x1e918       same, on the success path
#
# Each call's w0 selects the following print: 0 -> "... blocking: success".
# These four instructions are replaced by mov w0,#0, so the revocation is never
# requested and the flow reports the same "success" lines it prints when the
# call genuinely succeeded. Nothing else in the boot chain changes.
#
# Whether this restores access depends on EL3 (el3_mon.bin is encrypted): if the
# block is granted per request, RPMB becomes usable again and the unlock record
# can be written; if it was made one-way in the RPMB, this changes nothing.
# ---------------------------------------------------------------------------
def p5_keep_rpmb(d):
    for off, note in ((0xFD00, "SMC 0xB2000105 (disable handler execution)"),
                      (0xFD14, "TEEGRIS RPMB key blocking"),
                      (0xFD2C, "TEEGRIS RPMB hmac blocking"),
                      (0xFE24, "TEEGRIS RPMB hmac blocking (success path)")):
        got = word(d, off)
        if (got & 0xFC000000) != 0x94000000:
            raise ValueError(f"p5: {off:#x} is not a bl ({got:08x})")
        struct.pack_into("<I", d, off, 0x52800000)  # mov w0,#0
        PATCHED.append((f"p5_rpmb/{off:#x}", off, got, 0x52800000, note))
        print(f"p5_rpmb/{off:#x}: {got:08x} -> 0x52800000   {note}")


ALL = {
    "p1": p1_flash_signature,
    "p2": p2_rollback,
    "p3": p3_pit_table,
    "p4": p4_unlock_state,
    "p5": p5_keep_rpmb,
}


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_igyi3_clean.py <bootload.bin>")
    want = os.environ.get("EUB_CLEAN_PATCHES", "p1").split(",")
    bad = [w for w in want if w not in ALL]
    if bad:
        raise SystemExit(f"unknown patch id(s) {bad}; known: {sorted(ALL)}")
    with open(sys.argv[1], "rb") as f:
        data = bytearray(f.read())
    for pid in want:
        ALL[pid](data)
    with open(sys.argv[1], "wb") as f:
        f.write(data)
    print(f"wrote {sys.argv[1]}  ({len(PATCHED)} word(s) changed, patches={want})")


if __name__ == "__main__":
    main()
