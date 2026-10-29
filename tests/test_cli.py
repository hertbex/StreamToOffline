from streamtooffline.cli import build_parser, format_bytes, format_duration, profile_from_args
from streamtooffline.domain.models import MediaFormat, VersionPolicy


def test_formatters_and_custom_profile_arguments():
    assert format_bytes(1024) == "1.0 KiB"
    assert format_duration(3661) == "1:01:01"
    args = build_parser().parse_args([
        "song", "A - B", "--profile", "custom", "--format", "mp3",
        "--bitrate", "256", "--sample-rate", "44100", "--version", "remixes",
    ])
    profile = profile_from_args(args)
    assert profile.format is MediaFormat.MP3
    assert profile.preferred_bitrate_kbps == 256
    assert profile.version_policy is VersionPolicy.REMIXES


def test_kia_profile_and_unknown_song_duration():
    args = build_parser().parse_args(["song", "A - B", "--profile", "kia"])
    profile = profile_from_args(args)
    assert profile.sample_rate_hz == 44100
