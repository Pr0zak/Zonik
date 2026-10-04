package com.zonik.app.ui.tv

/*
 * More classic demo effects: shader bodies for [DemoEffect], each a `vec3 shade(vec2 p)` that the
 * enum wraps in the shared header and footer. The same rules apply as in DemoEffects.kt — no
 * raymarching, short loops, and `uPhase` / `uSpin` / `uTime` used only in ways that repeat every 2.
 */

/**
 * A 3x5 bitmap font for the text-mode effects, one glyph per call: 0-9, then A-G (10-16), then
 * - # . : = + * and a solid block (17-24); anything else is a space. Each glyph is a 15-bit mask,
 * bit `row * 3 + column` from the top left, which needs highp to stay exact (the header asks
 * for it).
 */
internal const val GLYPHS = """
float glyphMask(float c) {
    if (c < 0.5) return 31599.0;
    if (c < 1.5) return 29850.0;
    if (c < 2.5) return 29671.0;
    if (c < 3.5) return 31207.0;
    if (c < 4.5) return 18925.0;
    if (c < 5.5) return 31183.0;
    if (c < 6.5) return 31695.0;
    if (c < 7.5) return 9511.0;
    if (c < 8.5) return 31727.0;
    if (c < 9.5) return 31215.0;
    if (c < 10.5) return 23530.0;
    if (c < 11.5) return 15083.0;
    if (c < 12.5) return 29263.0;
    if (c < 13.5) return 15211.0;
    if (c < 14.5) return 29391.0;
    if (c < 15.5) return 4815.0;
    if (c < 16.5) return 31567.0;
    if (c < 17.5) return 448.0;
    if (c < 18.5) return 24445.0;
    if (c < 19.5) return 8192.0;
    if (c < 20.5) return 1040.0;
    if (c < 21.5) return 3640.0;
    if (c < 22.5) return 1488.0;
    if (c < 23.5) return 21973.0;
    if (c < 24.5) return 32767.0;
    return 0.0;
}
// Whether glyph c covers f, a point in its cell (0..1, y up). The cell has a one-pixel gutter
// on the right and bottom so neighbouring characters do not touch.
float glyph(float c, vec2 f) {
    vec2 g = floor(vec2(f.x * 4.0, (1.0 - f.y) * 6.0));
    if (g.x > 2.0 || g.y > 4.0) return 0.0;
    float bit = g.y * 3.0 + g.x;
    return mod(floor(glyphMask(c) / exp2(bit)), 2.0);
}
"""

/**
 * Spectrum waterfall: the spectrum painted as a fresh line at the bottom of the screen every
 * frame while everything already there scrolls up, so the music's recent past hangs above it
 * as a landscape of colour. Bass sits at both edges, treble in the middle; each kick leaves a
 * bright seam across the flow.
 */
internal const val WATERFALL_BODY = """
vec3 shade(vec2 p) {
    vec2 uv = vPos * 0.5 + 0.5;
    if (uv.y > uPx.y * 2.0) {
        return max(prevAt(uv - vec2(0.0, uPx.y * 2.0)) * 0.996 - 0.001, 0.0);
    }
    float b = floor((1.0 - abs(uv.x - 0.5) * 2.0) * 63.99);
    float level = band(b);
    vec3 col = colorAt(level * 0.7 + uPhase * 0.5) * pow(level, 1.4) * 1.3;
    col += vec3(1.0) * smoothstep(0.75, 1.0, level) * 0.5;
    col += vivid(uC0) * uKick * uKick * 0.5;
    return col;
}
"""

/**
 * Hex pulse: a honeycomb filling the screen, each cell lit by the band of the spectrum that
 * belongs to its distance from the centre — bass in the middle, treble at the edges — and every
 * kick's shockwave ring passing through it as a brighter wave.
 *
 * Variants: 1 Hex radar (spectrum by angle), 2 Triangle pulse (triangle grid), 3 Hex flip
 * (tiles turn over as the wave passes), 4 Cell pulse (drifting Voronoi cells).
 */
