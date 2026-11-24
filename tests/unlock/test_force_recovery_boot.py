"""Synthetic fixture tests for the force-recovery boot patch.

No Samsung binary is used. The fixture contains only the instruction window
the locator matches, the RET before the code cave, and the two NOP words the
patch replaces. That keeps the test host-only and safe to publish.
"""

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "unlock" / "patchers"))
sys.path.insert(0, str(ROOT / "tools" / "unlock" / "verify"))

import patch_9840 as patcher  # noqa: E402
import verify_chain as verifier  # noqa: E402

SELECTOR = 0x2B20
CAVE = 0xC624C
RECOVERY_BLOCK = 0x2F80


def fixture():
    """Return an image with the param[0] == 0 selector and the NOP cave."""
    data = bytearray(0xC6260)

    def write(offset, words):
        struct.pack_into("<%dI" % len(words), data, offset, *words)

    # platform_init: read param[0], branch to normal boot at 0x2a48.
    write(SELECTOR, [
        0x9400FC5E,  # bl   0x41c98
        0x34FFF920,  # cbz  w0, 0x2a48
        0x52800000,  # mov  w0, #0
        0x9400FC5B,  # bl   0x41c98
        0x2A0003F3,  # orr  w19, wzr, w0
        0x51001000,  # sub  w0, w0, #4
        0x7100041F,  # cmp  w0, #1
        0x54002229,  # b.ls 0x2f80
        0x71001A7F,  # cmp  w19, #6
        0x54FFF821,  # b.ne 0x2a48
    ])
    write(0xC6248, [0xD65F03C0])            # ret
    write(CAVE, [0xD503201F, 0xD503201F])   # two unused NOP words
    return data


class ForceRecoveryBootTests(unittest.TestCase):
    def setUp(self):
        patcher.PATCH_SITES.clear()

    def test_normal_mode_enters_recovery_without_changing_other_modes(self):
        data = fixture()
        source = bytes(data)

        patcher.patch_force_recovery_boot(data)

        self.assertEqual(int.from_bytes(data[0x2B24:0x2B28], "little"), 0x3461B940)
        self.assertEqual(int.from_bytes(data[0xC624C:0xC6250], "little"), 0x52800013)
        self.assertEqual(int.from_bytes(data[0xC6250:0xC6254], "little"), 0x17FCF34C)

        # The param[0] = 4/5 recovery case and the param[0] = 6 path stay intact.
        self.assertEqual(data[0x2B28:0x2B4C], source[0x2B28:0x2B4C])

        changed = {
            i for i, (before, after) in enumerate(zip(source, data))
            if before != after
        }
        self.assertEqual(
            changed,
            {0x2B24, 0x2B25, 0x2B26} | set(range(CAVE, CAVE + 8)),
        )

        contracts = {c["name"]: c for c in verifier.CONTRACTS}
        for name in (
            "force_recovery_default/branch",
            "force_recovery_default/trampoline",
        ):
            ok, lines = verifier.check_contract(data, contracts[name], "fixture")
            self.assertTrue(ok, lines)

    def test_verifier_rejects_a_trampoline_that_misses_recovery(self):
        data = fixture()
        patcher.patch_force_recovery_boot(data)

        contracts = {c["name"]: c for c in verifier.CONTRACTS}
        data[CAVE + 4:CAVE + 8] = bytes.fromhex("00000014")

        ok, _ = verifier.check_contract(
            data, contracts["force_recovery_default/trampoline"], "tampered"
        )
        self.assertFalse(ok)

    def test_locator_requires_the_full_selector_window(self):
        data = fixture()
        data[SELECTOR + 24:SELECTOR + 28] = struct.pack("<I", 0x7100001F)

        with self.assertRaisesRegex(ValueError, "expected one normal-mode selector"):
            patcher.patch_force_recovery_boot(data)


if __name__ == "__main__":
    unittest.main()
