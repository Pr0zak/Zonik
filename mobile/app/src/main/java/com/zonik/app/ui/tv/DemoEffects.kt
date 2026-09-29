package com.zonik.app.ui.tv

/**
 * The demo-scene effects the ambient screen can run. Each is a single fragment shader over a
 * full-screen quad: a `vec3 shade(vec2 p)` body wrapped in [HEADER] and [FOOTER], so they all
 * share the same uniforms, palette helper and cross-fade.
 *
 * Budget, set by the Chromecast with Google TV's Mali-G31 MP2: closed-form maths per pixel, at
 * most three texture reads, no raymarching and no loops longer than a handful of steps. That is
 * the old demo trick — work out where each pixel looks rather than simulating anything — and it
 * is why these cost almost nothing.
 *
 * `uPhase`, `uSpin` and `uTime` are wrapped into 0..2 on the CPU so precision never degrades over
 * a long session. Every effect must use them only in ways that repeat every 2 — as a mirrored
 * texture coordinate, through `fract(x * k / 2)`, or through `sin(πk · x)` with integer k — or
 * the wrap shows as a jump.
 */
enum class DemoEffect(
    val label: String,
    body: String,
    /**
     * Drawn at half resolution into an offscreen buffer and scaled up: for the escape-time
     * fractals, whose pixels along the set's edge run the whole iteration loop whatever else is
     * done. A quarter of the pixels, and their soft glowing filaments barely show the difference.
     */
    val lowRes: Boolean = false,
) {
    TUNNEL("Tunnel", TUNNEL_BODY),
    PLASMA("Plasma", PLASMA_BODY),
    STARFIELD("Starfield", STARFIELD_BODY),
    ROTOZOOM("Rotozoomer", ROTOZOOM_BODY),
    KALEIDOSCOPE("Kaleidoscope", KALEIDOSCOPE_BODY),
    METABALLS("Metaballs", METABALLS_BODY),
    COPPER("Copper bars", COPPER_BODY),
    SYNTHWAVE("Synthwave", SYNTHWAVE_BODY),
    MOIRE("Moiré", MOIRE_BODY),
    TWISTER("Twister", TWISTER_BODY),
    FIRE("Fire", FIRE_BODY),
    MATRIX("Code rain", MATRIX_BODY),
    VORONOI("Crystal", VORONOI_BODY),
    AURORA("Aurora", AURORA_BODY),
    VECTORBALLS("Vector balls", VECTORBALLS_BODY),
    JULIA("Julia", JULIA_BODY, lowRes = true),
    MANDELBROT("Mandelbrot zoom", MANDELBROT_BODY, lowRes = true);

    val fragmentShader: String = HEADER + body + FOOTER
}

/**
 * Scales a [DemoEffect.lowRes] effect's offscreen buffer up to the screen. It goes through the
 * shared FOOTER, so wipes and the fade-in still happen at full resolution.
 */
internal val BLIT_FRAGMENT: String = HEADER + """
uniform sampler2D uLowRes;
vec3 shade(vec2 p) { return texture2D(uLowRes, vPos * 0.5 + 0.5).rgb; }
""" + FOOTER

internal const val DEMO_VERTEX = """
attribute vec2 aPos;
varying vec2 vPos;
void main() {
    vPos = aPos;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

/**
 * Shared by every effect. highp where the GPU has it (the G31 does): the starfield's hash and
 * the metaball field both lose their shape in fp16.
 */
private const val HEADER = """
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
varying vec2 vPos;

uniform float uAspect;
uniform vec2 uCenter;
uniform float uPhase;
uniform float uSpin;
uniform float uTime;
uniform float uTwist;
uniform float uLow;
uniform float uMid;
uniform float uHigh;
uniform float uKick;
uniform float uBeat;
uniform float uFade;
uniform float uWipe;
uniform float uWipeSide;
uniform float uWipeKind;
uniform vec2 uZoomCenter;
uniform float uZoomScale;
uniform vec2 uZoomRot;
uniform float uZoomFlash;
uniform float uPre;
uniform float uPer;
uniform vec2 uCyc0;
uniform vec2 uCyc1;
uniform vec2 uCyc2;
uniform float uSkip;
uniform vec2 uA;
uniform vec2 uZ0;
uniform float uSegments;
uniform vec3 uBalls[5];
uniform vec3 uC0;
uniform vec3 uC1;
uniform vec3 uC2;
uniform sampler2D uTex;

const float PI = 3.14159265;

// A loop through the cover's three colours, so an effect coloured by a cycling value never
// hits a seam.
vec3 pal(float f) {
    f = fract(f) * 3.0;
    if (f < 1.0) return mix(uC0, uC1, smoothstep(0.0, 1.0, f));
    if (f < 2.0) return mix(uC1, uC2, smoothstep(0.0, 1.0, f - 1.0));
    return mix(uC2, uC0, smoothstep(0.0, 1.0, f - 2.0));
}