internal const val HEXPULSE_BODY = """
vec3 shade(vec2 p) {
#if VARIANT == 2
    // Triangles: skewed coordinates make an equilateral triangle grid; each cell is the lower
    // or upper half of a rhombus, and the edge measure comes from its smallest barycentric
    // coordinate (1/3 at the centre, 0 on an edge).
    const float S = 0.11;
    vec2 q = p / S;
    vec2 sk = vec2(q.x - q.y * 0.57735, q.y * 1.1547);
    vec2 base = floor(sk);
    vec2 f = fract(sk);
    bool upper = f.x + f.y > 1.0;
    vec3 bary = upper ? vec3(1.0 - f.x, 1.0 - f.y, f.x + f.y - 1.0) : vec3(f.x, f.y, 1.0 - f.x - f.y);
    vec2 cs = base + (upper ? vec2(2.0 / 3.0) : vec2(1.0 / 3.0));
    vec2 centre = vec2(cs.x + cs.y * 0.5, cs.y * 0.866) * S;
    float edge = 0.5 - min(min(bary.x, bary.y), bary.z) * 1.5;
#elif VARIANT == 4
    // Cells: a Voronoi diagram of drifting seeds; the edge measure is how close the
    // second-nearest seed is.
    const float S = 0.16;
    vec2 q = p / S;
    vec2 base = floor(q);
    float d1 = 9.0;
    float d2 = 9.0;
    vec2 best = vec2(0.0);
    for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
            vec2 c = base + vec2(float(i), float(j));
            float h = hash(c);
            vec2 seed = c + 0.5 + 0.35 * vec2(sin(uTime * PI * 2.0 * (1.0 + floor(h * 3.0)) + h * 6.3),
                                              cos(uTime * PI * 2.0 * (1.0 + floor(h * 3.0)) + h * 4.1));
            float d = length(q - seed);
            if (d < d1) { d2 = d1; d1 = d; best = seed; } else if (d < d2) { d2 = d; }
        }
    }
    vec2 centre = best * S;
    float edge = 0.5 - clamp((d2 - d1) * 1.2, 0.0, 0.5);
#else
    const float S = 0.075;
    vec2 r = vec2(1.0, 1.7320508);
    vec2 q = p / S;
    vec2 a = mod(q, r) - r * 0.5;
    vec2 b = mod(q - r * 0.5, r) - r * 0.5;
    vec2 g = dot(a, a) < dot(b, b) ? a : b;
    vec2 centre = (q - g) * S;
#endif
    float dist = length(centre);
    float wave = 0.0;
    for (int i = 0; i < 4; i++) {
        float age = i == 0 ? uRings.x : (i == 1 ? uRings.y : (i == 2 ? uRings.z : uRings.w));
        if (age < 0.0) continue;
        wave += exp(-abs(dist - age * 0.9) * 10.0) * exp(-age * 0.8);
    }
#if VARIANT == 3
    // Flip: each hexagon turns over like a tile as the wave passes, showing its other colour.
    float flip = wave * PI * 1.5;
    float cf = cos(flip);
    g.x /= max(abs(cf), 0.06);
    bool back = cf < 0.0;
#endif
#if VARIANT == 0 || VARIANT == 1 || VARIANT == 3
    float edge = max(abs(g.x) * 0.866 + abs(g.y) * 0.5, abs(g.y));   // 0 centre, ~0.5 edge
#endif
#if VARIANT == 1
    // Radar: the spectrum runs round the honeycomb by angle (bass at the top, mirrored down
    // both sides), as in the sunburst.
    float u = abs(fastAtan2(centre.x, centre.y)) / PI;
    float level = band(floor(u * 63.0));
    vec3 hue = colorAt(u * 0.5 + uPhase * 0.5);
#else
    float level = band(floor(clamp(dist / 1.9, 0.0, 1.0) * 63.0));
    vec3 hue = colorAt(dist * 0.3 + uPhase * 0.5);
#endif
#if VARIANT == 3
    if (back) hue = colorAt(dist * 0.3 + uPhase * 0.5 + 0.5);
#endif
    float fill = 1.0 - smoothstep(0.38, 0.44, edge);
    float rim = exp(-abs(edge - 0.43) * 40.0);
    vec3 col = hue * fill * (0.04 + 0.85 * level * level + 0.6 * wave);
    col += hue * rim * (0.08 + 0.4 * level);
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Lissajous scopes: the waveform plotted against a slightly later copy of itself, which draws
 * it as a looping knot instead of a line, the way an XY oscilloscope does. Two scopes, either
 * side of the cover, mirrored; the phosphor glows on in the trails of the previous frames.
 * Bass swells the knot, the kick flares it.
 */
internal const val LISSAJOUS_BODY = """
float segDist(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a;
    vec2 ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}
