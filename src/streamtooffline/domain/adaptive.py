from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from .models import Track


@dataclass(frozen=True, slots=True)
class AdaptiveBucket:
    name: str
    keywords: tuple[str, ...]
    mood_rule: str | None = None


class AdaptiveLibrary:
    def __init__(self, rules_path: Path | None = None) -> None:
        self.rules_path = rules_path or Path(__file__).parents[3] / "config" / "adaptive.yml"
        data = yaml.safe_load(self.rules_path.read_text(encoding="utf-8")) or {}
        self.genre_rules = data.get("genre_rules", [])
        self.mood_rules = data.get("mood_rules", [])
        self.fallback = data.get("fallback", "Other")
        self.min_tracks = data.get("min_tracks", 3)
        self.buckets: list[AdaptiveBucket] = []
        self._counts: dict[str, int] = {}

    def build(self, tracks: Iterable[Track]) -> "AdaptiveLibrary":
        track_list = tuple(tracks)
        counts: dict[str, int] = {}
        for track in track_list:
            category = self._classify_all_rules(track)
            counts[category] = counts.get(category, 0) + 1
        active = {name for name, count in counts.items() if count >= self.min_tracks}
        self._counts = counts
        if counts.get(self.fallback, 0) > 0:
            active.add(self.fallback)
        self.buckets = [
            AdaptiveBucket(rule["name"], tuple(rule.get("genres", [])))
            for rule in self.genre_rules
            if rule["name"] in active
        ]
        for rule in self.mood_rules:
            if rule["name"] in active:
                self.buckets.append(AdaptiveBucket(
                    rule["name"], tuple(rule.get("genres", [])), rule.get("condition"),
                ))
        if self.fallback in active:
            self.buckets.append(AdaptiveBucket(self.fallback, ()))
        return self

    def classify(self, track: Track) -> str:
        if not self.buckets:
            return self.fallback
        for bucket in self.buckets:
            if bucket.mood_rule:
                if self._mood_matches(track, bucket.mood_rule):
                    return bucket.name
            elif self._genre_matches(track, bucket.keywords):
                return bucket.name
        return self.fallback

    def _classify_all_rules(self, track: Track) -> str:
        for rule in self.genre_rules:
            if self._genre_matches(track, tuple(rule.get("genres", []))):
                return rule["name"]
        for rule in self.mood_rules:
            if self._mood_matches(track, rule.get("condition", "")):
                return rule["name"]
        return self.fallback

    def preview(self) -> list[tuple[str, int]]:
        return [(bucket.name, self._counts.get(bucket.name, 0)) for bucket in self.buckets]

    @staticmethod
    def _genre_matches(track: Track, keywords: tuple[str, ...]) -> bool:
        genres = " ".join(track.genres).lower()
        return any(keyword.lower() in genres for keyword in keywords)

    @staticmethod
    def _mood_matches(track: Track, condition: str) -> bool:
        if condition == "low_energy" and track.energy is not None and track.energy < 0.45:
            return True
        if condition == "high_energy" and track.energy is not None and track.energy >= 0.72:
            return True
        if condition == "low_valence" and track.valence is not None and track.valence < 0.35:
            return True
        return False
