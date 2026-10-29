from __future__ import annotations

import argparse
import os
import time
import uuid
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

from .application.download import DownloadService
from .domain.library import MetadataRules, safe_filename
from .domain.models import DownloadJob, DownloadProfile, MediaFormat, Track, VersionPolicy
from .domain.planner import LibraryPlanner
from .infrastructure.csv_source import ExportifyCsvReader
from .infrastructure.console import read_line
from .infrastructure.exportify import ExportifyLauncher
from .infrastructure.exportify_server import ExportifyImportServer
from .infrastructure.ffmpeg import AudioProcessor
from .infrastructure.sockseek import SockseekClient, SockseekConfig
from .infrastructure.state import JobStore
from .infrastructure.tags import TagWriter
from .infrastructure.tools import Toolchain
from .infrastructure.youtube import YouTubeFallback


class _UnavailableSockseek:
    def search(self, track, profile):
        return ()

    def download(self, candidate, destination):
        raise RuntimeError("Soulseek credentials are not configured")


def format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", choices=("auto", "kia", "lossless", "custom"), default="auto")
    parser.add_argument("--format", choices=("auto", "mp3", "flac"))
    parser.add_argument("--bitrate", type=int)
    parser.add_argument("--sample-rate", type=int)
    parser.add_argument("--version", choices=tuple(item.value for item in VersionPolicy))
    parser.add_argument("--youtube-fallback", action="store_true")
    parser.add_argument("--no-sort", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation")
    parser.add_argument("--output", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="streamtooffline")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--username", default=os.getenv("SOULSEEK_USERNAME"))
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("wizard", help="Interactive download wizard")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--root", type=Path, default=Path.cwd())
    doctor.add_argument("--install-ffmpeg", action="store_true")
    doctor.add_argument("--install-sockseek", action="store_true")
    doctor.add_argument("--fix", action="store_true")
    for name in ("song", "csv", "playlist"):
        command = sub.add_parser(name)
        command.add_argument("source", help="Artist - Title, CSV path, or Spotify playlist URL")
        add_run_options(command)
    retry = sub.add_parser("retry")
    retry.add_argument("job_id")
    add_run_options(retry)
    return parser


def profile_from_args(args) -> DownloadProfile:
    if args.profile == "kia":
        profile = DownloadProfile.kia_ceed_ed_fl()
    elif args.profile == "lossless":
        profile = DownloadProfile.lossless()
    else:
        profile = DownloadProfile()
    changes = {}
    if args.format:
        changes["format"] = MediaFormat(args.format)
    if args.bitrate:
        changes["min_bitrate_kbps"] = args.bitrate
        changes["preferred_bitrate_kbps"] = args.bitrate
    if args.sample_rate:
        changes["sample_rate_hz"] = args.sample_rate
    if args.version:
        changes["version_policy"] = VersionPolicy(args.version)
    if args.youtube_fallback:
        changes["youtube_fallback"] = True
    return replace(profile, **changes)


def _locate_required_tools(
    root: Path,
    *,
    require_ffmpeg: bool = True,
    require_sockseek: bool = True,
    require_ytdlp: bool = True,
) -> dict[str, Path]:
    tools = Toolchain(root)
    names = []
    if require_ffmpeg:
        names.append("ffmpeg")
    if require_sockseek:
        names.append("sockseek")
    if require_ytdlp:
        names.append("yt-dlp")
    required = {name: tools.locate(name) for name in names}
    missing = [name for name, status in required.items() if not status.available]
    if missing:
        raise RuntimeError(f"Missing tools: {', '.join(missing)}")
    return {name: status.path for name, status in required.items() if status.path}


def make_sockseek(root: Path, username: str | None, password: str | None) -> SockseekClient:
    username = username or os.getenv("SOULSEEK_USERNAME")
    password = password or os.getenv("SOULSEEK_PASSWORD")
    if not username or not password:
        raise RuntimeError("Soulseek credentials are required for Soulseek search")
    paths = _locate_required_tools(root, require_ffmpeg=False, require_ytdlp=False)
    return SockseekClient(SockseekConfig(
        paths["sockseek"], username, password, root / ".state" / "tmp",
    ))


def make_service_with_credentials(
    root: Path,
    username: str | None,
    password: str | None,
    *,
    youtube_fallback: bool = True,
) -> tuple[DownloadService, JobStore]:
    username = username or os.getenv("SOULSEEK_USERNAME")
    password = password or os.getenv("SOULSEEK_PASSWORD")
    paths = _locate_required_tools(
        root,
        require_sockseek=bool(username and password),
        require_ytdlp=youtube_fallback,
    )
    store = JobStore(root / ".state" / "jobs.sqlite3")
    sockseek = (
        SockseekClient(SockseekConfig(paths["sockseek"], username, password, root / ".state" / "tmp"))
        if username and password else _UnavailableSockseek()
    )
    processor = AudioProcessor(paths["ffmpeg"])
    fallback = (
        YouTubeFallback(paths["yt-dlp"], paths["ffmpeg"])
        if youtube_fallback else None
    )
    rules = MetadataRules.load(
        root / "config" / "artists.yml",
        root / "config" / "genres.yml",
        root / "config" / "adaptive.yml",
    )
    return DownloadService(sockseek, processor, fallback, TagWriter(), rules, store, root / ".state" / "work"), store


def make_service(root: Path, args) -> tuple[DownloadService, JobStore]:
    return make_service_with_credentials(
        root, args.username, None, youtube_fallback=args.youtube_fallback,
    )


def run_tracks(
    root: Path,
    username: str | None,
    password: str | None,
    tracks: tuple[Track, ...],
    profile: DownloadProfile,
    output: Path | str,
    *,
    sort_genres: bool = True,
    youtube_fallback: bool = False,
    yes: bool = False,
    job_name: str | None = None,
) -> int:
    if youtube_fallback:
        profile = replace(profile, youtube_fallback=True)
    if not username:
        username = os.getenv("SOULSEEK_USERNAME")
    if not password:
        password = os.getenv("SOULSEEK_PASSWORD")
    if not username:
        username = read_line("Soulseek username (Enter to skip): ").strip()
    if not password and username:
        password = read_line("Soulseek password (Enter to skip): ", secret=True).strip()
    if not username or not password:
        if not profile.youtube_fallback:
            raise RuntimeError("Soulseek login/password are required unless YouTube fallback is enabled.")
        print("Soulseek credentials not set; using YouTube fallback only.")
    service, store = make_service_with_credentials(
        root, username, password, youtube_fallback=profile.youtube_fallback,
    )
    try:
        output_path = Path(output)
        if job_name:
            output_path = output_path / safe_filename(job_name)
        job = DownloadJob(
            tracks, profile, uuid.uuid4().hex[:12],
            name=job_name, output_root=str(output_path),
        )
        return _execute(job, service, store, output_path, sort_genres=sort_genres, yes=yes)
    finally:
        store.close()


def _execute(
    job: DownloadJob,
    service: DownloadService,
    store: JobStore,
    output: Path | str,
    *,
    sort_genres: bool = True,
    yes: bool = False,
) -> int:
    if sort_genres:
        service.use_adaptive(job.tracks)
        preview = service.rules.adaptive_library.preview()
        if preview:
            print("Adaptive categories:")
            for name, _ in preview:
                print(f"  - {name}")
    estimate = LibraryPlanner().estimate(job.tracks, job.profile)
    size = format_bytes(estimate.min_bytes) if estimate.min_bytes == estimate.max_bytes else f"{format_bytes(estimate.min_bytes)}–{format_bytes(estimate.max_bytes)}"
    print(f"Tracks: {estimate.track_count}; duration: {format_duration(estimate.duration_seconds)}; size: {size} ({estimate.basis})")
    if not yes and read_line("Start download? [Y/n] ").strip().lower() not in {"", "y", "yes"}:
        return 0
    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    started = time.monotonic()
    downloaded = 0

    def progress(event) -> None:
        nonlocal downloaded
        if event.status == "started":
            print(f"[{event.index}/{event.total}] {event.track.display_name}")
            if event.selection_report:
                print(f"      {event.selection_report.summary}")
        elif event.status == "completed":
            downloaded += event.size_bytes
            elapsed = max(0.001, time.monotonic() - started)
            speed = downloaded / elapsed
            eta = LibraryPlanner.transfer_seconds(max(0, estimate.min_bytes - downloaded), speed)
            eta_text = format_duration(eta) if eta is not None else "unknown"
            print(
                f"  OK {format_bytes(event.size_bytes)}; total {format_bytes(downloaded)}; "
                f"speed {format_bytes(int(speed))}/s; elapsed {format_duration(int(elapsed))}; "
                f"ETA {eta_text} {event.message}"
            )
        else:
            print(f"  FAILED: {event.message}")

    summary = service.run(job, output_path, sort_genres=sort_genres, on_event=progress)
    print(f"Job {job.id}: {summary}; output: {output_path}")
    return 0 if not summary.get("failed") else 1


def execute(job: DownloadJob, args, service: DownloadService, store: JobStore) -> int:
    output = Path(job.output_root) if job.output_root else (args.output or args.root / "library")
    return _execute(job, service, store, output, sort_genres=not args.no_sort, yes=args.yes)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        toolchain = Toolchain(args.root)
        if args.fix:
            from .infrastructure.tool_fixer import ToolFixer
            ToolFixer(args.root, toolchain.platform_name).fix(progress=print)
            toolchain = Toolchain(args.root)
        statuses = toolchain.doctor()
        for status in statuses:
            print(f"{status.name:12} {'OK' if status.available else 'MISSING':7} {status.path or 'not found'}")
        ffmpeg_status = next((s for s in statuses if s.name == "ffmpeg"), None)
        if not ffmpeg_status or not ffmpeg_status.available:
            if args.install_ffmpeg:
                from .infrastructure.ffmpeg_installer import FFmpegInstaller
                installer = FFmpegInstaller(args.root, toolchain.platform_name)
                if installer.is_needed():
                    installer.install(progress=print)
                    return 0
            from .infrastructure.ffmpeg_installer import FFmpegInstaller
            print(FFmpegInstaller.instructions(toolchain.platform_name))
        sockseek_status = next((s for s in statuses if s.name == "sockseek"), None)
        if not sockseek_status or not sockseek_status.available:
            if args.install_sockseek:
                from .infrastructure.sockseek_installer import SockseekInstaller
                installer = SockseekInstaller(args.root, toolchain.platform_name)
                installer.install(progress=print)
                return 0
            from .infrastructure.sockseek_installer import SockseekInstaller
            print(SockseekInstaller.instructions(toolchain.platform_name))
        return 0 if all(status.available for status in statuses) else 1
    if args.command in {None, "wizard"}:
        from .tui import run_tui
        return run_tui(Path(args.root))

    if args.command == "retry":
        store = JobStore(args.root / ".state" / "jobs.sqlite3")
        try:
            job = store.load_job(args.job_id)
            service, service_store = make_service_with_credentials(
                args.root,
                args.username,
                None,
                youtube_fallback=job.profile.youtube_fallback,
            )
            store.close()
            store = service_store
            return execute(job, args, service, store)
        finally:
            store.close()

    playlist_name = None
    if args.command == "song":
        if " - " not in args.source:
            raise ValueError("Use format: Artist - Title")
        artist, title = args.source.split(" - ", 1)
        tracks = (Track(artist.strip(), title.strip(), 0),)
    elif args.command == "csv":
        result = ExportifyCsvReader().read(Path(args.source))
        tracks = result.tracks
        for error in result.errors:
            print(f"CSV line {error.line}: {error.message}")
    else:
        launcher = ExportifyLauncher(Toolchain(args.root))
        server = ExportifyImportServer()
        server.start()
        try:
            launcher.start(callback_url=server.url)
            print("Waiting for Exportify to send the playlist...")
            payload = server.wait(timeout=600)
            if payload is None:
                raise RuntimeError("No playlist received from Exportify")
            tracks = ExportifyCsvReader().read(StringIO(payload.csv_text)).tracks
            playlist_name = Path(payload.filename).stem
        finally:
            server.stop()
            launcher.stop()
    if not tracks:
        raise ValueError("No tracks to download")
    output = args.output or args.root / "library"
    return run_tracks(
        args.root, args.username, os.getenv("SOULSEEK_PASSWORD"),
        tuple(tracks), profile_from_args(args), output,
        sort_genres=not args.no_sort, yes=args.yes,
        job_name=playlist_name,
    )


if __name__ == "__main__":
    raise SystemExit(main())
