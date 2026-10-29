from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable

from .models import Candidate, DownloadProfile, MediaFormat, Track


@dataclass(frozen=True, slots=True)
class LibraryEstimate:
    track_count: int
    duration_seconds: int
    min_bytes: int
    max_bytes: int
    basis: str


@dataclass(frozen=True, slots=True)
class SelectionReport:
    total: int
    eligible: int
    rejected_by_quality: int
    rejected_by_length: int
    rejected_by_version: int
    best: Candidate | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"Soulseek: {self.total} found"]
        if self.eligible:
            parts.append(f"{self.eligible} eligible")
            if self.best:
                minutes, seconds = divmod(self.best.duration_seconds, 60)
                size_mib = self.best.size_bytes / (1024 * 1024)
                quality = (
                    f"{self.best.bitrate_kbps} kbps"
                    if self.best.bitrate_kbps
                    else self.best.format.value.upper()
                )
                parts.append(
                    f"best {minutes}:{seconds:02} / {size_mib:.1f} MiB / {quality}"
                )
        else:
            parts.append("none eligible")
        reasons = []
        if self.rejected_by_quality:
            reasons.append(f"{self.rejected_by_quality} wrong quality")
        if self.rejected_by_length:
            reasons.append(f"{self.rejected_by_length} wrong length")
        if self.rejected_by_version:
            reasons.append(f"{self.rejected_by_version} wrong version")
        if reasons:
            parts.append(", ".join(reasons))
        if self.reasons and not self.eligible:
            parts.append(self.reasons[0])
        return "; ".join(parts)


class LibraryPlanner:
    PCM_BITRATE_KBPS = 1411

    def estimate(self, tracks: Iterable[Track], profile: DownloadProfile) -> LibraryEstimate:
        track_list = tuple(tracks)
        estimated = any(track.duration_seconds <= 0 for track in track_list)
        duration = sum(track.duration_seconds if track.duration_seconds > 0 else 240 for track in track_list)
        suffix = " (estimated duration)" if estimated else ""
        if profile.format is MediaFormat.FLAC:
            pcm = self._bytes_at(duration, self.PCM_BITRATE_KBPS)
            return LibraryEstimate(len(track_list), duration, math.ceil(pcm * 0.5), math.ceil(pcm * 0.75), "FLAC: 50–75% of PCM" + suffix)
        if profile.format is MediaFormat.WAV:
            size = self._bytes_at(duration, self.PCM_BITRATE_KBPS)
            return LibraryEstimate(len(track_list), duration, size, size, "PCM 1411 kbps" + suffix)
        if profile.format is MediaFormat.AUTO:
            pcm = self._bytes_at(duration, self.PCM_BITRATE_KBPS)
            return LibraryEstimate(
                len(track_list), duration, self._bytes_at(duration, 128), math.ceil(pcm * 0.75),
                "Auto: MP3 128k through FLAC estimate" + suffix,
            )
        bitrate = profile.preferred_bitrate_kbps or profile.min_bitrate_kbps or 320
        size = self._bytes_at(duration, bitrate)
        return LibraryEstimate(len(track_list), duration, size, size, f"{profile.format.value.upper()} {bitrate} kbps" + suffix)

    @staticmethod
    def _bytes_at(duration_seconds: int, bitrate_kbps: int) -> int:
        return math.ceil(duration_seconds * bitrate_kbps * 1000 / 8)

    @staticmethod
    def transfer_seconds(size_bytes: int, bytes_per_second: float | None) -> int | None:
        if not bytes_per_second or bytes_per_second <= 0:
            return None
        return math.ceil(size_bytes / bytes_per_second)


