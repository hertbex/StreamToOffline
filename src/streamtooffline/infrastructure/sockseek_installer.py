from __future__ import annotations

import hashlib
import platform
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable


class SockseekInstaller:
    """Downloads the pinned Sockseek release into the repository tool directory."""

    VERSION = "3.0.6"
    WINDOWS_URL = (
        "https://github.com/fiso64/sockseek/releases/download/"
        f"v{VERSION}/sockseek_{VERSION}_win-x64.zip"
    )
    WINDOWS_SHA256 = "aa965bdf3bc9b04757380889e1ce96ce1d57fdf89423fb3f7ebf378e469e66c4"

    def __init__(self, root: Path, platform_name: str | None = None) -> None:
        self.root = root
        self.platform_name = platform_name or platform.system()

    def is_supported(self) -> bool:
        return self.platform_name.lower() == "windows"

    def install(self, progress: Callable[[str], None] | None = None) -> Path:
        if not self.is_supported():
            raise RuntimeError(
                f"Automatic Sockseek installation is currently supported only on Windows, "
                f"not {self.platform_name}"
            )
        target = self.root / ".tools" / "bin" / "sockseek.exe"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            return target

        def emit(message: str) -> None:
            if progress:
                progress(message)

        emit(f"Downloading Sockseek {self.VERSION} for Windows x64...")
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "sockseek.zip"
            urllib.request.urlretrieve(self.WINDOWS_URL, archive)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if digest != self.WINDOWS_SHA256:
                raise RuntimeError("Sockseek archive checksum mismatch")
            emit("Extracting Sockseek...")
            with zipfile.ZipFile(archive) as zip_file:
                members = [
                    member for member in zip_file.infolist()
                    if Path(member.filename).name.lower() == "sockseek.exe"
                ]
                if not members:
                    raise RuntimeError("sockseek.exe not found in downloaded archive")
                member = members[0]
                extracted = Path(tmp) / "sockseek.exe"
                with zip_file.open(member) as source, extracted.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
            shutil.copy2(extracted, target)
            emit(f"Sockseek installed to {target}")
        return target

    @staticmethod
    def instructions(platform_name: str) -> str:
        if platform_name.lower() == "windows":
            return "Run 'streamtooffline doctor --install-sockseek' or place sockseek.exe in .tools/bin"
        return "Download the Sockseek release for your platform and set SOCKSEEK_PATH to its executable"
