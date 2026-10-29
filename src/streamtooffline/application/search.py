from __future__ import annotations

import re
from dataclasses import dataclass

from streamtooffline.domain.models import Candidate, DownloadProfile, Track
from streamtooffline.domain.planner import CandidateSelector


@dataclass(frozen=True, slots=True)
class SearchMatch:
    track: Track
    candidates: tuple[Candidate, ...]


class TrackSearcher:
    def __init__(self, sockseek) -> None:
        self.sockseek = sockseek
        self.selector = CandidateSelector()

    def search(self, query: str, profile: DownloadProfile, limit: int = 15) -> tuple[SearchMatch, ...]:
        candidates = self.sockseek.search_query(query, profile)
        grouped: dict[tuple[str, str], tuple[str, str, list[Candidate]]] = {}
        for candidate in candidates:
            artist, title = self._parse_filename(candidate.location)
            key = (artist.lower(), title.lower())
            if key not in grouped:
                grouped[key] = (artist, title, [])
            grouped[key][2].append(candidate)

        matches = []
        for artist, title, group in grouped.values():
            track = Track(artist, title, group[0].duration_seconds)
            eligible = self.selector.ranked(track, group, profile)
            matches.append(SearchMatch(track, eligible or tuple(group)))
        matches.sort(key=lambda m: len(m.candidates), reverse=True)
        return tuple(matches[:limit])

    @staticmethod
    def _parse_filename(location: str) -> tuple[str, str]:
        normalized = re.sub(r"\\", "/", location)
        filename = normalized.rsplit("/", 1)[-1]
        filename = re.sub(r"\.[^.]+$", "", filename)
        filename = re.sub(r"_", " ", filename).strip()
        if " - " in filename:
            artist, title = filename.split(" - ", 1)
            return artist.strip(), title.strip()
        parts = [part for part in normalized.split("/") if part.strip()]
        if len(parts) >= 2:
            artist = re.sub(r"_", " ", parts[0]).strip()
            return artist, filename
        return "Unknown", filename
