from streamtooffline.cli import build_parser, format_bytes, format_duration, profile_from_args
from streamtooffline.domain.models import MediaFormat, VersionPolicy
from streamtooffline.tui import StreamToOfflineApp


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


def test_doctor_supports_sockseek_install_flag():
    args = build_parser().parse_args(["doctor", "--install-sockseek"])
    assert args.install_sockseek is True


def test_tui_app_constructs_with_repository_root(tmp_path):
    app = StreamToOfflineApp(tmp_path)
    assert app.root == tmp_path


def test_tui_accepts_spotify_album_urls():
    assert StreamToOfflineApp._playlist_id(
        "https://open.spotify.com/album/3WK7zNSkmniQ3raPvYyDQP?si=test"
    ) == "3WK7zNSkmniQ3raPvYyDQP"
