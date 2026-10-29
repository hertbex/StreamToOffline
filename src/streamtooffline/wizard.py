from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from streamtooffline.application.search import TrackSearcher
from streamtooffline.cli import main, make_sockseek, run_tracks
from streamtooffline.domain.models import DownloadProfile, MediaFormat, Track, VersionPolicy
from streamtooffline.infrastructure.csv_source import ExportifyCsvReader
from streamtooffline.infrastructure.console import read_line
from streamtooffline.infrastructure.exportify import ExportifyLauncher
from streamtooffline.infrastructure.exportify_server import ExportifyImportServer
from streamtooffline.infrastructure.state import JobStore
from streamtooffline.infrastructure.tools import Toolchain


def _ask(prompt: str, allow_empty: bool = False, validator=None):
    while True:
        value = read_line(prompt).strip()
        if value.lower() == "q":
            raise KeyboardInterrupt()
        if not value and not allow_empty:
            print("  Value cannot be empty. Enter 'q' to cancel.")
            continue
        if validator and value:
            error = validator(value)
            if error:
                print(f"  {error}")
                continue
        return value


def _ask_yn(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    value = _ask(prompt + suffix, allow_empty=True).lower()
    if not value:
        return default
    return value in {"y", "yes"}


def _validate_url(value: str) -> str | None:
    if "open.spotify.com/playlist/" not in value and "open.spotify.com/album/" not in value:
        return "Expected a Spotify playlist or album URL."
    return None


def _validate_csv_path(value: str) -> str | None:
    path = Path(value)
    if not path.is_file():
        return f"File not found: {value}"
    return None


def _validate_artist_title(value: str) -> str | None:
    if " - " not in value:
        return "Use format: Artist - Title"
    return None


def _pick_profile() -> DownloadProfile:
    name = _ask("Profile [auto/kia/lossless/custom] (auto): ", allow_empty=True).lower() or "auto"
    if name == "kia":
        return DownloadProfile.kia_ceed_ed_fl()
    if name == "lossless":
        return DownloadProfile.lossless()
    if name == "custom":
        profile = DownloadProfile()
        media_format = _ask("Format [auto/mp3/flac] (auto): ", allow_empty=True).lower() or "auto"
        profile = replace(profile, format=MediaFormat(media_format))
        bitrate = _ask("Bitrate kbps (auto): ", allow_empty=True)
        if bitrate:
            profile = replace(profile, min_bitrate_kbps=int(bitrate), preferred_bitrate_kbps=int(bitrate))
        sample_rate = _ask("Sample rate Hz (auto): ", allow_empty=True)
        if sample_rate:
            profile = replace(profile, sample_rate_hz=int(sample_rate))
        version = _ask("Version [auto/original/edits/remixes/all] (auto): ", allow_empty=True).lower() or "auto"
        return replace(profile, version_policy=VersionPolicy(version))
    return DownloadProfile()


def _pick_run_options(*, sort_genres: bool | None = None) -> dict:
    return {
        "profile": _pick_profile(),
        "sort_genres": _ask_yn("Sort by genre/mood", default=True) if sort_genres is None else sort_genres,
        "youtube_fallback": _ask_yn("Use YouTube fallback", default=True),
        "output": _ask("Output folder (library): ", allow_empty=True) or "library",
    }


def _prompt_credentials(
    username: str | None,
    *,
    allow_skip: bool,
    required: bool = False,
) -> tuple[str | None, str | None]:
    username = username or os.getenv("SOULSEEK_USERNAME")
    password = os.getenv("SOULSEEK_PASSWORD")
    suffix = " (Enter to skip)" if allow_skip else ""
    if not username:
        username = _ask(f"Soulseek username{suffix}: ", allow_empty=allow_skip)
    if username and not password:
        password = read_line(
            f"Soulseek password{suffix}: ",
            secret=True,
        ).strip()
    if required and (not username or not password):
        raise RuntimeError("Soulseek username and password are required for search.")
    return username or None, password or None


def _run_exportify(root: Path, playlist_id: str | None = None) -> tuple[tuple[Track, ...], str]:
    launcher = ExportifyLauncher(Toolchain(root))
    server = ExportifyImportServer()
    server.start()
    try:
        print(f"\nOpening Exportify at {launcher.url}")
        print("Log in with Spotify; the requested playlist will be sent automatically.")
        launcher.start(open_browser=True, callback_url=server.url, playlist_id=playlist_id)
        print("Waiting for Exportify to send the playlist...")
        payload = server.wait(timeout=600)
        if payload is None:
            raise RuntimeError("No playlist received from Exportify")
        from io import StringIO
        tracks = ExportifyCsvReader().read(StringIO(payload.csv_text)).tracks
        print(f"Received {len(tracks)} tracks from Exportify.")
        return tracks, Path(payload.filename).stem
    finally:
        server.stop()
        launcher.stop()


def _select_job(root: Path) -> str | None:
    store = JobStore(root / ".state" / "jobs.sqlite3")
    try:
        jobs = store.list_jobs()
        if not jobs:
            print("No unfinished jobs found.")
            return None
        print("\nUnfinished jobs:")
        for idx, job in enumerate(jobs, 1):
            status = job["status"]
            created = job["created_at"].strftime("%Y-%m-%d %H:%M")
            print(f"  {idx}. [{job['id']}] {job['label']} — {status} ({job['completed']}/{job['total']})")
        choice = _ask("Select job number (q to cancel): ")
        try:
            index = int(choice) - 1
            if 0 <= index < len(jobs):
                return jobs[index]["id"]
        except ValueError:
            pass
        print("Invalid selection.")
        return None
    finally:
        store.close()


def _source_song(root: Path, username: str | None) -> int:
    source = _ask("Artist - Title or search query: ")
    password = os.getenv("SOULSEEK_PASSWORD")
    if " - " in source:
        artist, title = source.split(" - ", 1)
        tracks = (Track(artist.strip(), title.strip(), 0),)
    else:
        print("Searching Soulseek...")
        username, password = _prompt_credentials(username, allow_skip=False, required=True)
        sockseek = make_sockseek(root, username, password)
        searcher = TrackSearcher(sockseek)
        matches = searcher.search(source, DownloadProfile())
        if not matches:
            print("No matches found.")
            return 0
        print("\nMatches:")
        for idx, match in enumerate(matches, 1):
            best = max(match.candidates, key=lambda candidate: candidate.size_bytes)
            duration = f"{best.duration_seconds // 60}:{best.duration_seconds % 60:02}"
            size_mib = best.size_bytes / (1024 * 1024)
            print(
                f"  {idx}. {match.track.display_name} "
                f"({len(match.candidates)} sources; {duration}; {size_mib:.1f} MiB)"
            )
        choice = _ask("Select tracks to download (comma-separated numbers, q to cancel): ")
        try:
            indices = {int(x.strip()) - 1 for x in choice.split(",")}
            tracks = tuple(matches[i].track for i in indices if 0 <= i < len(matches))
        except ValueError:
            print("Invalid selection.")
            return 0
        if not tracks:
            print("No tracks selected.")
            return 0
    options = _pick_run_options(sort_genres=False)
    if not password or not username:
        username, password = _prompt_credentials(
            username,
            allow_skip=options["youtube_fallback"],
            required=not options["youtube_fallback"],
        )
    return run_tracks(
        root, username, password,
        tracks, options["profile"], options["output"],
        sort_genres=options["sort_genres"], youtube_fallback=options["youtube_fallback"],
    )


def _source_playlist(root: Path, username: str | None) -> int:
    url = _ask("Spotify playlist URL: ", validator=_validate_url)
    options = _pick_run_options()
    username, password = _prompt_credentials(
        username,
        allow_skip=options["youtube_fallback"],
        required=not options["youtube_fallback"],
    )
    marker = "/playlist/" if "/playlist/" in url else "/album/"
    playlist_id = url.split(marker, 1)[1].split("?", 1)[0].split("/", 1)[0]
    tracks, playlist_name = _run_exportify(root)
    if not tracks:
        print("No tracks received.")
        return 1
    return run_tracks(
        root, username, password,
        tracks, options["profile"], options["output"],
        sort_genres=options["sort_genres"], youtube_fallback=options["youtube_fallback"],
        job_name=playlist_name,
    )


def _source_csv(root: Path, username: str | None) -> int:
    job_name = None
    use_exportify = _ask_yn("Do you need to export CSV from Exportify")
    if use_exportify:
        tracks, job_name = _run_exportify(root)
    else:
        path = _ask("CSV path: ", validator=_validate_csv_path)
        tracks = ExportifyCsvReader().read(Path(path)).tracks
    if not tracks:
        print("No tracks to download.")
        return 1
    options = _pick_run_options()
    username, password = _prompt_credentials(
        username,
        allow_skip=options["youtube_fallback"],
        required=not options["youtube_fallback"],
    )
    return run_tracks(
        root, username, password,
        tracks, options["profile"], options["output"],
        sort_genres=options["sort_genres"], youtube_fallback=options["youtube_fallback"],
        job_name=job_name,
    )


def _retry_job(root: Path, username: str | None) -> int:
    job_id = _select_job(root)
    if not job_id:
        return 0
    argv = ["--root", str(root), "retry", job_id, "--yes"]
    if username:
        argv += ["--username", username]
    return main(argv)


def _doctor(root: Path) -> int:
    return main(["--root", str(root), "doctor"])


def run_wizard(args) -> int:
    root = Path(args.root)
    username = args.username or os.getenv("SOULSEEK_USERNAME")

    while True:
        print("\n" + "=" * 64)
        print(" StreamToOffline")
        print("=" * 64)
        print("  1. Download a single song")
        print("  2. Download a Spotify playlist")
        print("  3. Download from Exportify CSV")
        print("  4. Retry an unfinished job")
        print("  5. Check tools (doctor)")
        print("  0. Exit")
        choice = read_line("\nSelect: ").strip().lower()

        if not choice:
            continue
        if choice == "q" or choice == "0":
            return 0
        if choice == "5":
            try:
                _doctor(root)
            except Exception as exc:
                print(f"Error: {exc}")
            read_line("\nPress Enter to return to the menu...")
            continue

        try:
            if choice == "1":
                result = _source_song(root, username)
            elif choice == "2":
                result = _source_playlist(root, username)
            elif choice == "3":
                result = _source_csv(root, username)
            elif choice == "4":
                result = _retry_job(root, username)
            else:
                print("Unknown option. Try again.")
                continue
            print(f"\nFinished. Exit code: {result}")
        except KeyboardInterrupt:
            print("\nCancelled. Returning to menu.")
        except Exception as exc:
            print(f"\nError: {exc}")
        read_line("\nPress Enter to return to the menu...")
