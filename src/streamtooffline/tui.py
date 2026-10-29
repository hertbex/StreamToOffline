from __future__ import annotations

import contextlib
import io
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Select, Static

if __package__:
    from .cli import run_tracks
    from .domain.models import DownloadProfile, MediaFormat, Track, VersionPolicy
    from .infrastructure.csv_source import ExportifyCsvReader
    from .infrastructure.credentials import CredentialStore
    from .infrastructure.sockseek import SockseekClient, SockseekConfig
    from .infrastructure.state import JobStore
    from .infrastructure.tools import Toolchain
    from .wizard import _run_exportify
else:
    # Support `python src/streamtooffline/tui.py` for local development.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from streamtooffline.cli import run_tracks
    from streamtooffline.domain.models import DownloadProfile, MediaFormat, Track, VersionPolicy
    from streamtooffline.infrastructure.csv_source import ExportifyCsvReader
    from streamtooffline.infrastructure.credentials import CredentialStore
    from streamtooffline.infrastructure.sockseek import SockseekClient, SockseekConfig
    from streamtooffline.infrastructure.state import JobStore
    from streamtooffline.infrastructure.tools import Toolchain
    from streamtooffline.wizard import _run_exportify


PROFILE_OPTIONS = [
    ("Auto - choose the best available quality", "auto"),
    ("Kia Ceed - MP3 320 kbps / 44.1 kHz", "kia"),
    ("Lossless - FLAC/WAV", "lossless"),
    ("Custom - set format and quality manually", "custom"),
]
FORMAT_OPTIONS = [
    ("Auto - keep the source format", "auto"),
    ("MP3", "mp3"),
    ("FLAC", "flac"),
]
VERSION_OPTIONS = [
    ("Auto - prefer the original version", "auto"),
    ("Original", "original"),
    ("Edits", "edits"),
    ("Remixes", "remixes"),
    ("All versions", "all"),
]


class NoticeScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close_notice", "Close")]

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self.title_text = title
        self.message = message

    def compose(self) -> ComposeResult:
        yield Container(
            Label(self.title_text, id="dialog-title"),
            VerticalScroll(Static(self.message, id="dialog-message"), id="dialog-scroll"),
            Button("Close", variant="primary", id="close"),
            id="dialog",
        )

    def action_close_notice(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class ProgressScreen(ModalScreen[None]):
    BINDINGS = [("escape", "cancel_progress", "Back")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title_text = title
        self.lines: list[str] = [title]
        self.started_at = time.monotonic()

    def compose(self) -> ComposeResult:
        yield Container(
            Label(self.title_text, id="dialog-title"),
            VerticalScroll(Static(self.title_text, id="progress-message"), id="progress-scroll"),
            Button("Minimize to status bar", id="minimize"),
            id="dialog",
        )

    def on_mount(self) -> None:
        self.set_interval(1, self._tick)

    def _tick(self) -> None:
        elapsed = int(time.monotonic() - self.started_at)
        if not self.lines or "Elapsed" not in self.lines[-1]:
            self.update_message(f"Elapsed: {elapsed // 60:02}:{elapsed % 60:02} — operation is still running")

    def update_message(self, message: str) -> None:
        self.lines.extend(line for line in message.splitlines() if line.strip())
        try:
            widget = self.query_one("#progress-message", Static)
            widget.update("\n".join(self.lines[-100:]))
            self.query_one("#progress-scroll", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass

    def action_cancel_progress(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "minimize":
            self.app.minimize_progress()


class ErrorScreen(ModalScreen[None]):
    BINDINGS = [("escape", "back_to_menu", "Back to menu")]

    def __init__(self, message: str, retry) -> None:
        super().__init__()
        self.message = message
        self.retry = retry

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Download failed", id="dialog-title"),
            VerticalScroll(Static(self.message, id="dialog-message"), id="dialog-scroll"),
            Horizontal(
                Button("Back to menu", id="back"),
                Button("Retry", variant="primary", id="retry"),
            ),
            id="dialog",
        )

    def action_back_to_menu(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "retry":
            self.dismiss(None)
            self.retry()
        else:
            self.dismiss(None)


class _LiveOutput(io.TextIOBase):
    def __init__(self, app: "StreamToOfflineApp") -> None:
        self.app = app

    def write(self, text: str) -> int:
        if text.strip():
            self.app._write_progress(text)
        return len(text)

    def flush(self) -> None:
        return None


class JobScreen(ModalScreen[dict[str, Any] | None]):
    BINDINGS = [
        ("escape", "cancel_form", "Cancel"),
        ("enter", "confirm_form", "Confirm"),
    ]
    def __init__(self, jobs: tuple[dict, ...]) -> None:
        super().__init__()
        self.jobs = jobs

    def compose(self) -> ComposeResult:
        options = [
            (f"{job['label']} — {job['completed']}/{job['total']} ({job['status']})", job["id"])
            for job in self.jobs
        ]
        yield Container(
            Label("Retry unfinished job", id="dialog-title"),
            Select(options, id="job-select", prompt="Choose a job"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Retry", variant="primary", id="submit"),
            ),
            id="dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#job-select", Select).focus()

    def action_cancel_form(self) -> None:
        self.dismiss(None)

    def action_confirm_form(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-exportify":
            self.app.open_exportify()
            return
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "submit":
            self._submit()

    def _submit(self) -> None:
        value = self.query_one("#job-select", Select).value
        if value is Select.BLANK:
            self.dismiss(None)
            return
        self.dismiss({"job_id": str(value)})


class CredentialsScreen(ModalScreen[dict[str, str] | None]):
    BINDINGS = [
        ("escape", "cancel_credentials", "Cancel"),
        ("enter", "save_credentials", "Save"),
    ]

    def compose(self) -> ComposeResult:
        username, password = CredentialStore(self.app.root).load()
        yield Container(
            Label("Soulseek credentials", id="dialog-title"),
            Static("Saved locally in the repository state. Use Test connection before saving.", id="dialog-message"),
            Input(value=username, placeholder="Soulseek username", id="username"),
            Input(value=password, placeholder="Soulseek password", password=True, id="password"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Test connection", id="test"),
                Button("Save", variant="primary", id="save"),
            ),
            id="dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#username", Input).focus()

    def action_cancel_credentials(self) -> None:
        self.dismiss(None)

    def action_save_credentials(self) -> None:
        self._save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "test":
            self.app.test_credentials(
                self.query_one("#username", Input).value.strip(),
                self.query_one("#password", Input).value,
            )
        elif event.button.id == "save":
            self._save()

    def _save(self) -> None:
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not username or not password:
            self.app.push_screen(NoticeScreen("Credentials required", "Enter both username and password."))
            return
        self.dismiss({"username": username, "password": password})


class CandidateScreen(ModalScreen[dict[str, Any] | None]):
    BINDINGS = [
        ("escape", "cancel_choice", "Cancel"),
        ("enter", "confirm_choice", "Choose"),
    ]

    def __init__(self, source: str, candidates: tuple[Any, ...]) -> None:
        super().__init__()
        self.source = source
        self.candidates = candidates

    def compose(self) -> ComposeResult:
        options = []
        for candidate in self.candidates:
            duration = (
                f"{candidate.duration_seconds // 60}:{candidate.duration_seconds % 60:02}"
                if candidate.duration_seconds else "unknown length"
            )
            options.append((f"{candidate.title} — {candidate.channel} ({duration})", candidate.title))
        yield Container(
            Label("Choose the exact version", id="dialog-title"),
            Static("The original title will be used for the downloaded filename.", id="dialog-message"),
            Select(options, id="candidate", prompt="Select a result"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Download selected", variant="primary", id="submit"),
            ),
            id="dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#candidate", Select).focus()

    def action_cancel_choice(self) -> None:
        self.dismiss(None)

    def action_confirm_choice(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "submit":
            self._submit()

    def _submit(self) -> None:
        value = self.query_one("#candidate", Select).value
        if value is Select.BLANK:
            return
        self.dismiss({"title": str(value)})


class DownloadScreen(ModalScreen[dict[str, Any] | None]):
    BINDINGS = [
        ("escape", "cancel_form", "Cancel"),
        ("enter", "confirm_form", "Confirm"),
    ]
    def __init__(self, kind: str) -> None:
        super().__init__()
        self.kind = kind

    def compose(self) -> ComposeResult:
        source_label = {
            "song": "Artist - Title",
            "playlist": "Spotify playlist or album URL",
            "csv": "CSV path",
        }[self.kind]
        yield Container(
            VerticalScroll(
                Label(f"Download: {self.kind.title()}", id="dialog-title"),
            Input(placeholder=f"{source_label} (required)", id="source"),
            Button("Open Exportify", id="open-exportify") if self.kind == "csv" else Static(""),
            Select(PROFILE_OPTIONS, value="auto", id="profile", prompt="Profile - default: Auto"),
            Select(FORMAT_OPTIONS, value="auto", id="format", prompt="Format - default: source format"),
            Input(placeholder="Bitrate in kbps (optional; profile default)", id="bitrate"),
            Input(placeholder="Sample rate in Hz (optional; source default)", id="sample-rate"),
            Select(VERSION_OPTIONS, value="auto", id="version", prompt="Version - default: original"),
            Input(value=CredentialStore(self.app.root).load()[0], placeholder="Soulseek username (saved in Credentials)", id="username"),
            Input(value=CredentialStore(self.app.root).load()[1], placeholder="Soulseek password (saved in Credentials)", password=True, id="password"),
            Input(value="", placeholder="Output folder (default: library)", id="output"),
            Checkbox("YouTube fallback (default: enabled)", value=True, id="youtube"),
            Checkbox("Sort by genre/mood (default: enabled)", value=True, id="sort"),
            ),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Confirm", variant="primary", id="submit"),
            ),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "submit":
            self._submit()

    def on_mount(self) -> None:
        self.query_one("#source", Input).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "profile":
            return
        profile = self._profile_for_name(str(event.value))
        if profile is None:
            return
        self.query_one("#format", Select).value = profile.format.value
        self.query_one("#bitrate", Input).value = str(profile.preferred_bitrate_kbps or "")
        self.query_one("#sample-rate", Input).value = str(profile.sample_rate_hz or "")
        self.query_one("#version", Select).value = profile.version_policy.value

    def action_cancel_form(self) -> None:
        self.dismiss(None)

    def action_confirm_form(self) -> None:
        self._submit()

    def _submit(self) -> None:
        values: dict[str, Any] = {
            "kind": self.kind,
            "source": self.query_one("#source", Input).value.strip(),
            "profile": self.query_one("#profile", Select).value,
            "format": self.query_one("#format", Select).value,
            "bitrate": self.query_one("#bitrate", Input).value.strip(),
            "sample_rate": self.query_one("#sample-rate", Input).value.strip(),
            "version": self.query_one("#version", Select).value,
            "username": self.query_one("#username", Input).value.strip(),
            "password": self.query_one("#password", Input).value,
            "output": self.query_one("#output", Input).value.strip() or "library",
            "youtube": self.query_one("#youtube", Checkbox).value,
            "sort": self.query_one("#sort", Checkbox).value,
        }
        if not values["source"]:
            self.app.push_screen(NoticeScreen("Input required", "Fill in the source field, then press Confirm."))
            return
        self.dismiss(values)

    @staticmethod
    def _profile_for_name(name: str) -> DownloadProfile | None:
        if name == "kia":
            return DownloadProfile.kia_ceed_ed_fl()
        if name == "lossless":
            return DownloadProfile.lossless()
        if name == "auto":
            return DownloadProfile()
        return None


class MainScreen(Screen):
    BINDINGS = [
        ("escape", "quit_app", "Exit"),
    ]
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            Static("StreamToOffline", id="title"),
            Static("Offline music library builder", id="subtitle"),
            Button("Download a single song", id="song"),
            Button("Download Spotify playlist", id="playlist"),
            Button("Download from CSV", id="csv"),
            Button("Retry unfinished job", id="retry"),
            Button("Soulseek credentials", id="credentials"),
            Button("Check / fix tools", id="doctor"),
            Button("Exit", id="exit"),
            id="menu",
        )
        yield Button("No active download", id="statusbar")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#song", Button).focus()
        self.query_one("#statusbar", Button).display = False

    def on_key(self, event) -> None:
        if event.key in {"down", "right"}:
            self.focus_next()
            event.stop()
        elif event.key in {"up", "left"}:
            self.focus_previous()
            event.stop()

    def action_quit_app(self) -> None:
        self.app.exit(0)


class StreamToOfflineApp(App[int]):
    CSS = """
    Screen { align: center middle; }
    #menu { width: 58; padding: 2 4; border: round $accent; }
    #title { text-align: center; text-style: bold; color: $accent; }
    #subtitle { text-align: center; margin-bottom: 2; color: $text-muted; }
    #menu Button { width: 100%; margin: 1 0; }
    #statusbar { dock: bottom; width: 100%; background: $panel; color: $text; }
    ModalScreen { background: $background 80%; }
    #dialog { width: 80; height: 90%; padding: 2 3; border: round $accent; background: $surface; }
    #dialog > VerticalScroll { height: 1fr; }
    #dialog-title { text-style: bold; margin-bottom: 1; }
    #dialog Input, #dialog Select { margin: 1 0; }
    #dialog Checkbox { width: 1fr; }
    #dialog Button { margin: 1 1 0 0; }
    #dialog-message { margin: 1 0 2 0; }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self._last_action = None
        self._last_values: dict[str, Any] | None = None
        self._progress_lines: list[str] = []
        self._worker_active = False

    def on_mount(self) -> None:
        self.push_screen(MainScreen())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "exit":
            self.exit(0)
        elif button_id in {"song", "playlist", "csv"}:
            self.push_screen(DownloadScreen(button_id), self._download_form_done)
        elif button_id == "retry":
            self._open_retry()
        elif button_id == "credentials":
            self.push_screen(CredentialsScreen(), self._credentials_done)
        elif button_id == "statusbar":
            self.restore_progress()
        elif button_id == "doctor":
            self._show_doctor()

    def _download_form_done(self, values: dict[str, Any] | None) -> None:
        if values is not None:
            if values["kind"] == "song":
                self._run_in_background(self._find_song_variants, values, "Searching exact song versions...")
            else:
                self._run_in_background(self._download, values, "Preparing download...")

    def _open_retry(self) -> None:
        store = JobStore(self.root / ".state" / "jobs.sqlite3")
        try:
            jobs = store.list_jobs()
        finally:
            store.close()
        if not jobs:
            self.push_screen(NoticeScreen("Retry", "No unfinished jobs found."))
            return
        self.push_screen(JobScreen(jobs), self._retry_done)

    def _retry_done(self, values: dict[str, Any] | None) -> None:
        if values is not None:
            self._run_in_background(self._retry, values, "Retrying job...")

    def _credentials_done(self, values: dict[str, str] | None) -> None:
        if values is not None:
            CredentialStore(self.root).save(values["username"], values["password"])
            self.push_screen(NoticeScreen("Credentials saved", "Soulseek credentials are saved for future runs."))

    def test_credentials(self, username: str, password: str) -> None:
        if not username or not password:
            self.push_screen(NoticeScreen("Credentials required", "Enter both username and password first."))
            return
        self._run_in_background(self._check_credentials, {"username": username, "password": password}, "Testing Soulseek connection...")

    def _check_credentials(self, values: dict[str, str]) -> None:
        try:
            path = Toolchain(self.root).locate("sockseek").path
            if not path:
                raise RuntimeError("Sockseek is not installed.")
            client = SockseekClient(SockseekConfig(path, values["username"], values["password"], self.root / ".state" / "tmp"))
            result = client.check_credentials()
            self._write_status(result)
        except Exception as exc:
            self._write_error(str(exc))

    def _show_doctor(self) -> None:
        try:
            from streamtooffline.infrastructure.tool_fixer import ToolFixer

            ToolFixer(self.root).fix(progress=None)
            title = "Tools fixed"
        except Exception as exc:
            title = "Tool setup error"
            statuses = Toolchain(self.root).doctor()
            message = "\n".join(
                f"{status.name:12} {'OK' if status.available else 'MISSING':7} "
                f"{status.path or 'not found'}"
                for status in statuses
            )
            self.push_screen(NoticeScreen(title, f"{exc}\n\n{message}"))
            return
        statuses = Toolchain(self.root).doctor()
        message = "\n".join(
            f"{status.name:12} {'OK' if status.available else 'MISSING':7} "
            f"{status.path or 'not found'}"
            for status in statuses
        )
        self.push_screen(NoticeScreen(title, message))

    def open_exportify(self) -> None:
        try:
            from streamtooffline.infrastructure.exportify import ExportifyLauncher

            ExportifyLauncher(Toolchain(self.root)).start(open_browser=True)
            self.push_screen(NoticeScreen(
                "Exportify opened",
                "Export the playlist or album to CSV, then enter the downloaded CSV path.",
            ))
        except Exception as exc:
            self.push_screen(NoticeScreen("Exportify error", str(exc)))

    def _run_in_background(self, action, values: dict[str, Any], status: str) -> None:
        if self._worker_active:
            return
        self._worker_active = True
        self._progress_lines = [status]
        self._last_action = action
        self._last_values = dict(values)
        if isinstance(self.screen, ProgressScreen):
            self.pop_screen()
        self.push_screen(ProgressScreen(status))
        self.run_worker(lambda: action(values), thread=True)

    def minimize_progress(self) -> None:
        if isinstance(self.screen, ProgressScreen):
            self._show_progress("Download continues in the background. Press Restore to reopen details.")
            self.pop_screen()
            main = self.screen
            if isinstance(main, MainScreen):
                bar = main.query_one("#statusbar", Button)
                bar.label = "Download running — Restore details"
                bar.display = True
                bar.focus()

    def restore_progress(self) -> None:
        if self._last_action is not None or self._progress_lines:
            screen = ProgressScreen("Download in progress")
            self.push_screen(screen)
            screen.lines = list(self._progress_lines) or screen.lines
            self.call_after_refresh(lambda: screen.update_message(""))

    def _download(self, values: dict[str, Any]) -> None:
        try:
            profile = self._profile(values)
            username = values["username"] or os.getenv("SOULSEEK_USERNAME")
            password = values["password"] or os.getenv("SOULSEEK_PASSWORD")
            if not profile.youtube_fallback and (not username or not password):
                raise RuntimeError("Soulseek credentials are required when YouTube fallback is disabled.")
            kind = values["kind"]
            if kind == "song":
                if " - " not in values["source"]:
                    raise ValueError("Use format: Artist - Title")
                artist, title = values["source"].split(" - ", 1)
                selected_title = values.get("selected_title")
                if selected_title:
                    title = selected_title
                tracks = (Track(artist.strip(), title.strip(), 0),)
                job_name = None
            elif kind == "csv":
                result = ExportifyCsvReader().read(Path(values["source"]))
                tracks, job_name = result.tracks, None
                if result.errors:
                    self._write_status("\n".join(f"CSV line {e.line}: {e.message}" for e in result.errors))
            else:
                tracks, job_name = _run_exportify(self.root)
            if not tracks:
                raise ValueError("No tracks received.")
            output = Path(values["output"])
            buffer = io.StringIO()
            with contextlib.redirect_stdout(_LiveOutput(self)):
                code = run_tracks(
                    self.root, username, password, tuple(tracks), profile, output,
                    sort_genres=values["sort"], youtube_fallback=profile.youtube_fallback,
                    yes=True, job_name=job_name,
                )
            self._write_status(f"Finished with exit code {code}.")
        except Exception as exc:
            self._write_error(str(exc))

    def _find_song_variants(self, values: dict[str, Any]) -> None:
        try:
            from streamtooffline.infrastructure.youtube import YouTubeFallback

            paths = Toolchain(self.root)
            yt = paths.locate("yt-dlp")
            ffmpeg = paths.locate("ffmpeg")
            if not yt.path or not ffmpeg.path:
                raise RuntimeError("yt-dlp and ffmpeg are required to search song versions.")
            artist, title = values["source"].split(" - ", 1)
            fallback = YouTubeFallback(yt.path, ffmpeg.path)
            candidates = fallback.search(Track(artist.strip(), title.strip(), 0))
            self.call_from_thread(self._show_song_candidates, values, candidates)
        except Exception as exc:
            self._write_status(f"Song search failed: {exc}")

    def _show_song_candidates(self, values: dict[str, Any], candidates: tuple[Any, ...]) -> None:
        self._worker_active = False
        if isinstance(self.screen, NoticeScreen):
            self.pop_screen()
        if not candidates:
            self.push_screen(NoticeScreen("No versions found", "No YouTube results matched this song."))
            return
        self.push_screen(
            CandidateScreen(values["source"], candidates),
            lambda choice: self._candidate_done(values, choice),
        )

    def _candidate_done(self, values: dict[str, Any], choice: dict[str, Any] | None) -> None:
        if choice is None:
            return
        values = dict(values)
        selected_title = choice["title"].strip()
        artist = values["source"].split(" - ", 1)[0].strip()
        prefix = f"{artist} - "
        if selected_title.casefold().startswith(prefix.casefold()):
            selected_title = selected_title[len(prefix):].strip()
        values["selected_title"] = selected_title
        self._run_in_background(self._download, values, "Downloading selected version...")

    def _retry(self, values: dict[str, Any]) -> None:
        try:
            from streamtooffline.cli import make_service_with_credentials, execute

            store = JobStore(self.root / ".state" / "jobs.sqlite3")
            job = store.load_job(values["job_id"])
            username = os.getenv("SOULSEEK_USERNAME")
            password = os.getenv("SOULSEEK_PASSWORD")
            service, service_store = make_service_with_credentials(
                self.root, username, password, youtube_fallback=job.profile.youtube_fallback,
            )
            store.close()
            buffer = io.StringIO()
            with contextlib.redirect_stdout(_LiveOutput(self)):
                code = execute(job, type("Args", (), {"no_sort": False, "yes": True, "output": None, "root": self.root})(), service, service_store)
            service_store.close()
            self._write_status(f"Finished with exit code {code}.")
        except Exception as exc:
            self._write_error(str(exc))

    def _write_status(self, message: str) -> None:
        self.call_from_thread(self._show_status, message)

    def _write_progress(self, message: str) -> None:
        self.call_from_thread(self._show_progress, message)

    def _write_error(self, message: str) -> None:
        self.call_from_thread(self._show_error, message)

    def _show_progress(self, message: str) -> None:
        self._progress_lines.extend(line for line in message.splitlines() if line.strip())
        if isinstance(self.screen, ProgressScreen):
            self.screen.update_message(message)
        if isinstance(self.screen, MainScreen):
            bar = self.screen.query_one("#statusbar", Button)
            bar.label = message.strip().splitlines()[-1] if message.strip() else "Download running"
            bar.display = True

    def _show_status(self, message: str) -> None:
        self._worker_active = False
        if isinstance(self.screen, ProgressScreen):
            self.pop_screen()
        self.push_screen(NoticeScreen("Result", message))

    def _show_error(self, message: str) -> None:
        self._worker_active = False
        if isinstance(self.screen, ProgressScreen):
            self.pop_screen()
        retry = lambda: self._run_in_background(
            self._last_action, self._last_values or {}, "Retrying download..."
        )
        self.push_screen(ErrorScreen(message, retry))

    @staticmethod
    def _playlist_id(url: str) -> str:
        for marker in ("/playlist/", "/album/"):
            if marker in url:
                return url.split(marker, 1)[1].split("?", 1)[0].split("/", 1)[0]
        raise ValueError("Expected a Spotify playlist or album URL.")

    @staticmethod
    def _profile(values: dict[str, Any]) -> DownloadProfile:
        if values["profile"] == "kia":
            profile = DownloadProfile.kia_ceed_ed_fl()
        elif values["profile"] == "lossless":
            profile = DownloadProfile.lossless()
        else:
            profile = DownloadProfile()
        changes: dict[str, Any] = {}
        if values["format"] != "auto":
            changes["format"] = MediaFormat(values["format"])
        if values["bitrate"]:
            bitrate = int(values["bitrate"])
            changes["min_bitrate_kbps"] = bitrate
            changes["preferred_bitrate_kbps"] = bitrate
        if values["sample_rate"]:
            changes["sample_rate_hz"] = int(values["sample_rate"])
        if values["version"] != "auto":
            changes["version_policy"] = VersionPolicy(values["version"])
        changes["youtube_fallback"] = bool(values["youtube"])
        return replace(profile, **changes)


def run_tui(root: Path) -> int:
    return StreamToOfflineApp(root).run()


if __name__ == "__main__":
    raise SystemExit(run_tui(Path.cwd()))
