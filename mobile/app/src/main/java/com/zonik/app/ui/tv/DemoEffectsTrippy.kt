package com.zonik.app.ui.tv

/*
 * Trippy, beat-driven effects: shader bodies for [DemoEffect], each a `vec3 shade(vec2 p)` that
 * the enum wraps in the shared header and footer. Every one answers the kick visibly (`uKick`)
 * and most change something outright every few kicks (`uKicks`), so they move with the music
 * rather than just drifting. Same rules as DemoEffects.kt: no raymarching, short loops, and
 * `uPhase` / `uSpin` / `uTime` used only in ways that repeat every 2.
 */

/**
 * Hypno spiral: logarithmic spiral arms pouring endlessly into the centre, crossed by a second
 * set turning the other way so the two beat against each other. The number of arms steps every
 * eight kicks; each kick lunges the zoom forward and flashes the stripes.
 */
internal const val HYPNO_BODY = """
vec3 shade(vec2 p) {
    float r = max(length(p), 1e-3);
    float a = fastAtan2(p.y, p.x) / (2.0 * PI);
    float lr = log(r) - 0.35 * uKick;
#if VARIANT == 1
    // Hypno rings: no arms, just concentric rings pouring inward, crossed by a faint two-arm spiral.
    float arms = 0.0;
#else
    float arms = 3.0 + mod(floor(uKicks / 8.0), 4.0);
#endif
    float s1 = fract(a * arms + lr * 1.6 - uPhase);
    float s2 = fract(-a * (arms + 2.0) + lr * 2.4 - uPhase * 2.0);
    float b1 = smoothstep(0.42, 0.5, s1) - smoothstep(0.92, 1.0, s1);
    float b2 = smoothstep(0.45, 0.5, s2) - smoothstep(0.95, 1.0, s2);
    vec3 c1 = colorAt(lr * 0.25 + uPhase * 0.5);
    vec3 c2 = colorAt(lr * 0.25 + uPhase * 0.5 + 0.5);
    vec3 col = mix(c1 * 0.12, c1, b1);
    col = mix(col, col * 0.35 + c2 * 0.8, b2 * 0.6);
    col *= 0.7 + 0.5 * uLow + 0.6 * uKick;
    col += vec3(1.0) * exp(-r * 9.0) * (0.3 + 0.8 * uBeat);
    col *= smoothstep(0.0, 0.12, r);
    return col;
}
"""

/**
 * Kaleido fractal: a kaleidoscopic IFS — fold the plane into its positive quadrant, shift,
 * turn and grow it, six times over — zooming endlessly, two copies a factor apart cross-fading
 * so the dive never stops. The fold angle breathes with the mids, bass widens the shift, the
 * kick lights the filaments.
 */
