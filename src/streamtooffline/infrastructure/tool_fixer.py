from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .ffmpeg_installer import FFmpegInstaller
from .sockseek_installer import SockseekInstaller
from .tools import Toolchain


class ToolFixer:
    """Installs repository-managed tools and prepares the local Exportify checkout."""

    EXPORTIFY_REPOSITORY = "https://github.com/watsonbox/exportify.git"
    EXPORTIFY_COMMIT = "d8eaeb92e7911a2bb626bdcb9d378b0cfe086c12"
    PNPM_VERSION = "10.34.5"

    def __init__(self, root: Path, platform_name: str | None = None) -> None:
        self.root = root
        self.platform_name = platform_name or platform.system()

    def fix(self, progress: Callable[[str], None] | None = None) -> tuple[str, ...]:
        messages: list[str] = []

        def emit(message: str) -> None:
            messages.append(message)
            if progress:
                progress(message)

        toolchain = Toolchain(self.root, platform_name=self.platform_name)
        if not toolchain.locate("ffmpeg").available and self.platform_name.lower() == "windows":
            FFmpegInstaller(self.root, self.platform_name).install(progress=emit)
        if not toolchain.locate("sockseek").available and self.platform_name.lower() == "windows":
            SockseekInstaller(self.root, self.platform_name).install(progress=emit)
        if not toolchain.locate("yt-dlp").available:
            target = self.root / ".tools" / "yt-dlp"
            self._run(
                [
                    self._python(), "-m", "pip", "install",
                    "--upgrade", "--ignore-installed", "--prefix", str(target),
                    "yt-dlp==2026.10.26",
                ],
                "Installing yt-dlp...",
                emit,
            )
        toolchain = Toolchain(self.root, platform_name=self.platform_name)
        if not toolchain.locate("node").available:
            raise RuntimeError(
                "Node.js is missing. Install Node.js LTS, restart the terminal, and run doctor --fix again."
            )
        if not toolchain.locate("pnpm").available:
            self._install_pnpm(emit)
        toolchain = Toolchain(self.root, platform_name=self.platform_name)
        if not toolchain.locate("exportify").available:
            self._install_exportify(emit)
        return tuple(messages)

    def _install_pnpm(self, emit: Callable[[str], None]) -> None:
        npm = shutil.which("npm")
        if not npm:
            node = shutil.which("node")
            if node:
                candidate = Path(node).with_name("npm.cmd" if self.platform_name.lower() == "windows" else "npm")
                if candidate.is_file():
                    npm = str(candidate)
        if not npm:
            raise RuntimeError("npm is missing; install Node.js LTS before installing pnpm.")
        target = self.root / ".tools" / "pnpm"
        self._run(
            [npm, "install", "--prefix", str(target), f"pnpm@{self.PNPM_VERSION}"],
            "Installing pnpm...",
            emit,
        )

    def _install_exportify(self, emit: Callable[[str], None]) -> None:
        git = shutil.which("git")
        pnpm = Toolchain(self.root, platform_name=self.platform_name).locate("pnpm").path
        if not git or not pnpm:
            raise RuntimeError("git and pnpm are required to install Exportify.")
        target = self.root / ".tools" / "exportify"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            self._run(
                [git, "clone", self.EXPORTIFY_REPOSITORY, str(target)],
                "Downloading Exportify...",
                emit,
            )
        self._run([git, "-C", str(target), "checkout", self.EXPORTIFY_COMMIT], "Pinning Exportify...", emit)
        self._run([str(pnpm), "install", "--frozen-lockfile"], "Installing Exportify dependencies...", emit, cwd=target)

    @staticmethod
    def _python() -> str:
        import sys

        return sys.executable

    @staticmethod
    def _run(
        command: list[str],
        message: str,
        emit: Callable[[str], None],
        *,
        cwd: Path | None = None,
    ) -> None:
        emit(message)
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "unknown error").strip()[-1000:]
            raise RuntimeError(f"{message} failed: {detail}")
