"""Exercise the real supervisor with isolated workers and redirected stdin."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BATCH_PATH = Path(__file__).with_name("codex_auto_confirm.bat")


class HiddenLauncherStabilityTests(unittest.TestCase):
    def test_restart_delay_is_honored_when_stdin_is_redirected(self):
        for stdin_mode in (subprocess.DEVNULL, subprocess.PIPE):
            with self.subTest(stdin_mode=stdin_mode):
                with tempfile.TemporaryDirectory(dir=BATCH_PATH.parent) as directory:
                    temp_path = Path(directory)
                    marker_path = temp_path / "attempts.txt"
                    stub_path = temp_path / "fail_once.py"
                    stub_path.write_text(
                        "from pathlib import Path\n"
                        "import os, sys, time\n"
                        "marker = Path(os.environ['CODEX_AUTO_CONFIRM_TEST_MARKER'])\n"
                        "prior = marker.read_text() if marker.exists() else ''\n"
                        "with marker.open('a') as log:\n"
                        "    log.write(str(time.monotonic()) + '\\n')\n"
                        "sys.exit(0 if prior else 7)\n",
                        encoding="utf-8",
                    )
                    env = os.environ.copy()
                    env.update({
                        "CODEX_AUTO_CONFIRM_PYTHON_EXE": sys.executable,
                        "CODEX_AUTO_CONFIRM_SCRIPT": str(stub_path),
                        "CODEX_AUTO_CONFIRM_RESTART_DELAY": "2",
                        "CODEX_AUTO_CONFIRM_TEST_MARKER": str(marker_path),
                    })
                    result = subprocess.run(
                        ["cmd.exe", "/d", "/c", str(BATCH_PATH)],
                        stdin=stdin_mode, capture_output=True, env=env, text=True, encoding="mbcs", errors="replace",
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        timeout=12,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    attempts = [float(value) for value in marker_path.read_text().splitlines()]
                    self.assertEqual(len(attempts), 2)
                    self.assertGreaterEqual(
                        attempts[1] - attempts[0], 1.9,
                        f"Supervisor skipped the 2-second delay: {result.stdout!r} {result.stderr!r}",
                    )


if __name__ == "__main__":
    unittest.main()
