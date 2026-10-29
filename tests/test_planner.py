from streamtooffline.domain.models import Candidate, DownloadProfile, MediaFormat, Track, VersionPolicy
from streamtooffline.domain.planner import CandidateSelector, LibraryPlanner


TRACK = Track("Artist", "Title", 200)


def candidate(name="song.mp3", fmt=MediaFormat.MP3, bitrate=320, duration=200, size=8_000_000):
    return Candidate("soulseek", name, size, duration, fmt, bitrate)


def test_mp3_estimate_is_deterministic_and_includes_duration():
    tracks = (Track("A", "One", 60), Track("B", "Two", 120))
    estimate = LibraryPlanner().estimate(tracks, DownloadProfile.kia_ceed_ed_fl())
    assert estimate.track_count == 2
    assert estimate.duration_seconds == 180
    assert estimate.min_bytes == estimate.max_bytes == 7_200_000


def test_flac_estimate_is_a_range_and_transfer_eta_handles_unknown_speed():
    estimate = LibraryPlanner().estimate((TRACK,), DownloadProfile.lossless())
    assert 0 < estimate.min_bytes < estimate.max_bytes
    assert LibraryPlanner.transfer_seconds(1000, 100) == 10
    assert LibraryPlanner.transfer_seconds(1000, None) is None


def test_unknown_duration_uses_visible_estimate():
    estimate = LibraryPlanner().estimate((Track("A", "Unknown", 0),), DownloadProfile.kia_ceed_ed_fl())
    assert estimate.duration_seconds == 240
    assert estimate.min_bytes > 0
    assert "estimated duration" in estimate.basis


def test_original_auto_rejects_edits_remixes_and_live_but_allows_remaster():
    selector = CandidateSelector()
    profile = DownloadProfile(version_policy=VersionPolicy.AUTO)
    assert selector.eligible(TRACK, candidate("Song (2015 Remaster).mp3"), profile)
    for name in ("Song (Radio Edit).mp3", "Song (Club Remix).mp3", "Song (Live).mp3"):
        assert not selector.eligible(TRACK, candidate(name), profile)


def test_edit_and_remix_policies_select_requested_versions():
    selector = CandidateSelector()
    assert selector.eligible(TRACK, candidate("Song (Radio Edit).mp3"), DownloadProfile(version_policy=VersionPolicy.EDITS))
    assert selector.eligible(TRACK, candidate("Song (Club Remix).mp3"), DownloadProfile(version_policy=VersionPolicy.REMIXES))
    assert not selector.eligible(TRACK, candidate("Song (Original Mix).mp3"), DownloadProfile(version_policy=VersionPolicy.REMIXES))


def test_quality_rules_and_ranking_prefer_native_mp3_over_lossless():
    selector = CandidateSelector()
    flac_profile = DownloadProfile.lossless()
    assert not selector.eligible(TRACK, candidate(), flac_profile)
    assert selector.eligible(TRACK, candidate("song.wav", MediaFormat.WAV, None), flac_profile)

    mp3 = candidate()
    flac = candidate("song.flac", MediaFormat.FLAC, None, size=25_000_000)
    ranked = selector.ranked(TRACK, (flac, mp3), DownloadProfile.kia_ceed_ed_fl())
    assert ranked[0] == mp3
    assert not selector.eligible(TRACK, candidate(bitrate=256), DownloadProfile.kia_ceed_ed_fl())


def test_ranking_accepts_single_pass_iterables():
    selected = candidate()
    ranked = CandidateSelector().ranked(
        TRACK, (item for item in (selected,)), DownloadProfile()
    )
    assert ranked == (selected,)


def test_ranking_prefers_free_slot_and_faster_soulseek_peer():
    slow = Candidate(
        "soulseek", "slow.mp3", 8_000_000, 200, MediaFormat.MP3,
        320, peer="slow", upload_speed_kbps=50, has_free_upload_slot=False,
    )
    fast = Candidate(
        "soulseek", "fast.mp3", 8_000_000, 200, MediaFormat.MP3,
        320, peer="fast", upload_speed_kbps=5000, has_free_upload_slot=True,
    )
    ranked = CandidateSelector().ranked(TRACK, (slow, fast), DownloadProfile())
    assert ranked[0].peer == "fast"


def test_duration_tolerance_can_be_disabled():
    selector = CandidateSelector()
    short = candidate(duration=180)
    assert not selector.eligible(TRACK, short, DownloadProfile())
    assert selector.eligible(TRACK, short, DownloadProfile(length_tolerance_seconds=None))


def test_diagnose_counts_rejection_reasons_and_summary():
    selector = CandidateSelector()
    profile = DownloadProfile.kia_ceed_ed_fl()
    short = candidate(duration=180)
    low_quality = candidate(bitrate=256)
    remix = candidate("Song (Club Remix).mp3")
    report = selector.diagnose(TRACK, (short, low_quality, remix), profile)
    assert report.total == 3
    assert report.eligible == 0
    assert report.rejected_by_length == 1
    assert report.rejected_by_quality == 1
    assert report.rejected_by_version == 1
    assert "wrong quality" in report.summary
    assert report.best is None


def test_diagnose_summary_includes_real_candidate_stats():
    selected = candidate(size=10 * 1024 * 1024, duration=240)
    report = CandidateSelector().diagnose(
        Track("Artist", "Song", 240), (selected,), DownloadProfile()
    )
    assert "best 4:00" in report.summary
    assert "10.0 MiB" in report.summary
    assert "320 kbps" in report.summary