// Sine-free hash (after Dave Hoskins): sin() of large numbers is unreliable on mobile GPUs.
float hash(vec2 q) {
    vec3 h = fract(vec3(q.xyx) * 0.1031);
    h += dot(h, h.yzx + 33.33);
    return fract((h.x + h.y) * h.z);
}

// The same hue at full brightness. Palette-driven effects need it: a dark sleeve gives dark
// swatches, and a plasma made of them is mud.
vec3 vivid(vec3 c) { return c / max(max(c.r, c.g), max(c.b, 0.15)); }

// A palette colour for effects drawn from colour alone rather than from the cover image. A
// black-and-white sleeve gives grey swatches, and no amount of brightening makes grey into a
// plasma, so the less colour the cover has, the more of the classic rainbow shows through.
vec3 colorAt(float f) {
    vec3 fromCover = vivid(pal(f));
    vec3 rainbow = 0.5 + 0.5 * cos(2.0 * PI * (f + vec3(0.0, 0.33, 0.67)));
    float sat = max(max(uC0.r, uC0.g), uC0.b) - min(min(uC0.r, uC0.g), uC0.b)
              + max(max(uC1.r, uC1.g), uC1.b) - min(min(uC1.r, uC1.g), uC1.b);
    return mix(rainbow, fromCover, clamp(sat * 2.0, 0.3, 1.0));
}

// Squaring pushes the midtones down, so a pale sleeve still reads as a shape rather than a haze.
vec3 punch(vec3 c) { return c * c * 1.3; }

mat2 rot(float a) { float c = cos(a); float s = sin(a); return mat2(c, s, -s, c); }
"""

/**
 * Transitions: during a switch both effects are drawn, and [wipeMask] gives every pixel a value
 * in 0..1. Pixels below the transition's progress belong to the incoming effect and the rest to
 * the outgoing one; each draw discards the other's pixels BEFORE shading, so the switch costs
 * one effect per pixel. A glowing seam in the cover's colour marks the edge, as the old demos did.
 */
private const val FOOTER = """
float wipeMask(vec2 frag, vec2 p) {
    if (uWipeKind < 0.5) return hash(floor(frag / 12.0));                    // block dissolve
    if (uWipeKind < 1.5) return length(p) / 2.1;                             // iris from centre
    if (uWipeKind < 2.5) return fract(atan(p.y, p.x + 1e-4) / (2.0 * PI) + 0.25); // clock sweep
    return clamp(p.x / uAspect * 0.45 + 0.5, 0.0, 1.0) * 0.85
         + hash(vec2(floor(frag.y / 10.0), 7.0)) * 0.15;                     // ragged wipe
}

