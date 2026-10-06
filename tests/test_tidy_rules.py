"""Library tidy naming rules, checked against names found in the real library (2026-10-05 survey).

Run: uv run --with pytest pytest tests/test_tidy_rules.py
"""
from backend.services.tidy_rules import (
    AlbumInfo, TrackTags, clean_album, clean_segment, main_artist, target_path,
)

ALBUM = AlbumInfo(tracks_in_library=12, discs=1, compilation=False)


def tags(**kw):
    base = dict(title=None, artist=None, albumartist=None, album=None, track=None, disc=None)
    base.update(kw)
    return TrackTags(**base)


def test_clean_segment_folds_punctuation_and_reserved_characters():
    assert clean_segment("Who’s Next") == "Who's Next"
    assert clean_segment("Mercury – Acts 1 & 2") == "Mercury - Acts 1 & 2"
    assert clean_segment("Haunted Ink: Original Artbook Soundtrack") == "Haunted Ink - Original Artbook Soundtrack"
    assert clean_segment('What Is Love (7" Mix)') == "What Is Love (7' Mix)"
    assert clean_segment("Do They Know It's Christmas?") == "Do They Know It's Christmas"
    assert clean_segment("Seven Nation Army | The White Stripes Cover") == "Seven Nation Army - The White Stripes Cover"
    assert clean_segment("Love Sick  (Deluxe)") == "Love Sick (Deluxe)"
    assert clean_segment("Jesus, Etc.") == "Jesus, Etc"
    assert clean_segment("") == "Unknown"


def test_clean_segment_strips_video_clutter_from_titles_only():
    assert clean_segment("The XX Intro - ELEZO remix ( Official video ) [N_ljGGiKe4A]", title=True) == "The XX Intro - ELEZO remix"
    assert clean_segment("Weak (Official Video)", title=True) == "Weak"
    assert clean_segment("Así (Video Oficial)", title=True) == "Así"
    assert clean_segment("Bones (Official Lyric Video)", title=True) == "Bones"
    # Not a title: left alone.
    assert clean_segment("Weak (Official Video)") == "Weak (Official Video)"


def test_clean_segment_caps_length_at_a_word():
    soulwax = ("Most of the remixes we've made for other people over the years except for the one for "
               "Einstürzende Neubauten because we lost it and a few we didn't think sounded good enough")
    out = clean_segment(soulwax)
    assert len(out) <= 120 and soulwax.startswith(out) and not out.endswith(" ")


def test_clean_segment_keeps_letters_of_every_script():
    assert clean_segment("ROSALÍA") == "ROSALÍA"
    assert clean_segment("ליילי - גל תורן") == "ליילי - גל תורן"
    assert clean_segment("Måneskin") == "Måneskin"


def test_clean_album_drops_format_noise_and_junk():
    assert clean_album("The Bear, Season 3 (44.1kHz, 16bit, 2ch.)") == "The Bear, Season 3"
    assert clean_album("Sweet Boy [Web, FLAC, 48-23, 44-23]") == "Sweet Boy"
    assert clean_album("OCTANE [24BIT-48KHZ]") == "OCTANE"
    assert clean_album("flac") is None
    assert clean_album("4DJsonline.com") is None
    assert clean_album("Unknown Album") is None
    assert clean_album("1989 (Taylor's Version)") == "1989 (Taylor's Version)"


def test_main_artist_drops_guests_and_splits_known_lists():
    known = {"clean bandit", "crystal rock"}
    assert main_artist("Anyma feat. Ellie Goulding") == "Anyma"
    assert main_artist("Calvin Harris Ft. John Newman") == "Calvin Harris"
    assert main_artist("Clean Bandit, Tiësto, Leony", known) == "Clean Bandit"
    assert main_artist("Crystal Rock; Pule", known) == "Crystal Rock"
    assert main_artist("GRiZ x CloZee") == "GRiZ"
    assert main_artist("Tyler, The Creator", known) == "Tyler, The Creator"
    assert main_artist("Simon & Garfunkel") == "Simon & Garfunkel"
    assert main_artist("She & Him") == "She & Him"


def test_album_track():
    t = tags(title="Earrings", artist="Malcolm Todd", album="Sweet Boy [Web, FLAC, 48-23, 44-23]", track=1)
    assert target_path(t, ".flac", "Music/Malcolm Todd (2024.04.05) (album) Sweet Boy/01. Malcolm Todd - Earrings.flac", ALBUM) == \
        ("Malcolm Todd/Sweet Boy/01 - Earrings.flac", "album")


def test_album_artist_tag_wins_over_a_featured_track_artist():
    t = tags(title="Hypnotized", artist="Anyma feat. Ellie Goulding", albumartist="Anyma", album="The End of Genesys", track=3)
    assert target_path(t, ".flac", "x", ALBUM)[0] == "Anyma/The End of Genesys/03 - Hypnotized.flac"


def test_multi_disc_numbers():
    t = tags(title="Sharks", artist="Imagine Dragons", album="Mercury – Acts 1 & 2", track=3, disc=2)
    two = AlbumInfo(tracks_in_library=32, discs=2, compilation=False)
    assert target_path(t, ".flac", "x", two)[0] == "Imagine Dragons/Mercury - Acts 1 & 2/2-03 - Sharks.flac"


def test_no_album_goes_to_singles():
    t = tags(title="Lush Life", artist="Zara Larsson")
    assert target_path(t, ".flac", "#SORT/Z/Zara Larsson - Lush Life.flac", None) == ("Zara Larsson/Singles/Lush Life.flac", "single")


def test_single_tagged_as_its_own_album_goes_to_singles():
    t = tags(title="Little Girl Gone", artist="CHINCHILLA", album="Little Girl Gone", track=1)
    one = AlbumInfo(tracks_in_library=1, discs=1, compilation=False)
    assert target_path(t, ".opus", "x", one)[0] == "CHINCHILLA/Singles/Little Girl Gone.opus"


def test_title_track_of_a_real_album_stays_in_the_album():
    t = tags(title="Sweet Boy", artist="Malcolm Todd", album="Sweet Boy", track=6)
    assert target_path(t, ".flac", "x", ALBUM)[0] == "Malcolm Todd/Sweet Boy/06 - Sweet Boy.flac"


def test_compilation_stays_whole_with_performer_in_the_name():
    t = tags(title="I Wish It Could Be Christmas Everyday", artist="Kylie Minogue", albumartist="Various Artists",
             album="Now That’s What I Call Christmas", track=10, disc=3)
    comp = AlbumInfo(tracks_in_library=60, discs=3, compilation=True)
    assert target_path(t, ".flac", "x", comp) == (
        "Various Artists/Now That's What I Call Christmas/3-10 - Kylie Minogue - I Wish It Could Be Christmas Everyday.flac",
        "compilation",
    )


def test_untagged_keeps_its_original_path_under_untagged():
    t = tags(title="Glitter And Gold")
    assert target_path(t, ".flac", "Henri Werner/04-Glitter And Gold.flac", None) == \
        ("_Untagged/Henri Werner/04-Glitter And Gold.flac", "untagged")
    # Already there: not nested again.
    assert target_path(t, ".flac", "_Untagged/Henri Werner/04-Glitter And Gold.flac", None)[0] == \
        "_Untagged/Henri Werner/04-Glitter And Gold.flac"


def test_extension_is_lowercased():
    t = tags(title="Song", artist="A")
    assert target_path(t, ".FLAC", "x", None)[0] == "A/Singles/Song.flac"
