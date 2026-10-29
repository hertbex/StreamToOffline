from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from streamtooffline.domain.models import DownloadProfile, MediaFormat


class QualityIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessingReport:
    path: Path
    converted: bool
    note: str


class AudioProcessor:
    def __init__(self, executable: Path, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self.executable = executable
        self.runner = runner

    def convert(self, source: Path, profile: DownloadProfile, destination: Path | None = None) -> ProcessingReport:
        source_format = self._format(source)
        target = profile.format
        if target is MediaFormat.AUTO:
            return ProcessingReport(source, False, f"Preserved {source_format.value} source")
        if target.is_lossless and not source_format.is_lossless:
            raise QualityIntegrityError(f"Refusing fake {target.value.upper()} from lossy {source_format.value}")

        output = destination or source.with_suffix(f".{target.value}")
        if source_format is target and profile.sample_rate_hz is None:
            return ProcessingReport(source, False, f"Preserved original {source_format.value}")

        temporary = output
        if source.resolve() == output.resolve():
            temporary = output.with_name(f"{output.stem}.converting{output.suffix}")
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [str(self.executable), "-y", "-v", "error", "-i", str(source), "-vn"]
        command += self._codec_args(target, profile)
        if profile.sample_rate_hz:
            command += ["-ar", str(profile.sample_rate_hz)]
        command += ["-ac", "2", str(temporary)]
        completed = self.runner(command, capture_output=True, text=True, encoding="utf-8")
        if completed.returncode != 0 or not temporary.is_file():
            raise RuntimeError(f"FFmpeg conversion failed: {(completed.stderr or 'unknown error')[-500:]}")
        if temporary != output:
            temporary.replace(output)
        note = f"{source_format.value} source converted to {target.value}; source quality is not increased"
        return ProcessingReport(output, True, note)

    @staticmethod
    def _format(path: Path) -> MediaFormat:
        try:
            return MediaFormat(path.suffix.lower().lstrip("."))
        except ValueError as exc:
            raise QualityIntegrityError(f"Unsupported audio format: {path.suffix}") from exc

    @staticmethod
    def _codec_args(target: MediaFormat, profile: DownloadProfile) -> list[str]:
        bitrate = profile.preferred_bitrate_kbps or profile.min_bitrate_kbps or 320
        if target is MediaFormat.MP3:
            return ["-c:a", "libmp3lame", "-b:a", f"{bitrate}k"]
        if target is MediaFormat.FLAC:
            return ["-c:a", "flac"]
        if target is MediaFormat.M4A:
            return ["-c:a", "aac", "-b:a", f"{bitrate}k"]
        if target is MediaFormat.OGG:
            return ["-c:a", "libvorbis", "-b:a", f"{bitrate}k"]
        if target is MediaFormat.OPUS:
            return ["-c:a", "libopus", "-b:a", f"{bitrate}k"]
        if target is MediaFormat.WAV:
            return ["-c:a", "pcm_s16le"]
        raise QualityIntegrityError(f"Unsupported target: {target}")
