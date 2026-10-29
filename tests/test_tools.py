from streamtooffline.infrastructure.tools import Toolchain


def test_toolchain_prefers_isolated_windows_tool(tmp_path):
    executable = tmp_path / ".tools" / "bin" / "sockseek.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    toolchain = Toolchain(tmp_path, platform_name="Windows", which=lambda _: None)

    status = toolchain.locate("sockseek")

    assert status.available
    assert status.isolated
    assert status.path == executable


def test_toolchain_reports_missing_tool_and_checks_exportify_manifest(tmp_path):
    toolchain = Toolchain(tmp_path, platform_name="Linux", which=lambda _: None)
    assert not toolchain.locate("ffmpeg").available

    manifest = tmp_path / ".tools" / "exportify" / "package.json"
    manifest.parent.mkdir(parents=True)
    manifest.touch()
    assert toolchain.locate("exportify").available


def test_environment_override_is_supported(tmp_path):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.touch()
    toolchain = Toolchain(tmp_path, environ={"FFMPEG_PATH": str(ffmpeg)}, which=lambda _: None)
    status = toolchain.locate("ffmpeg")
    assert status.available and not status.isolated


def test_toolchain_finds_venv_ytdlp_and_windows_pnpm(tmp_path):
    ytdlp = tmp_path / ".venv" / "Scripts" / "yt-dlp.exe"
    pnpm = tmp_path / ".tools" / "pnpm" / "node_modules" / ".bin" / "pnpm.cmd"
    ytdlp.parent.mkdir(parents=True)
    pnpm.parent.mkdir(parents=True)
    ytdlp.touch()
    pnpm.touch()
    toolchain = Toolchain(tmp_path, platform_name="Windows", which=lambda _: None)

    assert toolchain.locate("yt-dlp").isolated
    assert toolchain.locate("pnpm").isolated


def test_toolchain_uses_plain_executable_names_on_linux_and_macos(tmp_path):
    for platform_name in ("Linux", "Darwin"):
        sockseek = tmp_path / ".tools" / "bin" / "sockseek"
        sockseek.parent.mkdir(parents=True, exist_ok=True)
        sockseek.touch()
        toolchain = Toolchain(tmp_path, platform_name=platform_name, which=lambda _: None)

        status = toolchain.locate("sockseek")

        assert status.available
        assert status.path == sockseek


def test_toolchain_finds_venv_ytdlp_and_plain_pnpm_on_posix(tmp_path):
    for platform_name in ("Linux", "Darwin"):
        ytdlp = tmp_path / ".venv" / "bin" / "yt-dlp"
        pnpm = tmp_path / ".tools" / "pnpm" / "node_modules" / ".bin" / "pnpm"
        ytdlp.parent.mkdir(parents=True, exist_ok=True)
        pnpm.parent.mkdir(parents=True, exist_ok=True)
        ytdlp.touch()
        pnpm.touch()
        toolchain = Toolchain(tmp_path, platform_name=platform_name, which=lambda _: None)

        assert toolchain.locate("yt-dlp").isolated
        assert toolchain.locate("pnpm").isolated
