from pathlib import Path
from io import StringIO

import pytest

from streamtooffline.infrastructure.csv_source import ExportifyCsvReader


HEADER = "Track URI,Artist Name(s),Track Name,Album Name,Track Duration (ms),Genres\n"


def test_reader_normalizes_collaborators_duration_and_genres(tmp_path):
    path = tmp_path / "playlist.csv"
    path.write_text(
        HEADER + 'spotify:track:1,"AK-47;QП","В тепле 2 яйца","Мегаpolice",268339,"rap,hip hop"\n',
        encoding="utf-8",
    )
    result = ExportifyCsvReader().read(path)
    track = result.tracks[0]
    assert track.artist == "AK-47"
    assert track.featured_artists == ("QП",)
    assert track.duration_seconds == 268
    assert track.genres == ("rap", "hip hop")
    assert not result.errors


def test_reader_repairs_unescaped_label_quotes_and_valid_double_quote(tmp_path):
    path = tmp_path / "broken.csv"
    path.write_text(
        HEADER
        + 'spotify:track:1,Mnogotochie,"Бошки","Территория Желаний",383413,"ООО "Медиалайн""\n'
        + 'spotify:track:2,The Guess Who,"American Woman - 7"" Single Version","American Woman",231640,"rock"\n',
        encoding="utf-8",
    )
    result = ExportifyCsvReader().read(path)
    assert len(result.tracks) == 2
    assert result.tracks[1].title == 'American Woman - 7" Single Version'
    assert not result.errors


def test_reader_collects_bad_rows_and_supports_bom(tmp_path):
    path = tmp_path / "partial.csv"
    path.write_text("\ufeff" + HEADER + "spotify:track:1,Artist,Good,Album,100000,rock\nspotify:track:2,Artist,Bad,Album,,rock\n", encoding="utf-8")
    result = ExportifyCsvReader().read(path)
    assert [track.title for track in result.tracks] == ["Good"]
    assert len(result.errors) == 1 and result.errors[0].line == 3


def test_reader_rejects_missing_required_column(tmp_path):
    path = tmp_path / "invalid.csv"
    path.write_text("Artist,Duration (ms)\nArtist,1000\n", encoding="utf-8")
    with pytest.raises(ValueError, match="title"):
        ExportifyCsvReader().read(path)


def test_reader_accepts_text_stream_from_http_callback():
    result = ExportifyCsvReader().read(StringIO(HEADER + "spotify:track:1,Artist,Title,Album,1000,rock\n"))
    assert result.tracks[0].display_name == "Artist - Title"


def test_reader_supports_newlines_inside_quoted_fields():
    text = HEADER + 'spotify:track:1,Artist,"Title\npart",Album,1000,rock\n'
    result = ExportifyCsvReader().read(StringIO(text))
    assert result.tracks[0].title == "Title\npart"
