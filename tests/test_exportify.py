from pathlib import Path

import pytest

from streamtooffline.infrastructure.exportify import ExportifyLauncher
from streamtooffline.infrastructure.exportify_server import ExportifyImportServer
from streamtooffline.infrastructure.tools import ToolStatus, Toolchain


class FakeToolchain(Toolchain):
    def locate(self, name):
        paths = {"pnpm": Path("/repo/pnpm"), "exportify": Path("/repo/exportify/package.json")}
        return ToolStatus(name, name in paths, paths.get(name), True)


def test_exportify_command_uses_local_tools_and_strict_port():
    launcher = ExportifyLauncher(FakeToolchain(Path("/repo")))
    command, directory = launcher.command()
    assert command[-5:] == ["--host", "127.0.0.1", "--port", "3000", "--strictPort"]
    assert directory == Path("/repo/exportify")


def test_exportify_command_fails_without_dependencies(tmp_path):
    try:
        ExportifyLauncher(Toolchain(tmp_path, which=lambda _: None)).command()
    except RuntimeError as exc:
        assert "required" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


def test_discover_csv_returns_only_newest_matching_file(tmp_path):
    old = tmp_path / "old.csv"
    new = tmp_path / "new.csv"
    ignored = tmp_path / "notes.txt"
    old.touch()
    new.touch()
    ignored.touch()
    old_stat = old.stat().st_mtime
    assert ExportifyLauncher.discover_csv(tmp_path, old_stat) in {old, new}
    assert ExportifyLauncher.discover_csv(tmp_path, new.stat().st_mtime + 1) is None


def test_exportify_callback_url_is_appended_to_open_url():
    launcher = ExportifyLauncher(FakeToolchain(Path("/repo")))
    assert launcher.url == "http://127.0.0.1:3000"


def test_exportify_import_server_receives_csv():
    server = ExportifyImportServer(port=3002)
    server.start()
    try:
        import urllib.request
        req = urllib.request.Request(
            server.url + "?filename=test.csv",
            data="Artist,Title\nA,B".encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        req.full_url = server.url + "?filename=test.csv"
        with urllib.request.urlopen(req, timeout=2) as resp:
            assert resp.status == 200
            assert resp.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:3000"
        payload = server.wait(timeout=2)
        assert payload is not None
        assert payload.filename == "test.csv"
        assert "Artist,Title" in payload.csv_text
    finally:
        server.stop()


def test_exportify_import_server_handles_cors_preflight():
    server = ExportifyImportServer(port=3003)
    server.start()
    try:
        import urllib.request
        req = urllib.request.Request(server.url, method="OPTIONS")
        with urllib.request.urlopen(req, timeout=2) as resp:
            assert resp.status == 204
            assert resp.headers["Access-Control-Allow-Methods"] == "POST, OPTIONS"
    finally:
        server.stop()
