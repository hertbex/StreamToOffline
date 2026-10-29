from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from streamtooffline.domain.library import MetadataRules, track_relative_path
from streamtooffline.domain.models import DownloadJob, MediaFormat, Track
from streamtooffline.domain.planner import CandidateSelector, SelectionReport


@dataclass(frozen=True, slots=True)
class DownloadEvent:
    status: str
    index: int
    total: int
    track: Track
    path: Path | None = None
    size_bytes: int = 0
    message: str = ""
    selection_report: SelectionReport | None = None


class DownloadService:
    def __init__(self, sockseek, processor, fallback, tags, rules, store, work_root: Path) -> None:
        self.sockseek = sockseek
        self.processor = processor
        self.fallback = fallback
        self.tags = tags
        self.rules = rules
        self.store = store
        self.work_root = work_root
        self.selector = CandidateSelector()

    def use_adaptive(self, tracks: tuple[Track, ...]) -> None:
        self.rules.use_adaptive(tracks)

    def run(
        self,
        job: DownloadJob,
        output_root: Path,
        *,
        sort_genres: bool = True,
        on_event: Callable[[DownloadEvent], None] | None = None,
    ) -> dict[str, int]:
        self.store.create_job(job)
        tracks = self.store.unfinished_tracks(job.id)
        total = len(tracks)
        bucket_numbers: dict[str, int] = {}
        if sort_genres:
            for track in job.tracks:
                bucket = self.rules.classify(track, adaptive=True)
                if bucket not in bucket_numbers:
                    bucket_numbers[bucket] = len(bucket_numbers) + 1
        for index, original in enumerate(tracks, 1):
            track = self.rules.normalize_artists(original)
            search_results = self.sockseek.search(track, job.profile)
            report = self.selector.diagnose(track, search_results, job.profile)
            self._emit(on_event, "started", index, total, original, report=report)
            try:
                path, warning = self._download_one(
                    job, original, output_root, sort_genres, index, search_results,
                    report=report, bucket_numbers=bucket_numbers,
                )
                self.store.mark_completed(job.id, original, path)
                self._emit(on_event, "completed", index, total, original, path, path.stat().st_size, warning)
            except Exception as exc:
                self.store.mark_failed(job.id, original, str(exc))
                self._emit(on_event, "failed", index, total, original, message=str(exc))
        return self.store.summary(job.id)

    def _download_one(
        self, job, original: Track, output_root: Path, sort_genres: bool, index: int,
        search_results: tuple[Candidate, ...] = (),
        report: SelectionReport | None = None,
        bucket_numbers: dict[str, int] | None = None,
    ) -> tuple[Path, str]:
        track = self.rules.normalize_artists(original)
        bucket = self.rules.classify(original, adaptive=sort_genres) if sort_genres else None
        if bucket and bucket_numbers is not None:
            if bucket not in bucket_numbers:
                bucket_numbers[bucket] = len(bucket_numbers) + 1
            bucket = f"{bucket_numbers[bucket]:02d}_{bucket}"
        if report is None:
            report = self.selector.diagnose(track, search_results, job.profile)
        warning = ""
        last_error = ""
        candidates = self.selector.ranked(track, search_results, job.profile) if search_results else ()
        for attempt, candidate in enumerate(candidates, 1):
            extension = candidate.format.value if job.profile.format is MediaFormat.AUTO else job.profile.format.value
            final_path = output_root / track_relative_path(track, bucket, extension)
            raw_path = self.work_root / job.id / f"{index}_{attempt}.{candidate.format.value}"
            try:
                self.sockseek.download(candidate, raw_path)
                proc_report = self.processor.convert(raw_path, job.profile, final_path)
                if proc_report.path != final_path:
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    proc_report.path.replace(final_path)
                if raw_path.exists() and raw_path != final_path:
                    raw_path.unlink()
                warning = proc_report.note
                break
            except Exception as exc:
                last_error = str(exc)
                raw_path.unlink(missing_ok=True)
                continue
        else:
            if job.profile.youtube_fallback and self.fallback:
                extension = job.profile.format.value if job.profile.format is not MediaFormat.AUTO else "mp3"
                final_path = output_root / track_relative_path(track, bucket, extension)
                result = self.fallback.download(track, job.profile, final_path)
                final_path = result.path
                warning = f"{result.warning}; {report.summary}" if report.total else result.warning
            else:
                raise RuntimeError(last_error or report.summary or "No suitable Soulseek candidates")

        if final_path.suffix.lower() in {".mp3", ".flac"}:
            self.tags.write(final_path, track, job.profile)
        return final_path, warning

    @staticmethod
    def _emit(callback, status, index, total, track, path=None, size=0, message="", report=None):
        if callback:
            callback(DownloadEvent(status, index, total, track, path, size, message, report))
