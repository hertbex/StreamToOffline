from __future__ import annotations

import os
import platform
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ToolStatus:
    name: str
    available: bool
    path: Path | None
    isolated: bool


class Toolchain:
    """Locates repository-local tools before falling back to system executables."""

    ENV_OVERRIDES = {
        "sockseek": "SOCKSEEK_PATH",
        "ffmpeg": "FFMPEG_PATH",
        "yt-dlp": "YT_DLP_PATH",
        "exportify": "EXPORTIFY_PATH",
    }

    def __init__(
        self,
        root: Path,
        *,
        environ: Mapping[str, str] | None = None,
        platform_name: str | None = None,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.root = root
        self.environ = os.environ if environ is None else environ
        self.platform_name = platform.system() if platform_name is None else platform_name
        self.which = which

    def _executable(self, name: str) -> str:
        return f"{name}.exe" if self.platform_name.lower() == "windows" else name

    def _local_candidates(self, name: str) -> tuple[Path, ...]:
        if name == "exportify":
            return (self.root / ".tools" / "exportify" / "package.json",)
        if name == "pnpm":
            executable = "pnpm.cmd" if self.platform_name.lower() == "windows" else "pnpm"
            return (self.root / ".tools" / "pnpm" / "node_modules" / ".bin" / executable,)

        executable = self._executable(name)
        candidates = [self.root / ".tools" / "bin" / executable]
        if name == "yt-dlp":
            venv_bin = "Scripts" if self.platform_name.lower() == "windows" else "bin"
            candidates.append(self.root / ".venv" / venv_bin / executable)
        return tuple(candidates)

    def locate(self, name: str) -> ToolStatus:
        override = self.environ.get(self.ENV_OVERRIDES.get(name, ""))
        if override and Path(override).is_file():
            return ToolStatus(name, True, Path(override), False)

        for local in self._local_candidates(name):
            if local.is_file():
                return ToolStatus(name, True, local, True)

        if name != "exportify":
            system_path = self.which(name)
            if system_path:
                return ToolStatus(name, True, Path(system_path), False)

        return ToolStatus(name, False, None, False)

    def doctor(self) -> tuple[ToolStatus, ...]:
        return tuple(self.locate(name) for name in ("sockseek", "ffmpeg", "yt-dlp", "exportify", "pnpm", "node"))