class CandidateSelector:
    REMIX = re.compile(r"\b(?:remix|bootleg|mashup|mix)\b", re.I)
    ORIGINAL_MIX = re.compile(r"\boriginal\s+mix\b", re.I)
    EDIT = re.compile(r"\b(?:radio\s+edit|single\s+edit|clean|edit|edited|short\s+version)\b", re.I)
    UNSUPPORTED_ORIGINAL = re.compile(r"\b(?:live|cover|karaoke|sped\s+up|slowed|reverb|8d)\b", re.I)

    def diagnose(self, track: Track, candidates: Iterable[Candidate], profile: DownloadProfile) -> SelectionReport:
        total = 0
        eligible = 0
        rejected_by_quality = 0
        rejected_by_length = 0
        rejected_by_version = 0
        reasons: list[str] = []
        eligible_candidates: list[Candidate] = []

        for candidate in candidates:
            total += 1
            quality_ok = self._quality_matches(candidate, profile)
            length_ok = (
                track.duration_seconds <= 0
                or profile.length_tolerance_seconds is None
                or abs(candidate.duration_seconds - track.duration_seconds) <= profile.length_tolerance_seconds
            )
            version_ok = self._version_matches(candidate.location, profile)

            if quality_ok and length_ok and version_ok:
                eligible += 1
                eligible_candidates.append(candidate)
            else:
                if not quality_ok:
                    rejected_by_quality += 1
                    if not reasons:
                        reasons.append(f"quality below {profile.min_bitrate_kbps or profile.format.value}")
                if not length_ok:
                    rejected_by_length += 1
                    if not reasons:
                        reasons.append(f"duration mismatch (expected {track.duration_seconds}s)")
                if not version_ok:
                    rejected_by_version += 1
                    if not reasons:
                        reasons.append("version mismatch")

        ranked = sorted(eligible_candidates, key=lambda candidate: self._rank(track, candidate, profile), reverse=True)
        return SelectionReport(
            total=total,
            eligible=eligible,
            rejected_by_quality=rejected_by_quality,
            rejected_by_length=rejected_by_length,
            rejected_by_version=rejected_by_version,
            best=ranked[0] if ranked else None,
            reasons=reasons,
        )

    def ranked(self, track: Track, candidates: Iterable[Candidate], profile: DownloadProfile) -> tuple[Candidate, ...]:
        candidates = tuple(candidates)
        report = self.diagnose(track, candidates, profile)
        return tuple(
            sorted(
                (c for c in candidates if self.eligible(track, c, profile)),
                key=lambda candidate: self._rank(track, candidate, profile),
                reverse=True,
            )
        )

    def eligible(self, track: Track, candidate: Candidate, profile: DownloadProfile) -> bool:
        if not self._quality_matches(candidate, profile):
            return False
        if track.duration_seconds > 0 and profile.length_tolerance_seconds is not None:
            if abs(candidate.duration_seconds - track.duration_seconds) > profile.length_tolerance_seconds:
                return False
        return self._version_matches(candidate.location, profile)

    def _quality_matches(self, candidate: Candidate, profile: DownloadProfile) -> bool:
        target = profile.format
        if target is MediaFormat.FLAC and not candidate.format.is_lossless:
            return False
        if target not in {MediaFormat.AUTO, MediaFormat.MP3, MediaFormat.FLAC} and candidate.format is not target:
            return False
        if profile.min_bitrate_kbps and not candidate.format.is_lossless:
            if candidate.bitrate_kbps is None or candidate.bitrate_kbps < profile.min_bitrate_kbps:
                return False
        return True

    def _version_matches(self, location: str, profile: DownloadProfile) -> bool:
        if profile.version_policy.value == "all":
            return True
        is_remix = bool(self.REMIX.search(location) and not self.ORIGINAL_MIX.search(location))
        is_edit = bool(self.EDIT.search(location))
        if profile.version_policy.value == "remixes":
            return is_remix
        if profile.version_policy.value == "edits":
            return is_edit
        return not is_remix and not is_edit and not self.UNSUPPORTED_ORIGINAL.search(location)

    def _rank(self, track: Track, candidate: Candidate, profile: DownloadProfile) -> tuple[int, int, int, int, int, int]:
        if candidate.format is profile.format:
            format_score = 4
        elif profile.format is MediaFormat.AUTO:
            format_score = 4 if candidate.format is MediaFormat.MP3 else 3 if candidate.format.is_lossless else 2
        elif profile.format is MediaFormat.MP3 and candidate.format.is_lossless:
            format_score = 3
        else:
            format_score = 1
        quality_score = 1000 if candidate.format.is_lossless else candidate.bitrate_kbps or 0
        duration_score = -abs(candidate.duration_seconds - track.duration_seconds)
        slot_score = 1 if candidate.has_free_upload_slot else 0
        speed_score = round(candidate.upload_speed_kbps or 0)
        return format_score, quality_score, slot_score, speed_score, duration_score, -candidate.size_bytes
