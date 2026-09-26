"""Smoke checks for the Windows single-command local launcher."""

from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "start_local.py"


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class LocalLauncherSmokeTests(unittest.TestCase):
    def run_launcher(self, backend_port: int, frontend_port: int, data_root: Path):
        return subprocess.run(
            [
                sys.executable,
                str(LAUNCHER),
                "--backend-port",
                str(backend_port),
                "--frontend-port",
                str(frontend_port),
                "--data-root",
                str(data_root),
                "--smoke",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=40,
        )

    def test_starts_both_services_then_releases_ports(self):
        with tempfile.TemporaryDirectory(prefix="contract-launcher-") as temp:
            backend_port = free_port()
            frontend_port = free_port()
            while frontend_port == backend_port:
                frontend_port = free_port()
            result = self.run_launcher(backend_port, frontend_port, Path(temp))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Launcher smoke PASS", result.stdout)
            self.assertIn("paid model calls are disabled", result.stdout)
            self.assertTrue((Path(temp) / "contract_approval.sqlite3").exists())
            for port in (backend_port, frontend_port):
                with socket.socket() as connection:
                    self.assertNotEqual(connection.connect_ex(("127.0.0.1", port)), 0)

    def test_busy_backend_port_does_not_start_services(self):
        with tempfile.TemporaryDirectory(prefix="contract-launcher-") as temp:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                backend_port = listener.getsockname()[1]
                frontend_port = free_port()
                result = self.run_launcher(backend_port, frontend_port, Path(temp))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"Port {backend_port} is unavailable", result.stderr)
                self.assertFalse((Path(temp) / "contract_approval.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
