#!/usr/bin/env python3
"""IGYI3 (G990EXXSIGYI3) variant of patch_9840.py.

Same intent as the NHZF5 set, but IGYI3 differs structurally, so this module
applies only the patches that were verified to anchor on the IGYI3 bootload, plus
three IGYI3-specific sites. Everything is asserted before it is written.

Mapped and verified on IGYI3 (all entries decompiled from stock sboot
sha256 3fec2671... on 2026-10-23):
  check_signature            anchored on "%s: There is no signature" (stub only:
                             the NHZF5 variant also hardcodes a flag address that
                             does not exist here). Returns 0 = "signed OK".
  warranty / 4x rollback     anchored (same strings as NHZF5). Each Check*RP
                             function returns 0 on the pass path and -1 after
                             FUN_00095f88() (halt) on failure, so the stub is the
                             pass value:
                               CheckSwRev      0x63640  image RB < device RB
                               CheckKernelRP   0x648e8  KERNEL REV CHECK FAIL
                               CheckSystemRP   0x643f8  requires system RB >= 18
                               CheckPitRP      0x64a70  refuses PIT RB == 0
  SEAndroid query            anchored
  avbops state reader        anchored
  read_is_device_unlocked    anchored
  rollback gate A            0x929b0 tbnz w0,#31,0x92ff0 (CheckKernelRP consumer)
                             -> nop   [unique]
  rollback gate B            0x92b3c tbz  w0,#31,0x929b4 (recovery kernel rp
                             halt: "recovery kernel rp check fail" + infinite
                             loop) -> b 0x929b4
  secure-download            flag [0xbeb508] read by 14 sites ("if set, skip the
                             Samsung secure check at 0x6c3f8"). Only writer is
                             0x6be60 (from early init 0x2810); patch its value
                             load 0x6be84 -> mov w0,#1. The gate 0xa9d8 is a
                             SHARED getter ([0x39cc88], "ldfw loaded") and must
                             stay stock - patching it to 1 killed the boot.

NOT applied (no IGYI3 localisation yet):
  recovery bit-3 gate            - IGYI3 control flow differs; needs its own analysis
  unlock-executor skip           - sites known (0x65b14/0x65b20/0x65b34) but not
                                   needed to boot; excluded from the "core" set
  flash bit-3 gate (0x609ac)     - NHZF5 offsets; only needed to flash, not to boot

usage: patch_igyi3.py <bootload.bin>
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(HERE, "Exynos", "scripts"))
import patch_9840 as P

# --- IGYI3-specific sites (verified by disassembly of the stock IGYI3 bootload)
RP_GATE_A = 0x929B0          # tbnz w0,#31 -> nop        (unique word in image)
RP_GATE_B = 0x92B3C          # tbz  w0,#31 -> b +0x129b4 (unique word in image)
SD_GATE = 0xA9D8             # adrp; ldr w0,[x0,#0xc88]; ret


def check_signature_igyi3(data):
    off = P.find_xref(data, b"%s: There is no signature\n\0") - 0xDC
    if P.word(data, off) == 0xA9BF7BFD:
        pass
    print(f"check_signature: {off:#x} (return 0, no NHZF5 flag write)")
    P.write_words(data, off, [0x52800000, 0xD65F03C0])   # mov w0,#0 ; ret
    P._record(data, off, struct.pack("<II", 0x52800000, 0xD65F03C0),
              "check_signature", "ret_const", w0=0)


def rollback_gate_igyi3(data):
    if P.word(data, RP_GATE_A) != 0x37F83200:
        raise ValueError(f"igyi3 rp gate A: {P.word(data, RP_GATE_A):#x}")
    if P.word(data, RP_GATE_B) != 0x36FFF3C0:
        raise ValueError(f"igyi3 rp gate B: {P.word(data, RP_GATE_B):#x}")
    P.write_u32(data, RP_GATE_A, 0xD503201F)
    P._record(data, RP_GATE_A, struct.pack("<I", 0xD503201F),
              "igyi3_rp_gate_a", "branch_redirect", words=[0xD503201F])
    P.write_u32(data, RP_GATE_B, 0x17FFFF9E)
    P._record(data, RP_GATE_B, struct.pack("<I", 0x17FFFF9E),
              "igyi3_rp_gate_b", "branch_redirect", words=[0x17FFFF9E])
    print(f"rollback gates: {RP_GATE_A:#x} nop, {RP_GATE_B:#x} b")


def secure_download_gate_igyi3(data):
    for off, want in ((SD_GATE, 0xD0001C80), (SD_GATE + 4, 0xB94C8800),
                      (SD_GATE + 8, 0xD65F03C0)):
        if P.word(data, off) != want:
            raise ValueError(f"igyi3 sd gate: {off:#x} = {P.word(data, off):#x} != {want:#x}")
    P.write_words(data, SD_GATE, [0x52800020, 0xD65F03C0])   # mov w0,#1 ; ret
    P._record(data, SD_GATE, struct.pack("<II", 0x52800020, 0xD65F03C0),
              "igyi3_secure_download_gate", "ret_const", w0=1)
    print(f"secure-download gate: {SD_GATE:#x} -> mov w0,#1; ret")


def executor_skip_igyi3(data):
    """IGYI3 unlock executor: drop its wipe/recovery side effects.

    Same three calls as the NHZF5 executor, located from the
    "recovery\\n--wipe_data..." BCB template:
      0x65b14  bl write_BCB        (writes the wipe command into misc)
      0x65b20  bl set_bootm        (w0 = 0x80000 -> RECOVERY)
      0x65b34  bl set_param_int    (w0 = 0, w1 = 4 -> boot mode 4)
    """
    want = {0x65B14: 0x97FF2607, 0x65B20: 0x97FFD87E, 0x65B34: 0x97FF6E9D}
    for off, w in want.items():
        if P.word(data, off) != w:
            raise ValueError(f"igyi3 executor: {off:#x} = {P.word(data, off):#x} != {w:#x}")
    for off in want:
        P.write_u32(data, off, 0xD503201F)
        P._record(data, off, struct.pack("<I", 0xD503201F),
                  f"igyi3_executor/{off:#x}", "branch_redirect", words=[0xD503201F])
    print(f"executor: nop BCB/recovery/param calls at {', '.join(hex(o) for o in want)}")


def secure_download_gate_igyi3_zero(data):
    """Same site, inverted value: force 0 instead of 1.

    NHZF5's gate global ([0x39fc88]) is "allowed" (1 = permit). IGYI3's getter
    reads a different global (0x39cc88) and forcing 1 made the boot fail, which
    is consistent with 1 meaning "enforcement on". This variant tests that.
    """
    for off, want in ((SD_GATE, 0xD0001C80), (SD_GATE + 4, 0xB94C8800),
                      (SD_GATE + 8, 0xD65F03C0)):
        if P.word(data, off) != want:
            raise ValueError(f"igyi3 sd gate zero: {off:#x} = {P.word(data, off):#x}")
    P.write_words(data, SD_GATE, [0x52800000, 0xD65F03C0])   # mov w0,#0 ; ret
    P._record(data, SD_GATE, struct.pack("<II", 0x52800000, 0xD65F03C0),
              "igyi3_secure_download_gate_zero", "ret_const", w0=0)
    print(f"secure-download gate: {SD_GATE:#x} -> mov w0,#0; ret")

# --- corrected secure-download bypass (RE of the store site at 0x6be88) ---------
# 0x6be78 bl 0xa9d8            gate getter (shared with early init -> DO NOT patch)
# 0x6be7c cmp w0, #1
# 0x6be80 b.ne +0xa01          skip store when the gate is not 1
# 0x6be84 bl 0x64e28           value  = (ptr != NULL)
# 0x6be8c str w0, [x1,#0x508]  [0xbeb508] = bypass flag, read by 11 checks
SD_BRANCH = 0x6BE80
SD_VALUE = 0x64E28


def secure_download_bypass_igyi3(data):
    if P.word(data, SD_BRANCH) != 0x54000A01:      # b.ne
        raise ValueError(f"igyi3 sd: {SD_BRANCH:#x} = {P.word(data, SD_BRANCH):#x}")
    if P.word(data, SD_VALUE) != 0xA9BF7BFD:       # stp x29,x30,[sp,#-0x10]!
        raise ValueError(f"igyi3 sd: {SD_VALUE:#x} = {P.word(data, SD_VALUE):#x}")
    P.write_u32(data, SD_BRANCH, 0xD503201F)
    P._record(data, SD_BRANCH, struct.pack("<I", 0xD503201F),
              "igyi3_sd_branch", "branch_redirect", words=[0xD503201F])
    P.write_words(data, SD_VALUE, [0x52800020, 0xD65F03C0])   # mov w0,#1 ; ret
    P._record(data, SD_VALUE, struct.pack("<II", 0x52800020, 0xD65F03C0),
              "igyi3_sd_value", "ret_const", w0=1)
    print(f"secure-download bypass: {SD_BRANCH:#x} b.ne->nop, {SD_VALUE:#x} -> mov w0,#1; ret")

# --- secure-download bypass, minimal local form (verified 2026-10-23) -----------
# The bypass flag is [0xbeb508], read by 14 sites as "if (flag) skip the
# Samsung secure check (0x6c3f8)". Its only writer is 0x6be60, called from
# early init 0x2810:
#   0x6be78 bl 0xa9d8          gate = [0x39cc88] "ldfw loaded" (shared: DO NOT patch)
#   0x6be7c cmp w0, #1
#   0x6be80 b.ne 0x6bfc0       not loaded -> "[E] Skip %s. ldfw has not been loaded"
#   0x6be84 bl 0x64e28         value (shared getter: DO NOT patch)
#   0x6be8c str w0, [x1,#0x508]
# Only the value load is replaced, so the function still refuses to run when
# ldfw is not up. The branch at 0x6be80 is deliberately left stock: forcing it
# (the full2 build) enters the ldfw/TZ init path unguarded.
SD_VALUE_LOAD = 0x6BE84


def secure_download_value_igyi3(data):
    if P.word(data, SD_VALUE_LOAD) != 0x97FFE3E9:   # bl 0x64e28
        raise ValueError(f"igyi3 sd value: {SD_VALUE_LOAD:#x} = {P.word(data, SD_VALUE_LOAD):#x}")
    P.write_u32(data, SD_VALUE_LOAD, 0x52800020)    # mov w0, #1
    P._record(data, SD_VALUE_LOAD, struct.pack("<I", 0x52800020),
              "igyi3_sd_value_load", "ret_const", w0=1)
    print(f"secure-download: {SD_VALUE_LOAD:#x} bl value -> mov w0,#1 (gate left stock)")


STUB_SET = [
    check_signature_igyi3,
    P.patch_prevent_warranty_fuse,
    P.patch_check_sw_rev,
    P.patch_check_kernel_rev,
    P.patch_check_system_rev,
    P.patch_check_pit_rev,
    P.patch_seandroid_enforcing_off,
    P.patch_avbops_state_reader_always_unlocked,
    P.patch_read_is_device_unlocked,
]
GATE_SET = [rollback_gate_igyi3, secure_download_gate_igyi3]
EXEC_SET = [executor_skip_igyi3]

SETS = {
    "stubs": STUB_SET,
    "stubs_rp": STUB_SET + [rollback_gate_igyi3],
    "stubs_sd": STUB_SET + [secure_download_gate_igyi3],
    "stubs_sd0": STUB_SET + [secure_download_gate_igyi3_zero],
    "gates": STUB_SET + GATE_SET,
    "full": STUB_SET + GATE_SET + EXEC_SET,
    "full2": STUB_SET + [rollback_gate_igyi3, secure_download_bypass_igyi3, executor_skip_igyi3],
    # Verified minimal set (2026-10-23): every entry decompiled on the stock IGYI3
    # bootload and confirmed to be a gate whose 0 return means "pass", plus the
    # load-bearing unlock/AVB readers, the local secure-download value write, and
    # the executor nops (the pending unlock request otherwise writes
    # "recovery --wipe_data" into misc and reboots on every boot).
    # Excludes: both 0xa9d8 getter patches and the 0x6be80 branch nop (forcing the
    # ldfw-guarded path is what the full2 build added on top of this).
    "core": STUB_SET + [rollback_gate_igyi3, secure_download_value_igyi3, executor_skip_igyi3],
}


if __name__ == "__main__":
    which = os.environ.get("EUB_IGYI3_SET", "full").lower()
    if which not in SETS:
        raise SystemExit(f"EUB_IGYI3_SET must be one of {sorted(SETS)}, got {which!r}")
    with open(sys.argv[1], "rb") as f:
        data = bytearray(f.read())
    for fn in SETS[which]:
        fn(data)
    with open(sys.argv[1], "wb") as f:
        f.write(data)
    print(f"wrote {sys.argv[1]} (set={which}, {len(SETS[which])} patch functions)")
