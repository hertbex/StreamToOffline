from __future__ import annotations

import csv
from io import TextIOBase
from dataclasses import dataclass
from pathlib import Path

from streamtooffline.domain.models import Track


@dataclass(frozen=True, slots=True)
class CsvError:
    line: int
    message: str


@dataclass(frozen=True, slots=True)
class CsvImportResult:
    tracks: tuple[Track, ...]
    errors: tuple[CsvError, ...]


class ExportifyCsvReader:
    ARTIST = ("Artist Name(s)", "Artist", "artist")
    TITLE = ("Track Name", "Title", "title")
    ALBUM = ("Album Name", "Album", "album")
    DURATION_MS = ("Track Duration (ms)", "Duration (ms)")
    DURATION_SECONDS = ("Length", "Duration (s)")
    GENRES = ("Genres", "Artist Genres")
    URI = ("Track URI", "URI")
    ENERGY = ("Energy",)
    VALENCE = ("Valence",)
    TEMPO = ("Tempo",)

    def load(self, source: str) -> tuple[Track, ...]:
        return self.read(Path(source)).tracks

    def read(self, source: Path | str | TextIOBase) -> CsvImportResult:
        if isinstance(source, Path):
            text = source.read_text(encoding="utf-8-sig")
        elif isinstance(source, TextIOBase):
            text = source.read()
        else:
            text = source
        lines = text.splitlines()
        if not lines:
            raise ValueError("CSV file is empty")
        header = next(csv.reader([lines[0]], strict=True))
        indices = {name: self._find_column(header, aliases) for name, aliases in self._aliases().items()}
        for required in ("artist", "title"):
            if indices[required] is None:
                raise ValueError(f"Required CSV column is missing: {required}")

        tracks: list[Track] = []
        errors: list[CsvError] = []
        for line_number, raw_line in enumerate(lines[1:], start=2):
            if not raw_line.strip():
                continue
            try:
                row = self._parse_row(raw_line, len(header))
                tracks.append(self._track_from_row(row, indices))
            except (ValueError, csv.Error) as exc:
                errors.append(CsvError(line_number, str(exc)))
        return CsvImportResult(tuple(tracks), tuple(errors))

    def _aliases(self) -> dict[str, tuple[str, ...]]:
        return {
            "artist": self.ARTIST, "title": self.TITLE, "album": self.ALBUM,
            "duration_ms": self.DURATION_MS, "duration_seconds": self.DURATION_SECONDS,
            "genres": self.GENRES, "uri": self.URI,
            "energy": self.ENERGY, "valence": self.VALENCE, "tempo": self.TEMPO,
        }

    @staticmethod
    def _find_column(header: list[str], aliases: tuple[str, ...]) -> int | None:
        lowered = {name.strip().lower(): index for index, name in enumerate(header)}
        for alias in aliases:
            if alias.lower() in lowered:
                return lowered[alias.lower()]
        return None

    def _parse_row(self, line: str, expected_columns: int) -> list[str]:
        try:
            row = next(csv.reader([line], strict=True))
            if len(row) == expected_columns:
                return row
        except csv.Error:
            pass
        row = next(csv.reader([self.repair_quotes(line)], strict=True))
        if len(row) != expected_columns:
            raise ValueError(f"Expected {expected_columns} columns, got {len(row)}")
        return row

    @staticmethod
    def repair_quotes(line: str) -> str:
        """Escape unbalanced quotes inside CSV fields without changing valid rows."""
        output: list[str] = []
        in_quotes = False
        field_start = True
        index = 0
        while index < len(line):
            char = line[index]
            following = line[index + 1] if index + 1 < len(line) else ""
            if field_start:
                output.append(char)
                if char == '"':
                    in_quotes = True
                if char != ",":
                    field_start = False
                index += 1
                continue
            if char == "," and not in_quotes:
                output.append(char)
                field_start = True
                index += 1
                continue
            if char == '"' and in_quotes:
                if following == '"':
                    after_pair = line[index + 2] if index + 2 < len(line) else ""
                    if after_pair in {"", ","}:
                        output.append('"""')
                        in_quotes = False
                        index += 2
                    else:
                        output.append('""')
                        index += 2
                    continue
                if following in {"", ","}:
                    output.append(char)
                    in_quotes = False
                    index += 1
                    continue
                output.append('""')
                index += 1
                continue
            output.append(char)
            index += 1
        return "".join(output)

    def _track_from_row(self, row: list[str], indices: dict[str, int | None]) -> Track:
        def value(name: str) -> str:
            index = indices[name]
            return row[index].strip() if index is not None else ""

        artists = tuple(artist.strip() for artist in value("artist").split(";") if artist.strip())
        if not artists:
            raise ValueError("Artist is empty")
        duration_ms = value("duration_ms")
        duration_seconds = value("duration_seconds")
        if duration_ms:
            duration = max(1, round(int(duration_ms) / 1000))
        elif duration_seconds:
            duration = int(duration_seconds)
        else:
            raise ValueError("Duration is missing")
        return Track(
            artist=artists[0],
            featured_artists=artists[1:],
            title=value("title"),
            album=value("album") or None,
            duration_seconds=duration,
            genres=tuple(genre.strip() for genre in value("genres").split(",") if genre.strip()),
            uri=value("uri") or None,
            energy=float(value("energy")) if value("energy") else None,
            valence=float(value("valence")) if value("valence") else None,
            tempo=float(value("tempo")) if value("tempo") else None,
        )
