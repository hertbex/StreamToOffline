from __future__ import annotations

import platform
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable


class FFmpegInstaller:
    """Downloads a static Windows FFmpeg build into .tools/bin."""

    WINDOWS_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

    def __init__(self, root: Path, platform_name: str | None = None) -> None:
        self.root = root
        self.platform_name = platform_name or platform.system()

    def is_needed(self) -> bool:
        return self.platform_name.lower() == "windows"

    def install(self, progress: Callable[[str], None] | None = None) -> Path:
        if not self.is_needed():
            raise RuntimeError(f"Automatic FFmpeg installation is not supported on {self.platform_name}")
        target_dir = self.root / ".tools" / "bin"
        target_dir.mkdir(parents=True, exist_ok=True)
        if (target_dir / "ffmpeg.exe").is_file():
            return target_dir / "ffmpeg.exe"

        def emit(message: str) -> None:
            if progress:
                progress(message)

        emit("Downloading FFmpeg for Windows...")
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "ffmpeg.zip"
            urllib.request.urlretrieve(self.WINDOWS_URL, archive)
            emit("Extracting FFmpeg...")
            with zipfile.ZipFile(archive, "r") as zip_file:
                zip_file.extractall(tmp)
            extracted = list(Path(tmp).rglob("ffmpeg.exe"))
            if not extracted:
                raise RuntimeError("ffmpeg.exe not found in downloaded archive")
            shutil.copy2(extracted[0], target_dir / "ffmpeg.exe")
            emit(f"FFmpeg installed to {target_dir / 'ffmpeg.exe'}")
        return target_dir / "ffmpeg.exe"

    @staticmethod
    def instructions(platform_name: str) -> str:
        platform_name = platform_name.lower()
        if platform_name == "windows":
            return "Run 'streamtooffline doctor --install-ffmpeg' or place ffmpeg.exe in .tools/bin"
        if platform_name == "linux":
            return "Install FFmpeg with your package manager, e.g. sudo apt install ffmpeg"
        if platform_name == "darwin":
            return "Install FFmpeg with Homebrew: brew install ffmpeg"
        return "Install FFmpeg for your platform and ensure it is on PATH"
