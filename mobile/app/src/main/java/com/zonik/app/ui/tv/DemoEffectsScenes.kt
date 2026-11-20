package com.zonik.app.ui.tv

// Scenes that are not a forward flight (2026-11-19): an endless kaleidoscope zoom, a tiny
// planet seen from orbit, a liquid sculpture on a stage, an equalizer city turning below an
// isometric camera, and a storm at sea through a fixed window. Each one works out where its
// pixel looks in closed form, or with a short march, inside the Mali-470's 16-bit floats:
// times only through the wrapped uniforms (see DemoEffects.kt), coordinates kept small.

/**
 * Endless zoom: a kaleidoscope falling inward forever. Log-polar coordinates make every ring
 * of shapes the same size as the last, so the zoom is a scroll and never runs out; rings of
 * circles and diamonds, each lit by its own band of the spectrum, and one ring in four pops on
 * each kick in turn.
 */
internal const val ENDLESS_BODY = """
vec3 shade(vec2 p) {
    p += uCenter * 0.5;
    float r = max(length(p), 1e-3);
    float a = fastAtan2(p.y, p.x) + uSpin * PI;
    const float SEG = 0.785398;
    float aa = abs(mod(a, SEG) - SEG * 0.5);
    const float K = 3.2;
    // 8 rings per unit of uPhase; its wrap at 2 moves 16 rings, which the mod 16 hides.
    vec2 q = vec2(log(r) * K - uPhase * 8.0, aa * K);
    float ci = floor(q.x);
    float id = mod(ci, 16.0);
    vec2 f = vec2(fract(q.x) - 0.5, q.y);
    float hs = hash(vec2(id, 3.0));
    float pop = abs(mod(ci, 4.0) - mod(uKicks, 4.0)) < 0.5 ? uKick : 0.0;
    float d1 = length(f - vec2(0.0, 0.55)) - 0.2 - 0.14 * pop;
    float d2 = abs(f.x) + abs(f.y - 0.2) - 0.22 - 0.14 * pop;
    float d = hs > 0.5 ? d2 : d1;
    float lvl = band(id * 3.0);
    vec3 c = colorAt(id / 16.0 + uPhase * 0.5);
    vec3 col = c * smoothstep(0.03, 0.0, d) * (0.55 + 0.9 * lvl) + c * exp(-abs(d) * 18.0) * 0.35;
    col += vec3(0.9, 0.85, 1.0) * smoothstep(0.46, 0.5, abs(fract(q.x) - 0.5)) * 0.16 * (0.5 + uBeat);
    col += colorAt(0.6) * exp(-aa * K * 25.0) * 0.15;
    col *= smoothstep(0.0, 0.3, r);
    col += mix(vec3(1.0, 0.9, 0.7), colorAt(0.1), 0.3) * exp(-r * 9.0) * (0.5 + uKick);
    return col;
}
"""

/**
 * Tiny planet: a whole world seen from orbit, turning under a slowly circling camera. Land and
 * sea come from the tileable heightmap on unit 1 wrapped round the sphere (longitude by
 * latitude); the ray meets the sphere in closed form and then steps through the thin shell of
 * mountains. Bass lifts the mountains, kicks flare the atmosphere, the night side's cities
 * glow on the beat, and a moon keeps circling.
 */
