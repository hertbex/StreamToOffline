from streamtooffline.domain.models import DownloadJob, DownloadProfile, Track
from streamtooffline.infrastructure.state import JobStore


def test_store_resumes_only_unfinished_tracks(tmp_path):
    path = tmp_path / "state" / "jobs.db"
    first = Track("A", "Done", 100, uri="one")
    second = Track("B", "Retry", 200, uri="two")
    job = DownloadJob((first, second), DownloadProfile(), "job-1")
    store = JobStore(path)
    store.create_job(job)
    done_path = tmp_path / "done.mp3"
    done_path.write_bytes(b"audio")
    store.mark_completed(job.id, first, done_path)
    store.mark_failed(job.id, second, "not found")
    store.close()

    resumed = JobStore(path)
    assert resumed.unfinished_tracks(job.id) == (second,)
    assert resumed.summary(job.id) == {"completed": 1, "failed": 1}
    resumed.close()


def test_store_preserves_duplicate_tracks_and_reopens_missing_completed_files(tmp_path):
    track = Track("A", "Same", 100, uri="same")
    job = DownloadJob((track, track), DownloadProfile(), "duplicates")
    store = JobStore(tmp_path / "jobs.db")
    store.create_job(job)
    done_path = tmp_path / "done.mp3"
    done_path.write_bytes(b"audio")
    store.mark_completed(job.id, track, done_path)
    assert store.summary(job.id) == {"completed": 1, "pending": 1}
    done_path.unlink()
    assert store.unfinished_tracks(job.id) == (track, track)
    assert store.summary(job.id) == {"pending": 2}
    store.close()


def test_store_job_creation_is_idempotent(tmp_path):
    track = Track("A", "One", 100)
    job = DownloadJob((track,), DownloadProfile(), "job-1")
    store = JobStore(tmp_path / "jobs.db")
    store.create_job(job)
    store.create_job(job)
    assert store.summary(job.id) == {"pending": 1}
    loaded = store.load_job(job.id)
    assert loaded.tracks == (track,)
    assert loaded.profile == job.profile
    store.close()


def test_list_jobs_hides_completed_by_default(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    completed = DownloadJob((Track("A", "Done", 100),), DownloadProfile(), "done")
    pending = DownloadJob((Track("B", "Pending", 100),), DownloadProfile(), "pending")
    store.create_job(completed)
    store.create_job(pending)
    store.mark_completed("done", completed.tracks[0], tmp_path / "done.mp3")
    assert [job["id"] for job in store.list_jobs()] == ["pending"]
    assert {job["id"] for job in store.list_jobs(unfinished_only=False)} == {"done", "pending"}
    store.close()


def test_job_metadata_survives_reload(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    job = DownloadJob(
        (Track("A", "One", 100),), DownloadProfile(), "job-meta",
        name="My Playlist", output_root=str(tmp_path / "library" / "My Playlist"),
    )
    store.create_job(job)
    store.close()
    reloaded = JobStore(tmp_path / "jobs.db").load_job("job-meta")
    assert reloaded.name == "My Playlist"
    assert reloaded.output_root.endswith("My Playlist")
