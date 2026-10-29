from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from .models import Candidate, DownloadProfile, Track


class MetadataSource(Protocol):
    def load(self, source: str) -> Sequence[Track]: ...


class CandidateSearch(Protocol):
    def search(self, track: Track, profile: DownloadProfile) -> Sequence[Candidate]: ...


class CandidateDownloader(Protocol):
    def download(self, candidate: Candidate, destination: Path) -> Path: ...