vec3 shade(vec2 p) {
    vec2 uv = vPos * 0.5 + 0.5;
    vec2 q = vec2(vPos.x * uAspect, vPos.y);
    vec3 col = max(prevAt(uv) * 0.86 - 0.004, 0.0);
    float h = 0.24 + 0.01 * uKick;
    // Mirror so one plot draws both scopes.
    vec2 s = vec2(abs(q.x) - 1.0, q.y);
    s = rot(uSpin * PI) * s;
    float size = 0.32 + 0.18 * uLow + 0.1 * uKick;
    float d = 1e9;
    vec2 prev = vec2(wave(0.0), wave(0.06)) * size;
    for (int i = 1; i <= 16; i++) {
        float t = float(i) / 16.0 * 0.6;
        vec2 cur = vec2(wave(t), wave(t + 0.06)) * size;
        d = min(d, segDist(s, prev, cur));
        prev = cur;
    }
    vec3 hue = colorAt(0.05 + uPhase * 0.5);
    col += hue * (exp(-d * 260.0) * 1.0 + exp(-d * 40.0) * 0.15) * (0.8 + 0.6 * uKick);
    col += vec3(1.0) * exp(-d * 900.0) * 0.5;
    // The cover, fresh each frame so the trails never smear it.
    float inside = 1.0 - smoothstep(0.0, 0.006, coverDist(q, h));
    col = mix(col, texture2D(uTex, vec2(q.x, -q.y) / (2.0 * h) + 0.5).rgb, inside);
    col += hue * exp(-abs(coverDist(q, h)) * 50.0) * (0.15 + 0.6 * uKick);
    return col;
}
"""

/**
 * Bump-mapped cover: the cover tiled across a slowly turning plane as if embossed — its
 * brightness taken as height — and lit by a light that circles wider with the bass. The kick
 * flares the highlights.
 */
internal const val BUMP_BODY = """
float lum(vec3 c) { return dot(c, vec3(0.3, 0.55, 0.15)); }
vec3 shade(vec2 p) {
    vec2 q = rot(uSpin * PI) * p * 0.8 + vec2(uTime, 0.0);
    const float E = 1.0 / 256.0;
    vec3 base = texture2D(uTex, q).rgb;
    float h0 = lum(base);
    float hx = lum(texture2D(uTex, q + vec2(E, 0.0)).rgb);
    float hy = lum(texture2D(uTex, q + vec2(0.0, E)).rgb);
    vec3 n = normalize(vec3((h0 - hx) * 6.0, (h0 - hy) * 6.0, 0.25));
    float t = uTime * PI * 4.0;
    vec2 lp = vec2(cos(t), sin(t * 1.5)) * (0.4 + 0.6 * uLow) * vec2(uAspect, 1.0) * 0.6;
    vec3 l = normalize(vec3(lp - p, 0.5));
    float diff = max(dot(n, l), 0.0);
    float spec = pow(max(dot(reflect(-l, n), vec3(0.0, 0.0, 1.0)), 0.0), 24.0);
    float fall = 1.0 / (1.0 + dot(lp - p, lp - p) * 1.5);
    vec3 col = punch(base) * (0.08 + 1.1 * diff * fall);
    col += mix(vivid(uC1), vec3(1.0), 0.5) * spec * fall * (0.6 + 1.2 * uKick);
    return col;
}
"""

/**
 * Shadebobs: six soft blobs swinging on Lissajous paths, each adding its colour to the frame
 * before, which fades only slowly — so they paint glowing ribbons that overlap into white,
 * the Amiga way. Each blob swells with its band; the kick brightens them all.
 */
internal const val SHADEBOBS_BODY = """
vec3 shade(vec2 p) {
    vec2 uv = vPos * 0.5 + 0.5;
    vec2 q = vec2(vPos.x * uAspect, vPos.y);
    vec3 col = max(prevAt(uv) * 0.975 - 0.002, 0.0);
    float t = uTime * PI * 2.0;
    for (int i = 0; i < 6; i++) {
        float fi = float(i);
        vec2 c = vec2(sin(t * (3.0 + fi) + fi * 1.3) * uAspect * 0.75, sin(t * (4.0 + fi * 2.0) + fi * 0.7) * 0.75);
        float level = band(fi * 10.0 + 2.0);
        float rad = 0.05 + 0.06 * level;
        vec2 d = q - c;
        col += colorAt(fi / 6.0 + uPhase * 0.5) * exp(-dot(d, d) / (rad * rad)) * (0.08 + 0.1 * uKick);
    }
    return min(col, 1.2);
}
"""

/**
 * Checkerboard floor: the endless checked plane of a hundred intros, turning slowly as it
 * rushes towards you, with copper raster bars swinging through the sky above the horizon. Bass
 * is the speed, the kick flashes the floor.
 */
internal const val CHECKER_BODY = """
vec3 shade(vec2 p) {
    float hz = 0.1 + 0.03 * sin(uTime * PI * 2.0);
    vec3 col;
    if (p.y < hz) {
        float d = 0.3 / (hz - p.y);
        vec2 w = rot(uSpin * PI) * vec2(p.x * d, d) + vec2(0.0, uPhase * 4.0);
        vec2 c = floor(w);
        float ch = mod(c.x + c.y, 2.0);
        vec3 a = colorAt(0.05 + uPhase * 0.5);
        vec3 b = colorAt(0.55 + uPhase * 0.5) * 0.25;
        col = mix(b, a, ch) * (0.7 + 0.3 * uLow + 0.4 * uKick);
        // Soften the far squares into the horizon instead of letting them shimmer.
        col = mix(col, mix(a, b, 0.5) * 0.5, smoothstep(4.0, 30.0, d));
        col *= 0.35 + 0.65 * exp(-d * 0.04);
    } else {
        col = colorAt(0.66) * 0.04 * (1.0 + (p.y - hz));
        for (int i = 0; i < 3; i++) {
            float fi = float(i);
            float y = hz + 0.35 + 0.28 * sin(uTime * PI * (2.0 + 2.0 * fi) + fi * 2.1);
            float x = abs(p.y - y) / 0.06;
            col += colorAt(fi / 3.0) * max(1.0 - x, 0.0) * (0.6 + 0.4 * cos(x * PI)) * (0.6 + 0.6 * uMid);
        }
    }
    col += vivid(uC0) * exp(-abs(p.y - hz) * 60.0) * 0.5;
    col *= clamp(1.35 - 0.25 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Truchet maze: square tiles each holding two quarter-circle arcs, turned one way or the other
 * at random so the arcs join into endless winding paths. Every kick re-turns the tiles, so the
 * maze rewires itself on the beat; light flows along the paths, brighter where the band for
 * that part of the screen is loud.
 *
 * Variants: 1 Hex Truchet (three arcs per hexagon), 2 Maze (C64 "10 PRINT" diagonals),
 * 3 Truchet tubes (fat, shaded paths).
 */
internal const val TRUCHET_BODY = """
vec3 shade(vec2 p) {
    float level = band(floor(clamp(length(p) / 1.9, 0.0, 1.0) * 63.0));
    vec3 hue = colorAt(length(p) * 0.35 + uPhase * 0.5);
#if VARIANT == 1
    // Hex Truchet: each hexagon holds three arcs round alternate corners, joining the middles
    // of neighbouring sides, so the paths wind in three directions instead of two.
    const float S = 0.17;
    vec2 q = rot(0.25 * sin(uTime * PI * 2.0)) * p / S + vec2(uTime * 4.0, 0.0);
    vec2 r = vec2(1.0, 1.7320508);
    vec2 a = mod(q, r) - r * 0.5;
    vec2 b = mod(q - r * 0.5, r) - r * 0.5;
    vec2 g = dot(a, a) < dot(b, b) ? a : b;
    vec2 cell = floor((q - g) * 2.0 + 0.5);
    float flip = step(0.5, hash(cell + vec2(uKicks * 1.37, uKicks * 0.71)));
    float d = 9.0;
    float along = 0.0;
    for (int k = 0; k < 3; k++) {
        float ang = PI / 6.0 + (float(k) * 2.0 + flip) * PI / 3.0;
        vec2 v = 0.57735 * vec2(cos(ang), sin(ang));
        vec2 rel = g - v;
        float dk = abs(length(rel) - 0.288675);
        if (dk < d) { d = dk; along = fastAtan2(rel.y, rel.x) / (PI / 1.5) + float(k); }
    }
    d *= 0.95;
    float lineW = 0.055;
#elif VARIANT == 2
    // Maze: the "10 PRINT" diagonals of the Commodore 64, one slash or backslash per cell,
    // rewired on every kick.
    const float S = 0.1;
    vec2 q = rot(0.25 * sin(uTime * PI * 2.0)) * p / S + vec2(uTime * 4.0, 0.0);
    vec2 cell = floor(q);
    vec2 f = fract(q);
    float flip = step(0.5, hash(cell + vec2(uKicks * 1.37, uKicks * 0.71)));
    float d = (flip > 0.5 ? abs(f.x - f.y) : abs(f.x + f.y - 1.0)) * 0.7071;
    float along = (flip > 0.5 ? f.x + f.y : f.x - f.y + 1.0) * 0.5 + mod(cell.x + cell.y, 2.0);
    float lineW = 0.07;
#else
    const float S = 0.14;
    vec2 q = rot(0.25 * sin(uTime * PI * 2.0)) * p / S + vec2(uTime * 4.0, 0.0);
    vec2 cell = floor(q);
    vec2 f = fract(q);
    float flip = step(0.5, hash(cell + vec2(uKicks * 1.37, uKicks * 0.71)));
    if (flip > 0.5) f.x = 1.0 - f.x;
    float d1 = abs(length(f) - 0.5);
    float d2 = abs(length(f - 1.0) - 0.5);
    float d = min(d1, d2);
    // Position along the arc, so light can run along the path.
    vec2 rel = d1 < d2 ? f : 1.0 - f;
    float along = atan(rel.y, rel.x + 1e-4) / (0.5 * PI) + mod(cell.x + cell.y, 2.0);
#if VARIANT == 3
    float lineW = 0.17;
#else
    float lineW = 0.06;
#endif
#endif
    float flow = 0.5 + 0.5 * sin(along * PI * 2.0 - uPhase * PI * 4.0);
#if VARIANT == 3
    // Tubes: fat paths shaded as if round, lit from the top left, with a moving band of light.
    float hgt = sqrt(max(1.0 - (d / lineW) * (d / lineW), 0.0));
    float inside = step(d, lineW);
    vec3 col = hue * inside * (0.12 + 0.75 * hgt) * (0.6 + 0.8 * level);
    col += vec3(1.0) * inside * pow(hgt, 12.0) * 0.35;
    col += hue * inside * flow * hgt * (0.2 + 0.6 * uKick);
#else
    float line = 1.0 - smoothstep(lineW, lineW + 0.04, d);
    vec3 col = hue * line * (0.15 + (0.5 + 0.8 * level) * flow);
    col += hue * exp(-d * 18.0) * (0.06 + 0.3 * uKick);
#endif
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Tracker: a ProTracker-style pattern view — four channels of note, instrument and effect
 * columns scrolling past a highlighted play line, with a VU bar per channel above. The notes are
 * made up (a 64-row pattern seeded per row), the VU bars are the real spectrum. It frames no
 * cover, but asks the overlay to leave its own out (framesCover) so the pattern stays readable.
 */
internal const val TRACKER_BODY = GLYPHS + """
// Glyph code for character slot x (0..9 within a channel column) of a pattern row.
float cellChar(float x, float row, float ch) {
    float h = hash(vec2(row, ch * 17.0));
    bool note = h < 0.32;
    if (x < 2.5) {
        if (!note) return 17.0;                                  // ---
        float n = floor(hash(vec2(row, ch + 3.0)) * 7.0);
        if (x < 0.5) return n < 5.0 ? 12.0 + n : 10.0 + (n - 5.0); // C D E F G A B
        if (x < 1.5) return hash(vec2(row, ch + 5.0)) < 0.3 ? 18.0 : 17.0;  // # or -
        return 3.0 + floor(hash(vec2(row, ch + 7.0)) * 3.0);       // octave
    }
    if (x < 3.5) return 99.0;
    if (x < 5.5) {
        if (!note) return 19.0;                                  // ..
        float inst = 1.0 + floor(hash(vec2(ch, 1.0)) * 15.0);
        return x < 4.5 ? 0.0 : inst;
    }
    if (x < 6.5) return 99.0;
    if (hash(vec2(row, ch + 9.0)) > 0.25) return 19.0;           // ...
    return floor(hash(vec2(row * 3.0 + x, ch)) * 16.0);
}
vec3 shade(vec2 p) {
    p += uCenter;
    vec3 col = colorAt(0.66) * 0.03;
    const float CW = 0.072;
    const float CH = 0.1;
    // 47 characters: row number, then four channels of ten plus a gap.
    float x = (p.x + 47.0 * CW * 0.5) / CW;
    float rows = uTime * 160.0;                     // 8 rows a second; 320 a cycle = 5 patterns
    float y = (0.25 - p.y) / CH + fract(rows);
    float rowOnScreen = floor(y);
    float row = mod(floor(rows) + rowOnScreen - 5.0, 64.0);
    float cx = floor(x);
    vec2 f = vec2(fract(x), 1.0 - fract(y));
    // VU bars across the top.
    if (p.y > 0.42 && p.y < 0.85 && cx >= 3.0 && cx < 47.0) {
        float ch = floor((cx - 3.0) / 11.0);
        float within = mod(cx - 3.0, 11.0);
        float level = band(ch * 14.0 + 2.0);
        float top = 0.44 + level * 0.4;
        if (within > 0.5 && within < 9.5 && p.y < top) {
            float seg = step(0.25, fract(p.y / 0.025));
            col += colorAt((p.y - 0.44) * 1.5 + uPhase * 0.5) * seg * 0.9;
        }
        return col;
    }
    if (p.y > 0.3 || p.y < -0.62 || cx < 0.0 || cx >= 47.0) return col;
    float code = 99.0;
    vec3 ink = vec3(0.75);
    if (cx < 2.0) {
        code = cx < 1.0 ? floor(row / 16.0) : mod(row, 16.0);
        ink = colorAt(0.66) * 0.8 + 0.2;
    } else if (cx >= 3.0) {
        float ch = floor((cx - 3.0) / 11.0);
        float within = mod(cx - 3.0, 11.0);
        if (within < 9.5) code = cellChar(within, row, ch);
        ink = within < 2.5 ? vec3(0.95) : (within < 5.5 ? colorAt(0.33) : colorAt(0.05));
    }
    float on = glyph(code, f);
    bool play = rowOnScreen == 5.0;
    if (play) col += colorAt(0.66) * 0.35 * (0.8 + 0.4 * uBeat);
    if (mod(row, 4.0) < 0.5) col += vec3(0.03);
    col += ink * on * (play ? 1.2 : 0.65);
    return col;
}
"""

/**
 * Halftone: the cover printed as three screens of dots — red, green and blue, each grid turned
 * to its own angle like a print press, added together on black. Each dot's size is the colour
 * at its centre; bass swells them all. The cover drifts and turns slowly underneath.
 */
internal const val HALFTONE_BODY = """
float dots(vec2 p, float ang, int ch) {
    const float S = 0.032;
    vec2 q = rot(ang) * p / S;
    vec2 c = floor(q) + 0.5;
    vec2 at = rot(-ang) * c * S;
    vec2 uv = rot(uSpin * PI) * at * 0.55 + vec2(uTime, 0.0);
    vec3 col = punch(texture2D(uTex, uv).rgb);
    float v = ch == 0 ? col.r : (ch == 1 ? col.g : col.b);
    float r = sqrt(clamp(v * (0.85 + 0.4 * uLow), 0.0, 1.0)) * 0.62;
    return 1.0 - smoothstep(r - 0.08, r + 0.02, length(q - c));
}
vec3 shade(vec2 p) {
    vec3 col = vec3(dots(p, 0.26, 0), dots(p, 1.31, 1), dots(p, 0.79, 2));
    col *= 0.9 + 0.3 * uKick;
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * ASCII: the cover drawn in text-mode characters, picked by brightness from a ramp running
 * from a dot to a solid block, each in its own colour from the cover. The cover pans and zooms
 * slowly; the kick briefly brightens the whole ramp a step.
 */
internal const val ASCII_BODY = GLYPHS + """
vec3 shade(vec2 p) {
    vec2 px = gl_FragCoord.xy / vec2(8.0, 12.0);
    vec2 cell = floor(px);
    vec2 f = fract(px);
    vec2 at = (cell + 0.5) * vec2(8.0, 12.0) * uPx * 2.0 - 1.0;
    at.x *= uAspect;
    vec2 uv = vec2(at.x, -at.y) * (0.6 + 0.12 * sin(uTime * PI * 2.0)) + vec2(uTime, 0.0);
    vec3 c = punch(texture2D(uTex, uv).rgb);
    float l = clamp(dot(c, vec3(0.3, 0.55, 0.15)) * 1.3 + 0.12 * uKick, 0.0, 0.999);
    float k = floor(l * 10.0);
    // Ramp: space . : - = + * # 8 block
    float code = k < 0.5 ? 99.0 : (k < 1.5 ? 19.0 : (k < 2.5 ? 20.0 : (k < 3.5 ? 17.0 : (k < 4.5 ? 21.0
               : (k < 5.5 ? 22.0 : (k < 6.5 ? 23.0 : (k < 7.5 ? 18.0 : (k < 8.5 ? 8.0 : 24.0))))))));
    vec3 col = vivid(c + 0.02) * glyph(code, f) * (0.55 + 0.5 * l);
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Milkdrop warp: the previous frame pulled through a slowly breathing warp — zoomed, turned and
 * rippled by the bands — and faded, with a fresh glowing waveform ring and spectrum sparks
 * drawn on top each frame, so whatever is drawn swirls away into flowing colour.
 */
internal const val MILKDROP_BODY = """
vec3 shade(vec2 p) {
    vec2 uv = vPos * 0.5 + 0.5;
    vec2 c = vec2((uv.x - 0.5) * uAspect, uv.y - 0.5);
    float t = uTime * PI * 2.0;
    c = rot(0.006 + 0.02 * uMid * sin(t)) * c * (0.985 - 0.02 * uLow);
    c += 0.004 * vec2(sin(c.y * 12.0 + t * 3.0), cos(c.x * 10.0 - t * 2.0)) * (1.0 + 2.0 * uHigh);
    vec2 src = vec2(c.x / uAspect, c.y) + 0.5;
    vec3 col = max(prevAt(src) * 0.965 - 0.002, 0.0);
    // A slow hue drift in the feedback keeps the trails changing colour as they fade.
    col = mix(col, col.gbr, 0.015);
    vec2 q = vec2(vPos.x * uAspect, vPos.y);
    float r = length(q);
    float a = abs(fastAtan2(q.y, q.x)) / PI;
    float ring = 0.38 + wave(a * 0.5) * (0.06 + 0.1 * uLow);
    float d = abs(r - ring);
    col += colorAt(uPhase * 0.5 + a * 0.3) * (exp(-d * 200.0) * 0.9 + exp(-d * 30.0) * 0.08) * (0.7 + 0.8 * uKick);
    // Sparks thrown off at the spectrum's loud bands.
    float b = floor(a * 63.0);
    float spark = exp(-abs(r - (0.5 + band(b) * 0.5)) * 120.0) * step(0.5, band(b)) * (1.0 - smoothstep(0.2, 0.45, abs(fract(a * 63.0) - 0.5)));
    col += colorAt(a + uPhase * 0.5) * spark * 0.6;
    return min(col, 1.3);
}
"""
