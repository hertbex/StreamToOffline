from __future__ import annotations

import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from .tools import Toolchain


class ExportifyLauncher:
    def __init__(self, toolchain: Toolchain, host: str = "127.0.0.1", port: int = 3000) -> None:
        self.toolchain = toolchain
        self.host = host
        self.port = port
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def command(self) -> tuple[list[str], Path]:
        pnpm = self.toolchain.locate("pnpm")
        exportify = self.toolchain.locate("exportify")
        if not pnpm.available or not exportify.available:
            raise RuntimeError("Local pnpm and Exportify are required")
        directory = exportify.path.parent
        command = [
            str(pnpm.path), "start", "--", "--host", self.host,
            "--port", str(self.port), "--strictPort",
        ]
        return command, directory

    def is_ready(self) -> bool:
        try:
            with urlopen(self.url, timeout=2) as response:
                return response.status == 200
        except OSError:
            return False

    def start(
        self, *, open_browser: bool = True, timeout: float = 30,
        callback_url: str | None = None, playlist_id: str | None = None,
    ) -> None:
        url = self.url
        params = {}
        if callback_url:
            params["streamtooffline_callback"] = callback_url
        if playlist_id:
            params["streamtooffline_playlist"] = playlist_id
        if params:
            url += "?" + urlencode(params)
        if self.is_ready():
            if open_browser:
                webbrowser.open(url)
            return
        command, directory = self.command()
        log_path = self.toolchain.root / "artifacts" / "exportify.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log:
            self.process = subprocess.Popen(command, cwd=directory, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.is_ready():
            time.sleep(0.2)
        if not self.is_ready():
            self.stop()
            raise RuntimeError(f"Exportify did not start; see {log_path}")
        if open_browser:
            webbrowser.open(url)

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        self.process = None

    @staticmethod
    def discover_csv(directory: Path, modified_after: float) -> Path | None:
        candidates = [
            path for path in directory.glob("*.csv")
            if path.is_file() and path.stat().st_mtime >= modified_after
        ]
        return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