internal const val KIFS_BODY = """
vec3 kifs(vec2 p, float z) {
    float zoom = exp2(-1.5 * z);
    vec2 q = rot(uSpin * PI) * p * zoom * 1.6;
    float scale = 1.0;
    float trap = 1e9;
    float ang = 0.55 + 0.12 * sin(uTime * PI * 2.0) + 0.1 * uMid;
    vec2 off = vec2(0.62, 0.38) * (1.0 + 0.15 * uLow);
    for (int i = 0; i < 6; i++) {
        q = abs(q) - off;
        q = rot(ang) * q * 1.32;
        scale *= 1.32;
        trap = min(trap, abs(q.y) / scale);
    }
    float line = exp(-trap * 400.0 / zoom);
    vec3 col = colorAt(length(q) * 0.05 + uPhase * 0.5) * (0.12 + 0.2 / (1.0 + length(q) * 0.2));
    col += colorAt(0.05 + uPhase * 0.5) * line * (0.9 + 1.0 * uKick);
    return col;
}
vec3 shade(vec2 p) {
    float t = fract(uTime * 2.0 + uPhase * 0.5);
    vec3 col = mix(kifs(p, t - 1.0), kifs(p, t), smoothstep(0.0, 1.0, 1.0 - t));
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Bass lens: a calm grid of dots, and every kick drops a lens into it where the stone lands
 * (the shockwave rings' drop points), bulging the grid outward and rippling as it relaxes. Bass
 * swells a lens at the centre; each dot's size is the band for its column.
 */
internal const val BASSLENS_BODY = """
vec3 shade(vec2 p) {
    p += uCenter;
    vec2 q = p;
    float bulge = 0.25 * uLow + 0.25 * uKick;
    q *= 1.0 - bulge * exp(-dot(p, p) * 3.0);
    for (int i = 0; i < 4; i++) {
        float age = i == 0 ? uRings.x : (i == 1 ? uRings.y : (i == 2 ? uRings.z : uRings.w));
        if (age < 0.0) continue;
        vec2 d = p - uDrops[i];
        float k = exp(-age * 2.5);
        q -= d * k * 0.6 * exp(-dot(d, d) * 10.0) * (1.0 + 0.4 * sin(age * 25.0 - length(d) * 30.0));
    }
    q = rot(0.1 * sin(uTime * PI * 2.0)) * q;
    const float S = 0.065;
    vec2 cell = floor(q / S);
    vec2 f = fract(q / S) - 0.5;
    float level = band(mod(abs(cell.x), 32.0) * 2.0);
    float rad = 0.12 + 0.22 * level;
    float dotv = 1.0 - smoothstep(rad - 0.05, rad + 0.03, length(f));
    vec3 hue = colorAt(length(cell) * 0.02 + uPhase * 0.5);
    vec3 col = hue * dotv * (0.35 + 0.9 * level + 0.4 * uKick);
    col += hue * exp(-length(f) * 6.0) * 0.06;
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Op art: concentric squares crossed with radial wedges in two hard colours, the stripes
 * rushing inward, the whole field warped by a wobble that swells with the mids. Every kick swaps
 * the two colours, so the pattern strobes in time.
 */
internal const val OPART_BODY = """
vec3 shade(vec2 p) {
    float r = length(p);
    float a = fastAtan2(p.y, p.x) / (2.0 * PI);
    float d = max(abs(p.x), abs(p.y));
    d += (0.04 + 0.08 * uMid) * sin(a * PI * 2.0 * 5.0 + uTime * PI * 4.0);
    float rings = step(0.5, fract(d * 7.0 - uPhase * 2.0));
    float wedges = step(0.5, fract(a * 12.0 + uSpin));
    float v = abs(rings - wedges);
    if (mod(uKicks, 2.0) > 0.5) v = 1.0 - v;
    vec3 a1 = vivid(uC0);
    vec3 a2 = colorAt(0.66) * 0.08;
    vec3 col = mix(a2, a1, v) * (0.75 + 0.4 * uKick);
    col *= clamp(1.35 - 0.3 * r, 0.0, 1.0);
    return col;
}
"""

/**
 * Wormhole: a neon tunnel with no texture — glowing rings racing past and spiral rails winding
 * along the walls — whose far end swings about as it twists. Each kick floods the rings with
 * light; bass is the speed.
 */
internal const val WORMHOLE_BODY = """
vec3 shade(vec2 p) {
    vec2 c = 0.18 * vec2(sin(uTime * PI * 2.0), cos(uTime * PI * 4.0));
    vec2 q = p - c * (1.0 - smoothstep(0.0, 1.0, length(p)));
    float r = max(length(q), 0.02);
    float depth = 0.3 / r;
    float a = fastAtan2(q.y, q.x) / (2.0 * PI) + depth * 0.06 * sin(uTime * PI * 2.0);
    float ring = fract(depth * 1.5 + uPhase * 2.0);
    float rail = fract(a * 10.0 + depth * 0.25 - uSpin * 2.0);
    float ringL = exp(-min(ring, 1.0 - ring) * 30.0);
    float railL = exp(-min(rail, 1.0 - rail) * 22.0);
    vec3 hue = colorAt(depth * 0.08 + uPhase * 0.5);
    vec3 col = hue * ringL * (0.4 + 1.4 * uKick + 0.4 * uLow);
    col += colorAt(depth * 0.08 + uPhase * 0.5 + 0.4) * railL * 0.55;
    col *= exp(-depth * 0.06) * smoothstep(0.02, 0.15, r);
    col += vec3(1.0) * exp(-r * 18.0) * 0.4 * (0.5 + uBeat);
    return col;
}
"""

/**
 * Liquid marble: noise warped by noise warped by noise (after Iñigo Quilez), so colour flows
 * like oil on water in the cover's palette. The warp drifts round a loop, so it never jumps;
 * the kick yanks the warp harder and bass rolls the colours. Half resolution.
 */
internal const val MARBLE_BODY = """
float mnoise(vec2 x) {
    vec2 i = floor(x);
    vec2 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
               mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}
float mfbm(vec2 x) {
    float v = 0.0;
    float amp = 0.5;
    for (int i = 0; i < 4; i++) {
        v += amp * mnoise(x);
        x = rot(0.5) * x * 2.02;
        amp *= 0.5;
    }
    return v;
}
vec3 shade(vec2 p) {
    float t = uTime * PI * 2.0;
    vec2 drift = vec2(cos(t), sin(t)) * 1.5;
    vec2 x = p * 1.4 + drift;
    vec2 q = vec2(mfbm(x), mfbm(x + vec2(5.2, 1.3)));
    float warp = 3.0 + 2.5 * uKick + uLow;
    float f = mfbm(x + warp * q + vec2(sin(t * 2.0), cos(t)) * 0.8);
    vec3 col = colorAt(f * 1.2 + q.x * 0.5 + uPhase * 0.5) * (0.25 + f * f * 1.6);
    col += vivid(uC1) * smoothstep(0.6, 0.9, f) * (0.2 + 0.6 * uKick);
    col *= clamp(1.35 - 0.25 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Hex tunnel: flying down a six-sided tunnel built of neon-edged panels. Panels light up at
 * random, a new pattern on every kick; the tunnel rolls with the mids, bass is the speed.
 */
internal const val HEXTUNNEL_BODY = """
vec3 shade(vec2 p) {
    vec2 q = rot(uSpin * PI + 0.3 * sin(uTime * PI * 2.0)) * p;
    vec2 aq = abs(q);
    float hr = max(aq.x * 0.866 + aq.y * 0.5, aq.y);
    hr = max(hr, 0.02);
    float depth = 0.3 / hr * (1.0 - 0.08 * uKick);
    float a = fastAtan2(q.y, q.x) / (2.0 * PI) + 0.5;
    float sector = floor(a * 6.0);
    float across = fract(a * 6.0);
    float v = depth * 1.5 + uPhase * 2.0;
    float ringId = floor(v);
    float along = fract(v);
    float lit = step(0.72, hash(vec2(ringId, sector) + uKicks * 1.7));
    float edge = exp(-min(across, 1.0 - across) * 30.0) + exp(-min(along, 1.0 - along) * 25.0);
    vec3 hue = colorAt(sector / 6.0 + uPhase * 0.5);
    vec3 col = hue * edge * 0.45;
    col += hue * lit * (0.25 + 0.9 * uKick + 0.4 * uLow) * (0.4 + 0.6 * (1.0 - abs(along - 0.5) * 2.0));
    col *= exp(-depth * 0.07) * smoothstep(0.02, 0.12, hr);
    return col;
}
"""

/**
 * Laser show: beams fanning up from two projectors at the bottom corners through a light haze,
 * sweeping back and forth; each kick throws the fans wide and strobes them. Beams pick up the
 * cover's colours, and a faint reflection lies on the floor.
 */
internal const val LASERS_BODY = """
float beam(vec2 p, vec2 o, float ang) {
    vec2 dir = vec2(sin(ang), cos(ang));
    vec2 d = p - o;
    float along = dot(d, dir);
    if (along < 0.0) return 0.0;
    float off = abs(d.x * dir.y - d.y * dir.x);
    return exp(-off * 260.0) * 0.9 + exp(-off * 25.0) * 0.08;
}
vec3 shade(vec2 p) {
    p += uCenter;
    float floorY = -0.82;
    bool refl = p.y < floorY;
    if (refl) p.y = 2.0 * floorY - p.y;
    float haze = 0.6 + 0.4 * sin(p.x * 3.0 + sin(p.y * 4.0 + uTime * PI * 4.0) + uTime * PI * 2.0);
    vec3 col = colorAt(0.66) * 0.03;
    float spread = 0.35 + 0.5 * uKick + 0.2 * uLow;
    for (int s = 0; s < 2; s++) {
        float side = s == 0 ? -1.0 : 1.0;
        vec2 o = vec2(side * uAspect * 0.95, floorY);
        for (int i = 0; i < 5; i++) {
            float fi = float(i);
            float ang = -side * (0.45 + 0.2 * sin(uTime * PI * 6.0 + fi + side))
                      + (fi - 2.0) * spread * 0.22;
            col += colorAt(fi / 5.0 + side * 0.25 + uPhase * 0.5) * beam(p, o, ang) * haze;
        }
    }
    col *= 0.8 + 0.9 * uKick;
    if (refl) col *= 0.25;
    return col;
}
"""

/**
 * Rose curves: four layered flowers drawn as glowing lines — r = cos(kθ) — each turning at
 * its own pace. The petal counts change every four kicks, and each kick pumps the flowers out
 * and back. Petal counts are whole numbers, so each curve closes cleanly.
 */
internal const val ROSE_BODY = """
vec3 shade(vec2 p) {
    float r = length(p);
    float th = fastAtan2(p.y, p.x);
    vec3 col = colorAt(0.66) * 0.025;
    float step4 = floor(uKicks / 4.0);
    for (int i = 0; i < 4; i++) {
        float fi = float(i);
        float k = 2.0 + mod(step4 + fi * 3.0, 6.0);
        float R = (0.35 + fi * 0.17) * (1.0 + 0.18 * uKick + 0.1 * uLow);
        float turn = uSpin * PI * (fi + 1.0) * (mod(fi, 2.0) * 2.0 - 1.0);
        float rr = R * abs(cos(k * (th + turn) * 0.5));
        float d = abs(r - rr);
        vec3 hue = colorAt(fi / 4.0 + uPhase * 0.5);
        col += hue * (exp(-d * 160.0) * 0.9 + exp(-d * 22.0) * 0.1) * (0.6 + 0.6 * uMid);
    }
    col += vec3(1.0) * exp(-r * 12.0) * 0.3 * uBeat;
    col *= clamp(1.35 - 0.3 * r, 0.0, 1.0);
    return col;
}
"""

/**
 * Tile zoom: an endless dive into tiles that split into four smaller tiles, each holding a
 * shape — circle, diamond, arcs or stripes — picked by a hash of its position alone, so after
 * each doubling the picture is exactly where it began. Five levels show at once, faded by size.
 * Bass is the dive speed; the kick flashes the outlines.
 */
internal const val TILEZOOM_BODY = """
float tileShape(vec2 f, float kind) {
    vec2 c = f - 0.5;
    if (kind < 0.25) return abs(length(c) - 0.33);
    if (kind < 0.5) return abs(abs(c.x) + abs(c.y) - 0.38);
    if (kind < 0.75) return min(abs(length(f) - 0.5), abs(length(f - 1.0) - 0.5));
    return abs(fract((c.x + c.y) * 3.0) - 0.5) * 0.33;
}
vec3 shade(vec2 p) {
    float z = fract(uPhase * 0.5);
    float zoom = exp2(z);
    vec2 q0 = rot(uSpin * PI) * p / zoom;
    vec3 col = colorAt(0.66) * 0.03;
    for (int l = 0; l < 5; l++) {
        float scale = exp2(float(l));
        vec2 q = q0 * scale * 1.5;
        vec2 cell = floor(q);
        vec2 f = fract(q);
        float h = hash(cell + 0.37);
        // On-screen size of a tile at this level: fade the tiny ones out and the huge ones away.
        float size = zoom / scale;
        float w = smoothstep(0.04, 0.18, size) * (1.0 - smoothstep(0.7, 1.4, size));
        float d = tileShape(f, h) * size;
        vec3 hue = colorAt(h + uPhase * 0.5);
        col += hue * w * (exp(-d * 260.0) * (0.7 + 0.8 * uKick) + exp(-d * 30.0) * 0.06);
    }
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Pulse grid: a field of squares that spin and swell in a wave rolling out from the centre on
 * every kick — the beat travelling across the screen — with each square's colour cycling
 * through the cover's palette by distance.
 */
internal const val PULSEGRID_BODY = """
vec3 shade(vec2 p) {
    const float S = 0.11;
    vec2 cell = floor(p / S);
    vec2 f = fract(p / S) - 0.5;
    vec2 centre = (cell + 0.5) * S;
    float dist = length(centre);
    float wave = 0.0;
    for (int i = 0; i < 4; i++) {
        float age = i == 0 ? uRings.x : (i == 1 ? uRings.y : (i == 2 ? uRings.z : uRings.w));
        if (age < 0.0) continue;
        wave += exp(-abs(dist - age * 1.1) * 9.0) * exp(-age * 0.7);
    }
    float ang = wave * 1.6 + uSpin * PI * 2.0;
    vec2 q = rot(ang) * f;
    float size = 0.18 + 0.2 * wave + 0.08 * uLow;
    float sq = max(abs(q.x), abs(q.y));
    float fill = 1.0 - smoothstep(size - 0.02, size + 0.02, sq);
    float rim = exp(-abs(sq - size) * 60.0);
    vec3 hue = colorAt(dist * 0.4 - uPhase * 0.5);
    vec3 col = hue * (fill * (0.12 + 0.9 * wave) + rim * (0.25 + 0.6 * wave));
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Lightning: each kick fires a bolt from the centre to where its stone lands (the shockwave
 * rings' drop points), jagged and flickering, fading fast; between kicks a dim storm of arcs
 * crackles round the middle. The jitter reseeds sixty times a second.
 */
internal const val LIGHTNING_BODY = """
float jag(float t, float seed) {
    return (hash(vec2(floor(t * 14.0), seed)) - 0.5) * (1.0 - fract(t * 14.0))
         + (hash(vec2(floor(t * 14.0) + 1.0, seed)) - 0.5) * fract(t * 14.0)
         + (hash(vec2(floor(t * 40.0), seed + 3.0)) - 0.5) * 0.35;
}
vec3 shade(vec2 p) {
    p += uCenter;
    float frame = floor(uTime * 1200.0);
    vec3 col = colorAt(0.66) * 0.03;
    col += colorAt(0.33) * 0.05 * (0.5 + 0.5 * sin(p.x * 3.0 + sin(p.y * 2.0 + uTime * PI * 2.0)));
    for (int i = 0; i < 4; i++) {
        float age = i == 0 ? uRings.x : (i == 1 ? uRings.y : (i == 2 ? uRings.z : uRings.w));
        if (age < 0.0 || age > 0.6) continue;
        vec2 target = uDrops[i] * 1.2;
        float len = length(target);
        vec2 dir = target / max(len, 1e-3);
        float along = dot(p, dir) / len;
        if (along < 0.0 || along > 1.0) continue;
        float side = p.x * dir.y - p.y * dir.x;
        float off = jag(along, frame + float(i) * 7.0) * 0.12 * sin(along * PI);
        float d = abs(side - off);
        float fade = exp(-age * 6.0);
        col += mix(vec3(0.75, 0.85, 1.0), colorAt(float(i) * 0.25), 0.3) * (exp(-d * 500.0) * 1.4 + exp(-d * 40.0) * 0.25) * fade;
    }
    // The resting storm: short arcs flickering round the centre.
    float r = length(p);
    float a = fastAtan2(p.y, p.x);
    float arc = abs(r - 0.25 - 0.05 * jag(a * 0.5 + 2.0, frame));
    float arc2 = abs(r - 0.42 - 0.07 * jag(a * 0.5 + 5.0, frame + 11.0));
    col += vec3(0.6, 0.75, 1.0) * (exp(-arc * 120.0) + 0.6 * exp(-arc2 * 140.0)) * (0.3 + 0.6 * uLow);
    col += vec3(0.7, 0.8, 1.0) * uKick * uKick * 0.12;
    return col;
}
"""

/**
 * Flower of life (sacred geometry) — a lattice of overlapping circles — drawn twice at
 * different sizes turning against each other, so the overlaps bloom into rosettes and dissolve
 * again. Each kick pulses the circle size; bass brightens the lines.
 */
internal const val SACRED_BODY = """
// Distance to the nearest circle edge in a hexagonal lattice of circles of radius R spaced R
// apart. Each point lies inside several circles, so the neighbouring cells of both
// interleaved rectangular lattices are checked, not only the nearest centre.
float lattice(vec2 p, float R) {
    vec2 r = vec2(1.0, 1.7320508) * R;
    float d = 1e9;
    for (int k = 0; k < 2; k++) {
        vec2 q = p - (k == 0 ? vec2(0.0) : r * 0.5);
        vec2 base = floor(q / r);
        for (int i = -1; i <= 1; i++) {
            for (int j = -1; j <= 1; j++) {
                vec2 c = (base + vec2(float(i), float(j)) + 0.5) * r;
                d = min(d, abs(length(q - c) - R));
            }
        }
    }
    return d;
}
vec3 shade(vec2 p) {
    float pulse = 1.0 + 0.08 * uKick;
    float d1 = lattice(rot(uSpin * PI) * p, 0.34 * pulse);
    float d2 = lattice(rot(-uSpin * PI * 2.0) * p, 0.62 * pulse);
    vec3 col = colorAt(0.66) * 0.03;
    col += colorAt(0.05 + uPhase * 0.5) * (exp(-d1 * 180.0) * 0.8 + exp(-d1 * 25.0) * 0.06) * (0.6 + 0.6 * uLow);
    col += colorAt(0.45 + uPhase * 0.5) * (exp(-d2 * 160.0) * 0.6 + exp(-d2 * 20.0) * 0.05) * (0.6 + 0.6 * uMid);
    col += vec3(1.0) * exp(-(d1 + d2) * 220.0) * (0.3 + 0.9 * uKick);
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Strobe kaleidoscope: a procedural pattern of interfering stripes folded into mirrored wedges
 * and zooming endlessly outward in log space. The wedge count steps every few bars; each kick
 * flashes the fold lines and the colours jump a third of the way round.
 */
internal const val STROBEKALEIDO_BODY = """
vec3 shade(vec2 p) {
    float r = max(length(p), 1e-3);
    float a = fastAtan2(p.y, p.x) + uSpin * PI;
    float seg = 2.0 * PI / uSegments;
    a = mod(a, seg);
    a = abs(a - seg * 0.5);
    float lr = log(r) - uPhase;
    vec2 q = vec2(a * 3.0, lr * 2.0);
    float v = sin(q.x * 9.0 + sin(q.y * PI * 2.0) * 2.0) * sin(q.y * PI * 4.0 + q.x * 5.0);
    v = 0.5 + 0.5 * v;
    float jump = mod(floor(uKicks), 3.0) / 3.0;
    vec3 col = colorAt(v * 0.6 + log(r) * 0.1 + jump) * pow(v, 1.5) * (0.6 + 0.6 * uLow);
    col += vec3(1.0) * exp(-a * r * 60.0) * (0.15 + 1.0 * uKick);
    col *= smoothstep(0.0, 0.1, r) * clamp(1.35 - 0.3 * r, 0.0, 1.0);
    return col;
}
"""
