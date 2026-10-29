from pathlib import Path

import pytest
from mutagen.id3 import APIC, ID3

from streamtooffline.domain.models import DownloadProfile, Track
from streamtooffline.infrastructure.tags import TagWriter


def test_mp3_tags_are_id3v23_utf16_and_remove_artwork(tmp_path):
    path = tmp_path / "song.mp3"
    tags = ID3()
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=b"image"))
    path.write_bytes(b"")
    tags.save(path, v2_version=3)

    track = Track("АК-47", "В тепле 2 яйца", 268, featured_artists=("QП",), album="Мегаpolice")
    TagWriter().write(path, track, DownloadProfile.kia_ceed_ed_fl())

    saved = ID3(path)
    assert saved["TPE1"].text == ["АК-47"]
    assert saved["TIT2"].text == ["В тепле 2 яйца (ft. QП)"]
    assert saved["TIT2"].encoding == 1
    assert not saved.getall("APIC")


def test_tag_writer_rejects_unknown_extension(tmp_path):
    path = tmp_path / "song.unknown"
    path.write_bytes(b"data")
    with pytest.raises(ValueError):
        TagWriter().write(path, Track("A", "B", 100), DownloadProfile())
