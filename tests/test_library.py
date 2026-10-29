from pathlib import Path

from streamtooffline.domain.library import MetadataRules, safe_filename, track_relative_path
from streamtooffline.domain.models import Track


ROOT = Path(__file__).parents[1]


def rules():
    return MetadataRules.load(
        ROOT / "config" / "artists.yml",
        ROOT / "config" / "genres.yml",
        ROOT / "config" / "adaptive.yml",
    )


def test_rules_normalize_russian_artists_and_collaborators():
    track = Track("AK-47", "В тепле 2 яйца", 268, featured_artists=("QP",))
    normalized = rules().normalize_artists(track)
    assert normalized.artist == "АК-47"
    assert normalized.featured_artists == ("QП",)
    assert normalized.display_title.endswith("(ft. QП)")


def test_genre_rules_and_mood_fallback():
    assert rules().classify(Track("AK-47", "Song", 200)) == "01_Rus_Rap_OldSchool"
    assert rules().classify(Track("Pink Floyd", "Song", 200, genres=("progressive rock",))) == "07_Classic_Rock_70s_80s"
    assert rules().classify(Track("Unknown", "Song", 200, energy=0.2)) == "10_Funk_Soul_Chill_Vibe"
    assert rules().classify(Track("Unknown", "Song", 200)) == "10_Other"


def test_adaptive_rules_hide_empty_categories():
    r = rules()
    tracks = (
        Track("A", "Metal Song", 200, genres=("heavy metal",)),
        Track("B", "Metal Song 2", 200, genres=("thrash metal",)),
        Track("C", "Metal Song 3", 200, genres=("heavy metal",)),
        Track("D", "Rock Song", 200, genres=("classic rock",)),
        Track("E", "Rock Song 2", 200, genres=("classic rock",)),
        Track("F", "Rock Song 3", 200, genres=("classic rock",)),
    )
    r.use_adaptive(tracks)
    assert r.classify(tracks[0], adaptive=True) == "Metal"
    assert r.classify(tracks[3], adaptive=True) == "Rock"
    preview = r.adaptive_library.preview()
    assert {name for name, _ in preview} == {"Metal", "Rock"}


def test_track_path_sanitizes_windows_names_and_preserves_ft():
    track = Track("АК-47", 'A/B: "Test"?', 200, featured_artists=("QП",))
    path = track_relative_path(track, "01/Rap", "mp3")
    assert path.parts[0] == "01-Rap"
    assert "ft. QП" in path.name
    assert not set('<>:"/\\|?*').intersection(path.name)
    assert safe_filename("...") == "Unknown"
