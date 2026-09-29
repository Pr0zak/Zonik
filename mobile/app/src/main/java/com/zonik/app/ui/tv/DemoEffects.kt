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
enum class DemoEffect(val label: String, body: String) {
    TUNNEL("Tunnel", TUNNEL_BODY),
    PLASMA("Plasma", PLASMA_BODY),
    STARFIELD("Starfield", STARFIELD_BODY),
    ROTOZOOM("Rotozoomer", ROTOZOOM_BODY),
    KALEIDOSCOPE("Kaleidoscope", KALEIDOSCOPE_BODY),
    METABALLS("Metaballs", METABALLS_BODY);

    val fragmentShader: String = HEADER + body + FOOTER
}

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

// Squaring pushes the midtones down, so a pale sleeve still reads as a shape rather than a haze.
vec3 punch(vec3 c) { return c * c * 1.3; }

mat2 rot(float a) { float c = cos(a); float s = sin(a); return mat2(c, s, -s, c); }
"""

private const val FOOTER = """
void main() {
    vec2 p = vec2(vPos.x * uAspect, vPos.y) - uCenter;
    gl_FragColor = vec4(shade(p) * uFade, 1.0);
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
    // A black-and-white sleeve gives a grey palette, and no amount of brightening makes grey a
    // plasma, so the less colour the cover has, the more of the classic rainbow shows through.
    vec3 fromCover = vivid(pal(f));
    vec3 rainbow = 0.5 + 0.5 * cos(2.0 * PI * (f + vec3(0.0, 0.33, 0.67)));
    float sat = max(max(uC0.r, uC0.g), uC0.b) - min(min(uC0.r, uC0.g), uC0.b)
              + max(max(uC1.r, uC1.g), uC1.b) - min(min(uC1.r, uC1.g), uC1.b);
    vec3 col = mix(rainbow, fromCover, clamp(sat * 2.0, 0.3, 1.0));
    col *= 0.45 + 0.55 * uLow + 0.25 * uKick;
    // Darken the troughs hard so the field has depth instead of being a flat wash of colour.
    float depth = v * 0.25 + 0.5;
    col *= 0.2 + 0.8 * depth * depth;
    col *= clamp(1.3 - 0.35 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Flying through stars: four layers of hashed cells, each zooming toward the viewer and fading
 * in from the distance. The kick stretches every star into a hyperspace streak; highs make them
 * twinkle.
 */
private const val STARFIELD_BODY = """
vec3 shade(vec2 p) {
    p = rot(uSpin * PI) * p;
    vec2 dir = normalize(p + 1e-4);
    float stretch = 1.0 + uLow * 2.0 + uKick * 10.0;
    vec3 col = uC2 * 0.06 + uC1 * 0.10 * uBeat * (1.0 - smoothstep(0.0, 1.2, length(p)));

    for (int i = 0; i < 4; i++) {
        float fi = float(i);
        float d = fract(fi * 0.25 + uPhase * 0.5);
        float scale = mix(24.0, 1.5, d);
        float fade = smoothstep(0.0, 0.35, d) * (1.0 - smoothstep(0.85, 1.0, d));

        vec2 q = p * scale + fi * 17.3;
        vec2 cell = floor(q);
        vec2 f = fract(q) - 0.5;
        float h = hash(cell + fi * 31.7);
        vec2 off = vec2(hash(cell + 3.1), hash(cell + 7.9)) - 0.5;
        vec2 s = f - off * 0.7;

        // Squash the star along the direction it is flying, which is away from the centre.
        float along = dot(s, dir) / stretch;
        float across = dot(s, vec2(-dir.y, dir.x));
        float dist = length(vec2(along, across));

        float size = 0.03 + 0.07 * h * h;
        float twinkle = 0.7 + 0.6 * uHigh * hash(cell + floor(uTime * 40.0));
        float star = smoothstep(size, 0.0, dist) * step(0.55, h) * fade * twinkle;
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
