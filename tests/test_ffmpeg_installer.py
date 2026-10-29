from pathlib import Path

from streamtooffline.infrastructure.ffmpeg_installer import FFmpegInstaller


def test_ffmpeg_installer_only_supports_windows_auto_install():
    assert FFmpegInstaller(Path("/tmp"), "Windows").is_needed()
    assert not FFmpegInstaller(Path("/tmp"), "Linux").is_needed()
    assert not FFmpegInstaller(Path("/tmp"), "Darwin").is_needed()


def test_ffmpeg_installer_instructions_are_platform_specific():
    assert "apt" in FFmpegInstaller.instructions("Linux")
    assert "brew" in FFmpegInstaller.instructions("Darwin")
    assert ".tools" in FFmpegInstaller.instructions("Windows")
