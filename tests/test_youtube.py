import subprocess

import pytest

from streamtooffline.domain.models import DownloadProfile, Track
from streamtooffline.infrastructure.ffmpeg import QualityIntegrityError
from streamtooffline.infrastructure.youtube import YouTubeFallback


def test_youtube_mp3_fallback_is_explicit_about_lossy_quality(tmp_path):
    destination = tmp_path / "song.mp3"
    def runner(command, **kwargs):
        destination.write_bytes(b"mp3")
        return subprocess.CompletedProcess(command, 0, str(destination) + "\n", "")
    fallback = YouTubeFallback(tmp_path / "yt-dlp", tmp_path / "ffmpeg", runner)
    result = fallback.download(Track("Artist", "Title", 200), DownloadProfile.kia_ceed_ed_fl(), destination)
    assert result.path == destination
    assert "lossy" in result.warning


def test_youtube_fallback_rejects_flac_before_network(tmp_path):
    def forbidden_runner(command, **kwargs):
        raise AssertionError("Network must not run")
    fallback = YouTubeFallback(tmp_path / "yt-dlp", tmp_path / "ffmpeg", forbidden_runner)
    with pytest.raises(QualityIntegrityError):
        fallback.download(Track("Artist", "Title", 200), DownloadProfile.lossless(), tmp_path / "song.flac")


def test_youtube_fallback_passes_explicit_proxy(tmp_path):
    seen = {}
    destination = tmp_path / "song.mp3"
    def runner(command, **kwargs):
        seen["command"] = command
        destination.write_bytes(b"mp3")
        return subprocess.CompletedProcess(command, 0, str(destination) + "\n", "")
    fallback = YouTubeFallback(tmp_path / "yt-dlp", tmp_path / "ffmpeg", runner, proxy="http://proxy:8080")
    fallback.download(Track("Artist", "Title", 200), DownloadProfile.kia_ceed_ed_fl(), destination)
    assert seen["command"][1] == "ytsearch5:Artist - Title"
    assert ("--proxy", "http://proxy:8080") in zip(seen["command"], seen["command"][1:])


def test_youtube_fallback_reports_duration_filter_miss(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "", "")

    fallback = YouTubeFallback(tmp_path / "yt-dlp", tmp_path / "ffmpeg", runner)
    with pytest.raises(RuntimeError, match="within 5s"):
        fallback.download(Track("Artist", "Title", 200), DownloadProfile(), tmp_path / "song.mp3")


def test_youtube_search_returns_version_candidates(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            '{"entries":[{"title":"Title (Radio Edit)","channel":"Artist","duration":180}]}',
            "",
        )

    fallback = YouTubeFallback(tmp_path / "yt-dlp", tmp_path / "ffmpeg", runner)
    results = fallback.search(Track("Artist", "Title", 0))
    assert results[0].title == "Title (Radio Edit)"
    assert results[0].duration_seconds == 180
