package com.zonik.app.ui.tv

/*
 * A sixth batch of visualizer effects: shader bodies for [DemoEffect], each a `vec3 shade(vec2 p)`
 * that the enum wraps in the shared header and footer. Same rules as the others — no
 * raymarching, short loops, and `uPhase` / `uSpin` / `uTime` only ever used in ways that repeat
 * every 2, so their wrap is invisible.
 *
 * Written against the Chromecast's measured frame rates: the effects that ran under 30 fps were
 * the ones stacking noise octaves or marching rays, so these stick to a handful of distance
 * tests, texture reads and hashes per pixel.
 */

/**
 * Fireworks: every kick launches a shell where a ripple would land, which bursts into streaking
 * sparks that slow, droop under gravity and fade. The treble makes the sparks twinkle.
 */
internal const val FIREWORKS_BODY = """
vec3 shade(vec2 p) {
    vec3 col = mix(colorAt(0.66) * 0.015, colorAt(0.1) * 0.05, clamp(0.5 - p.y * 0.5, 0.0, 1.0));
    vec2 sf = fract(p * 60.0) - 0.5;
    float sh = hash(floor(p * 60.0));
    col += vec3(0.6) * step(0.985, sh) * smoothstep(0.25, 0.0, length(sf))
        * (0.5 + 0.5 * sin(sh * 90.0 + uTime * PI * 8.0));
    for (int i = 0; i < 4; i++) {
        float age = i == 0 ? uRings.x : (i == 1 ? uRings.y : (i == 2 ? uRings.z : uRings.w));
        if (age < 0.0) continue;
        vec2 c = uDrops[i] * vec2(0.8, 0.6) + vec2(0.0, 0.2);
        float seed = hash(uDrops[i] * 17.0 + 3.0);
        vec3 hue = colorAt(seed + float(i) * 0.25);
        // The whole burst sinks, faster as it ages.
        vec2 d = rot(seed * 6.2831) * (p - c + vec2(0.0, 0.1 * age * age));
        float a = fastAtan2(d.y, d.x) / (2.0 * PI) + 0.5;
        const float N = 30.0;
        float sector = floor(a * N);
        float ang = ((sector + 0.5) / N - 0.5) * 2.0 * PI;
        vec2 dir = vec2(cos(ang), sin(ang));
        float reach = (0.3 + 0.28 * hash(vec2(sector, seed * 50.0))) * (1.0 - exp(-age * 2.5));
        float along = clamp(dot(d, dir), reach * 0.5, reach);
        float streak = exp(-length(d - dir * along) * 170.0) * smoothstep(reach * 0.5, reach, along);
        float spark = exp(-length(d - dir * reach) * 80.0);
        float life = exp(-age * 1.1) * smoothstep(3.0, 2.2, age);
        float twinkle = 0.7 + hash(vec2(sector + seed, floor(uTime * 400.0))) * (0.3 + uHigh);
        col += hue * (streak * 0.7 + spark * 1.3) * life * twinkle;
        col += mix(hue, vec3(1.0), 0.6) * exp(-length(d) * 9.0) * exp(-age * 7.0) * 1.4;
    }
    return col * (1.0 + 0.25 * uKick);
}
"""

/**
 * Disco ball: a mirrored sphere of tiles turning under a key light. The tiles glint on the
 * treble and on every kick, the light it throws drifts round the room as coloured spots, and
 * faint beams fan out from it with the bass.
 */