internal const val TINYPLANET_BODY = """
float tpHeight(vec3 n) {
    float lon = fastAtan2(n.z, n.x) / (2.0 * PI) + uSpin * 0.5;
    float lat = asin(clamp(n.y, -1.0, 1.0)) / PI;
    // Two scales of the heightmap, so the coasts wander instead of repeating as round blobs.
    float h = texture2D(uHeight, vec2(lon * 2.0, lat * 2.0 + 0.3)).r * 0.6
        + texture2D(uHeight, vec2(lon * 5.0 + 0.37, lat * 4.0 + 0.71)).r * 0.4;
    return max(h - 0.5, 0.0) * 2.4;
}
vec3 shade(vec2 p) {
    float a = uTime * PI;
    float el = 0.35 + 0.25 * sin(uTime * PI * 2.0);
    vec3 ro = vec3(sin(a) * cos(el), sin(el), cos(a) * cos(el)) * 3.4;
    vec3 w = normalize(-ro);
    vec3 u = normalize(cross(w, vec3(0.0, 1.0, 0.0)));
    vec3 v = cross(u, w);
    vec3 rd = normalize(w * 1.9 + u * p.x + v * p.y);
    vec3 col = colorAt(0.66) * 0.012;
    vec2 sg = floor(p * 90.0);
    col += vec3(step(0.994, hash(sg + 7.0))) * 0.6;
    float H = 0.06 + 0.07 * uLow;
    float b = dot(-ro, rd);
    float c2 = dot(ro, ro) - b * b;
    vec3 L = normalize(vec3(0.8, 0.45, 0.4));
    vec3 atm = mix(colorAt(0.55), vec3(0.5, 0.75, 1.0), 0.5);
    // Atmosphere: brightest where the ray grazes the planet.
    float rim = sqrt(max(c2, 0.0));
    if (b > 0.0) col += atm * exp(-max(rim - 1.0, 0.0) * 9.0) * (0.45 + 0.9 * uKick);
    // The moon.
    float ma = uTime * PI * 3.0;
    vec3 mc = vec3(cos(ma) * 1.9, 0.3 * sin(ma), sin(ma) * 1.9);
    vec3 oc = ro - mc;
    float mb = dot(oc, rd);
    float mh = mb * mb - dot(oc, oc) + 0.02;
    float tm = mh > 0.0 ? -mb - sqrt(mh) : 99.0;
    float Ro = 1.0 + H;
    float hOut = Ro * Ro - c2;
    float tp = 99.0;
    vec3 n = vec3(0.0);
    float h = 0.0;
    if (hOut > 0.0) {
        float t0 = b - sqrt(hOut);
        float t1 = b - sqrt(max(1.0 - c2, 0.0));
        if (c2 > 1.0) t1 = b;
        float dt = (t1 - t0) / 10.0;
        float t = t0;
        for (int i = 0; i < 10; i++) {
            vec3 q = ro + rd * t;
            float lq = length(q);
            float hq = tpHeight(q / lq);
            if (lq < 1.0 + hq * H) { tp = t; h = hq; break; }
            t += dt;
        }
        if (tp > 98.0 && c2 < 1.0) { tp = t1; h = 0.0; }
    }
    if (tp < tm && tp < 98.0) {
        vec3 q = ro + rd * tp;
        vec3 sn = normalize(q);
        // A normal from the height's slope: two more reads, east and north.
        vec3 e1 = normalize(cross(sn, vec3(0.0, 1.0, 0.0)) + 1e-3);
        vec3 e2 = cross(e1, sn);
        float hx = tpHeight(normalize(sn + e1 * 0.02));
        float hy = tpHeight(normalize(sn + e2 * 0.02));
        n = normalize(sn - (e1 * (hx - h) + e2 * (hy - h)) * H * 40.0);
        vec3 land = mix(colorAt(0.3) * 0.5 + vec3(0.05, 0.18, 0.05), vec3(0.45, 0.35, 0.25), smoothstep(0.1, 0.5, h));
        land = mix(land, vec3(0.95), smoothstep(0.6, 0.85, h));
        vec3 sea = mix(vec3(0.02, 0.08, 0.25), colorAt(0.6) * 0.4, 0.3);
        bool wet = h <= 0.0;
        vec3 base = wet ? sea : land;
        float dif = max(dot(wet ? sn : n, L), 0.0);
        col = base * (0.04 + dif);
        if (wet) col += vec3(0.8) * pow(max(dot(reflect(rd, sn), L), 0.0), 24.0) * 0.6;
        float night = smoothstep(0.1, -0.25, dot(sn, L));
        if (!wet) col += night * step(0.75, hash(floor(sn.xz * 60.0 + sn.y * 37.0))) * colorAt(0.1) * (0.3 + 0.9 * uKick);
        col += atm * pow(1.0 - max(dot(-rd, sn), 0.0), 3.0) * 0.55;
    } else if (tm < 98.0) {
        vec3 mn = normalize(ro + rd * tm - mc);
        col = vec3(0.7, 0.68, 0.65) * (0.04 + max(dot(mn, L), 0.0)) * (0.8 + 0.2 * hash(floor(mn.xy * 9.0)));
    }
    return col;
}
"""

