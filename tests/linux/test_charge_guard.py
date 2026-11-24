"""Host-side tests for the charge guard state machine.

The guard reads a single sysfs battery directory, so the test supplies a fake
one. No device and no privileged path is needed.
"""

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "linux" / "tools" / "device" / "charge-guard"


class ChargeGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="charge-guard-"))
        self.bat = self.tmp / "battery"
        self.bat.mkdir()
        (self.bat / "capacity").write_text("85\n")
        self.log = self.tmp / "charge.log"
        self.proc = None

    def tearDown(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self):
        env = os.environ.copy()
        env.update(
            BAT=str(self.bat),
            CEIL="80",
            FLOOR="75",
            POLL="1",
            LOG=str(self.log),
        )
        self.proc = subprocess.Popen(
            ["sh", str(SCRIPT)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self.proc

    def wait_for(self, name, value, timeout=8):
        path = self.bat / name
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists() and path.read_text().strip() == value:
                return
            time.sleep(0.05)
        raise AssertionError(f"{name} never became {value!r}")

    def test_holds_at_ceiling_and_resumes_at_floor(self):
        self.start()
        self.wait_for("charging_enabled", "0")

        (self.bat / "capacity").write_text("70\n")
        self.wait_for("charging_enabled", "1")

    def test_unreadable_capacity_leaves_charging_enabled(self):
        (self.bat / "capacity").write_text("unknown\n")
        self.start()
        time.sleep(1.5)

        self.assertFalse((self.bat / "charging_enabled").exists())
        self.assertIsNone(self.proc.poll(), "guard exited instead of failing safe")

    def test_sets_the_swelling_backstop_when_writable(self):
        (self.bat / "batt_swelling_control").write_text("0\n")
        self.start()

        self.wait_for("batt_swelling_control", "1")


if __name__ == "__main__":
    unittest.main()
