"""Lyrics parsing (backend/services/lyrics.py)."""
from backend.services.lyrics import parse_lrc, plain_lines, to_lines


def test_lrc_lines_are_timed_and_sorted_with_repeats_split():
    lines = parse_lrc("[00:15.00][01:10.5]Chorus line\n[00:12.30]Hello world\n[ar:Someone]\nno stamp")
    assert lines == [[12300, "Hello world"], [15000, "Chorus line"], [70500, "Chorus line"]]


def test_plain_text_drops_blank_lines_and_section_markers():
    assert plain_lines("Verse one\n\n[Chorus]\n  Line two  ") == [[-1, "Verse one"], [-1, "Line two"]]


def test_to_lines_needs_a_few_stamps_to_call_it_timed():
    timed, synced = to_lines("[00:01.00]a\n[00:02.00]b\n[00:03.00]c")
    assert synced and [ms for ms, _ in timed] == [1000, 2000, 3000]
    plain, synced = to_lines("[00:01.00]only one\nthen plain")
    assert not synced