/**
 * Liquid sculpture: one glossy shape alone on a dark stage, morphing slowly between a sphere
 * and a ring while the spectrum ruffles its surface, bass in long swells and treble in fine
 * ripples. Each kick swells it and sends a ring out across the floor. The camera barely
 * moves, so all the motion is the music.
 */
internal const val SCULPTURE_BODY = """
float scMorph() { return 0.5 + 0.5 * sin(uTime * PI * 2.0); }
float scObj(vec3 p) {
    float c = cos(uSpin * PI); float s = sin(uSpin * PI);
    p.xz = mat2(c, s, -s, c) * p.xz;
    p.yz = rot(0.4) * p.yz;
    float sph = length(p) - 0.78 - 0.18 * uKick;
    vec2 tq = vec2(length(p.xz) - 0.72, p.y);
    float tor = length(tq) - 0.26 - 0.1 * uKick;
    float d = mix(sph, tor, scMorph());
    float lo = band(4.0); float mi = band(20.0); float hi = band(44.0);
    d += 0.07 * (0.3 + lo) * sin(p.x * 4.0 + uPhase * PI * 2.0) * sin(p.y * 4.0) * sin(p.z * 4.0 + 1.0);
    d += 0.025 * (0.2 + mi + hi) * sin(p.x * 13.0) * sin(p.y * 13.0 + uPhase * PI * 4.0) * sin(p.z * 13.0);
    return d * 0.7;
}
vec3 scSky(vec3 rd) {
    vec3 c = mix(colorAt(0.66) * 0.03, colorAt(0.5) * 0.35, smoothstep(-0.2, 0.9, rd.y));
    // Two soft light strips overhead, for the gloss to catch.
    c += vec3(1.0) * smoothstep(0.92, 1.0, 1.0 - abs(rd.x - 0.35)) * smoothstep(0.2, 0.6, rd.y) * 0.8;
    c += colorAt(0.1) * smoothstep(0.95, 1.0, 1.0 - abs(rd.x + 0.5)) * smoothstep(0.1, 0.5, rd.y) * 0.6;
    return c;
}
vec3 shade(vec2 p) {
    vec3 ro = vec3(0.6 * sin(uTime * PI), 0.75, 3.3);
    vec3 w = normalize(vec3(0.0, -0.1, 0.0) - ro);
    vec3 u = normalize(cross(w, vec3(0.0, 1.0, 0.0)));
    vec3 v = cross(u, w);
    vec3 rd = normalize(w * 1.8 + u * p.x + v * p.y);
    vec3 col = scSky(rd);
    float tf = rd.y < -0.01 ? (-1.25 - ro.y) / rd.y : 99.0;
    // Only rays near the shape march: it stays within a sphere of 1.35.
    float b = dot(-ro, rd);
    float c2 = dot(ro, ro) - b * b;
    float t = 99.0;
    if (c2 < 1.35 * 1.35) {
        t = b - sqrt(1.35 * 1.35 - c2);
        bool hit = false;
        for (int i = 0; i < 24; i++) {
            float d = scObj(ro + rd * t);
            if (d < 0.003) { hit = true; break; }
            t += d;
            if (t > b + 1.4) break;
        }
        if (!hit) t = 99.0;
    }
    if (t < tf) {
        vec3 q = ro + rd * t;
        const vec2 k = vec2(1.0, -1.0);
        vec3 n = normalize(k.xyy * scObj(q + k.xyy * 0.004) + k.yyx * scObj(q + k.yyx * 0.004)
            + k.yxy * scObj(q + k.yxy * 0.004) + k.xxx * scObj(q + k.xxx * 0.004));
        float fr = pow(1.0 - max(dot(-rd, n), 0.0), 3.0);
        vec3 tint = colorAt(dot(n, vec3(0.3, 0.6, 0.2)) * 0.5 + uPhase * 0.25);
        col = vivid(tint) * (0.12 + 0.6 * max(dot(n, normalize(vec3(0.5, 0.8, 0.4))), 0.0));
        col += scSky(reflect(rd, n)) * (0.45 + 0.75 * fr);
    } else if (tf < 98.0) {
        vec3 q = ro + rd * tf;
        float r = length(q.xz);
        vec3 fl = colorAt(0.66) * 0.02;
        for (int i = 0; i < 4; i++) {
            float age = i == 0 ? uRings.x : (i == 1 ? uRings.y : (i == 2 ? uRings.z : uRings.w));
            if (age < 0.0) continue;
            fl += colorAt(0.2 + age * 0.3) * exp(-abs(r - age * 2.2) * 9.0) * exp(-age * 1.5) * 1.2;
        }
        // The shape's glow on the floor under it, and a faint reflection of the light strips.
        fl += colorAt(uPhase * 0.25) * exp(-r * r * 1.2) * 0.25 * (0.6 + uKick);
        fl += scSky(reflect(rd, vec3(0.0, 1.0, 0.0))) * 0.12;
        col = mix(fl, col, smoothstep(5.0, 14.0, tf));
    }
    return col * clamp(1.25 - 0.25 * length(p), 0.0, 1.0);
}
"""

