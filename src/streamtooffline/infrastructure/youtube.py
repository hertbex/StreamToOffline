from __future__ import annotations

import subprocess
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from streamtooffline.domain.models import DownloadProfile, MediaFormat, Track
from .ffmpeg import QualityIntegrityError


@dataclass(frozen=True, slots=True)
class YouTubeResult:
    path: Path
    warning: str


class YouTubeFallback:
    def __init__(
        self,
        executable: Path,
        ffmpeg_executable: Path,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        proxy: str | None = None,
    ) -> None:
        self.executable = executable
        self.ffmpeg_executable = ffmpeg_executable
        self.runner = runner
        self.proxy = proxy or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")

    def download(self, track: Track, profile: DownloadProfile, destination: Path) -> YouTubeResult:
        if profile.format.is_lossless:
            raise QualityIntegrityError("YouTube fallback cannot produce genuine lossless audio")
        if destination.is_file() and destination.stat().st_size > 0:
            return YouTubeResult(destination, self.WARNING)
        if profile.format not in {MediaFormat.AUTO, MediaFormat.MP3}:
            raise QualityIntegrityError("YouTube fallback supports Auto or MP3 output only")

        destination.parent.mkdir(parents=True, exist_ok=True)
        query = f"ytsearch1:{track.artist} - {track.title}"
        command = [
            str(self.executable), query, "--ffmpeg-location", str(self.ffmpeg_executable),
            "-f", "bestaudio/best", "--no-playlist", "--quiet", "--no-warnings",
            "--print", "after_move:filepath", "-o", str(destination.with_suffix(".%(ext)s")),
        ]
        if profile.format is MediaFormat.MP3:
            bitrate = profile.preferred_bitrate_kbps or profile.min_bitrate_kbps or 320
            command += ["-x", "--audio-format", "mp3", "--audio-quality", f"{bitrate}K"]
        if profile.sample_rate_hz:
            command += ["--postprocessor-args", f"ffmpeg:-ar {profile.sample_rate_hz} -ac 2"]
        if self.proxy:
            command += ["--proxy", self.proxy]
        if track.duration_seconds > 0 and profile.length_tolerance_seconds is not None:
            low = max(1, track.duration_seconds - profile.length_tolerance_seconds)
            high = track.duration_seconds + profile.length_tolerance_seconds
            command += ["--match-filter", f"duration >= {low} & duration <= {high}"]

        completed = self.runner(command, capture_output=True, text=True, encoding="utf-8", timeout=900)
        output = completed.stdout.strip().splitlines()
        produced = Path(output[-1]) if output else destination
        if completed.returncode != 0 or not produced.is_file():
            raise RuntimeError(f"YouTube download failed: {(completed.stderr or 'no output file')[-500:]}")
        return YouTubeResult(produced, self.WARNING)

    WARNING = "YouTube provides lossy audio; container bitrate/sample rate does not represent original studio quality"