internal const val DISCOBALL_BODY = """
vec3 shade(vec2 p) {
    float R = 0.42 * (1.0 + 0.04 * uKick);
    float r = length(p);
    float spin = uSpin * PI * 2.0;
    vec3 col = colorAt(0.66) * 0.02;
    // The reflections it throws: spots on a slowly turning grid.
    vec2 q = rot(spin) * p;
    vec2 cell = floor(q / 0.22);
    vec2 f = fract(q / 0.22) - 0.5;
    float h = hash(cell + 11.0);
    vec2 off = (vec2(hash(cell + 3.0), hash(cell + 7.0)) - 0.5) * 0.5;
    float spot = exp(-dot(f - off, f - off) * 140.0) * step(0.5, h);
    col += colorAt(h + uPhase * 0.25) * spot * (0.2 + 0.7 * uKick + 0.3 * uHigh) * smoothstep(R, R + 0.2, r);
    float beams = pow(max(cos((fastAtan2(p.y, p.x) + spin) * 6.0), 0.0), 40.0);
    col += colorAt(0.2) * beams * exp(-(r - R) * 2.0) * 0.15 * (0.4 + uLow) * step(R, r);
    // The wire it hangs from.
    col += vec3(0.25) * smoothstep(0.004, 0.0, abs(p.x)) * step(R, p.y);
    if (r < R) {
        vec3 n = vec3(p / R, sqrt(max(1.0 - dot(p, p) / (R * R), 0.0)));
        float lat = asin(clamp(n.y, -1.0, 1.0)) / PI + 0.5;
        float lon = fract((fastAtan2(n.x, n.z) + spin) / (2.0 * PI));
        const float ROWS = 16.0;
        float row = floor(lat * ROWS);
        // Fewer tiles round the narrow rows near the poles, as on a real ball.
        float cols = max(4.0, floor(2.0 * ROWS * sin((row + 0.5) / ROWS * PI)));
        vec2 tile = vec2(floor(lon * cols), row);
        vec2 tf = vec2(fract(lon * cols), fract(lat * ROWS));
        float grout = smoothstep(0.0, 0.14, min(min(tf.x, 1.0 - tf.x), min(tf.y, 1.0 - tf.y)));
        float th = hash(tile + 1.7);
        vec3 l = normalize(vec3(-0.5, 0.6, 0.8));
        float diff = max(dot(n, l), 0.0);
        float spec = pow(max(dot(reflect(-l, n), vec3(0.0, 0.0, 1.0)), 0.0), 10.0);
        float glint = step(1.0 - 0.06 * (0.3 + uHigh + 1.5 * uKick), hash(tile + floor(uTime * 300.0)));
        vec3 ball = colorAt(th + uPhase * 0.3) * (0.12 + 0.45 * th) * (0.35 + 0.65 * diff)
            + vec3(1.0) * (spec * 0.55 * (0.5 + th) + glint * 1.3);
        ball *= (grout * 0.85 + 0.15) * (0.3 + 0.7 * n.z);
        col = mix(col, ball, smoothstep(R, R - 0.006, r));
    }
    return col;
}
"""

/**
 * Hypercube: a tesseract's 32 edges turning through four dimensions, projected to three and
 * then to the screen — the inner cube swallows the outer one and turns inside out. The bass
 * drives the turn and each kick pulses it.
 */
internal const val HYPERCUBE_BODY = """
vec2 hyperProject(vec4 v, float a, float b) {
    v.xw = rot(a) * v.xw;
    v.yz = rot(b) * v.yz;
    v.xz = rot(0.5) * v.xz;
    vec3 q = v.xyz / (2.6 - v.w);
    return q.xy * 1.55 / (2.4 - q.z);
}
vec3 shade(vec2 p) {
    vec3 col = colorAt(0.66) * 0.02;
    p /= 1.0 + 0.12 * uKick;
    // Everything it draws stays inside this; the rest of the screen skips the edge loop.
    if (dot(p, p) > 0.9) return col;
    float a = uPhase * PI;
    float b = uSpin * PI * 2.0;
    vec3 acc = vec3(0.0);
    for (int i = 0; i < 16; i++) {
        vec4 bits = mod(floor(float(i) / vec4(1.0, 2.0, 4.0, 8.0)), 2.0);
        vec4 v0 = bits * 2.0 - 1.0;
        vec2 p0 = hyperProject(v0, a, b);
        for (int ax = 0; ax < 4; ax++) {
            vec4 e = vec4(equal(vec4(float(ax)), vec4(0.0, 1.0, 2.0, 3.0)));
            if (dot(bits, e) > 0.5) continue;
            vec2 ba = hyperProject(v0 + e * 2.0, a, b) - p0;
            vec2 pa = p - p0;
            float d = length(pa - ba * clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0));
            acc += colorAt(float(ax) * 0.25 + uPhase * 0.25) * (exp(-d * 220.0) + 0.2 * exp(-d * 30.0));
        }
        acc += vec3(1.0) * exp(-length(p - p0) * 70.0) * (0.3 + 0.9 * uKick);
    }
    return col + acc * (0.5 + 0.5 * uLow);
}
"""

