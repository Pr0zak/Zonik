"""Collapse free-text genre tags into a small set of broad families.

Tags in the library are fragmented ("Hip Hop", "Hip-Hop", "Rap/Hip Hop",
"Pop, Rock", "Dance-Pop"), which turned the Music Map legend into a dozen
near-duplicates. The map colours and filters by family instead.
"""
from __future__ import annotations

import re

UNKNOWN = "Unknown"
OTHER = "Other"

# Ordered: the first family whose keyword appears in the tag wins, so the more
# specific families (metal, dance, hip hop) sit ahead of pop and rock.
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Metal", ("metal", "metalcore", "hardcore", "grindcore", "djent")),
    ("Hip Hop", ("hip hop", "hip-hop", "hiphop", "rap", "trap", "drill", "grime")),
    ("R&B / Soul", ("r&b", "rnb", "soul", "funk", "motown", "neo soul", "gospel")),
    ("Dance", ("dance", "house", "trance", "techno", "edm", "disco", "garage", "hardstyle", "eurodance")),
    ("Electronic", ("electro", "synth", "ambient", "downtempo", "dubstep", "drum and bass", "drum & bass",
                    "dnb", "breakbeat", "idm", "chill", "lo-fi", "lofi", "trip hop", "electronica")),
    ("Alternative", ("alternative", "alt ", "indie", "emo", "grunge", "post-punk", "punk", "shoegaze", "new wave")),
    ("Country / Folk", ("country", "folk", "americana", "bluegrass", "singer-songwriter", "acoustic")),
    ("Jazz / Blues", ("jazz", "blues", "swing", "bossa")),
    ("Latin", ("latin", "reggaeton", "salsa", "bachata", "cumbia", "reggae", "dancehall", "afro")),
    ("Classical / Score", ("classical", "soundtrack", "score", "orchestral", "instrumental", "piano", "opera")),
    ("Rock", ("rock", "hard rock", "classic rock")),
    ("Pop", ("pop", "k-pop", "j-pop", "top 40")),
]

FAMILIES = [name for name, _ in _RULES] + [OTHER, UNKNOWN]

_SPLIT = re.compile(r"[;,/|]")


def _match(tag: str) -> str | None:
    t = f" {tag.lower()} "
    for family, keys in _RULES:
        if any(k in t for k in keys):
            return family
    return None


def genre_family(raw: str | None) -> str:
    """Broad family for a raw genre tag. The first listed genre decides; if it
    matches nothing, the rest of the tag gets a chance before falling to Other."""
    if not raw or not raw.strip():
        return UNKNOWN
    parts = [p.strip() for p in _SPLIT.split(raw) if p.strip()]
    if not parts:
        return UNKNOWN
    for part in parts:
        fam = _match(part)
        if fam:
            return fam
    return OTHER
