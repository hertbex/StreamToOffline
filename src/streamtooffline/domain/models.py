from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class MediaFormat(StrEnum):
    AUTO = "auto"
    MP3 = "mp3"
    FLAC = "flac"
    M4A = "m4a"
    WAV = "wav"
    OGG = "ogg"
    OPUS = "opus"

    @property
    def is_lossless(self) -> bool:
        return self in {MediaFormat.FLAC, MediaFormat.WAV}


class VersionPolicy(StrEnum):
    AUTO = "auto"
    ORIGINAL = "original"
    EDITS = "edits"
    REMIXES = "remixes"
    ALL = "all"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Track:
    artist: str
    title: str
    duration_seconds: int
    album: str | None = None
    genres: tuple[str, ...] = ()
    featured_artists: tuple[str, ...] = ()
    uri: str | None = None
    energy: float | None = None
    valence: float | None = None
    tempo: float | None = None

    def __post_init__(self) -> None:
        if not self.artist.strip() or not self.title.strip():
            raise ValueError("Artist and title must not be empty")
        if self.duration_seconds < 0:
            raise ValueError("Track duration cannot be negative")

    @property
    def display_title(self) -> str:
        if not self.featured_artists or re.search(r"\b(?:feat\.?|ft\.?)\b", self.title, re.I):
            return self.title
        return f"{self.title} (ft. {', '.join(self.featured_artists)})"

    @property
    def display_name(self) -> str:
        return f"{self.artist} - {self.display_title}"


@dataclass(frozen=True, slots=True)
class DownloadProfile:
    format: MediaFormat = MediaFormat.AUTO
    min_bitrate_kbps: int | None = None
    preferred_bitrate_kbps: int | None = None
    sample_rate_hz: int | None = None
    length_tolerance_seconds: int | None = 5
    version_policy: VersionPolicy = VersionPolicy.AUTO
    youtube_fallback: bool = False
    keep_artwork: bool = True

    def __post_init__(self) -> None:
        if self.min_bitrate_kbps is not None and self.min_bitrate_kbps <= 0:
            raise ValueError("Minimum bitrate must be positive")
        if self.preferred_bitrate_kbps is not None and self.preferred_bitrate_kbps <= 0:
            raise ValueError("Preferred bitrate must be positive")
        if self.sample_rate_hz is not None and self.sample_rate_hz <= 0:
            raise ValueError("Sample rate must be positive")
        if self.length_tolerance_seconds is not None and self.length_tolerance_seconds < 0:
            raise ValueError("Length tolerance cannot be negative")

    @classmethod
    def lossless(cls) -> DownloadProfile:
        return cls(format=MediaFormat.FLAC)

    @classmethod
    def kia_ceed_ed_fl(cls) -> DownloadProfile:
        return cls(
            format=MediaFormat.MP3,
            min_bitrate_kbps=320,
            preferred_bitrate_kbps=320,
            sample_rate_hz=44_100,
            keep_artwork=False,
        )


@dataclass(frozen=True, slots=True)
class Candidate:
    source: str
    location: str
    size_bytes: int
    duration_seconds: int
    format: MediaFormat
    bitrate_kbps: int | None = None
    sample_rate_hz: int | None = None
    peer: str | None = None

    def __post_init__(self) -> None:
        if self.size_bytes <= 0 or self.duration_seconds <= 0:
            raise ValueError("Candidate size and duration must be positive")
        if self.format is MediaFormat.AUTO:
            raise ValueError("Candidate format must be concrete")


@dataclass(frozen=True, slots=True)
class DownloadJob:
    tracks: tuple[Track, ...]
    profile: DownloadProfile
    id: str
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    name: str | None = None
    output_root: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Job id must not be empty")
        if not self.tracks:
            raise ValueError("A job must contain at least one track")
