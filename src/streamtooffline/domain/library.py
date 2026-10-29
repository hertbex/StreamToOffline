from __future__ import annotations

import re
from pathlib import Path

import yaml

from .adaptive import AdaptiveLibrary
from .models import Track


class MetadataRules:
    def __init__(
        self,
        artist_map: dict[str, str],
        genre_config: dict,
        adaptive_library: AdaptiveLibrary | None = None,
    ) -> None:
        self.artist_map = artist_map
        self.genre_config = genre_config
        self.adaptive_library = adaptive_library

    @classmethod
    def load(
        cls,
        artists_path: Path,
        genres_path: Path,
        adaptive_path: Path | None = None,
    ) -> MetadataRules:
        artists = yaml.safe_load(artists_path.read_text(encoding="utf-8")) or {}
        genres = yaml.safe_load(genres_path.read_text(encoding="utf-8")) or {}
        if not isinstance(artists, dict) or not isinstance(genres.get("buckets", []), list):
            raise ValueError("Invalid metadata rule files")
        adaptive_library = AdaptiveLibrary(adaptive_path) if adaptive_path else None
        return cls(artists, genres, adaptive_library)

    def use_adaptive(self, tracks: tuple[Track, ...]) -> MetadataRules:
        if self.adaptive_library is None:
            return self
        self.adaptive_library.build(tracks)
        return self

    def normalize_artists(self, track: Track) -> Track:
        return Track(
            artist=self.artist_map.get(track.artist, track.artist),
            featured_artists=tuple(self.artist_map.get(artist, artist) for artist in track.featured_artists),
            title=track.title, duration_seconds=track.duration_seconds, album=track.album,
            genres=track.genres, uri=track.uri, energy=track.energy,
            valence=track.valence, tempo=track.tempo,
        )

    def classify(self, track: Track, *, adaptive: bool = False) -> str:
        if adaptive and self.adaptive_library is not None and self.adaptive_library.buckets:
            adaptive_name = self.adaptive_library.classify(track)
            if adaptive_name != self.adaptive_library.fallback:
                return adaptive_name
        artists = {track.artist, self.artist_map.get(track.artist, track.artist)}
        genres = " ".join(track.genres).lower()
        for bucket in self.genre_config.get("buckets", []):
            if artists.intersection(bucket.get("artists", [])):
                return bucket["name"]
            if any(keyword.lower() in genres for keyword in bucket.get("genres", [])):
                return bucket["name"]
            if bucket.get("cyrillic") and re.search(r"[\u0400-\u04FF]", f"{track.artist} {track.title} {track.album or ''}"):
                return bucket["name"]
        mood = self.genre_config.get("mood", {})
        if track.energy is not None:
            if track.energy < mood.get("chill_max_energy", 0.45):
                return mood.get("chill", "Chill")
            if track.energy >= mood.get("drive_min_energy", 0.72):
                return mood.get("drive", "Drive")
        return self.genre_config.get("fallback", "Other")


def safe_filename(value: str, max_length: int = 180) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "-", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or "Unknown")[:max_length].rstrip(" .")


def track_relative_path(track: Track, bucket: str | None, extension: str) -> Path:
    filename = f"{safe_filename(track.display_name)}.{extension.lstrip('.')}"
    return Path(safe_filename(bucket)) / filename if bucket else Path(filename)
