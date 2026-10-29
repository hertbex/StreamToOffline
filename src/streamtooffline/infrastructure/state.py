from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from streamtooffline.domain.models import DownloadJob, DownloadProfile, JobStatus, MediaFormat, Track, VersionPolicy


class JobStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL,
                created_at TEXT NOT NULL, profile_json TEXT NOT NULL,
                name TEXT, output_root TEXT
            );
            CREATE TABLE IF NOT EXISTS items (
                job_id TEXT NOT NULL, track_key TEXT NOT NULL,
                track_json TEXT NOT NULL, status TEXT NOT NULL,
                path TEXT, error TEXT,
                PRIMARY KEY (job_id, track_key)
            );
        """)
        for column in ("name", "output_root"):
            try:
                self.connection.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
            except sqlite3.OperationalError:
                pass
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def create_job(self, job: DownloadJob) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO jobs (id, status, created_at, profile_json, name, output_root) VALUES (?, ?, ?, ?, ?, ?)",
                (job.id, job.status.value, job.created_at.isoformat(), json.dumps(asdict(job.profile)), job.name, job.output_root),
            )
            for track in job.tracks:
                self.connection.execute(
                    "INSERT OR IGNORE INTO items (job_id, track_key, track_json, status) VALUES (?, ?, ?, 'pending')",
                    (job.id, self._track_key(track), json.dumps(asdict(track), ensure_ascii=False)),
                )

    def unfinished_tracks(self, job_id: str) -> tuple[Track, ...]:
        rows = self.connection.execute(
            "SELECT track_json FROM items WHERE job_id = ? AND status != 'completed' ORDER BY rowid",
            (job_id,),
        ).fetchall()
        return tuple(self._track_from_json(row[0]) for row in rows)

    def mark_completed(self, job_id: str, track: Track, path: Path) -> None:
        self._mark(job_id, track, "completed", str(path), None)

    def mark_failed(self, job_id: str, track: Track, error: str) -> None:
        self._mark(job_id, track, "failed", None, error[:1000])

    def _mark(self, job_id: str, track: Track, status: str, path: str | None, error: str | None) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE items SET status = ?, path = ?, error = ? WHERE job_id = ? AND track_key = ?",
                (status, path, error, job_id, self._track_key(track)),
            )
            counts = self.summary(job_id)
            if counts.get("pending", 0):
                job_status = "partial"
            elif not counts.get("failed", 0):
                job_status = "completed"
            else:
                job_status = "partial" if counts.get("completed", 0) else "failed"
            self.connection.execute("UPDATE jobs SET status = ? WHERE id = ?", (job_status, job_id))

    def load_job(self, job_id: str) -> DownloadJob:
        row = self.connection.execute(
            "SELECT status, created_at, profile_json, name, output_root FROM jobs WHERE id = ?", (job_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Job not found: {job_id}")
        profile_data = json.loads(row[2])
        profile_data["format"] = MediaFormat(profile_data["format"])
        profile_data["version_policy"] = VersionPolicy(profile_data["version_policy"])
        tracks = self.connection.execute(
            "SELECT track_json FROM items WHERE job_id = ? ORDER BY rowid", (job_id,),
        ).fetchall()
        return DownloadJob(
            tracks=tuple(self._track_from_json(item[0]) for item in tracks),
            profile=DownloadProfile(**profile_data), id=job_id,
            status=JobStatus(row[0]), created_at=datetime.fromisoformat(row[1]),
            name=row[3], output_root=row[4],
        )

    def summary(self, job_id: str) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT status, COUNT(*) FROM items WHERE job_id = ? GROUP BY status", (job_id,),
        ).fetchall()
        return {status: count for status, count in rows}

    def list_jobs(self, unfinished_only: bool = True) -> tuple[dict, ...]:
        rows = self.connection.execute(
            """
            SELECT j.id, j.status, j.created_at,
                   (SELECT COUNT(*) FROM items i WHERE i.job_id = j.id) AS total,
                   (SELECT COUNT(*) FROM items i WHERE i.job_id = j.id AND i.status = 'completed') AS completed,
                   (SELECT COUNT(*) FROM items i WHERE i.job_id = j.id AND i.status = 'failed') AS failed,
                   (SELECT i.track_json FROM items i WHERE i.job_id = j.id ORDER BY rowid LIMIT 1) AS first_track,
                   j.name, j.output_root
            FROM jobs j
            WHERE ? = 0 OR EXISTS (
                SELECT 1 FROM items pending
                WHERE pending.job_id = j.id AND pending.status != 'completed'
            )
            ORDER BY j.created_at DESC
            """,
            (unfinished_only,),
        ).fetchall()
        result = []
        for row in rows:
            first = self._track_from_json(row[6]) if row[6] else None
            label = row[7] or (first.display_name if first else "unknown")
            result.append({
                "id": row[0],
                "status": row[1],
                "created_at": datetime.fromisoformat(row[2]),
                "total": row[3],
                "completed": row[4],
                "failed": row[5],
                "label": label,
                "output_root": row[8],
            })
        return tuple(result)

    def delete_job(self, job_id: str) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM items WHERE job_id = ?", (job_id,))
            self.connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    @staticmethod
    def _track_key(track: Track) -> str:
        return track.uri or f"{track.display_name}|{track.duration_seconds}"

    @staticmethod
    def _track_from_json(payload: str) -> Track:
        data = json.loads(payload)
        data["genres"] = tuple(data.get("genres", ()))
        data["featured_artists"] = tuple(data.get("featured_artists", ()))
        return Track(**data)