/**
 * Equalizer city: a little city seen from above at an angle, the camera turning round it once
 * every 40 s. Each tower stands as tall as its band of the spectrum, bass in the middle and
 * treble at the edges, with lit roofs and windows; kicks pump the centre. Orthographic rays
 * walk the grid cell by cell (no distance march): each cell's tower is a box tested in
 * closed form.
 */
internal const val EQCITY_BODY = """
float ecHeight(vec2 c) {
    float r = length(c);
    float lvl = band(min(r * 7.0, 62.0));
    return 0.12 + (0.25 + 1.9 * lvl + 0.9 * uKick * exp(-r * 0.8)) * (1.0 - r * 0.07);
}
vec3 shade(vec2 p) {
    float a = uTime * PI;
    vec3 w = normalize(vec3(-cos(a), -0.78, -sin(a)));
    vec3 u = normalize(cross(w, vec3(0.0, 1.0, 0.0)));
    vec3 v = cross(u, w);
    vec3 rd = w;
    vec3 ro = vec3(0.0, 0.7, 0.0) + (u * p.x + v * p.y) * 5.0;
    // Start where the ray comes down through the top of the tallest tower.
    ro += rd * ((3.6 - ro.y) / rd.y);
    vec3 col = mix(colorAt(0.66) * 0.02, colorAt(0.7) * 0.08, p.y * 0.5 + 0.5);
    vec2 cell = floor(ro.xz + 0.5);
    vec2 stepv = sign(rd.xz);
    vec2 inv = 1.0 / max(abs(rd.xz), vec2(1e-3));
    vec2 tNext = ((cell + 0.5 * stepv) - ro.xz) * stepv * inv;
    float t = 0.0;
    float tGround = -ro.y / rd.y;
    bool hit = false;
    vec3 n = vec3(0.0, 1.0, 0.0);
    vec2 hc = vec2(0.0);
    float hh = 0.0;
    for (int i = 0; i < 26; i++) {
        if (max(abs(cell.x), abs(cell.y)) <= 6.0) {
            float h = ecHeight(cell);
            // The tower: a box 0.76 wide in the cell, tested by slabs.
            vec3 bmin = vec3(cell.x - 0.38, 0.0, cell.y - 0.38);
            vec3 bmax = vec3(cell.x + 0.38, h, cell.y + 0.38);
            vec3 t1 = (bmin - ro) / rd;
            vec3 t2 = (bmax - ro) / rd;
            vec3 tn = min(t1, t2);
            vec3 tf = max(t1, t2);
            float ta = max(max(tn.x, tn.y), tn.z);
            float tb = min(min(tf.x, tf.y), tf.z);
            if (ta < tb && tb > 0.0) {
                t = ta;
                hit = true;
                hc = cell;
                hh = h;
                n = ta == tn.y ? vec3(0.0, 1.0, 0.0) : (ta == tn.x ? vec3(-stepv.x, 0.0, 0.0) : vec3(0.0, 0.0, -stepv.y));
                break;
            }
        }
        if (tNext.x < tNext.y) { cell.x += stepv.x; tNext.x += inv.x; } else { cell.y += stepv.y; tNext.y += inv.y; }
        if (min(tNext.x, tNext.y) > tGround + 1.0) break;
    }
    vec3 tint = colorAt(length(hc) * 0.07 + uPhase * 0.25);
    if (hit) {
        vec3 q = ro + rd * t;
        if (n.y > 0.5) {
            col = tint * (0.45 + 0.6 * hh / 2.5) * (1.0 + 0.5 * uKick);
        } else {
            float side = abs(n.x) > 0.5 ? q.z - hc.y : q.x - hc.x;
            float fl = floor(q.y * 7.0);
            float lit = step(0.45, fract(q.y * 7.0)) * step(0.3, fract(side * 5.0 + 0.5)) * step(0.5, hash(hc * 3.0 + fl));
            col = colorAt(0.66) * 0.05 * (0.6 + 0.4 * dot(n, vec3(0.7, 0.0, 0.7)));
            col += mix(vec3(1.0, 0.8, 0.5), tint, 0.4) * lit * 0.8;
        }
    } else if (tGround > 0.0) {
        vec3 q = ro + rd * tGround;
        vec2 g = abs(fract(q.xz + 0.5) - 0.5);
        float ln = smoothstep(0.45, 0.5, max(g.x, g.y));
        float inside = step(max(abs(q.x), abs(q.z)), 6.5);
        col = colorAt(0.66) * 0.02 + ln * tint * (0.12 + 0.6 * uBeat) * inside;
    }
    return col;
}
"""