/**
 * Twister: the Amiga classic — a square column of the album cover, twisting down the screen as
 * it spins. Only the faces turned toward you are drawn, lit by how square-on they are; the bass
 * winds the twist tighter and each kick swells it.
 */
internal const val TWISTER_BODY = """
vec4 twistFace(float x, float a, float b, float v, float w) {
    if (b <= a || x < a || x > b) return vec4(0.0);
    float u = (x - a) / (b - a);
    float light = (b - a) / (w * 1.4142);
    vec3 c = texture2D(uTex, vec2(u, v)).rgb * (0.25 + 0.85 * light);
    c += vec3(0.7) * exp(-min(u, 1.0 - u) * 40.0) * 0.25;
    return vec4(c, 1.0);
}
vec3 shade(vec2 p) {
    p += uCenter;
    vec3 col = colorAt(0.66 + p.y * 0.1) * 0.06 * (0.6 + 0.4 * sin(p.y * 40.0 + uPhase * PI * 4.0));
    float w = 0.32 * (1.0 + 0.08 * uKick);
    float ang = uPhase * PI + p.y * (1.0 + 1.6 * uLow) + 0.6 * sin(p.y * 2.0 + uTime * PI * 2.0);
    float x0 = w * sin(ang);
    float x1 = w * sin(ang + PI * 0.5);
    float x2 = w * sin(ang + PI);
    float x3 = w * sin(ang + PI * 1.5);
    float v = fract(p.y * 0.5);
    col *= 1.0 - 0.5 * smoothstep(w * 1.8, w, abs(p.x));
    vec4 f = twistFace(p.x, x0, x1, v, w);
    if (f.a < 0.5) f = twistFace(p.x, x1, x2, v, w);
    if (f.a < 0.5) f = twistFace(p.x, x2, x3, v, w);
    if (f.a < 0.5) f = twistFace(p.x, x3, x0, v, w);
    return f.a > 0.5 ? f.rgb : col;
}
"""

/**
 * Sine dots: a field of dots riding sine waves, the depth of each one setting its size and
 * brightness so the field reads as a ribbon turning in space. The spectrum sets how high each
 * column swings.
 */
internal const val SINEDOTS_BODY = """
vec3 shade(vec2 p) {
    p += uCenter;
    vec3 col = colorAt(0.66) * 0.02;
    const float COLS = 36.0;
    float sp = 2.0 * uAspect / COLS;
    float c = floor(p.x / sp + 0.5);
    float dx = p.x - c * sp;
    float lvl = band(mod(abs(c), 32.0) * 2.0);
    float amp = 0.05 + 0.08 * lvl + 0.04 * uKick;
    for (int r = 0; r < 12; r++) {
        float fr = float(r);
        float y = (fr - 5.5) * 0.13 + amp * sin(c * 0.45 + fr * 0.3 + uPhase * PI * 2.0);
        float z = 0.5 + 0.5 * cos(c * 0.35 + fr * 0.55 + uPhase * PI * 2.0);
        float size = 0.011 + 0.011 * z + 0.005 * uKick;
        float d = length(vec2(dx, p.y - y));
        vec3 hue = colorAt(fr / 12.0 + uPhase * 0.25);
        col = mix(col, hue * (0.35 + 0.65 * z) * (0.75 + 0.5 * lvl), smoothstep(size, size * 0.55, d));
        col += hue * exp(-d * 45.0) * 0.04;
    }
    return col;
}
"""

