from pathlib import Path

from streamtooffline.domain.adaptive import AdaptiveLibrary
from streamtooffline.domain.models import Track


def test_adaptive_build_shows_only_relevant_categories():
    lib = AdaptiveLibrary(Path(__file__).parents[1] / "config" / "adaptive.yml")
    tracks = (
        Track("A", "One", 200, genres=("heavy metal",), energy=0.9),
        Track("B", "Two", 200, genres=("thrash metal",), energy=0.85),
        Track("C", "Three", 200, genres=("heavy metal",), energy=0.9),
        Track("D", "Four", 200, genres=("classic rock",), energy=0.6),
        Track("E", "Five", 200, genres=("classic rock",), energy=0.6),
        Track("F", "Six", 200, genres=("classic rock",), energy=0.6),
    )
    lib.build(tracks)
    assert lib.classify(tracks[0]) == "Metal"
    assert lib.classify(tracks[3]) == "Rock"
    assert "Electronic" not in {b.name for b in lib.buckets}


def test_adaptive_mood_fallback_for_unknown_genre():
    lib = AdaptiveLibrary(Path(__file__).parents[1] / "config" / "adaptive.yml")
    tracks = (
        Track("A", "Chill 1", 200, energy=0.2),
        Track("B", "Chill 2", 200, energy=0.15),
        Track("C", "Chill 3", 200, energy=0.1),
    )
    lib.build(tracks)
    assert lib.classify(tracks[0]) == "Chill"


def test_adaptive_uses_repository_default_config():
    assert AdaptiveLibrary().fallback == "Other"