/**
 * Storm sea: a locked-off shot of the open sea at dusk, like a window. The waves are worked out
 * where the ray meets the sea's plane (their slope bends the reflection), so it costs no march;
 * the swell builds with the bass, clouds drift, and every eighth kick brings lightning, a bolt
 * and a flash that lights the clouds from inside. A lighthouse on a rock sweeps its beam round
 * and flashes its lamp on the beat, a ship rocks on the horizon with its windows lit, and rain
 * slants across in front of it all.
 */
internal const val STORMSEA_BODY = """
float ssNoise(vec2 x) {
    vec2 i = floor(x); vec2 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}
float ssFlash() {
    // Every eighth kick: the bolt is that kick's, fading with it.
    return mod(uKicks, 8.0) < 0.5 ? uKick : 0.0;
}
vec3 ssSky(vec3 rd, float flash) {
    vec3 c = mix(mix(vec3(0.5, 0.25, 0.22), colorAt(0.1) * 0.5, 0.3), vec3(0.05, 0.06, 0.12), smoothstep(0.0, 0.45, rd.y));
    c += vec3(1.0, 0.55, 0.3) * pow(max(dot(rd, normalize(vec3(0.3, 0.05, 1.0))), 0.0), 50.0) * 1.2;
    vec2 cp = rd.xz / max(rd.y, 0.06) * 0.7 + vec2(uPhase * 2.0, 0.0);
    float cl = smoothstep(0.45, 0.85, ssNoise(cp) * 0.65 + ssNoise(cp * 2.3) * 0.35);
    // The clouds glow from inside when the lightning strikes.
    vec3 cloud = vec3(0.12, 0.11, 0.16) + colorAt(0.66) * 0.05 + vec3(0.55, 0.6, 0.85) * flash * (0.4 + 0.6 * ssNoise(cp * 1.7 + 3.0));
    c = mix(c, cloud, cl * smoothstep(0.0, 0.15, rd.y));
    return c + vec3(0.6, 0.65, 0.9) * flash * 0.45 * smoothstep(-0.05, 0.3, rd.y);
}
vec2 ssSlope(vec2 x) {
    float amp = 0.14 * (0.45 + uLow);
    float t = uPhase * PI * 4.0;
    vec2 d1 = vec2(0.5, 0.85); vec2 d2 = vec2(-0.75, 0.6); vec2 d3 = vec2(0.25, -1.0);
    vec2 g = d1 * cos(dot(x, d1) * 0.9 - t) * amp * 0.9;
    g += d2 * cos(dot(x, d2) * 2.0 - t * 1.5) * amp;
    g += d3 * cos(dot(x, d3) * 4.4 - t * 2.0) * amp * 1.1;
    return g;
}
vec3 shade(vec2 p) {
    vec3 rd = normalize(vec3(p.x, p.y - 0.15, 1.7));
    rd.xy = rot(0.02 * sin(uTime * PI * 2.0)) * rd.xy;
    float flash = ssFlash();
    vec3 col = ssSky(rd, flash);
    if (rd.y > 0.0) {
        float bi = floor(uKicks / 8.0);
        float bx = (hash(vec2(bi, 1.0)) - 0.5) * 1.5 + 0.06 * (ssNoise(vec2(p.y * 9.0, bi)) - 0.5) + 0.03 * (ssNoise(vec2(p.y * 30.0, bi + 4.0)) - 0.5);
        col += vec3(0.8, 0.85, 1.0) * exp(-abs(p.x - bx) * 160.0) * flash * step(0.1, p.y);
    } else {
        float t = -1.2 / rd.y;
        vec2 x = rd.xz * t;
        vec2 g = ssSlope(x) * smoothstep(40.0, 4.0, t);
        vec3 n = normalize(vec3(-g.x, 1.0, -g.y));
        float fr = 0.04 + 0.96 * pow(1.0 - max(dot(-rd, n), 0.0), 5.0);
        vec3 wc = mix(vec3(0.02, 0.05, 0.07), ssSky(reflect(rd, n), flash), fr);
        float crest = smoothstep(0.1, 0.25, length(g)) * (0.5 + 0.5 * ssNoise(x * 3.0));
        wc += vec3(0.7, 0.75, 0.8) * crest * (0.25 + 0.5 * uLow + flash * 0.5);
        col = mix(wc, ssSky(vec3(rd.x, 0.001, rd.z), flash), smoothstep(12.0, 50.0, t));
        // The lighthouse lamp's path of light on the water below it.
        col += vec3(1.0, 0.85, 0.55) * exp(-abs(p.x + 1.15) * 30.0) * smoothstep(-0.6, 0.15, p.y) * 0.12 * (0.4 + uBeat);
    }
    // A little under the true horizon, where the far water fades into the sky.
    float hz = 0.13;

    // A ship on the horizon, rocking: a dark hull and deckhouse with a row of lit windows.
    float sx = 0.55 + 0.12 * sin(uTime * PI);
    float by = hz + 0.004 * sin(uPhase * PI * 6.0);
    // Drawn at 1.6 times its sizes below.
    vec2 sp = rot(0.04 * sin(uPhase * PI * 4.0)) * (p - vec2(sx, by)) / 1.6;
    bool hull = sp.y > -0.004 && sp.y < 0.016 && abs(sp.x) < 0.11 + sp.y * 1.2;
    bool house = sp.y >= 0.016 && sp.y < 0.04 && sp.x > -0.03 && sp.x < 0.04;
    bool mast = abs(sp.x - 0.005) < 0.0025 && sp.y >= 0.04 && sp.y < 0.075;
    if (hull || house || mast) {
        col = vec3(0.012, 0.012, 0.02) + vec3(0.6, 0.65, 0.9) * flash * 0.15;
        float wx = fract(sp.x / 0.016);
        float on = step(0.4, hash(vec2(floor(sp.x / 0.016), 2.0)));
        if (house && sp.y > 0.022 && sp.y < 0.032 && wx > 0.3 && wx < 0.7) col += vec3(1.0, 0.8, 0.45) * on * 0.9;
        if (hull && sp.y > 0.006 && sp.y < 0.011 && wx > 0.35 && wx < 0.65) col += vec3(1.0, 0.85, 0.5) * on * 0.6;
    }
    col += vec3(1.0, 0.3, 0.2) * exp(-length(sp - vec2(0.005, 0.077)) * 220.0) * (0.5 + 0.5 * uBeat);

    // A lighthouse on a rock at the left: the beam sweeps round (bright when it faces us) and
    // the lamp flashes on the beat.
    vec2 lh = vec2(-1.15, hz);
    float rockTop = lh.y + 0.04 * smoothstep(0.35, 0.0, abs(p.x - lh.x)) + 0.006 * ssNoise(vec2(p.x * 40.0, 1.0));
    bool rock = abs(p.x - lh.x) < 0.33 && p.y < rockTop && p.y > lh.y - 0.006;
    bool tower = p.y >= lh.y && p.y < lh.y + 0.21 && abs(p.x - lh.x) < 0.02 - (p.y - lh.y) * 0.035;
    if (rock || tower) {
        col = vec3(0.015, 0.015, 0.025) + vec3(0.6, 0.65, 0.9) * flash * 0.12;
        // Red and white bands on the tower.
        if (tower) col += vec3(0.06, 0.012, 0.01) * step(0.5, fract((p.y - lh.y) * 18.0));
    }
    vec2 lamp = vec2(lh.x, lh.y + 0.22);
    float sw = uPhase * PI * 2.0;
    float side = sin(sw);
    float facing = max(cos(sw), 0.0);
    vec2 v = p - lamp;
    float along = v.x * (side >= 0.0 ? 1.0 : -1.0);
    float width = 0.015 + max(along, 0.0) * (0.07 + 0.25 * facing);
    float beam = step(0.0, along) * smoothstep(width, 0.0, abs(v.y)) * smoothstep(0.05 + 2.6 * abs(side), 0.0, along);
    col += vec3(1.0, 0.92, 0.7) * beam * (0.18 + 0.45 * facing);
    col += vec3(1.0, 0.9, 0.6) * exp(-length(v) * 45.0) * (0.5 + 1.6 * facing + 0.9 * uBeat);

    // Rain slanting across, two layers; it falls with the flight's phase (20 cells per unit,
    // so its wrap at 2 is a whole number of cells).
    for (int k = 0; k < 2; k++) {
        float fk = float(k);
        vec2 g = vec2((p.x + p.y * 0.3) * (34.0 + fk * 20.0), p.y * (2.5 + fk) + uPhase * (20.0 + fk * 10.0));
        vec2 id = floor(g);
        vec2 f = fract(g);
        float h = hash(id + vec2(fk * 7.0, 3.0));
        float x = 0.2 + 0.6 * fract(h * 13.0);
        float y = fract(h * 7.0) * 0.5;
        float streak = step(0.65, h) * smoothstep(0.1, 0.0, abs(f.x - x)) * step(y, f.y) * step(f.y, y + 0.45);
        col += vec3(0.5, 0.58, 0.7) * streak * (0.22 - 0.07 * fk) * (1.0 + flash);
    }
    return col;
}
"""
