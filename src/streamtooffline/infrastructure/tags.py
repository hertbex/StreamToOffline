from __future__ import annotations

from pathlib import Path

from mutagen.flac import FLAC
from mutagen.id3 import APIC, ID3, TALB, TCON, TIT2, TPE1

from streamtooffline.domain.models import DownloadProfile, Track


class TagWriter:
    def write(self, path: Path, track: Track, profile: DownloadProfile) -> None:
        suffix = path.suffix.lower()
        if suffix == ".mp3":
            self._write_mp3(path, track, profile)
        elif suffix == ".flac":
            self._write_flac(path, track, profile)
        else:
            raise ValueError(f"Tags are not supported for {suffix}")

    @staticmethod
    def _write_mp3(path: Path, track: Track, profile: DownloadProfile) -> None:
        try:
            tags = ID3(path)
        except Exception:
            tags = ID3()
        if not profile.keep_artwork:
            tags.delall("APIC")
        tags.delall("GEOB")
        tags.delall("PRIV")
        tags.delall("TPE1")
        tags.delall("TIT2")
        tags.delall("TALB")
        tags.delall("TCON")
        tags.add(TPE1(encoding=1, text=track.artist))
        tags.add(TIT2(encoding=1, text=track.display_title))
        if track.album:
            tags.add(TALB(encoding=1, text=track.album))
        if track.genres:
            tags.add(TCON(encoding=1, text=", ".join(track.genres)))
        tags.save(path, v1=0, v2_version=3)

    @staticmethod
    def _write_flac(path: Path, track: Track, profile: DownloadProfile) -> None:
        tags = FLAC(path)
        tags["artist"] = track.artist
        tags["title"] = track.display_title
        if track.album:
            tags["album"] = track.album
        if track.genres:
            tags["genre"] = list(track.genres)
        if not profile.keep_artwork:
            tags.clear_pictures()
        tags.save()
