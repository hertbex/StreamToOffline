from streamtooffline.application.download import DownloadService
from streamtooffline.domain.library import MetadataRules
from streamtooffline.domain.models import Candidate, DownloadJob, DownloadProfile, MediaFormat, Track
from streamtooffline.infrastructure.ffmpeg import ProcessingReport
from streamtooffline.infrastructure.state import JobStore


class FakeSockseek:
    def __init__(self, candidates):
        self.candidates = candidates
        self.searches = 0
    def search(self, track, profile):
        self.searches += 1
        return self.candidates
    def download(self, candidate, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"mp3")
        return destination


class FakeProcessor:
    def convert(self, source, profile, destination):
        return ProcessingReport(source, False, "preserved")


class FakeTags:
    def __init__(self): self.paths = []
    def write(self, path, track, profile): self.paths.append(path)


def make_service(tmp_path, candidates):
    rules = MetadataRules({}, {"buckets": [], "fallback": "Other"})
    store = JobStore(tmp_path / "jobs.db")
    sockseek = FakeSockseek(candidates)
    tags = FakeTags()
    service = DownloadService(sockseek, FakeProcessor(), None, tags, rules, store, tmp_path / "work")
    return service, store, sockseek, tags


def test_download_service_completes_and_resumes(tmp_path):
    candidate = Candidate("soulseek", "song.mp3", 3, 100, MediaFormat.MP3, peer="peer")
    service, store, sockseek, tags = make_service(tmp_path, [candidate])
    track = Track("Artist", "Title", 100)
    job = DownloadJob((track,), DownloadProfile(format=MediaFormat.MP3), "job-1")
    summary = service.run(job, tmp_path / "library")
    assert summary == {"completed": 1}
    assert tags.paths[0].name == "Artist - Title.mp3"
    service.run(job, tmp_path / "library")
    assert sockseek.searches == 1
    store.close()


def test_download_service_records_failure_and_continues(tmp_path):
    service, store, _, _ = make_service(tmp_path, [])
    job = DownloadJob((Track("A", "Missing", 100),), DownloadProfile(), "job-2")
    summary = service.run(job, tmp_path / "library")
    assert summary == {"failed": 1}
    assert len(store.unfinished_tracks(job.id)) == 1
    store.close()
