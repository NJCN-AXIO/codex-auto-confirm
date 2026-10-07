"""Focused regression tests for the desktop Codex CDP detector."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("codex_auto_confirm.py")


def load_module():
    spec = importlib.util.spec_from_file_location("codex_auto_confirm_desktop", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeWebSocket:
    def __init__(self):
        self.expression = None
        self.closed = False

    def send(self, payload):
        self.expression = json.loads(payload)["params"]["expression"]

    def recv(self):
        return json.dumps(
            {
                "id": 1,
                "result": {
                    "result": {
                        "value": [{"text": "Allow once", "visible": True}],
                    }
                },
            }
        )

    def close(self):
        self.closed = True


class DesktopCdpTests(unittest.TestCase):
    def test_desktop_detector_sends_parseable_dom_expression(self):
        """The Runtime.evaluate payload must compile in a real JS engine."""
        mod = load_module()
        fake_ws = _FakeWebSocket()
        websocket_module = types.SimpleNamespace(
            create_connection=lambda *_args, **_kwargs: fake_ws
        )
        targets = [
            {
                "type": "page",
                "title": "Codex",
                "webSocketDebuggerUrl": "ws://codex",
            }
        ]

        with (
            patch.object(mod, "discover_cdp_targets", return_value=targets),
            patch.dict(sys.modules, {"websocket": websocket_module}),
        ):
            self.assertTrue(mod.read_desktop_allow_once())

        self.assertIsNotNone(fake_ws.expression)
        compile_result = subprocess.run(
            ["node", "-e", f"new Function({json.dumps(fake_ws.expression)})"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            compile_result.returncode,
            0,
            compile_result.stderr or compile_result.stdout,
        )
        self.assertIn("aria-label", fake_ws.expression)
        self.assertIn("role", fake_ws.expression)
        self.assertTrue(fake_ws.closed)


if __name__ == "__main__":
    unittest.main()
