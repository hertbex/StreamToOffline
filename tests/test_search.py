from streamtooffline.application.search import TrackSearcher
from streamtooffline.domain.models import Candidate, DownloadProfile, MediaFormat, Track


class FakeSockseek:
    def __init__(self, candidates):
        self.candidates = candidates
    def search_query(self, query, profile):
        return self.candidates


def test_searcher_groups_candidates_and_returns_unique_tracks():
    candidates = (
        Candidate("soulseek", "Artist/Album/Song.mp3", 3_000_000, 200, MediaFormat.MP3, peer="p1"),
        Candidate("soulseek", "Artist/Album/Song.mp3", 3_100_000, 200, MediaFormat.MP3, peer="p2"),
        Candidate("soulseek", "Other/Cover.mp3", 2_000_000, 180, MediaFormat.MP3, peer="p3"),
    )
    searcher = TrackSearcher(FakeSockseek(candidates))
    matches = searcher.search("query", DownloadProfile())
    assert len(matches) == 2
    assert matches[0].track.display_name == "Artist - Song"
    assert len(matches[0].candidates) == 2
