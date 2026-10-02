package com.zonik.app.ui.tv

/*
 * Zoom and flight effects: shader bodies for [DemoEffect], each a `vec3 shade(vec2 p)` that the
 * enum wraps in the shared header and footer. The same rules apply as in DemoEffects.kt — no
 * raymarching, short loops, and `uPhase` / `uSpin` / `uTime` used only in ways that repeat every 2.
 */

/**
 * Droste zoom: the cover holding a smaller copy of itself where its middle should be, and that
 * one a smaller copy again, zooming in forever — one copy's worth every two units of travel, so
 * bass drives it. For half of every 40 s cycle the picture is twisted into Escher's spiral (the
 * log-polar shear that makes the nesting one continuous coil); it cuts between the two on a flash.
 */
internal const val DROSTE_BODY = """
vec3 shade(vec2 p) {
    const float S = 3.0;
    const float H = 0.82;
    float lnS = log(S);
    p *= 1.0 - 0.08 * uKick;
    float half_ = fract(uTime * 0.5);
#if VARIANT == 1
    float spiral = 1.0;
#else
    float spiral = step(0.5, half_);
#endif
    float alpha = atan(lnS / (2.0 * PI)) * spiral;
    vec2 w = vec2(log(max(length(p), 1e-4)), fastAtan2(p.y, p.x));
    // Complex multiply by e^(i·alpha)·cos(alpha): the identity when alpha is 0.
    w = vec2(w.x * cos(alpha) + w.y * sin(alpha), w.y * cos(alpha) - w.x * sin(alpha)) * cos(alpha);
    w.x -= fract(uPhase * 0.5) * lnS;
    w.y += uSpin * PI;
    vec2 q = exp(w.x) * vec2(cos(w.y), sin(w.y));
    // Scale into the band between one copy's edge and the next one in.
    float m = max(abs(q.x), abs(q.y)) / H;
    q /= exp((floor(log(m) / lnS) + 1.0) * lnS);
    float edge = max(abs(q.x), abs(q.y)) / H;      // 1/S .. 1
    vec3 col = punch(texture2D(uTex, vec2(q.x, -q.y) / (2.0 * H) + 0.5).rgb) * (0.75 + 0.4 * uLow);
    // A lit frame on each copy's edge, and the shadow it casts on the copy inside it.
    col *= 0.55 + 0.45 * smoothstep(1.0 / S, 1.0 / S + 0.12, edge);
    col += colorAt(0.05 + uPhase * 0.5) * exp(-(1.0 - edge) * 60.0) * (0.4 + 0.8 * uKick);
    col += vec3(1.0) * exp(-abs(fract(half_ * 2.0) - 0.0) * 30.0) * 0.6;
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Cover mosaic dive: the cover is made of small covers, each tinted to the colour of the bit it
 * stands for, and diving in, each small cover turns out to be made of smaller ones again. Three
 * depths are read at once and blended so the end of one sixteen-fold zoom is exactly the start
 * of the next. The dive aims at the point 8/15 of the way across — the one spot that lands on
 * itself, unflipped, after a sixteen-fold zoom of the mirrored texture — so the loop has no seam.
 * The deepest level fades in only over the second half of each zoom, once its cells are big enough to see.
 */
internal const val MOSAIC_BODY = """
vec3 look(vec3 a, vec3 b) { return mix(a, sqrt(a * b) * 1.5, 0.7); }
vec3 shade(vec2 p) {
    float z = fract(uPhase * 0.5);
    float zoom = exp2(4.0 * z) * (1.0 + 0.08 * uKick);
    const float C = 8.0 / 15.0;
    vec2 u0 = vec2(C) + vec2(p.x, -p.y) * 0.5 / zoom;
    vec3 a = texture2D(uTex, u0).rgb;
    vec3 b = texture2D(uTex, u0 * 16.0).rgb;
    vec3 c = texture2D(uTex, u0 * 256.0).rgb;
    // The deepest level comes in late: earlier its cells are a pixel or two and only shimmer.
    // Both ends of the blend are untouched (0 at the start, 1 at the end), so the loop still meets.
    vec3 col = mix(look(a, b), look(b, c), smoothstep(0.55, 1.0, z));
    col = punch(col) * (0.8 + 0.4 * uLow);
    col += uC0 * uKick * 0.1;
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * The Amiga square tunnel: depth from the larger of |x| and |y| rather than the radius, so the
 * walls are four flat panels of the cover meeting in lit corners. It rolls slowly; bass is the
 * speed and lights the corners, every kick sends a bright frame racing down the tunnel.
 */
internal const val SQUARETUNNEL_BODY = """
vec3 shade(vec2 p) {
    vec2 q = rot(uSpin * PI + 0.35 * sin(uTime * PI * 2.0)) * p;
#if VARIANT == 0
    float m = max(max(abs(q.x), abs(q.y)), 0.03);
    bool side = abs(q.x) > abs(q.y);
    float u = side ? q.y / m : q.x / m;            // -1..1 across the panel
#else
    // Triangle (1) or octagon (2): distance to the nearest side of a regular polygon, and the
    // position along that side.
#if VARIANT == 1
    const float N = 3.0;
#else
    const float N = 8.0;
#endif
    float th = fastAtan2(q.y, q.x) + PI / 2.0;
    float sectorA = mod(th, 2.0 * PI / N) - PI / N;
    float m = max(length(q) * cos(sectorA), 0.03);
    bool side = mod(floor(th / (2.0 * PI / N)), 2.0) > 0.5;
    float u = tan(sectorA) / tan(PI / N);
#endif
    float depth = 0.3 / m * (1.0 - 0.08 * uKick);
    float v = depth * 0.5 + uPhase;
    vec3 col = punch(texture2D(uTex, vec2(u * 0.5 + 0.5, v)).rgb);
    col *= side ? 0.8 : 1.0;
    float corner = exp(-(1.0 - abs(u)) * 25.0);
    col += colorAt(0.05 + uPhase * 0.5) * corner * (0.25 + 1.0 * uLow);
    // Frames down the tunnel, every half unit of depth; one brightens on each kick.
    float f = fract(v * 2.0);
    col += colorAt(0.33) * exp(-min(f, 1.0 - f) * 40.0) * (0.15 + 0.9 * uKick);
    col *= clamp(m * 3.2, 0.0, 1.0);
    return col;
}
"""

/**
 * Bent tube: a round tunnel whose path winds, so the far end swings about and the camera seems
 * to bank through the turns. Each pixel guesses its depth from its radius, shifts by the bend at
 * that depth, and guesses again — two rounds are plenty. The path and the walls both move with
 * the travel, so they stay locked together.
 */
internal const val BENTTUBE_BODY = """
vec2 path(float d) {
    return vec2(sin(PI * (0.5 * d + uPhase)), 0.6 * sin(PI * (d + 2.0 * uPhase) + 1.0)) * 0.9;
}
vec3 shade(vec2 p) {
    vec2 here = path(0.0);
    vec2 q = p;
    float d = 0.3 / max(length(q), 0.03);
    for (int i = 0; i < 2; i++) {
        vec2 off = (path(d) - here) * 0.3 / d;
        q = p - off;
        d = 0.3 / max(length(q), 0.03) * (1.0 - 0.08 * uKick);
    }
    float a = fastAtan2(q.y, q.x) / PI;            // -1..1
    float v = d * 0.5 + uPhase;
    vec3 col = punch(texture2D(uTex, vec2(a * 2.0 + uSpin, v)).rgb);
    float f = fract(v * 4.0);
    col += colorAt(0.05 + uPhase * 0.5) * exp(-min(f, 1.0 - f) * 30.0) * (0.15 + 0.6 * uLow + 0.6 * uKick);
    col *= clamp(length(q) * 3.0, 0.0, 1.0) * (0.7 + 0.4 * uLow);
    return col;
}
"""

/**
 * Flying covers: the album cover scattered through space in three depth layers, each cover
 * turning as it rushes past. Each layer flies from far to near and is replaced as it leaves; the
 * nearest cover hit wins. Bass is the speed, the kick flashes the covers' edges.
 */
internal const val FLYINGCOVERS_BODY = """
vec3 shade(vec2 p) {
    vec3 col = colorAt(0.66) * 0.03;
    // Faint stars behind.
    vec2 sc = floor(p * 90.0);
    col += vec3(step(0.995, hash(sc))) * 0.5;
    float best = -1.0;
    vec3 hit = vec3(0.0);
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float travel = uPhase * 0.5 + fi / 3.0;
        float z = fract(travel);
        float layer = floor(travel) + fi * 7.0;
        float scale = mix(4.5, 0.8, z * z);
        vec2 w = p * scale + vec2(fi * 3.7, fi * 1.3);
        vec2 cell = floor(w);
        vec2 f = fract(w) - 0.5;
        float h = hash(cell + layer * 13.1);
        if (h < 0.16 && z > best) {
            vec2 off = (vec2(hash(cell + 1.7), hash(cell + 4.3)) - 0.5) * 0.35;
            float dir = h < 0.08 ? 1.0 : -1.0;
            vec2 q = rot(h * 60.0 + dir * uTime * PI * 2.0) * (f - off) / 0.3;
            float m = max(abs(q.x), abs(q.y));
            if (m < 1.0) {
                float fade = smoothstep(0.0, 0.25, z) * (1.0 - smoothstep(0.85, 1.0, z));
                vec3 c = texture2D(uTex, vec2(q.x, -q.y) * 0.5 + 0.5).rgb;
                c += colorAt(h * 6.0) * exp(-(1.0 - m) * 30.0) * (0.3 + 0.9 * uKick);
                hit = mix(col, c * (0.5 + 0.6 * z), fade);
                best = z;
            }
        }
    }
    if (best >= 0.0) col = hit;
    return col;
}
"""

/**
 * Hyperspace: streaks of light rushing out from the centre in two layers, brightening as they
 * pass. Bass lengthens them; each kick is a jump — the streaks stretch right across the screen
 * and the centre flares blue-white before everything snaps back to cruising.
 */
internal const val HYPERSPACE_BODY = """
vec3 shade(vec2 p) {
    float r = length(p);
    float a = fastAtan2(p.y, p.x) / (2.0 * PI) + 0.5;
    vec3 col = colorAt(0.66) * 0.02;
    for (int l = 0; l < 2; l++) {
#if VARIANT == 1
        float n = l == 0 ? 200.0 : 320.0;
#else
        float n = l == 0 ? 140.0 : 230.0;
#endif
        float s = floor(a * n);
        float h = hash(vec2(s, float(l) * 9.0));
        float pos = fract(h * 7.0 + uPhase * (1.0 + floor(h * 3.0)));
        float head = pos * pos * 2.2;
        float len = 0.02 + 0.12 * uLow + 1.6 * uKick * uKick;
        float along = smoothstep(head - len, head, r) * step(r, head);
        float across = 1.0 - smoothstep(0.0, 0.35, abs(fract(a * n) - 0.5));
#if VARIANT == 1
        vec3 tint = 0.5 + 0.5 * cos(2.0 * PI * (a + uPhase * 0.5 + vec3(0.0, 0.33, 0.67)));
#else
        vec3 tint = mix(vec3(0.75, 0.85, 1.0), colorAt(h), 0.4);
#endif
        col += tint * along * across * (0.3 + 0.9 * pos) * (l == 0 ? 1.0 : 0.6);
    }
    col += vec3(0.6, 0.75, 1.0) * exp(-r * 4.0) * (0.15 + 1.2 * uKick);
    col += vec3(1.0) * uKick * uKick * 0.25;
    return col;
}
"""

/**
 * Ocean flyover: skimming low over a sea at sunset. The water is a plane seen in perspective
 * with three crossing swells on it; each pixel works out the slope there, reflects the sky in
 * it, and catches the sun's glitter. Bass raises the swell; the sun swells into each beat.
 */
internal const val OCEAN_BODY = """
vec3 sky(float y) {
#if VARIANT == 1
    // Moonlight: a deep blue night, the cover's colour only a hint at the horizon.
    vec3 top = vec3(0.01, 0.015, 0.04);
    vec3 low = mix(vec3(0.08, 0.12, 0.25), colorAt(0.05), 0.2);
#else
    vec3 top = colorAt(0.66) * 0.18;
    vec3 low = mix(colorAt(0.05), vec3(1.0, 0.55, 0.3), 0.4);
#endif
    return mix(low, top, smoothstep(0.0, 0.7, y));
}
vec3 shade(vec2 p) {
    p = rot(0.04 * sin(uTime * PI * 2.0)) * p;
    float hz = 0.12;
    vec2 sun = vec2(0.85, hz + 0.2);
    vec3 col;
    if (p.y > hz) {
        col = sky(p.y - hz);
        float sd = length(p - sun);
#if VARIANT == 1
        col += vec3(0.95, 0.95, 1.0) * (1.0 - smoothstep(0.045, 0.05, sd)) + vec3(0.6, 0.7, 1.0) * exp(-sd * 8.0) * (0.15 + 0.3 * uBeat);
#else
        col += vivid(uC1) * (exp(-sd * 40.0) * 1.5 + exp(-sd * 5.0) * (0.25 + 0.4 * uBeat));
#endif
        col += vec3(step(0.997, hash(floor(p * 120.0)))) * smoothstep(0.3, 0.8, p.y) * 0.6;
    } else {
        float dy = hz - p.y;
        float d = 0.18 / dy;
        float x = p.x * d;
        float amp = (0.05 + 0.06 * uLow) * exp(-d * 0.08);
        // Three swells; the travel goes in through whole multiples of π·uPhase.
        float t = uTime * PI * 2.0;
        vec2 g = vec2(0.0);
        g += vec2(0.6, 1.0) * cos(0.6 * x + 1.0 * d + PI * 2.0 * uPhase + t) * 1.0;
        g += vec2(-1.3, 1.7) * cos(-1.3 * x + 1.7 * d + PI * 4.0 * uPhase + t * 2.0) * 0.5;
        g += vec2(3.1, 2.3) * cos(3.1 * x + 2.3 * d + PI * 6.0 * uPhase - t * 3.0) * 0.2;
        g *= amp;
        // Reflect the view off the tilted surface, and look the sky up in that direction.
        float refl = dy * 0.6 + g.y * 0.8;
        col = sky(refl) * 0.55;
        col *= 0.5 + 0.5 * exp(-d * 0.05);
        float glint = exp(-abs(p.x - sun.x + g.x * 0.6) * (3.0 + d * 0.3)) * exp(-abs(g.y) * 2.0);
#if VARIANT == 1
        col += vec3(0.8, 0.85, 1.0) * pow(max(g.y * 4.0 + 0.6, 0.0), 3.0) * glint * 0.5;
#else
        col += vivid(uC1) * pow(max(g.y * 4.0 + 0.6, 0.0), 3.0) * glint * 0.6;
#endif
        col = mix(col, sky(0.0), clamp(exp(-dy * 25.0), 0.0, 1.0) * 0.8);
    }
    col *= clamp(1.35 - 0.25 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * City at night, seen from a plane: a street grid with cars streaming along it, and blocks of
 * buildings whose roofs lean outward from the centre (the nearer the camera, the further they
 * lean), showing lit windows down the walls between roof and street. Neon on some roofs pulses
 * with the bands; bass is the flight speed.
 */
internal const val CITY_BODY = """
float tallness(vec2 b) { return 0.2 + 0.8 * hash(b + 0.5) * hash(b + 9.1); }
// Inside the footprint of building cell b at grid point x (both in building units)?
bool inside(vec2 x, vec2 b) {
    vec2 f = x - b - 0.5;
    return floor(x) == b && max(abs(f.x), abs(f.y)) < 0.34;
}
vec3 shade(vec2 p) {
    // Two buildings per world unit; blocks repeat every 32 rows so the travel wrap (16 units)
    // lands on the same city.
    vec2 w = (p * 1.3 + vec2(0.4 * sin(uTime * PI * 2.0), uPhase * 8.0)) * 2.0;
    const float K = 0.45;
    vec2 b = floor(w - p * 0.5 * K);
    vec2 id = vec2(b.x, mod(b.y, 32.0));
    float ht = tallness(id);
    vec3 col;
    if (inside(w - p * ht * K, b)) {
        vec2 fr = w - p * ht * K - b - 0.5;
        col = vec3(0.06, 0.06, 0.08) + colorAt(hash(id)) * 0.05;
        float edge = max(abs(fr.x), abs(fr.y));
        float neon = step(0.75, hash(id + 3.3));
        float level = hash(id + 5.5) < 0.5 ? uLow : uMid;
        col += colorAt(hash(id + 7.7)) * neon * exp(-abs(edge - 0.3) * 70.0) * (0.3 + 1.3 * level);
        col += vec3(0.08) * exp(-abs(edge - 0.34) * 120.0);
    } else if (inside(w, b) || inside(w - p * ht * K * 0.5, b)) {
        // Wall, seen between the street and the roof: rows of windows, a few lit.
        vec2 win = floor(w * vec2(14.0, 14.0) - p * 20.0);
        float lit = step(0.72, hash(win + id * 3.1));
        col = vec3(0.025, 0.025, 0.035) + vec3(1.0, 0.82, 0.5) * lit * 0.3;
    } else {
        vec2 f = fract(w);
        col = vec3(0.012, 0.012, 0.018);
        bool vertical = abs(f.x - 0.5) > abs(f.y - 0.5);
        // Distance across the street from its centre line, and position along it.
        float across = vertical ? abs(fract(w.x + 0.5) - 0.5) : abs(fract(w.y + 0.5) - 0.5);
        float along = vertical ? w.y : w.x;
        float side = (vertical ? fract(w.x + 0.5) : fract(w.y + 0.5)) < 0.5 ? 1.0 : -1.0;
        // Streetlights along the kerbs.
        col += vec3(1.0, 0.7, 0.35) * exp(-length(vec2(across - 0.13, fract(along * 2.0) - 0.5)) * 30.0) * 0.9;
        // Cars: white headlights in one lane, red tail lights in the other.
        float lane = exp(-abs(across - 0.06) * 120.0);
        float car = fract(along * 1.5 + side * uTime * 20.0 + hash(vec2(floor(vertical ? w.x + 0.5 : w.y + 0.5), side)));
        float spot = exp(-abs(car - 0.5) * 40.0) * lane;
        col += (side > 0.0 ? vec3(1.0, 0.95, 0.85) : vec3(1.0, 0.15, 0.1)) * spot * 1.4;
    }
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Cloud flight: gliding between a floor of cloud and a thinner ceiling, both lit in the
 * cover's colours. Each layer is four octaves of value noise on a plane seen in perspective,
 * made to repeat along the flight path so the travel wrap never shows; distance fogs both into
 * the horizon glow. Drawn at half resolution.
 */
internal const val CLOUDS_BODY = """
float vnoise(vec2 x, float period) {
    vec2 i = floor(x);
    vec2 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    vec2 j = vec2(i.x, mod(i.y, period));
    vec2 k = vec2(i.x, mod(i.y + 1.0, period));
    float a = hash(j);
    float b = hash(j + vec2(1.0, 0.0));
    float c = hash(k);
    float d = hash(k + vec2(1.0, 0.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
float clouds(vec2 x) {
    float v = 0.0;
    float amp = 0.5;
    float period = 16.0;
    for (int i = 0; i < 4; i++) {
        v += vnoise(x, period) * amp;
        x *= 2.0;
        period *= 2.0;
        amp *= 0.5;
    }
    return v;
}
vec3 shade(vec2 p) {
    float hz = 0.05 * sin(uTime * PI * 2.0);
    vec3 glow = mix(colorAt(0.05), vec3(1.0), 0.3);
    vec3 col = mix(glow * 0.8, colorAt(0.66) * 0.15, smoothstep(0.0, 0.8, abs(p.y - hz)));
    float dy = p.y - hz;
    float below = dy < 0.0 ? 1.0 : 0.0;
    float d = (below > 0.5 ? 0.25 : 0.5) / max(abs(dy), 0.01);
    // Sixteen units of world per wrap of the travel, matching the noise's repeat.
    vec2 x = vec2(p.x * d, d + uPhase * 8.0) * 0.5 + vec2(below * 13.0, 0.0);
    float c = clouds(x);
    float dens = smoothstep(below > 0.5 ? 0.42 : 0.55, 0.8, c);
    float lit = clouds(x + vec2(0.0, 0.15));
    vec3 cc = mix(colorAt(0.33) * 0.35, glow, clamp(0.5 + (c - lit) * 4.0, 0.0, 1.0)) * (0.8 + 0.4 * uLow);
    float fog = exp(-d * 0.12);
    col = mix(col, cc, dens * fog);
    col += glow * uKick * 0.08;
    return col;
}
"""

/**
 * Planet flyby: a ringed planet drifting slowly past against stars and a faint nebula, its
 * surface the cover wrapped round the sphere and turning, lit from one side. A small moon
 * circles it. Bass brightens the atmosphere's rim; the kick flashes the rings.
 */
internal const val PLANET_BODY = """
vec3 shade(vec2 p) {
    vec3 col = colorAt(0.66) * 0.02;
    col += colorAt(0.33) * 0.08 * (0.5 + 0.5 * sin(p.x * 2.3 + sin(p.y * 3.1 + uTime * PI * 2.0)))
         * (0.5 + 0.5 * sin(p.y * 1.7 - p.x));
    col += vec3(step(0.996, hash(floor(p * 140.0)))) * 0.7;
    vec2 c = vec2(cos(uTime * PI) * 0.75 * uAspect * 0.6, sin(uTime * PI * 2.0) * 0.18 - 0.05);
    float R = 0.5 + 0.02 * uKick;
    vec2 q = (p - c) / R;
    const float TILT = 0.35;
    vec2 rq = rot(TILT) * q;
    // Ring plane: an ellipse squashed 4:1.
    float rr = length(vec2(rq.x, rq.y * 4.0));
    float ringBand = smoothstep(1.35, 1.4, rr) * (1.0 - smoothstep(2.1, 2.15, rr)) * (1.0 - 0.7 * step(1.72, rr) * step(rr, 1.78));
    float ringTex = 0.55 + 0.45 * sin(rr * 40.0) * sin(rr * 13.0);
    vec3 ringCol = mix(colorAt(0.05), vec3(1.0), 0.3) * ringBand * ringTex * (0.5 + 0.8 * uKick);
    bool front = rq.y < 0.0;
    float q2 = dot(q, q);
    if (!front) col = mix(col, ringCol, ringBand * 0.85);
    if (q2 < 1.0) {
        vec3 n = vec3(q, sqrt(1.0 - q2));
        float lon = fastAtan2(n.x, n.z) / PI + uSpin;
        float lat = asin(clamp(n.y, -1.0, 1.0)) / PI;
        vec3 surf = punch(texture2D(uTex, vec2(lon, lat + 0.5)).rgb);
        float light = clamp(dot(n, normalize(vec3(-0.8, 0.4, 0.5))), 0.0, 1.0);
        col = surf * (0.08 + 1.1 * light);
        col += colorAt(0.05) * pow(1.0 - n.z, 3.0) * (0.3 + 0.8 * uLow);
    } else {
        col += colorAt(0.05) * exp(-(sqrt(q2) - 1.0) * 14.0) * (0.15 + 0.5 * uLow);
    }
    if (front) col = mix(col, ringCol, ringBand * 0.85);
    // The moon.
    vec2 mc = c + vec2(cos(uTime * PI * 6.0), sin(uTime * PI * 6.0) * 0.3) * R * 2.4;
    float md = length(p - mc) / 0.06;
    if (md < 1.0 && (sin(uTime * PI * 6.0) < 0.0 || q2 > 1.0)) {
        vec3 mn = vec3((p - mc) / 0.06, sqrt(1.0 - md * md));
        col = vec3(0.7) * clamp(dot(mn, normalize(vec3(-0.8, 0.4, 0.5))), 0.03, 1.0);
    }
    return col;
}
"""

/**
 * Apollonian zoom: an endless dive into a circle packing — the space folded back into a unit
 * cell and inverted in a circle, seven times over, leaves a distance to the nearest circle edge
 * and the closest approach to the centre. Two copies at zooms four times apart cross-fade so
 * the dive never ends. Drawn at half resolution.
 */
internal const val APOLLONIAN_BODY = """
vec2 apo(vec2 q) {
    float scale = 1.0;
    float trap = 1e9;
    for (int i = 0; i < 7; i++) {
        q = -1.0 + 2.0 * fract(0.5 * q + 0.5);
        float r2 = dot(q, q);
        trap = min(trap, r2);
        float k = (1.15 + 0.05 * uLow) / r2;
        q *= k;
        scale *= k;
    }
    return vec2(0.25 * abs(q.y) / scale, trap);
}
vec3 layer(vec2 p, float z) {
    float zoom = exp2(-2.0 * z);
    vec2 q = rot(uSpin * PI) * p * zoom * 1.1 + vec2(0.31, 0.27);
    vec2 a = apo(q);
    float d = a.x / zoom;
    vec3 col = colorAt(a.y * 0.6 + uPhase * 0.5) * (0.25 + 0.35 * a.y);
    col += colorAt(0.05) * exp(-d * 260.0) * (0.8 + 0.6 * uKick);
    return col;
}
vec3 shade(vec2 p) {
    float t = fract(uTime * 2.0 + uPhase * 0.5);
    vec3 a = layer(p, t);
    vec3 b = layer(p, t - 1.0);
    vec3 col = mix(b, a, smoothstep(0.0, 1.0, 1.0 - t));
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Kaliset flight: Kali's fold — z → |z| / |z|² − c, nine times — makes nested cells of light
 * that drift past as the view slides and turns. c wanders slowly so the structure keeps
 * changing; bass zooms in, the kick flares the brightest filaments. Drawn at half resolution.
 */
internal const val KALISET_BODY = """
vec3 shade(vec2 p) {
    float t = uTime * PI * 2.0;
    vec2 cst = vec2(0.58 + 0.05 * sin(t), 0.72 + 0.05 * cos(t * 2.0));
    vec2 z = rot(uSpin * PI) * p * (0.55 - 0.1 * uLow - 0.05 * uKick)
           + vec2(0.4 * sin(PI * uPhase), 0.4 * cos(PI * uPhase));
    vec3 col = vec3(0.0);
    for (int i = 0; i < 9; i++) {
        z = abs(z) / dot(z, z) - cst;
        float m = length(z);
        col += colorAt(float(i) / 9.0 + uPhase * 0.5) * exp(-m * m * 14.0) * 0.45;
    }
    col = min(col, 1.5) * (0.9 + 0.8 * uKick);
    col *= clamp(1.35 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""
