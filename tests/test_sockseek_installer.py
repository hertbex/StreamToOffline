from pathlib import Path

from streamtooffline.infrastructure.sockseek_installer import SockseekInstaller


def test_sockseek_installer_supports_windows_only():
    assert SockseekInstaller(Path("/tmp"), "Windows").is_supported()
    assert not SockseekInstaller(Path("/tmp"), "Linux").is_supported()


def test_sockseek_installer_has_pinned_release_and_platform_instructions():
    installer = SockseekInstaller(Path("/tmp"), "Windows")
    assert "v3.0.6" in installer.WINDOWS_URL
    assert len(installer.WINDOWS_SHA256) == 64
    assert "--install-sockseek" in installer.instructions("Windows")