void main() {
    vec2 p = vec2(vPos.x * uAspect, vPos.y);
    float seam = 0.0;
    if (uWipe >= 0.0) {
        float m = wipeMask(gl_FragCoord.xy, p);
        bool isIncoming = m < uWipe;
        if (isIncoming != (uWipeSide > 0.5)) discard;
        seam = 1.0 - smoothstep(0.0, 0.035, abs(m - uWipe));
    }
    vec3 col = shade(p - uCenter);
    col += vivid(uC0) * seam * 0.9;
    gl_FragColor = vec4(col * uFade, 1.0);
}
"""

/**
 * The classic polar tunnel: each pixel's angle becomes the texture's u, the inverse of its
 * distance from the centre becomes v, and adding to v flies you forward. The walls are the
 * album cover, so every record gets its own tunnel.
 */
private const val TUNNEL_BODY = """
vec3 shade(vec2 p) {
    // Clamped so depth stays bounded; the fog hides the clamp.
    float r = max(length(p), 0.04);
    float a = atan(p.y, p.x + 1e-4) / (2.0 * PI);

    // The kick punches the walls outward for a moment.
    float depth = 0.32 / r * (1.0 - 0.10 * uKick);

    // Four copies of the cover around the circumference (a whole number of mirrored periods,
    // so the atan seam is invisible), twisting more the deeper you look. Denser than one copy
    // on purpose: stretched across the near walls a 128px cover is only a blur.
    float u = a * 4.0 + uSpin + depth * uTwist;
    float v = depth * 0.8 + uPhase;
    vec3 col = punch(texture2D(uTex, vec2(u, v)).rgb);

    // Tint the walls toward the sleeve's muted colour so bright covers do not blow out.
    col = mix(col, col * uC2 * 1.8, 0.35);
    col *= 0.55 + 0.6 * uLow;

    // Glowing ring at every quarter of the texture's depth. Highs widen the line, the kick
    // and the bass make it burn.
    float f = fract(v * 4.0);
    float d = min(f, 1.0 - f);
    float ring = 1.0 - smoothstep(0.0, 0.03 + 0.09 * uHigh, d);
    col += ring * uC0 * (0.25 + 0.5 * uLow + 0.9 * uKick);

    // Fog to black at the vanishing point, which sits behind the cover art on screen; a soft
    // glow there swells into each beat.
    col *= smoothstep(0.05, 0.55, r);
    col += uC1 * (0.10 + 0.35 * uBeat) * (1.0 - smoothstep(0.0, 0.45, r));

    col += uC0 * uKick * 0.06;
    col *= clamp(1.35 - 0.45 * r, 0.0, 1.0);
    return col;
}
"""

/**
 * Sum-of-sines plasma through the cover's palette, quantised into bands the way a 256-colour
 * palette would have drawn it. Bass cycles the palette, mids tighten the waves, the kick jumps
 * the colours forward.
 */
private const val PLASMA_BODY = """
vec3 shade(vec2 p) {
    float t = uTime * PI;
    float ph = uPhase * PI;
    float w = 2.2 + uMid * 1.8;
    float v = sin(p.x * w * 1.3 + t * 2.0)
            + sin(p.y * w + ph * 2.0)
            + sin((p.x + p.y) * w * 0.7 + t * 3.0)
            + sin(length(p * w + vec2(sin(t) * 1.5, cos(t * 2.0) * 1.2)) * 2.0 - ph * 4.0);
    float f = v * 0.125 + 0.5 + uPhase * 0.5 + uKick * 0.15;
    // Banding is the look: 12 steps of palette rather than a smooth gradient.
    f = floor(f * 12.0) / 12.0;
    vec3 col = colorAt(f);
    col *= 0.45 + 0.55 * uLow + 0.25 * uKick;
    // Darken the troughs hard so the field has depth instead of being a flat wash of colour.
    float depth = v * 0.25 + 0.5;
    col *= 0.2 + 0.8 * depth * depth;
    col *= clamp(1.3 - 0.35 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Flying through stars: three layers of hashed cells, each zooming toward the viewer and fading
 * in from the distance. The kick stretches every star into a hyperspace streak; highs make them
 * twinkle.
 *
 * One hash per cell, and everything else — position, size, colour, twinkle — derived from it.
 * The first version hashed four times a layer and ran at exactly 30 fps on the Chromecast: just
 * over the frame budget, so every other vsync was missed. It also runs three layers, not four.
 */
private const val STARFIELD_BODY = """
vec3 shade(vec2 p) {
    p = rot(uSpin * PI) * p;
    vec2 dir = normalize(p + 1e-4);
    float stretch = 1.0 + uLow * 2.0 + uKick * 10.0;
    vec3 col = uC2 * 0.06 + uC1 * 0.10 * uBeat * (1.0 - smoothstep(0.0, 1.2, length(p)));

    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float d = fract(fi / 3.0 + uPhase * 0.5);
        float scale = mix(24.0, 1.5, d);
        float fade = smoothstep(0.0, 0.35, d) * (1.0 - smoothstep(0.85, 1.0, d));

        vec2 q = p * scale + fi * 17.3;
        vec2 cell = floor(q);
        vec2 f = fract(q) - 0.5;
        float h = hash(cell + fi * 31.7);
        // Most cells are empty. A cell spans many pixels, so neighbours take the same branch
        // and the skip is real rather than a divergent-branch cost.
        if (h < 0.55) continue;
        vec2 off = fract(vec2(h * 17.0, h * 43.0)) - 0.5;
        vec2 s = f - off * 0.7;

        // Squash the star along the direction it is flying, which is away from the centre.
        float along = dot(s, dir) / stretch;
        float across = dot(s, vec2(-dir.y, dir.x));
        float dist = length(vec2(along, across));

        float size = 0.03 + 0.07 * h * h;
        float twinkle = 0.7 + 0.6 * uHigh * (0.5 + 0.5 * sin(h * 50.0 + uTime * PI * 40.0));
        float star = smoothstep(size, 0.0, dist) * fade * twinkle;
        col += star * mix(vec3(1.0), pal(h), 0.5) * 1.6;
    }
    return col;
}
"""

/**
 * The rotozoomer: the cover tiled across an infinite plane that turns and breathes. The kick
 * zooms in and splits the colour channels apart; scanlines at the surface's native 540 lines
 * give the CRT look once the display doubles it up.
 */
private const val ROTOZOOM_BODY = """
vec3 shade(vec2 p) {
    float ang = uSpin * PI * 2.0 + sin(uTime * PI) * 0.4;
    float zoom = 1.6 + 0.7 * sin(uTime * PI * 2.0) - 0.45 * uKick - 0.25 * uLow;
    vec2 q = rot(ang) * p * zoom + vec2(uPhase, -uPhase);

    float split = 0.012 * uKick + 0.004 * uHigh;
    vec3 col = vec3(
        texture2D(uTex, q + vec2(split, 0.0)).r,
        texture2D(uTex, q).g,
        texture2D(uTex, q - vec2(split, 0.0)).b);
    col = punch(col) * (0.6 + 0.5 * uLow);
    col += uC0 * uKick * 0.12;

    col *= 0.82 + 0.18 * sin(gl_FragCoord.y * PI);
    col *= clamp(1.3 - 0.35 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * The cover folded into mirrored wedges around the centre. The number of wedges steps every few
 * bars (set on the CPU from the kick count); each kick sends a ring of light out from the middle.
 */
private const val KALEIDOSCOPE_BODY = """
vec3 shade(vec2 p) {
    float r = length(p);
    float a = atan(p.y, p.x + 1e-4) + uSpin * PI;
    float seg = 2.0 * PI / uSegments;
    a = mod(a, seg);
    a = abs(a - seg * 0.5);
    vec2 q = vec2(cos(a), sin(a)) * r * (0.9 - 0.25 * uLow);
    q += vec2(uPhase, 0.35 * sin(uTime * PI));

    vec3 col = punch(texture2D(uTex, q).rgb) * (0.6 + 0.5 * uMid);

    float r0 = (1.0 - uKick) * 1.6;
    col += uC0 * exp(-abs(r - r0) * 18.0) * uKick * 1.2;
    col += uC1 * 0.25 * uBeat * (1.0 - smoothstep(0.0, 0.5, r));

    col *= clamp(1.35 - 0.4 * r, 0.0, 1.0);
    return col;
}
"""

/**
 * Five blobs melting into one another: three sized by bass, mids and highs, two drifting. The
 * CPU moves them and passes (x, y, radius) in `uBalls`. Contour bands in the field give the
 * old-school banded glow; the edge burns brighter on the kick.
 */
private const val METABALLS_BODY = """
vec3 shade(vec2 p) {
    float field = 0.0;
    for (int i = 0; i < 5; i++) {
        vec2 d = p - uBalls[i].xy;
        field += uBalls[i].z * uBalls[i].z / (dot(d, d) + 1e-3);
    }

    float inside = smoothstep(0.95, 1.05, field);
    vec3 body = vivid(pal(field * 0.15 + uPhase * 0.5)) * (0.45 + 0.4 * uLow);
    float rim = smoothstep(0.75, 1.0, field) * (1.0 - smoothstep(1.0, 1.35, field));
    float f = fract(field * 3.0);
    float bands = (1.0 - smoothstep(0.0, 0.12, min(f, 1.0 - f))) * smoothstep(0.25, 0.9, field);

    vec3 col = uC2 * 0.08;
    col += uC1 * 0.25 * bands * (1.0 - inside);
    col = mix(col, body, inside);
    col += uC0 * rim * (0.6 + 1.2 * uKick);
    col *= clamp(1.3 - 0.35 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Copper bars, the Amiga cracktro staple: six shaded horizontal bars swinging up and down
 * through each other. Bass speeds the swing (it rides uPhase); each bar's thickness answers to
 * one band, and the kick fattens them all.
 */
private const val COPPER_BODY = """
vec3 shade(vec2 p) {
    // Faint raster lines behind the bars, at the surface's native line pitch.
    vec3 col = colorAt(0.66) * 0.04 * (0.6 + 0.4 * sin(gl_FragCoord.y * PI));
    float depthTop = -2.0;
    for (int i = 0; i < 6; i++) {
        float fi = float(i);
        float ang = uPhase * PI * 2.0 + fi * 0.75;
        float cy = 0.72 * sin(ang) * (0.7 + 0.3 * sin(uTime * PI * 2.0 + fi));
        // Bars at the front of their swing are drawn over the ones behind.
        float z = cos(ang);
        float band = i == 0 || i == 3 ? uLow : (i == 1 || i == 4 ? uMid : uHigh);
        float thick = 0.06 + 0.05 * band + 0.035 * uKick;
        float d = (p.y - cy) / thick;
        if (abs(d) < 1.0 && z > depthTop) {
            depthTop = z;
            // Cylinder shading plus a hot highlight line: the "metal tube" look.
            float lit = sqrt(1.0 - d * d);
            vec3 c = colorAt(fi / 6.0 + uPhase * 0.5) * lit * (0.55 + 0.45 * (z * 0.5 + 0.5));
            c += vec3(1.0) * pow(lit, 12.0) * 0.35;
            col = c * (0.8 + 0.4 * uLow);
        }
    }
    col *= clamp(1.3 - 0.3 * abs(p.x) / uAspect, 0.0, 1.0);
    return col;
}
"""

/**
 * Synthwave: a checkerboard floor racing toward the viewer under a striped sun. Bass sets the
 * speed and swells the sun, the kick lights the grid lines, the horizon glows into each beat.
 */
private const val SYNTHWAVE_BODY = """
vec3 shade(vec2 p) {
    p = rot(sin(uTime * PI) * 0.06) * p;
    float horizon = 0.06 + 0.03 * sin(uTime * PI * 2.0);
    float y = p.y - horizon;
    vec3 hot = colorAt(0.05);
    vec3 cool = colorAt(0.55);
    vec3 col;

    if (y < 0.0) {
        float z = 0.3 / max(-y, 0.01);
        vec2 uv = vec2(p.x * z + 0.6 * sin(uTime * PI * 2.0), z + uPhase * 2.0);
        float chk = mod(floor(uv.x) + floor(uv.y), 2.0);
        col = mix(cool * 0.10, cool * 0.45, chk);
        // Grid lines on the cell edges, burning on the kick.
        vec2 e = abs(fract(uv) - 0.5);
        float line = smoothstep(0.44, 0.5, max(e.x, e.y));
        col += hot * line * (0.35 + 1.1 * uKick + 0.4 * uLow);
        // Distance haze hides the checker aliasing near the horizon.
        col = mix(col, hot * 0.35, exp(y * 14.0));
    } else {
        col = mix(hot * 0.30, vec3(0.0), smoothstep(0.0, 0.9, y));
        vec2 sp = p - vec2(0.0, horizon + 0.32);
        float r = 0.30 + 0.05 * uLow + 0.02 * uKick;
        float sun = 1.0 - smoothstep(r - 0.01, r, length(sp));
        // The stripes thicken toward the bottom of the sun and scroll down.
        float stripe = step(0.5 + 0.45 * clamp(-sp.y / r, 0.0, 1.0),
                            fract(sp.y * 14.0 + uPhase * 2.0));
        float cut = sp.y < 0.0 ? 1.0 - stripe : 1.0;
        col = mix(col, mix(hot, colorAt(0.3), clamp(0.5 - sp.y / r * 0.5, 0.0, 1.0)), sun * cut);
    }
    col += hot * exp(-abs(y) * 45.0) * (0.5 + 0.8 * uBeat + 0.4 * uLow);
    return col;
}
"""

/**
 * Moiré: two sets of concentric rings drifting past each other; where they interfere, the
 * pattern they make is the effect. Mids tighten the rings, bass pushes them outward.
 */
private const val MOIRE_BODY = """
vec3 shade(vec2 p) {
    vec2 a = vec2(sin(uTime * PI * 2.0) * 0.7, cos(uTime * PI * 4.0) * 0.35);
    vec2 b = vec2(sin(uTime * PI * 2.0 + 2.4) * 0.7, sin(uTime * PI * 2.0 + 1.1) * 0.35);
    float freq = 12.0 + 6.0 * uMid;
    // Clamped sines rather than hard steps, so the rings stay crisp without aliasing.
    float wa = clamp(sin(2.0 * PI * (length(p - a) * freq - uPhase * 2.0)) * 4.0, -1.0, 1.0);
    float wb = clamp(sin(2.0 * PI * (length(p - b) * freq - uPhase * 2.0)) * 4.0, -1.0, 1.0);
    float x = 0.5 - 0.5 * wa * wb;
    vec3 col = mix(colorAt(uPhase * 0.5) * 0.08, colorAt(uPhase * 0.5 + 0.33), x);
    col *= 0.55 + 0.5 * uLow;
    col += colorAt(uPhase * 0.5 + 0.66) * uKick * 0.2 * x;
    col *= clamp(1.3 - 0.35 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * The twister: a square column rotating at a different angle on every line, so it twists like
 * wrung cloth, and snakes side to side. Each scanline works out which of the four faces it can
 * see — the same trick the Amiga did one raster line at a time.
 */
private const val TWISTER_BODY = """
vec3 shade(vec2 p) {
    vec3 col = colorAt(0.8) * 0.05 * (1.0 - smoothstep(0.0, 1.5, length(p)));
    float w = 0.30 + 0.08 * uLow + 0.05 * uKick;
    float cx = 0.25 * sin(p.y * 1.6 + uTime * PI * 4.0);
    float th = uSpin * PI + uPhase * PI + p.y * (1.3 + 1.0 * sin(uTime * PI * 2.0));
    float x = p.x - cx;
    for (int k = 0; k < 4; k++) {
        float fk = float(k);
        float x0 = sin(th + fk * PI * 0.5) * w;
        float x1 = sin(th + (fk + 1.0) * PI * 0.5) * w;
        if (x1 > x0 && x >= x0 && x < x1) {
            // A face turned toward the viewer is wide and bright; one edge-on is narrow and dark.
            float lit = (x1 - x0) / (w * 1.4142);
            float stripe = 0.8 + 0.2 * step(0.5, fract(p.y * 6.0 - uPhase * 4.0));
            float edge = 1.0 - smoothstep(0.0, 0.012, min(x - x0, x1 - x));
            col = colorAt(fk * 0.25 + uPhase * 0.5) * lit * stripe * (0.6 + 0.5 * uMid);
            col += vec3(1.0) * edge * (0.25 + 0.8 * uKick);
        }
    }
    return col;
}
"""

/**
 * Demo fire: four octaves of warped sines (no hashing — value noise would cost four hashes an
 * octave) scrolled upward, thresholded against height so flames lick up from the bottom. Bass
 * raises the flames, the kick makes them flare.
 */
private const val FIRE_BODY = """
vec3 shade(vec2 p) {
    float t = uPhase * PI;
    mat2 m = rot(0.7);
    vec2 q = vec2(p.x * 2.4, p.y * 1.8);
    float n = 0.0;
    float amp = 0.5;
    for (int i = 0; i < 4; i++) {
        float k = 2.0 * float(i + 1);
        n += amp * (0.5 + 0.5 * sin(q.x + 1.6 * sin(q.y - t * k) - t * 2.0));
        q = m * q * 1.9;
        amp *= 0.5;
    }
    // Uneven height across the width, so the fire rises in tongues rather than as a flat band.
    float tongues = 0.8 + 0.2 * sin(p.x * 3.7 + t * 2.0) + 0.12 * sin(p.x * 9.1 - t * 4.0);
    float height = (0.8 + 0.8 * uLow + 0.35 * uKick) * tongues;
    float base = 1.0 - (p.y + 1.0) / height;
    float heat = clamp(base * 1.15 + (n - 0.5) * 1.3, 0.0, 1.0);
    heat *= 0.9 + 0.3 * uKick;

    // A fire ramp in the cover's colours: black, then its deep shade, its main colour, a pale
    // tip, and a white-hot core. colorAt falls back to a rainbow for greyscale sleeves, so a
    // black-and-white cover still burns in colour.
    vec3 deep = colorAt(0.66) * 0.45;
    vec3 body = colorAt(0.0);
    vec3 tip = mix(colorAt(0.33), vec3(1.0), 0.5);
    vec3 col = mix(vec3(0.0), deep, smoothstep(0.05, 0.35, heat));
    col = mix(col, body, smoothstep(0.3, 0.6, heat));
    col = mix(col, tip, smoothstep(0.55, 0.85, heat));
    col = mix(col, vec3(1.0, 0.97, 0.9), smoothstep(0.85, 1.0, heat) * 0.7);
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Code rain: columns of blocky 3x5 glyphs falling at their own speeds, each with a bright head
 * and a fading trail. The glyphs are bit patterns pulled from a hash, not a font. Highs make them
 * flicker faster, the kick flashes the heads, bass lifts the trails.
 */
private const val MATRIX_BODY = """
vec3 shade(vec2 p) {
    // Laid out on the raw screen position so the columns stay put while other effects wander.
    vec2 g = vec2((vPos.x + 1.0) * uAspect * 20.0, (1.0 - vPos.y) * 15.0);
    vec2 cell = floor(g);
    vec2 f = fract(g);
    float colH = hash(vec2(cell.x, 3.7));
    // A whole-number rate per column keeps the fall seamless across uPhase's wrap.
    float rate = 2.0 + floor(colH * 4.0);
    float cycle = 45.0;
    float head = fract(uPhase * 0.5 * rate + colH * 7.0) * cycle;
    float d = head - cell.y;
    float trailLen = 10.0 + 14.0 * fract(colH * 31.0);

    vec3 col = vec3(0.0);
    if (d >= 0.0 && d < trailLen) {
        float gid = hash(cell + vec2(0.0, floor(uTime * (20.0 + 60.0 * uHigh))) * 1.37);
        float bx = floor(f.x * 4.0);
        float by = floor(f.y * 6.0);
        float bit = 0.0;
        if (bx < 3.0 && by < 5.0) {
            float idx = by * 3.0 + bx;
            bit = mod(floor(gid * 32768.0 / exp2(idx)), 2.0);
        }
        vec3 tint = colorAt(0.35);
        float trail = 1.0 - d / trailLen;
        col = tint * bit * trail * trail * (0.5 + 0.5 * uLow);
        if (d < 1.0) col = mix(tint, vec3(1.0), 0.7) * bit * (1.0 + 0.8 * uKick);
    }
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Crystal: drifting Voronoi cells, each filled with its own palette colour, split by glowing
 * seams. One hash per neighbour cell (nine, the ceiling for this budget); mids jitter the seeds,
 * the kick burns the seams, bass lights the cells.
 */
private const val VORONOI_BODY = """
vec3 shade(vec2 p) {
    p = rot(uSpin * PI) * p;
    vec2 g = p * 3.2;
    vec2 ci = floor(g);
    vec2 f = fract(g);
    float d1 = 8.0;
    float d2 = 8.0;
    float id = 0.0;
    for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
            vec2 o = vec2(float(i), float(j));
            float h = hash(ci + o);
            float h2 = fract(h * 13.7);
            vec2 seed = 0.5
                + 0.38 * vec2(sin(uTime * PI * 2.0 + h * 6.2831), cos(uTime * PI * 4.0 + h2 * 6.2831))
                + 0.08 * uMid * vec2(sin(uPhase * PI * 4.0 + h * 40.0), cos(uPhase * PI * 4.0 + h2 * 40.0));
            vec2 r = o + seed - f;
            float d = dot(r, r);
            if (d < d1) {
                d2 = d1;
                d1 = d;
                id = h;
            } else if (d < d2) {
                d2 = d;
            }
        }
    }
    // Gap between nearest and second-nearest seed: near zero on a seam.
    float e = sqrt(d2) - sqrt(d1);
    float seam = 1.0 - smoothstep(0.0, 0.06 + 0.05 * uKick, e);
    vec3 col = colorAt(id + uPhase * 0.5) * (0.22 + 0.35 * uLow) * (1.0 - 0.5 * sqrt(d1));
    col += colorAt(0.1) * seam * (0.5 + 1.3 * uKick + 0.3 * uHigh);
    col *= clamp(1.3 - 0.35 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Aurora: three curtains of light hanging over a starry sky, each a sharp lower edge with rays
 * fading upward, warped side to side by sines. Mids make the curtains sway, bass brightens them.
 */
private const val AURORA_BODY = """
vec3 shade(vec2 p) {
    vec3 col = mix(colorAt(0.62) * 0.06, vec3(0.0), smoothstep(-1.0, 1.0, p.y));
    float sh = hash(floor(gl_FragCoord.xy / 2.0));
    col += vec3(0.9) * step(0.996, sh) * (0.6 + 0.4 * sin(sh * 80.0 + uTime * PI * 20.0))
         * smoothstep(-0.2, 0.6, p.y);

    for (int k = 0; k < 3; k++) {
        float fk = float(k);
        float wx = p.x * (1.1 + 0.35 * fk)
                 + 0.35 * sin(p.x * 2.3 + uTime * PI * 2.0 + fk * 1.9)
                 + (0.15 + 0.35 * uMid) * sin(p.x * 0.8 - uPhase * PI * 2.0 + fk * 2.7);
        float edge = -0.15 + 0.22 * fk + 0.18 * sin(wx * 1.7 + fk);
        float v = p.y - edge;
        float glow = v > 0.0 ? exp(-v * (3.0 + fk)) : exp(v * 22.0);
        float rays = 0.55 + 0.45 * sin(wx * 23.0 + 3.0 * sin(wx * 4.0));
        col += colorAt(0.3 + 0.18 * fk + uPhase * 0.5) * glow * rays
             * (0.28 + 0.55 * uLow + 0.25 * uKick) * (1.0 - 0.25 * fk);
    }
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Vector balls: 24 shaded balls in three rings of eight, a sphere-ish cage turning in 3D. Each
 * pixel tests every ball with a plain distance check and keeps the nearest in depth — painter's
 * order without sorting. Ring positions step by a fixed 45° rotation, so the loop has no trig.
 * Bass spins it faster, the kick swells the balls.
 */
private const val VECTORBALLS_BODY = """
vec3 shade(vec2 p) {
    float a = uPhase * PI;
    float b = 0.45 * sin(uTime * PI * 2.0);
    float ca = cos(a);
    float sa = sin(a);
    float cb = cos(b);
    float sb = sin(b);
    float bestZ = 99.0;
    vec2 hitC = vec2(0.0);
    float hitR = 1.0;
    float hitRing = 0.0;
    for (int r = 0; r < 3; r++) {
        float fr = float(r);
        float y = (fr - 1.0) * 0.55;
        float ringR = r == 1 ? 1.0 : 0.72;
        vec2 v = vec2(ringR, 0.0);
        if (r == 1) v = rot(PI / 8.0) * v;
        for (int k = 0; k < 8; k++) {
            float x1 = v.x * ca - v.y * sa;
            float z1 = v.x * sa + v.y * ca;
            float y2 = y * cb - z1 * sb;
            float z2 = y * sb + z1 * cb;
            float persp = 1.8 / (3.0 + z2);
            vec2 sc = vec2(x1, y2) * persp * 0.62;
            float br = 0.085 * persp * (1.0 + 0.35 * uKick + 0.15 * uLow);
            vec2 dv = p - sc;
            if (dot(dv, dv) < br * br && z2 < bestZ) {
                bestZ = z2;
                hitC = sc;
                hitR = br;
                hitRing = fr;
            }
            v = vec2(v.x - v.y, v.x + v.y) * 0.70710678;
        }
    }

    vec3 col = colorAt(0.7) * 0.05 * (1.0 - smoothstep(0.0, 1.6, length(p)));
    col += colorAt(0.1) * 0.12 * uBeat * (1.0 - smoothstep(0.0, 0.8, length(p)));
    if (bestZ < 98.0) {
        vec2 n2 = (p - hitC) / hitR;
        vec3 n = vec3(n2, sqrt(max(1.0 - dot(n2, n2), 0.0)));
        vec3 light = normalize(vec3(-0.45, 0.55, 0.7));
        float diff = max(dot(n, light), 0.0);
        float spec = pow(max(dot(reflect(-light, n), vec3(0.0, 0.0, 1.0)), 0.0), 18.0);
        float depth = clamp(1.1 - (bestZ + 1.0) * 0.3, 0.35, 1.0);
        col = colorAt(hitRing / 3.0 + uPhase * 0.5) * (0.18 + 0.82 * diff) * depth
            + vec3(1.0) * spec * 0.6;
    }
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Julia set: c circles the classic 0.7885 radius, so the fractal melts continuously from one
 * shape into the next. 24 iterations with smooth escape-time colouring through the palette. Bass
 * zooms in a touch, the kick shifts the colours.
 */
private const val JULIA_BODY = """
vec3 shade(vec2 p) {
    float a = uTime * PI * 2.0;
    vec2 c = 0.7885 * vec2(cos(a), sin(a));
    vec2 z = rot(uSpin * PI) * p * (1.25 - 0.12 * uLow);
    float n = 0.0;
    float m2 = 0.0;
    for (int i = 0; i < 24; i++) {
        z = vec2(z.x * z.x - z.y * z.y, 2.0 * z.x * z.y) + c;
        m2 = dot(z, z);
        if (m2 > 16.0) break;
        n += 1.0;
    }
    vec3 col;
    if (n >= 24.0) {
        col = colorAt(0.6 + uPhase * 0.5) * 0.06;
    } else {
        // Fractional escape count, so the bands blend instead of stepping.
        float sn = n + 1.0 - log2(0.5 * log2(m2));
        float t = clamp(sn / 24.0, 0.0, 1.0);
        col = colorAt(sn * 0.2 - uTime * 8.0 - uPhase * 0.5 + uKick * 0.2) * (0.25 + 1.1 * sqrt(t))
            * (0.7 + 0.4 * uLow);
    }
    col *= clamp(1.3 - 0.35 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * An endless dive into the Mandelbrot set, toward a random Misiurewicz point (see
 * `MandelbrotTargets`).
 *
 * Rendered by perturbation: every pixel is the target's own orbit Z plus a small difference ε,
 * and only ε is iterated — ε' = 2Zε + ε² + δ, where δ is the pixel's offset from the target.
 * That keeps full precision at any depth in fp32, because nothing adds a tiny δ to a large c.
 * Z needs no iterating either: the first `uPre` steps are computed here, after which it is the
 * cycle `uCyc0..2` repeating forever.
 *
 * The CPU loops the zoom through one step of the point's self-similarity, so the dive never
 * ends and never gets deeper than one loop's worth of iterations. Bass speeds the dive, the
 * kick jumps the palette, the bands cycle steadily inward.
 */
private const val MANDELBROT_BODY = """
vec2 cmul(vec2 a, vec2 b) { return vec2(a.x * b.x - a.y * b.y, a.x * b.y + a.y * b.x); }

vec3 shade(vec2 p) {
    // FOOTER shifts p by the centre wander; undo it so the dive stays on its target.
    vec2 d = cmul(p + uCenter, uZoomRot) * uZoomScale;
    // Series skip: the CPU has already run the first uSkip iterations, which at depth are the
    // same for every pixel up to a linear factor — ε = A·δ and z' = A — so start from there.
    vec2 Z = uZ0;
    vec2 e = cmul(uA, d);
    vec2 dz = uA;
    float n = uSkip;
    float m2 = 0.0;
    bool escaped = false;
    for (int i = 0; i < 32; i++) {
        vec2 z = Z + e;
        dz = 2.0 * cmul(z, dz) + vec2(1.0, 0.0);
        e = 2.0 * cmul(Z, e) + cmul(e, e) + d;
        float next = n + 1.0;
        if (next < uPre) {
            Z = cmul(Z, Z) + uZoomCenter;
        } else {
            float j = mod(next - uPre, uPer);
            Z = j < 0.5 ? uCyc0 : (j < 1.5 ? uCyc1 : uCyc2);
        }
        n = next;
        z = Z + e;
        m2 = dot(z, z);
        // A large bailout keeps the smooth colouring below free of bands.
        if (m2 > 64.0) {
            escaped = true;
            break;
        }
    }
    vec3 col;
    if (!escaped) {
        col = colorAt(0.66) * (0.04 + 0.1 * uBeat);
    } else {
        float mu = n - log2(log2(m2) * 0.5);
        // Distance to the set, in screen pixels: the filaments glow and open space goes dark,
        // where escape time alone washes everything out once the dive is deep.
        float dist = 0.25 * sqrt(m2) * log(m2) / max(length(dz), 1e-6);
        float px = dist / (uZoomScale * 2.0 / 540.0);
        float glow = exp(-px * 0.12);
        // Many trips round the palette across the escape range, cycling steadily inward
        // (uTime * 8 is one cycle every 2.5 s and whole at the wrap; bass and the kick push them).
        // The bands fill open space dimly; the filaments glow in the palette's opposite colour,
        // so both read instead of the glow washing the bands out.
        float f = mu * 0.45 - uTime * 8.0 - uPhase * 0.5 + uKick * 0.12;
        float band = 0.5 + 0.5 * sin(2.0 * PI * f);
        col = colorAt(f) * (0.2 + 0.25 * band);
        col += colorAt(f + 0.5) * glow * (0.8 + 0.5 * uLow);
    }
    col = mix(col, vec3(1.0), uZoomFlash);
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""
