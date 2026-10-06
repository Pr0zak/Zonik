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


# --- Settings (TidyOptions) ---

from backend.services.tidy_rules import TidyOptions, folder_artist  # noqa: E402


def test_album_artist_is_cleaned_like_a_track_artist():
    t = tags(title="Bones", artist="Imagine Dragons", albumartist="Imagine Dragons feat. Baker Boy", album="Mercury", track=1)
    assert folder_artist(t, set(), TidyOptions()) == "Imagine Dragons"
    t = tags(title="x", artist="Stray Kids", albumartist="Arcane; League of Legends", album="Arcane", track=1)
    assert folder_artist(t, set(), TidyOptions()) == "Arcane"


def test_split_artist_lists_setting():
    assert main_artist("Queen, Megan Thee Stallion", set()) == "Queen, Megan Thee Stallion"
    assert main_artist("Queen, Megan Thee Stallion", set(), TidyOptions(split_artist_lists="always")) == "Queen"
    assert main_artist("Crystal Rock; Pule", set(), TidyOptions(split_artist_lists="never")) == "Crystal Rock; Pule"


def test_year_and_disc_folder_settings():
    t = tags(title="Sharks", artist="Imagine Dragons", album="Mercury", track=3, disc=2, year=2022)
    two = AlbumInfo(tracks_in_library=32, discs=2, compilation=False)
    o = TidyOptions(album_year_style="suffix", disc_style="folder")
    assert target_path(t, ".flac", "x", two, opts=o)[0] == "Imagine Dragons/Mercury (2022)/Disc 2/03 - Sharks.flac"


def test_untagged_modes():
    t = tags(title=None)
    rel = "Nelly Furtado/06 Nelly Furtado - Say It Right.wav"
    assert target_path(t, ".wav", rel, None, opts=TidyOptions(untagged_mode="filename"))[0] == "Nelly Furtado/Singles/Say It Right.wav"
    assert target_path(t, ".wav", rel, None, opts=TidyOptions(untagged_mode="leave")) == (rel, "untagged")
    assert target_path(t, ".wav", rel, None, opts=TidyOptions(untagged_folder="Unsorted"))[0] == "Unsorted/" + rel


def test_excluded_folders_stay_put():
    t = tags(title="Song", artist="A", album="B", track=1)
    o = TidyOptions(exclude_folders=["Audiobooks", "Live/"])
    assert target_path(t, ".mp3", "Audiobooks/x/1.mp3", ALBUM, opts=o) == ("Audiobooks/x/1.mp3", "excluded")
    assert target_path(t, ".mp3", "Live/1.mp3", ALBUM, opts=TidyOptions.from_dict(o.to_dict())) == ("Live/1.mp3", "excluded")


def test_punctuation_and_clutter_can_be_kept():
    o = TidyOptions(ascii_punctuation=False, strip_video_clutter=False)
    assert clean_segment("Who’s Next", opts=o) == "Who’s Next"
    assert clean_segment("Weak (Official Video)", title=True, opts=o) == "Weak (Official Video)"


def test_options_from_dict_rejects_bad_values():
    o = TidyOptions.from_dict({"disc_style": "nonsense", "max_name_length": 5, "singles_folder": "a/b:c",
                               "album_year_style": "sideways", "unknown": 1})
    assert o.disc_style == "prefix" and o.max_name_length == 40 and o.singles_folder == "abc" and o.album_year_style == "none"


def test_year_prefix_matches_the_existing_folder_style():
    t = tags(title="Haunted Ink", artist="Alex Vede", album="Haunted Ink: Original Artbook Soundtrack", track=1, year=2022)
    o = TidyOptions(album_year_style="prefix")
    assert target_path(t, ".opus", "x", ALBUM, opts=o)[0] == "Alex Vede/2022 - Haunted Ink - Original Artbook Soundtrack/01 - Haunted Ink.opus"
    t = tags(title="Africa", artist="Crystal Rock", album="Africa", track=1, year=None)
    assert target_path(t, ".opus", "x", ALBUM, opts=o)[0] == "Crystal Rock/Africa/01 - Africa.opus"


def test_old_album_year_setting_carries_over():
    assert TidyOptions.from_dict({"album_year": True}).album_year_style == "suffix"
    assert TidyOptions.from_dict({"album_year": False}).album_year_style == "none"


def test_filename_is_clean():
    from backend.services.tidy_rules import filename_is_clean
    assert filename_is_clean("06 Dreams.flac", "Dreams")
    assert filename_is_clean("I Don't Wanna Wait.flac", "I Don't Wanna Wait")
    assert filename_is_clean("002. Cars (Remix).flac", "Cars (Remix)")
    assert not filename_is_clean("NF_The Search_02_Leave Me Alone.flac", "Leave Me Alone")
    assert not filename_is_clean("It’s Just Forever.flac", "It's Just Forever")
    assert not filename_is_clean("Weak (Official Video).flac", "Weak")
    assert not filename_is_clean("Track 07.flac", "Shadows")
    assert not filename_is_clean("06 Dreams.FLAC", "Dreams")


