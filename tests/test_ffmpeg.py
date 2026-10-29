import subprocess

import pytest

from streamtooffline.domain.models import DownloadProfile, MediaFormat
from streamtooffline.infrastructure.ffmpeg import AudioProcessor, QualityIntegrityError


def successful_runner(command, **kwargs):
    command[-1] and __import__("pathlib").Path(command[-1]).write_bytes(b"audio")
    return subprocess.CompletedProcess(command, 0, "", "")


def test_mp3_conversion_uses_profile_quality(tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"wav")
    profile = DownloadProfile.kia_ceed_ed_fl()
    report = AudioProcessor(tmp_path / "ffmpeg", successful_runner).convert(source, profile)
    assert report.converted and report.path.suffix == ".mp3"
    assert "not increased" in report.note


def test_lossy_to_lossless_is_rejected_without_running_ffmpeg(tmp_path):
    source = tmp_path / "source.mp3"
    source.write_bytes(b"mp3")
    def forbidden_runner(command, **kwargs):
        raise AssertionError("FFmpeg must not run")
    with pytest.raises(QualityIntegrityError):
        AudioProcessor(tmp_path / "ffmpeg", forbidden_runner).convert(source, DownloadProfile.lossless())


def test_same_format_without_resampling_is_preserved(tmp_path):
    source = tmp_path / "source.mp3"
    source.write_bytes(b"mp3")
    report = AudioProcessor(tmp_path / "ffmpeg", successful_runner).convert(source, DownloadProfile(format=MediaFormat.MP3))
    assert not report.converted and report.path == source