/**
 * Spirograph: a pen tracing hypotrochoids, the lines fading as it laps them so the figure is
 * always being drawn. Every sixteen kicks the wheel changes and a new figure grows out of the
 * old one; the bass thickens the pen.
 */
internal const val SPIROGRAPH_BODY = """
vec2 spiro(float t, float k, float d) {
    float rr = 1.0 - k;
    return (vec2(cos(t), sin(t)) * rr + vec2(cos(rr / k * t), -sin(rr / k * t)) * d * k) * 0.85;
}
vec3 shade(vec2 p) {
    vec2 uv = vPos * 0.5 + 0.5;
    vec2 q = rot(uSpin * PI * 2.0) * vec2(vPos.x * uAspect, vPos.y);
    vec3 col = max(prevAt(uv) * 0.997 - 0.001, 0.0);
    // Wheel-to-ring ratios whose figures close on a uTime wrap, so the pen never jumps.
    float set = mod(floor(uKicks / 16.0), 5.0);
    float k = set < 0.5 ? 0.3 : (set < 1.5 ? 0.4 : (set < 2.5 ? 0.2857143 : (set < 3.5 ? 0.375 : 0.25)));
    float d = 0.7 + 0.25 * sin(uTime * PI * 2.0);
    // 60 makes every ratio above come back to its start when uTime wraps.
    float t = uTime * PI * 60.0;
    float best = 1e9;
    vec2 a = spiro(t, k, d);
    // The last stretch of the curve in short straight pieces, about six frames of travel at
    // 60 fps, so it stays unbroken even where frames come slowly (a browser preview, ~10 fps).
    for (int i = 1; i <= 8; i++) {
        vec2 b = spiro(t - float(i) * 0.12, k, d);
        vec2 pa = q - a;
        vec2 ba = b - a;
        best = min(best, length(pa - ba * clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0)));
        a = b;
    }
    vec3 pen = colorAt(uPhase * 0.5 + uTime);
    col += pen * (exp(-best * (420.0 - 200.0 * uLow)) * 0.9 + exp(-best * 50.0) * 0.04) * (0.7 + 0.5 * uKick);
    return min(col, vec3(1.0));
}
"""

/**
 * Galaxy: a two-armed spiral galaxy seen at a tilt, its arms wound in a logarithmic spiral and
 * lit by stars that turn with them, with a dust lane along each arm. The core flares with the
 * bass and the arms brighten on each kick.
 */
internal const val GALAXY_BODY = """
vec3 shade(vec2 p) {
    vec2 q = rot(0.35) * p;
    q.y *= 1.9;
    float r = max(length(q), 1e-3);
    float spin = uSpin * PI * 2.0;
    float a = fastAtan2(q.y, q.x);
    float wind = 2.0 * (a - spin) - log(r) * 4.0;
    float arm = pow(0.5 + 0.5 * cos(wind), 3.0) * exp(-r * 1.5);
    float lane = pow(0.5 + 0.5 * cos(wind - 0.7), 14.0) * exp(-r * 1.3);
    vec3 col = colorAt(0.66) * 0.015;
    col += colorAt(r * 0.4 + 0.1 + uPhase * 0.2) * arm * (0.8 + 0.6 * uKick);
    col *= 1.0 - 0.6 * lane;
    // Stars that turn with the disc, thickest in the arms.
    vec2 qs = rot(spin) * q * 55.0;
    float h = hash(floor(qs));
    col += vec3(1.0) * step(0.97 - 0.3 * arm, h) * smoothstep(0.32, 0.0, length(fract(qs) - 0.5)) * (0.4 + arm);
    vec2 bf = fract(p * 70.0) - 0.5;
    col += vec3(0.5) * step(0.993, hash(floor(p * 70.0) + 5.0)) * smoothstep(0.3, 0.0, length(bf));
    col += mix(vec3(1.0, 0.95, 0.85), colorAt(0.1), 0.3) * (exp(-r * 7.0) * (0.7 + 0.9 * uLow) + exp(-r * 2.5) * 0.2);
    return col;
}
"""