# --- Mode "fix_names": repair bad names in place ---

from backend.services.tidy_rules import fix_path  # noqa: E402

FIX = TidyOptions(mode="fix_names")


def test_fix_names_keeps_the_structure_and_good_names():
    t = tags(title="Dreams", artist="Beck", album="Colors", track=6)
    assert fix_path("Beck/Colors/06 Dreams.flac", t, opts=FIX) == "Beck/Colors/06 Dreams.flac"
    t = tags(title="Slow It Down", artist="Benson Boone", album="Fireworks & Rollerblades", track=3)
    assert fix_path("Benson Boone/03 - Slow It Down.flac", t, opts=FIX) == "Benson Boone/03 - Slow It Down.flac"
    t = tags(title="Africa", artist="Crystal Rock", album="Africa", track=1)
    assert fix_path("Crystal Rock/2022 - Africa/01 - Africa.opus", t, opts=FIX) == "Crystal Rock/2022 - Africa/01 - Africa.opus"


def test_fix_names_repairs_bad_ones():
    t = tags(title="The DJ Is Crying for Help", artist="AJR", album="The Maybe Man", track=8)
    assert fix_path("AJR/AJR-The_Maybe_Man-24BIT-44KHZ-WEB-FLAC-2023-OBZEN/08-ajr-the_dj_is_crying_for_help.flac", t, opts=FIX) == \
        "AJR/The Maybe Man/08-ajr-the dj is crying for help.flac"
    t = tags(title="party 4 u", artist="Charli xcx", album="how i’m feeling now", track=9)
    assert fix_path("Charli xcx/(2020) how i’m feeling now [e6f8d52b-3b24-4546-b86d-99d79b0df209}]/09 party 4 u.flac", t, opts=FIX) == \
        "Charli xcx/(2020) how i'm feeling now/09 party 4 u.flac"
    t = tags(title="Earrings", artist="Malcolm Todd", album="Sweet Boy", track=1)
    assert fix_path("Music/Sweet Boy [Web, FLAC, 48-23, 44-23]/01. Malcolm Todd - Earrings.flac", t, opts=FIX) == \
        "Music/Sweet Boy/01. Malcolm Todd - Earrings.flac"
    t = tags(title="Keeping Secrets", artist="Digits")
    assert fix_path("Digits/Keeping_Secrets_by_Digits.mp3", t, opts=FIX) == "Digits/Keeping Secrets by Digits.mp3"
    t = tags(title="Ballroom Blitz", artist="Tia Carrere", album="Wayne's World: Music From the Motion Picture", track=8)
    assert fix_path("Various Artists/Wayne’s World_ Music From the Motion Picture/08 Tia Carrere - Ballroom Blitz.flac", t, opts=FIX) == \
        "Various Artists/Wayne's World - Music From the Motion Picture/08 Tia Carrere - Ballroom Blitz.flac"
    t = tags(title="ELEZO remix", artist="ELEZO")
    assert fix_path("_Unmatched/ELEZO - The XX Intro - ELEZO remix ( Official video ) [N_ljGGiKe4A].opus", t, opts=FIX) == \
        "_Unmatched/ELEZO - The XX Intro - ELEZO remix.opus"


def test_fix_names_renames_symbol_only_folders_from_tags():
    t = tags(title="Duvet", artist="boa", album="Twilight", track=1)
    assert fix_path("･ﾟ✧(=✪ ᅆ ✪=)-･ﾟ✧/Duvet.flac", t, opts=FIX) == "Twilight/Duvet.flac"
    assert fix_path("･ﾟ✧(=✪ ᅆ ✪=)-･ﾟ✧/Album/Duvet.flac", t, opts=FIX) == "boa/Album/Duvet.flac"


def test_fix_names_underscores_between_fields_and_at_the_end():
    t = tags(title="Zombie", artist="Bad Wolves", album="Disobey", track=4)
    assert fix_path("Bad Wolves/Bad Wolves_Disobey_04_Zombie.flac", t, opts=FIX) == "Bad Wolves/Bad Wolves - Disobey - 04 - Zombie.flac"
    t = tags(title="What Will I Say When You're Gone?", artist="Erasure", track=3)
    assert fix_path("Erasure/103 - What Will I Say When You\u2019re Gone_.flac", t, opts=FIX) == "Erasure/103 - What Will I Say When You're Gone.flac"
    t = tags(title="I Feel Alive Again", artist="Killswitch Engage", track=5)
    assert fix_path("Killswitch Engage/05-killswitch_engage-i_feel_alive_again.flac", t, opts=FIX) == \
        "Killswitch Engage/05-killswitch engage-i feel alive again.flac"
