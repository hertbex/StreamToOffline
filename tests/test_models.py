import pytest

from streamtooffline.domain.models import (
    Candidate,
    DownloadJob,
    DownloadProfile,
    MediaFormat,
    Track,
)


def test_track_display_name_includes_featured_artists_once():
    track = Track("АК-47", "В тепле 2 яйца", 268, featured_artists=("QП",))
    assert track.display_name == "АК-47 - В тепле 2 яйца (ft. QП)"
    already_tagged = Track("АК-47", "В тепле 2 яйца (ft. QП)", 268, featured_artists=("QП",))
    assert already_tagged.display_title.count("ft.") == 1


@pytest.mark.parametrize("artist,title,duration", [("", "Song", 100), ("Artist", " ", 100), ("Artist", "Song", -1)])
def test_track_rejects_invalid_metadata(artist, title, duration):
    with pytest.raises(ValueError):
        Track(artist, title, duration)


def test_kia_profile_enforces_car_compatible_defaults():
    profile = DownloadProfile.kia_ceed_ed_fl()
    assert profile.format is MediaFormat.MP3
    assert profile.min_bitrate_kbps == 320
    assert profile.sample_rate_hz == 44_100
    assert not profile.keep_artwork


def test_candidate_rejects_auto_format_and_non_positive_size():
    with pytest.raises(ValueError):
        Candidate("soulseek", "file.mp3", 0, 100, MediaFormat.MP3)
    with pytest.raises(ValueError):
        Candidate("soulseek", "file.mp3", 100, 100, MediaFormat.AUTO)


def test_job_requires_tracks():
    with pytest.raises(ValueError):
        DownloadJob((), DownloadProfile(), "job-1")