/**
 * Ridgelines, after the Unknown Pleasures sleeve: stacked lines that rise into peaks in the
 * middle, each one hiding the ones behind it. Every line reads the spectrum at its own offset,
 * so the whole range plays out across the stack; kicks lift every peak at once.
 */
internal const val PULSAR_BODY = """
vec3 shade(vec2 p) {
    p += uCenter;
    vec3 col = vec3(0.0);
    if (abs(p.x) > 0.95) return col;
    const float LINES = 36.0;
    float bottom = -0.8;
    float stepY = 1.42 / LINES;
    float x = p.x / 0.85;
    float env = exp(-x * x * 7.0);
    float cx = floor(x * 9.0);
    float fx = smoothstep(0.0, 1.0, fract(x * 9.0));
    for (int i = 0; i < 36; i++) {
        float fi = float(i);
        float lvl = band(mod(abs(x) * 26.0 + fi * 1.7, 48.0));
        float vn = mix(hash(vec2(cx, fi)), hash(vec2(cx + 1.0, fi)), fx);
        float y = bottom + fi * stepY + env * (0.02 + 0.2 * vn * (0.3 + lvl) * (1.0 + 0.5 * uKick));
        float d = p.y - y;
        if (abs(d) < 0.011) {
            vec3 ink = mix(vec3(0.95), colorAt(fi / LINES + uPhase * 0.25), 0.35);
            return ink * smoothstep(0.011, 0.002, abs(d));
        }
        // Below this line's curve: hidden by the black fill under it.
        if (d < 0.0) return col;
    }
    return col;
}
"""

/**
 * Bubbles: an underwater column of bubbles rising at their own speeds and wobbling as they go,
 * each one's size set by its column's spectrum band, with light rays slanting down from the
 * surface. The bass speeds the rise and each kick puffs them up.
 */
internal const val BUBBLES_BODY = """
vec3 shade(vec2 p) {
    p += uCenter;
    vec3 col = mix(colorAt(0.66) * 0.015, colorAt(0.55) * 0.07, p.y * 0.5 + 0.5);
    col += colorAt(0.5) * 0.035 * pow(max(sin(p.x * 3.0 + p.y * 0.8 + uTime * PI * 2.0), 0.0), 6.0) * (p.y * 0.5 + 0.5);
    const float W = 0.16;
    float cx = floor(p.x / W);
    for (int j = -1; j <= 1; j++) {
        float c = cx + float(j);
        for (int k = 0; k < 3; k++) {
            float fk = float(k);
            float seed = hash(vec2(c, fk * 7.1));
            // Rise speeds whose double is a whole number keep uPhase's wrap seamless.
            float m = 0.5 + floor(seed * 3.0) * 0.5;
            float y = -1.3 + 2.6 * fract(uPhase * m + seed);
            float x = (c + 0.5 + 0.5 * (hash(vec2(c, fk + 2.0)) - 0.5)) * W + 0.02 * sin(y * 8.0 + seed * 20.0);
            float lvl = band(mod(abs(c) * 3.0, 48.0));
            float rad = 0.015 + 0.04 * hash(vec2(c, fk + 3.0)) * (0.6 + 0.8 * lvl) + 0.01 * uKick;
            float d = length(p - vec2(x, y));
            float body = smoothstep(rad, rad - 0.005, d);
            float rim = body * smoothstep(rad * 0.55, rad, d);
            float shine = exp(-length(p - vec2(x, y) - vec2(-0.35, 0.35) * rad) * 4.0 / rad);
            vec3 hue = colorAt(seed + 0.4);
            col = col * (1.0 - body * 0.25) + hue * (rim * 0.6 + body * 0.06) + vec3(1.0) * shine * body * 0.9;
        }
    }
    return col;
}
"""

/**
 * Digital rain: columns of glyphs streaming down the screen, a bright head on each with a
 * fading tail behind it, the characters flickering as they fall. The bass sets the pace and
 * each kick flashes the heads.
 */
