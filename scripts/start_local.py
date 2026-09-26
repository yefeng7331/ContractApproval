"""Start the local query-mode API and Vite from one Windows terminal."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def port_free(port: int) -> bool:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def http_status(url: str) -> int:
    try:
        with urlopen(url, timeout=2) as response:
            return response.status
    except HTTPError as error:
        return error.code
    except (OSError, URLError):
        return 0


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-port", type=int, default=8010)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--process-local", action="store_true",
                        help="Run local parsing, review preparation, reports, and mock writeback; paid model dispatch remains manual")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if not all(1 <= port <= 65535 for port in (args.backend_port, args.frontend_port)):
        parser.error("ports must be between 1 and 65535")
    if args.backend_port == args.frontend_port:
        parser.error("backend and frontend ports must differ")
    vite = ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite.is_file():
        parser.error(f"Missing {vite}")
    node = shutil.which("node")
    if not node:
        parser.error("Missing node")
    for port in (args.backend_port, args.frontend_port):
        if not port_free(port):
            parser.error(f"Port {port} is unavailable; existing services were not touched")

    backend_env = os.environ.copy()
    backend_env.pop("CONTRACT_LOCAL_DATA_ROOT", None)
    backend_env["CONTRACT_LOCAL_PROCESSING"] = '1' if args.process_local else '0'
    if args.data_root:
        backend_env["CONTRACT_LOCAL_DATA_ROOT"] = str(args.data_root.resolve())
    frontend_env = os.environ.copy()
    frontend_env["CONTRACT_API_PROXY_TARGET"] = f"http://127.0.0.1:{args.backend_port}"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    backend = None
    frontend = None
    try:
        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.local_runtime:create_local_app", "--factory", "--host", "127.0.0.1", "--port", str(args.backend_port), "--log-level", "warning"],
            cwd=ROOT,
            env=backend_env,
            creationflags=creationflags,
        )
        frontend = subprocess.Popen(
            [node, str(vite), "--host", "127.0.0.1", "--port", str(args.frontend_port), "--strictPort"],
            cwd=ROOT / "frontend",
            env=frontend_env,
            creationflags=creationflags,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if backend.poll() is not None or frontend.poll() is not None:
                raise RuntimeError("A local service exited before becoming ready")
            if (
                http_status(f"http://127.0.0.1:{args.backend_port}/openapi.json") == 200
                and http_status(f"http://127.0.0.1:{args.frontend_port}/") == 200
                and http_status(f"http://127.0.0.1:{args.frontend_port}/api/v1/tasks") == 401
            ):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Local services did not become ready")
        print(f"Ready: http://127.0.0.1:{args.frontend_port}/ (API port {args.backend_port})")
        if args.process_local:
            print("Local processing mode: background jobs enabled; paid model calls require separate authorization.")
        else:
            print("Query mode: background processing and paid model calls are disabled.")
        if args.smoke:
            print("Launcher smoke PASS")
            return 0
        print("Press Ctrl+C to stop both services.")
        while backend.poll() is None and frontend.poll() is None:
            time.sleep(1)
        raise RuntimeError("A local service exited unexpectedly")
    except KeyboardInterrupt:
        return 0
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        for process in (frontend, backend):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    raise SystemExit(run())
