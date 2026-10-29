from __future__ import annotations

import csv
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from streamtooffline.domain.models import Candidate, DownloadProfile, MediaFormat, Track


class SockseekUserPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(alias="Username")
    upload_speed: float = Field(alias="UploadSpeed")
    has_free_upload_slot: bool = Field(alias="HasFreeUploadSlot")


class SockseekFilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    length: int = Field(default=-1, alias="Length")
    filename: str = Field(alias="Filename")
    size: int = Field(alias="Size")
    bitrate: int | None = Field(default=None, alias="Bitrate")
    sample_rate: int | None = Field(default=None, alias="SampleRate")
    bit_depth: int | None = Field(default=None, alias="BitDepth")


class SockseekResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user: SockseekUserPayload = Field(alias="User")
    file: SockseekFilePayload = Field(alias="File")


@dataclass(frozen=True, slots=True)
class SockseekConfig:
    executable: Path
    username: str
    password: str
    work_dir: Path
    search_timeout: int = 60
    download_timeout: int = 45


class SockseekError(RuntimeError):
    pass


class SockseekClient:
    def __init__(self, config: SockseekConfig, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self.config = config
        self.runner = runner
        self.config.work_dir.mkdir(parents=True, exist_ok=True)

    def search(self, track: Track, profile: DownloadProfile) -> Sequence[Candidate]:
        with tempfile.TemporaryDirectory(dir=self.config.work_dir) as temp_dir:
            source = Path(temp_dir) / "track.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Artist", "Title", "Length"])
                writer.writerow([track.artist, track.title, track.duration_seconds or ""])
            command = self._base_command(str(source), profile) + [
                "--artist-maybe-wrong", "--desperate", "--print-json-full",
            ]
            completed = self._run(command, self.config.search_timeout)
            candidates = self._parse_candidates(completed.stdout)
        if candidates:
            return candidates
        candidates: list[Candidate] = []
        seen: set[tuple[str, str, str, int]] = set()
        for query in (
            f"artist={track.artist}, title={track.title}",
            f"title={track.title}",
            f"artist={track.artist}",
        ):
            for candidate in self.search_query(query, profile):
                key = (candidate.peer or "", candidate.location, candidate.format.value, candidate.size_bytes)
                if key not in seen:
                    seen.add(key)
                    candidates.append(candidate)
        return tuple(candidates)

    def check_credentials(self) -> str:
        """Check authentication by issuing a harmless empty-result search."""
        completed = self._run(
            self._base_command("title=streamtooffline-credential-check", None)
            + ["--input-type", "string", "--print-json-full"],
            self.config.search_timeout,
        )
        if completed.returncode not in (0, 1):
            raise SockseekError("Soulseek rejected the credentials")
        return "Soulseek responded successfully; credentials are accepted."

    def search_query(self, query: str, profile: DownloadProfile) -> Sequence[Candidate]:
        queries = [query]
        if "=" not in query:
            queries = [f"artist={query}", f"title={query}", query]
        candidates: list[Candidate] = []
        seen: set[tuple[str, str, str, int]] = set()
        for search in queries:
            command = self._base_command(search, profile) + [
                "--input-type", "string", "--artist-maybe-wrong",
                "--desperate", "--no-remove-special-chars", "--print-json-full",
            ]
            completed = self._run(command, self.config.search_timeout)
            for candidate in self._parse_candidates(completed.stdout):
                key = (candidate.peer or "", candidate.location, candidate.format.value, candidate.size_bytes)
                if key not in seen:
                    seen.add(key)
                    candidates.append(candidate)
        return tuple(candidates)

    def download(self, candidate: Candidate, destination: Path) -> Path:
        if destination.is_file() and destination.stat().st_size > 0:
            return destination
        if not candidate.peer:
            raise SockseekError("Soulseek candidate has no peer")
        destination.parent.mkdir(parents=True, exist_ok=True)
        link = f"slsk://{candidate.peer}/{candidate.location.replace(chr(92), '/')}"
        before = {
            path.resolve()
            for path in destination.parent.rglob("*")
            if path.is_file()
        }
        command = self._base_command(link, None) + [
            "--no-write-index", "--name-format", destination.stem, "-o", str(destination.parent),
            "--max-stale-time", "120000", "--max-retries", "3",
        ]
        self._run(command, self.config.download_timeout)
        if not destination.is_file():
            staged = [
                path for path in destination.parent.rglob(f"*{destination.suffix}")
                if path.is_file() and path != destination and path.resolve() not in before
            ]
            exact_size = [path for path in staged if path.stat().st_size == candidate.size_bytes]
            if exact_size:
                staged = exact_size
            if staged:
                max(staged, key=lambda path: path.stat().st_mtime).replace(destination)
        if not destination.is_file():
            raise SockseekError(f"Sockseek did not create {destination.name}")
        return destination

    def _base_command(self, source: str, profile: DownloadProfile | None) -> list[str]:
        command = [
            str(self.config.executable), source,
            "--user", self.config.username, "--pass", self.config.password,
            "--no-listen", "--no-progress",
        ]
        if profile:
            formats = self._formats(profile.format)
            if formats:
                command += ["--format", formats]
            if profile.min_bitrate_kbps:
                command += ["--pref-min-bitrate", str(profile.min_bitrate_kbps)]
            if profile.length_tolerance_seconds is not None:
                command += ["--length-tol", str(profile.length_tolerance_seconds)]
        return command

    @staticmethod
    def _formats(target: MediaFormat) -> str | None:
        if target is MediaFormat.MP3:
            return "mp3,flac,m4a,wav,ogg"
        if target is MediaFormat.FLAC:
            return "flac,wav"
        if target is MediaFormat.AUTO:
            return None
        return target.value

    def _run(self, command: list[str], timeout: int) -> subprocess.CompletedProcess:
        try:
            completed = self.runner(command, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SockseekError(f"Soulseek process failed: {type(exc).__name__}") from exc
        if completed.returncode not in (0, 1):
            detail = (completed.stderr or completed.stdout or "unknown error").strip()[-500:]
            raise SockseekError(f"Soulseek exited with {completed.returncode}: {detail}")
        return completed

    @staticmethod
    def _parse_candidates(output: str) -> tuple[Candidate, ...]:
        try:
            raw_payloads = json.loads(output or "[]")
            if not isinstance(raw_payloads, list):
                raise ValueError("Expected a JSON array")
        except (json.JSONDecodeError, ValueError) as exc:
            raise SockseekError("Invalid Sockseek JSON response") from exc
        candidates: list[Candidate] = []
        for raw_payload in raw_payloads:
            try:
                payload = SockseekResultPayload.model_validate(raw_payload)
                suffix = Path(payload.file.filename).suffix.lower().lstrip(".")
                media_format = MediaFormat(suffix)
                candidates.append(Candidate(
                    source="soulseek", location=payload.file.filename,
                    size_bytes=payload.file.size, duration_seconds=payload.file.length,
                    format=media_format, bitrate_kbps=payload.file.bitrate,
                    sample_rate_hz=payload.file.sample_rate, peer=payload.user.username,
                    upload_speed_kbps=payload.user.upload_speed,
                    has_free_upload_slot=payload.user.has_free_upload_slot,
                ))
            except (ValidationError, ValueError):
                continue
        return tuple(candidates)