internal const val DIGITALRAIN_BODY = GLYPHS + """
vec3 shade(vec2 p) {
    p += uCenter;
    const float CW = 0.045;
    const float CH = 0.063;
    vec2 g = vec2(p.x / CW, p.y / CH);
    vec2 cell = floor(g);
    vec2 f = fract(g);
    float seed = hash(vec2(cell.x, 4.2));
    float m = 0.5 + floor(seed * 3.0) * 0.5;
    float head = 1.15 - 2.6 * fract(uPhase * m + seed);
    float headRow = floor(head / CH);
    float dy = (cell.y - headRow) * CH;
    vec3 tint = mix(colorAt(0.33 + seed * 0.2), vec3(0.35, 1.0, 0.5), 0.45);
    float c = floor(hash(cell + floor(uTime * 200.0 * (0.5 + seed))) * 25.0);
    float on = glyph(c, f);
    vec3 col = vec3(0.0);
    if (dy >= 0.0) col = tint * on * exp(-dy * 3.5) * (0.35 + 0.65 * seed);
    if (dy == 0.0) col = mix(tint, vec3(1.0), 0.7) * on * (1.0 + 0.8 * uKick);
    return col;
}
"""

/**
 * Bouncing cover: the album cover crossing the screen and bouncing off its edges, leaving a
 * stack of fading copies and a coloured trail behind it. Each kick swells it; the bass
 * brightens the trail.
 */
internal const val COVERBOUNCE_BODY = """
vec3 shade(vec2 p) {
    vec2 uv = vPos * 0.5 + 0.5;
    vec2 q = vec2(vPos.x * uAspect, vPos.y);
    vec3 col = max(prevAt(uv) * 0.955 - 0.004, 0.0);
    float h = 0.24 * (1.0 + 0.1 * uKick);
    // Bounce speeds whose double is a whole number keep uTime's wrap seamless.
    vec2 c = vec2(tri(uTime * 2.5) * (uAspect - 0.27), tri(uTime * 3.5 + 0.25) * 0.73);
    vec2 d = q - c;
    float dist = coverDist(d, h);
    float edge = exp(-abs(dist) * 60.0);
    col = max(col, colorAt(uPhase * 0.5) * edge * (0.5 + 0.7 * uLow));
    vec3 cover = texture2D(uTex, vec2(d.x, -d.y) / (2.0 * h) + 0.5).rgb;
    return mix(col, cover, 1.0 - smoothstep(0.0, 0.006, dist));
}
"""

/**
 * Ribbons: five glowing ribbons weaving across the screen, each swelling with its own part of
 * the music — two with the bass, two with the mids, one with the treble — and widening on a
 * kick.
 */
internal const val RIBBONS_BODY = """
vec3 shade(vec2 p) {
    vec3 col = colorAt(0.66) * 0.02;
    for (int i = 0; i < 5; i++) {
        float fi = float(i);
        float level = i == 0 ? uLow : (i == 1 ? uMid : (i == 2 ? uHigh : (i == 3 ? uLow : uMid)));
        float k1 = 1.1 + fi * 0.37;
        float k2 = 2.3 + fi * 0.51;
        float t1 = uPhase * PI * (fi < 2.5 ? 1.0 : -1.0) + fi * 1.3;
        float t2 = uTime * PI * 2.0 * (1.0 + fi) - fi;
        float gain = 0.8 + 0.6 * level;
        float y = (0.35 * sin(p.x * k1 + t1) + 0.2 * sin(p.x * k2 - t2)) * gain + (fi - 2.0) * 0.08;
        float slope = (0.35 * k1 * cos(p.x * k1 + t1) + 0.2 * k2 * cos(p.x * k2 - t2)) * gain;
        float d = abs(p.y - y) / sqrt(1.0 + slope * slope);
        float width = 0.004 + 0.012 * (0.5 + 0.5 * sin(p.x * 2.0 + fi + uTime * PI * 2.0)) + 0.01 * uKick;
        vec3 hue = colorAt(fi / 5.0 + uPhase * 0.25);
        col += hue * (smoothstep(width, 0.0, d) * 0.9 + exp(-d * 18.0) * 0.12) * (0.6 + 0.6 * level);
    }
    return col;
}
"""
