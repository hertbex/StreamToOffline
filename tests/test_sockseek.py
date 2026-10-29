import json
import subprocess
from pathlib import Path

import pytest

from streamtooffline.domain.models import Candidate, DownloadProfile, MediaFormat, Track
from streamtooffline.infrastructure.sockseek import SockseekClient, SockseekConfig, SockseekError


RESPONSE = [{
    "User": {"Username": "peer", "UploadSpeed": 1.5, "HasFreeUploadSlot": True},
    "File": {"Length": 268, "Filename": "folder\\АК-47 - В тепле 2 яйца.mp3", "Size": 10_000_000, "Bitrate": 320},
}]


def config(tmp_path):
    return SockseekConfig(tmp_path / "sockseek", "user", "secret", tmp_path / "work")


def test_search_uses_csv_and_parses_json_candidates(tmp_path):
    seen = {}
    def runner(command, **kwargs):
        seen["command"] = command
        seen["csv"] = Path(command[1]).read_text(encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, json.dumps(RESPONSE), "")
    client = SockseekClient(config(tmp_path), runner)
    candidates = client.search(Track("АК-47", "В тепле 2 яйца", 268), DownloadProfile.kia_ceed_ed_fl())
    assert candidates[0].peer == "peer"
    assert candidates[0].format is MediaFormat.MP3
    assert "Artist,Title,Length" in seen["csv"]
    assert "--artist-maybe-wrong" in seen["command"]
    assert "--desperate" in seen["command"]
    assert "--print-json-full" in seen["command"]


def test_free_text_search_enables_flexible_matching(tmp_path):
    seen = {}
    def runner(command, **kwargs):
        seen.setdefault("commands", []).append(command)
        return subprocess.CompletedProcess(command, 0, "[]", "")
    SockseekClient(config(tmp_path), runner).search_query("полина", DownloadProfile())
    assert len(seen["commands"]) == 3
    assert all("--input-type" in command for command in seen["commands"])
    assert all("string" in command for command in seen["commands"])
    assert all("--song" not in command for command in seen["commands"])
    assert all("--artist-maybe-wrong" in command for command in seen["commands"])
    assert all("--desperate" in command for command in seen["commands"])
    assert all("--no-remove-special-chars" in command for command in seen["commands"])


def test_search_retries_with_keyed_string_when_csv_search_is_empty(tmp_path):
    seen = {}
    def runner(command, **kwargs):
        seen.setdefault("commands", []).append(command)
        output = json.dumps(RESPONSE) if len(seen["commands"]) == 2 else "[]"
        return subprocess.CompletedProcess(command, 0, output, "")
    client = SockseekClient(config(tmp_path), runner)
    candidates = client.search(Track("АК-47", "В тепле 2 яйца", 268), DownloadProfile())
    assert candidates
    assert "artist=АК-47, title=В тепле 2 яйца" in seen["commands"][1]
    assert len(seen["commands"]) == 4


def test_search_rejects_invalid_json_without_leaking_password(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, "", "fatal error")
    client = SockseekClient(config(tmp_path), runner)
    with pytest.raises(SockseekError) as error:
        client.search(Track("A", "B", 100), DownloadProfile())
    assert "secret" not in str(error.value)


def test_download_builds_direct_soulseek_link_and_skips_existing(tmp_path):
    destination = tmp_path / "library" / "song.mp3"
    def runner(command, **kwargs):
        assert command[1] == "slsk://peer/folder/АК-47 - В тепле 2 яйца.mp3"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"mp3")
        return subprocess.CompletedProcess(command, 0, "", "")
    client = SockseekClient(config(tmp_path), runner)
    candidate = Candidate("soulseek", "folder\\АК-47 - В тепле 2 яйца.mp3", 3, 268, MediaFormat.MP3, peer="peer")
    assert client.download(candidate, destination) == destination
    assert client.download(candidate, destination) == destination


def test_parser_skips_unknown_duration_and_accepts_bit_depth():
    valid = RESPONSE[0]
    valid["File"]["BitDepth"] = 16
    missing_length = {"User": valid["User"], "File": {"Filename": "unknown.flac", "Size": 1000}}
    candidates = SockseekClient._parse_candidates(json.dumps([valid, missing_length]))
    assert len(candidates) == 1


def test_download_moves_staged_file_to_requested_destination(tmp_path):
    destination = tmp_path / "library" / "renamed.mp3"
    def runner(command, **kwargs):
        staged = destination.parent / ".sockseek-staging" / "job" / "original.mp3"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"mp3")
        return subprocess.CompletedProcess(command, 0, "", "")
    client = SockseekClient(config(tmp_path), runner)
    candidate = Candidate("soulseek", "original.mp3", 3, 100, MediaFormat.MP3, peer="peer")
    client.download(candidate, destination)
    assert destination.read_bytes() == b"mp3"
