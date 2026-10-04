#!/usr/bin/env python3
"""Export the TV visualizer's shaders for the web UI's live previews.

Reads the effect enum and GLSL strings out of mobile/app/.../ui/tv/DemoEffects*.kt and writes
frontend/static/tv-shaders.json, which the /visualizer page compiles with WebGL and the server
reads for the effect catalogue. Run it after adding or changing an effect:

    python3 scripts/extract-tv-shaders.py

`--check` exits non-zero when the JSON is out of date instead of writing it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TV_DIR = ROOT / "mobile/app/src/main/java/com/zonik/app/ui/tv"
OUT = ROOT / "frontend/static/tv-shaders.json"

# How docs/tv-visualizer.md groups the effects. An effect missing here lands in "Other", so a
# new one still shows up; add it to a group when it is added to the app.
GROUPS = {
    "Patterns and their variations": (
        "HEXPULSE HEXRADAR TRIPULSE HEXFLIP CELLPULSE SPECTRUMRINGS SPECTRUMSQUARES "
        "SPECTRUMSPIRAL RADAR APOLLONIAN APONEON APOPULSE APOGLASS TRUCHET HEXTRUCHET MAZE TUBES"
    ),
    "Trippy and beat-driven": (
        "HYPNO HYPNORINGS KIFS BASSLENS OPART MARBLE ROSE PULSEGRID LIGHTNING SACRED "
        "STROBEKALEIDO LASERS"
    ),
    "Tunnels and flight": (
        "TUNNEL WARPTUNNEL WORMHOLE HEXTUNNEL SQUARETUNNEL TRITUNNEL OCTOTUNNEL BENTTUBE "
        "DOTTUNNEL STARFIELD NEBULA HYPERSPACE RAINBOWWARP FLYINGCOVERS SYNTHWAVE NIGHTDRIVE "
        "VOXEL OCEAN MOONLIGHT CITY CLOUDS PLANET SKYLINE CHECKER"
    ),
    "Zooms and fractals": (
        "ROTOZOOM KALEIDOSCOPE KALEIDOZOOM KALEIDOFRAME JULIA JULIAPULSE MANDELBROT DROSTE "
        "DROSTESPIRAL MOSAIC KALISET TILEZOOM DEFORM"
    ),
    "Spectrum and scopes": "SUNBURST OSCILLOSCOPE LEDBARS WATERFALL LISSAJOUS SHOCKWAVE TRACKER",
    "Classic demo": (
        "PLASMA ACIDPLASMA SMOOTHPLASMA METABALLS COPPER MOIRE FIRE VORONOI AURORA SHADEBOBS ORBITS"
    ),
    "Cover treatments and feedback": "GODRAYS MELT INK RIPPLES VHS BUMP HALFTONE ASCII MILKDROP",
}


def build() -> dict:
    files = sorted(TV_DIR.glob("DemoEffects*.kt"))
    main = (TV_DIR / "DemoEffects.kt").read_text()
    source = "".join(f.read_text() for f in files)

    consts: dict[str, str] = {}
    pattern = r'(?:private |internal )?const val (\w+) = (\w+ \+ )?"""(.*?)"""'
    for name, prefix, body in re.findall(pattern, source, re.S):
        consts[name] = (consts[prefix.split()[0]] if prefix else "") + body

    group_of = {name: group for group, names in GROUPS.items() for name in names.split()}
    enum = main[main.index("enum class DemoEffect"):main.index("val fragmentShader")]
    effects = []
    for m in re.finditer(r'^\s+([A-Z]+)\("([^"]+)", (\w+)([^)\n]*)\)[,;]', enum, re.M):
        name, label, body, rest = m.groups()
        variant = re.search(r"variant = (\d+)", rest)
        view = re.search(r"view = (\w+)", rest)
        effects.append({
            "id": name,
            "label": label,
            "group": group_of.get(name, "Other"),
            "feedback": "feedback = true" in rest,
            "halfRes": "halfRes = true" in rest,
            "framesCover": "framesCover = true" in rest,
            "floats": "floats = true" in rest,
            # Wrapped in the shared header and footer by the page, as the app does, so the
            # ~10 KB they come to is sent once instead of once per effect.
            "body": f"#define VARIANT {variant.group(1) if variant else 0}\n" + consts[body],
            # A feedback effect can draw its buffer to the screen through its own shader.
            "view": ("uniform sampler2D uBlit;\n" + consts[view.group(1)]) if view else None,
        })

    # Copies an offscreen buffer to the screen: for feedback effects.
    blit = ("\nuniform sampler2D uBlit;\nuniform float uBlitScale;\n"
            "vec3 shade(vec2 p) { return texture2D(uBlit, (vPos * 0.5 + 0.5) * uBlitScale).rgb; }\n")
    return {
        "groups": list(GROUPS) + ["Other"],
        "effects": effects,
        "vertex": consts["DEMO_VERTEX"],
        "header": consts["HEADER"],
        "footer": consts["FOOTER"],
        "blit": blit,
    }


def main() -> int:
    data = json.dumps(build(), separators=(",", ":"))
    if "--check" in sys.argv:
        current = OUT.read_text() if OUT.exists() else ""
        if current != data:
            print(f"{OUT.relative_to(ROOT)} is out of date: run scripts/extract-tv-shaders.py")
            return 1
        return 0
    OUT.write_text(data)
    n = len(json.loads(data)["effects"])
    print(f"wrote {OUT.relative_to(ROOT)}: {n} effects, {len(data) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
