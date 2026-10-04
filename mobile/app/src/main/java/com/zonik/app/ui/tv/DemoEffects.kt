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
     * The effect draws the album cover itself, dead centre, and frames it. The ambient
     * overlay then leaves out its own cover and keeps only the title and progress, at the
     * bottom, so the two never sit on top of each other.
     */
    val framesCover: Boolean = false,
    /**
     * The effect reads its own previous frame (`uPrev`) and draws the next one from it — fire
     * rising, ink drifting, an image melting outward. The renderer keeps a pair of buffers per
     * effect on screen for it.
     */
    val feedback: Boolean = false,
    /**
     * Drawn at half resolution and scaled up: for the voxel flight, whose per-pixel ray march
     * cannot be made cheap enough for the Chromecast at full size — and the original voxel
     * engines were chunky anyway. Wipes and fades still happen at full resolution.
     */
    val halfRes: Boolean = false,
    /**
     * Which version of a shared body to compile: the body sees it as `VARIANT` and switches
     * with `#if VARIANT == n`, so one effect's code can give several looks (Warp tunnel,
     * Acid plasma…) without a copy of it per look. 0 is the original.
     */
    variant: Int = 0,
    /**
     * The effect is built around one centre point — a framed cover with rings, a spiral, a
     * kaleidoscope — and would sit dead centre forever. It floats instead: the renderer moves
     * the whole composition slowly around the screen through `uFloat`.
     */
    val floats: Boolean = false,
) {
    TUNNEL("Tunnel", TUNNEL_BODY),
    PLASMA("Plasma", PLASMA_BODY),
    STARFIELD("Starfield", STARFIELD_BODY),
    ROTOZOOM("Rotozoomer", ROTOZOOM_BODY),
    KALEIDOSCOPE("Kaleidoscope", KALEIDOSCOPE_BODY, floats = true),
    METABALLS("Metaballs", METABALLS_BODY),
    COPPER("Copper bars", COPPER_BODY),
    SYNTHWAVE("Synthwave", SYNTHWAVE_BODY),
    MOIRE("Moiré", MOIRE_BODY),
    FIRE("Fire", FIRE_BODY),
    VORONOI("Crystal", VORONOI_BODY),
    AURORA("Aurora", AURORA_BODY),
    JULIA("Julia", JULIA_BODY),
    MANDELBROT("Mandelbrot", MANDELBROT_BODY),
    SHOCKWAVE("Shockwaves", SHOCKWAVE_BODY, framesCover = true, floats = true),
    GODRAYS("God rays", GODRAYS_BODY, framesCover = true, floats = true),
    SUNBURST("Sunburst", SUNBURST_BODY, framesCover = true, floats = true),
    MELT("Melt", MELT_BODY, framesCover = true, feedback = true),
    INK("Ink", INK_BODY, feedback = true),
    OSCILLOSCOPE("Oscilloscope", OSCILLOSCOPE_BODY, framesCover = true, floats = true),
    ORBITS("Orbits", ORBITS_BODY, framesCover = true, floats = true),
    SKYLINE("Neon skyline", SKYLINE_BODY),
    KALEIDOFRAME("Kaleido frame", KALEIDOFRAME_BODY, framesCover = true, floats = true),
    DOTTUNNEL("Dot tunnel", DOTTUNNEL_BODY),
    VOXEL("Voxel hills", VOXEL_BODY, halfRes = true),
    LEDBARS("LED bars", LEDBARS_BODY, framesCover = true, floats = true),
    SPECTRUMRINGS("Spectrum rings", SPECTRUMRINGS_BODY, framesCover = true, floats = true),
    RIPPLES("Water ripples", RIPPLES_BODY, framesCover = true, floats = true),
    DEFORM("Deformations", DEFORM_BODY),
    VHS("VHS glitch", VHS_BODY, framesCover = true),
    DROSTE("Droste zoom", DROSTE_BODY),
    MOSAIC("Cover mosaic", MOSAIC_BODY),
    SQUARETUNNEL("Square tunnel", SQUARETUNNEL_BODY),
    BENTTUBE("Bent tube", BENTTUBE_BODY),
    FLYINGCOVERS("Flying covers", FLYINGCOVERS_BODY),
    HYPERSPACE("Hyperspace", HYPERSPACE_BODY),
    OCEAN("Ocean flyover", OCEAN_BODY),
    CITY("City at night", CITY_BODY),
    CLOUDS("Cloud flight", CLOUDS_BODY, halfRes = true),
    PLANET("Planet flyby", PLANET_BODY),
    APOLLONIAN("Apollonian", APOLLONIAN_BODY, halfRes = true),
    KALISET("Kaliset", KALISET_BODY, halfRes = true),
    WATERFALL("Waterfall", WATERFALL_BODY, feedback = true),
    HEXPULSE("Hex pulse", HEXPULSE_BODY),
    LISSAJOUS("Lissajous", LISSAJOUS_BODY, framesCover = true, feedback = true),
    BUMP("Bump-mapped", BUMP_BODY),
    SHADEBOBS("Shadebobs", SHADEBOBS_BODY, feedback = true),
    CHECKER("Checkerboard", CHECKER_BODY),
    TRUCHET("Truchet maze", TRUCHET_BODY),
    TRACKER("Tracker", TRACKER_BODY, framesCover = true),
    HALFTONE("Halftone", HALFTONE_BODY),
    ASCII("ASCII", ASCII_BODY),
    MILKDROP("Milkdrop warp", MILKDROP_BODY, feedback = true),
    HYPNO("Hypno spiral", HYPNO_BODY, floats = true),
    KIFS("Kaleido fractal", KIFS_BODY, halfRes = true),
    BASSLENS("Bass lens", BASSLENS_BODY, floats = true),
    OPART("Op art", OPART_BODY),
    WORMHOLE("Wormhole", WORMHOLE_BODY),
    MARBLE("Liquid marble", MARBLE_BODY, halfRes = true),
    HEXTUNNEL("Hex tunnel", HEXTUNNEL_BODY),
    LASERS("Laser show", LASERS_BODY),
    ROSE("Rose curves", ROSE_BODY, floats = true),
    TILEZOOM("Tile zoom", TILEZOOM_BODY),
    PULSEGRID("Pulse grid", PULSEGRID_BODY),
    LIGHTNING("Lightning", LIGHTNING_BODY),
    SACRED("Flower of life", SACRED_BODY),
    STROBEKALEIDO("Strobe kaleido", STROBEKALEIDO_BODY, floats = true),
    // Variations on the effects above, from the same bodies (see `variant`).
    WARPTUNNEL("Warp tunnel", TUNNEL_BODY, variant = 1),
    ACIDPLASMA("Acid plasma", PLASMA_BODY, variant = 1),
    SMOOTHPLASMA("Soft plasma", PLASMA_BODY, variant = 2),
    NEBULA("Nebula stars", STARFIELD_BODY, variant = 1),
    KALEIDOZOOM("Kaleido zoom", KALEIDOSCOPE_BODY, variant = 1, floats = true),
    NIGHTDRIVE("Night drive", SYNTHWAVE_BODY, variant = 1),
    JULIAPULSE("Julia pulse", JULIA_BODY, variant = 1),
    DROSTESPIRAL("Droste spiral", DROSTE_BODY, variant = 1),
    TRITUNNEL("Triangle tunnel", SQUARETUNNEL_BODY, variant = 1),
    OCTOTUNNEL("Octagon tunnel", SQUARETUNNEL_BODY, variant = 2),
    RAINBOWWARP("Rainbow warp", HYPERSPACE_BODY, variant = 1),
    MOONLIGHT("Moonlit ocean", OCEAN_BODY, variant = 1),
    HYPNORINGS("Hypno rings", HYPNO_BODY, variant = 1, floats = true),
    HEXRADAR("Hex radar", HEXPULSE_BODY, variant = 1),
    TRIPULSE("Triangle pulse", HEXPULSE_BODY, variant = 2),
    HEXFLIP("Hex flip", HEXPULSE_BODY, variant = 3),
    CELLPULSE("Cell pulse", HEXPULSE_BODY, variant = 4),
    SPECTRUMSQUARES("Square meter", SPECTRUMRINGS_BODY, framesCover = true, variant = 1, floats = true),
    SPECTRUMSPIRAL("Spiral meter", SPECTRUMRINGS_BODY, framesCover = true, variant = 2, floats = true),
    RADAR("Radar", SPECTRUMRINGS_BODY, framesCover = true, variant = 3, floats = true),
    APONEON("Neon circles", APOLLONIAN_BODY, variant = 1, halfRes = true),
    APOPULSE("Circle pulse", APOLLONIAN_BODY, variant = 2, halfRes = true),
    APOGLASS("Glass circles", APOLLONIAN_BODY, variant = 3, halfRes = true),
    HEXTRUCHET("Hex Truchet", TRUCHET_BODY, variant = 1),
    MAZE("Maze", TRUCHET_BODY, variant = 2),
    TUBES("Truchet tubes", TRUCHET_BODY, variant = 3),
    FIREWORKS("Fireworks", FIREWORKS_BODY),
    DISCOBALL("Disco ball", DISCOBALL_BODY, floats = true),
    HYPERCUBE("Hypercube", HYPERCUBE_BODY, halfRes = true, floats = true),
    TWISTER("Twister", TWISTER_BODY),
    SINEDOTS("Sine dots", SINEDOTS_BODY),
    SPIROGRAPH("Spirograph", SPIROGRAPH_BODY, feedback = true),
    GALAXY("Galaxy", GALAXY_BODY, floats = true),
    PULSAR("Ridgelines", PULSAR_BODY),
    BUBBLES("Bubbles", BUBBLES_BODY),
    DIGITALRAIN("Digital rain", DIGITALRAIN_BODY),
    COVERBOUNCE("Bouncing cover", COVERBOUNCE_BODY, feedback = true),
    RIBBONS("Ribbons", RIBBONS_BODY);

    val fragmentShader: String = HEADER + "#define VARIANT $variant\n" + body + FOOTER
}

/**
 * Copies an offscreen buffer (`uBlit`) to the screen through the shared FOOTER, so a feedback
 * or trails effect still gets its wipe and fade at full resolution.
 */
internal val BLIT_FRAGMENT: String = HEADER + """
uniform sampler2D uBlit;
// 1 for a full-size buffer; 0.5 when the effect drew into the lower-left quarter (halfRes).
uniform float uBlitScale;
vec3 shade(vec2 p) { return texture2D(uBlit, (vPos * 0.5 + 0.5) * uBlitScale).rgb; }
""" + FOOTER

/**
 * Trails: this frame (`uCur`) laid over the last trails frame, zoomed out a hair and faded, so
 * anything that moves leaves a streak. `max` rather than a blend keeps the fresh frame at full
 * strength; the small subtraction makes the tail reach true black in 8-bit instead of
 * stalling at a faint haze.
 */
internal val TRAILS_FRAGMENT: String = HEADER + """
uniform sampler2D uCur;
vec3 shade(vec2 p) {
    vec2 uv = vPos * 0.5 + 0.5;
    vec3 cur = texture2D(uCur, uv).rgb;
    vec3 old = prevAt((uv - 0.5) * 0.992 + 0.5) * 0.86 - 0.01;
    return max(cur, old);
}
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
uniform vec2 uFloat;
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
uniform sampler2D uSpectrum;
uniform vec4 uRings;
uniform sampler2D uWave;
uniform sampler2D uTitle;
uniform float uTitleAspect;
uniform sampler2D uPrev;
uniform sampler2D uHeight;
uniform vec3 uTunnel[9];
uniform float uRainbow;
uniform vec2 uPx;
uniform vec2 uDrops[4];
// Kicks so far, counting 0..255 and round again; for effects that change state on a kick.
uniform float uKicks;

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
// `uRainbow` (0..0.7) is how much rainbow to mix in, worked out on the CPU from the palette's
// saturation. It is 0 for any colourful cover, and then the three cos() calls are skipped —
// a branch every pixel takes the same way, so it costs nothing, and effects call this a lot.
vec3 colorAt(float f) {
    vec3 fromCover = vivid(pal(f));
    if (uRainbow <= 0.0) return fromCover;
    vec3 rainbow = 0.5 + 0.5 * cos(2.0 * PI * (f + vec3(0.0, 0.33, 0.67)));
    return mix(fromCover, rainbow, uRainbow);
}

// Squaring pushes the midtones down, so a pale sleeve still reads as a shape rather than a haze.
vec3 punch(vec3 c) { return c * c * 1.3; }

// Signed distance to the album cover: a rounded square of half-size h at the centre.
float coverDist(vec2 p, float h) {
    vec2 q = abs(p) - vec2(h - 0.03);
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - 0.03;
}

// Lays the album cover, half-size h, over col at the centre, with a soft drop shadow. For the
// effects that frame the cover rather than build from it.
vec3 withCover(vec3 col, vec2 p, float h) {
    float d = coverDist(p + vec2(0.0, 0.025), h);
    col *= 1.0 - 0.55 * exp(-max(d, 0.0) * 16.0);
    float inside = 1.0 - smoothstep(0.0, 0.006, coverDist(p, h));
    vec2 uv = vec2(p.x, -p.y) / (2.0 * h) + 0.5;
    return mix(col, texture2D(uTex, uv).rgb, inside);
}

// One band of the 64-band spectrum, 0..1.
float band(float i) { return texture2D(uSpectrum, vec2((i + 0.5) / 64.0, 0.5)).r; }

// The held peak of one band, 0..1: jumps up with the band, holds, then falls.
float peakOf(float i) { return texture2D(uSpectrum, vec2((i + 0.5) / 64.0, 0.5)).a; }

// The audio waveform at x in 0..1 across the capture, as -1..1.
float wave(float x) { return texture2D(uWave, vec2(x, 0.5)).r * 2.0 - 1.0; }

// Coverage (0..1) of the track title, rendered white on transparent, at uv in 0..1 over the
// text's own box (uTitleAspect wide per 1 high). Outside the box: 0.
float titleAt(vec2 uv) {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) return 0.0;
    return texture2D(uTitle, vec2(uv.x, 1.0 - uv.y)).a;
}

// The previous frame at screen uv (0..1), for feedback effects.
vec3 prevAt(vec2 uv) { return texture2D(uPrev, uv).rgb; }

// For effects built around one object at the centre, which is where the album cover sits
// while track info shows: moves the object round a wide ellipse (one lap every 20 s) at
// `scale` of its size, so it spends only moments behind the cover. Returns the point in the
// object's own coordinates.
vec2 roam(vec2 p, float scale) {
    float t = uTime * PI * 2.0;
    vec2 centre = vec2(cos(t) * 0.68 * uAspect, sin(t) * 0.55);
    return (p - centre) / scale;
}

// atan2 to within ~0.005 rad from a polynomial: plenty for picking the nearest of a ring's
// dots, and a fraction of what the built-in costs on the Chromecast's GPU.
float fastAtan2(float y, float x) {
    float ax = abs(x);
    float ay = abs(y);
    float a = min(ax, ay) / (max(ax, ay) + 1e-6);
    float s = a * a;
    float r = ((-0.0464964749 * s + 0.15931422) * s - 0.327622764) * s * a + a;
    if (ay > ax) r = 1.57079637 - r;
    if (x < 0.0) r = 3.14159274 - r;
    if (y < 0.0) r = -r;
    return r;
}

// Triangle wave in -1..1 with period 1: a trig-free stand-in for sin(2πx) where the exact
// curve does not matter.
float tri(float x) { return abs(fract(x) - 0.5) * 4.0 - 1.0; }

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
    float a = fract(atan(p.y, p.x + 1e-4) / (2.0 * PI) + 0.25);
    if (uWipeKind < 0.5) return hash(floor(frag / 12.0));                    // block dissolve
    if (uWipeKind < 1.5) return length(p) / 2.1;                             // iris from centre
    if (uWipeKind < 2.5) return a;                                           // clock sweep
    if (uWipeKind < 3.5) return clamp(p.x / uAspect * 0.45 + 0.5, 0.0, 1.0) * 0.85
         + hash(vec2(floor(frag.y / 10.0), 7.0)) * 0.15;                     // ragged wipe
    if (uWipeKind < 4.5) {                                                   // checkerboard
        vec2 f = fract(frag / 60.0) - 0.5;
        vec2 cell = floor(frag / 60.0);
        return mod(cell.x + cell.y, 2.0) * 0.5 + max(abs(f.x), abs(f.y));
    }
    if (uWipeKind < 5.5) return (abs(p.x) / uAspect + abs(p.y)) * 0.5;      // diamond
    if (uWipeKind < 6.5) return clamp((a + floor(length(p) * 2.4)) / 5.2, 0.0, 1.0); // spiral
    if (uWipeKind < 7.5) return fract(frag.y / 54.0) * 0.8
         + (p.x / uAspect * 0.5 + 0.5) * 0.2;                                // venetian blinds
    if (uWipeKind < 8.5) return abs(p.x) / uAspect;                         // split doors
    if (uWipeKind < 9.5) return hash(floor(frag / 24.0)) * 0.45 + length(p) / 2.1 * 0.55; // radiating dissolve
    if (uWipeKind < 10.5)                                                    // melt, as in Doom
        return (0.5 - vPos.y * 0.5) * 0.75 + hash(vec2(floor(frag.x / 8.0), 3.0)) * 0.25;
    if (uWipeKind < 11.5) {                                                  // hexagon dissolve
        vec2 r = vec2(1.0, 1.7320508);
        vec2 q = p / 0.09;
        vec2 a = mod(q, r) - r * 0.5;
        vec2 b = mod(q - r * 0.5, r) - r * 0.5;
        vec2 g = dot(a, a) < dot(b, b) ? a : b;
        return hash(floor((q - g) * 2.0 + 0.5));
    }
    if (uWipeKind < 12.5) {                                                  // shatter
        vec2 q = p / 0.16;
        vec2 sk = vec2(q.x - q.y * 0.57735, q.y * 1.1547);
        vec2 f = fract(sk);
        vec2 cell = floor(sk) * 2.0 + (f.x + f.y > 1.0 ? 1.0 : 0.0);
        return hash(cell) * 0.6 + length(p) / 2.1 * 0.4;
    }
    float ang = atan(p.y, p.x + 1e-4);
    if (uWipeKind < 13.5) return length(p) / (0.75 + 0.25 * cos(ang * 5.0)) / 4.1; // star iris
    if (uWipeKind < 14.5)                                                    // wavy iris
        return clamp((length(p) + 0.12 * sin(ang * 8.0 + length(p) * 6.0)) / 2.25, 0.0, 1.0);
    if (uWipeKind < 15.5) return fract((ang / (2.0 * PI) + 0.5) * 6.0);      // pinwheel
    if (uWipeKind < 16.5) {                                                  // alternating rings
        float rr = length(p) * 3.0;
        return mod(floor(rr), 2.0) * 0.5 + fract(rr) * 0.5;
    }
    if (uWipeKind < 17.5)                                                    // interlace
        return mod(floor(frag.y / 3.0), 2.0) * 0.5 + (vPos.x * 0.5 + 0.5) * 0.5;
    if (uWipeKind < 18.5) {                                                  // block cascade
        vec2 cell = floor(frag / 48.0);
        return clamp((cell.x + cell.y) / 31.0, 0.0, 1.0) * 0.8 + hash(cell) * 0.2;
    }
    // burn: smooth value noise, so the incoming effect spreads in from scattered holes
    vec2 q = p * 2.5;
    vec2 i = floor(q);
    vec2 f = fract(q);
    f = f * f * (3.0 - 2.0 * f);
    float n = mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
                  mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
    return n * 0.85 + hash(floor(frag / 3.0)) * 0.15;
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
    vec3 col = shade(p - uCenter - uFloat);
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
#if VARIANT == 1
    // Warp tunnel: the walls bulge in five lobes that ripple down the tunnel with the mids.
    r *= 1.0 + (0.08 + 0.14 * uMid) * sin(a * PI * 10.0 + r * 9.0 - uTime * PI * 8.0);
#endif

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
#if VARIANT == 1
    col += ring * colorAt(floor(v * 4.0) * 0.125) * (0.35 + 0.5 * uLow + 1.1 * uKick);
#else
    col += ring * uC0 * (0.25 + 0.5 * uLow + 0.9 * uKick);
#endif

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
#if VARIANT == 1
    float w = 3.4 + uMid * 2.5 + uKick * 1.5;
#else
    float w = 2.2 + uMid * 1.8;
#endif
    float v = sin(p.x * w * 1.3 + t * 2.0)
            + sin(p.y * w + ph * 2.0)
            + sin((p.x + p.y) * w * 0.7 + t * 3.0)
            + sin(length(p * w + vec2(sin(t) * 1.5, cos(t * 2.0) * 1.2)) * 2.0 - ph * 4.0);
    float f = v * 0.125 + 0.5 + uPhase * 0.5 + uKick * 0.15;
#if VARIANT == 1
    // Acid: four hard bands, flipped on every other kick.
    f = floor(f * 4.0) / 4.0 + (mod(uKicks, 2.0) > 0.5 ? 0.5 : 0.0);
#elif VARIANT == 2
    // Smooth: no banding at all, the bands' edges replaced by soft glowing contours.
#else
    // Banding is the look: 12 steps of palette rather than a smooth gradient.
    f = floor(f * 12.0) / 12.0;
#endif
    vec3 col = colorAt(f);
#if VARIANT == 2
    col += vec3(1.0) * exp(-abs(fract(v * 2.0) - 0.5) * 14.0) * 0.12 * (1.0 + uKick);
#endif
    col *= 0.45 + 0.55 * uLow + 0.25 * uKick;
#if VARIANT == 1
    // Acid stays flat and saturated: hard poster bands with no shading.
    col = vivid(col) * (0.8 + 0.4 * uKick);
#else
    // Darken the troughs hard so the field has depth instead of being a flat wash of colour.
    float depth = v * 0.25 + 0.5;
    col *= 0.2 + 0.8 * depth * depth;
#endif
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
#if VARIANT == 1
    // Nebula: slow clouds of the cover's colours behind the stars.
    float neb = sin(p.x * 2.1 + sin(p.y * 3.3 + uTime * PI * 2.0) * 1.5) * sin(p.y * 1.7 - p.x + uTime * PI * 2.0);
    col += colorAt(0.3 + neb * 0.3) * (0.08 + 0.12 * neb * neb) * (0.7 + 0.6 * uLow);
#endif

    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float d = fract(fi / 3.0 + uPhase * 0.5);
        float scale = mix(24.0, 1.5, d);
        float fade = smoothstep(0.0, 0.35, d) * (1.0 - smoothstep(0.85, 1.0, d));

        vec2 q = p * scale + fi * 17.3;
        vec2 cell = floor(q);
        vec2 f = fract(q) - 0.5;
        float h = hash(cell + fi * 31.7);
        vec2 off = fract(vec2(h * 17.0, h * 43.0)) - 0.5;
        vec2 s = f - off * 0.7;

        // Squash the star along the direction it is flying, which is away from the centre.
        float along = dot(s, dir) / stretch;
        float across = dot(s, vec2(-dir.y, dir.x));
        float dist = length(vec2(along, across));

        float size = 0.03 + 0.07 * h * h;
        // A sawtooth twinkle and a two-colour tint rather than sin() and the full palette, and
        // empty cells masked by a multiply rather than a `continue`: still 30 fps before this.
        // (uTime * 20: whole cycles over uTime's wrap.)
        float twinkle = 0.7 + 0.6 * uHigh * fract(h * 7.0 + uTime * 20.0);
        float star = smoothstep(size, 0.0, dist) * fade * twinkle * step(0.55, h);
#if VARIANT == 1
        col += star * mix(vec3(1.0), colorAt(h * 3.0), 0.7) * 1.8;
#else
        col += star * mix(vec3(1.0), mix(uC0, uC1, h), 0.5) * 1.6;
#endif
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
#if VARIANT == 1
    // Kaleido zoom: the wedge mapped in log-polar, so the pattern pours out of the centre forever.
    vec2 q = vec2(a * 1.5, log(max(r, 1e-3)) * 0.7 - uPhase - 0.3 * uKick);
#else
    vec2 q = vec2(cos(a), sin(a)) * r * (0.9 - 0.25 * uLow);
    q += vec2(uPhase, 0.35 * sin(uTime * PI));
#endif

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
#if VARIANT == 1
        // Night drive: stars, and a pale moon in place of the striped sun.
        col = mix(cool * 0.18, vec3(0.0), smoothstep(0.0, 0.6, y));
        col += vec3(step(0.996, hash(floor(p * 130.0)))) * smoothstep(0.05, 0.4, y) * (0.5 + 0.5 * uHigh);
        float mr = 0.16 + 0.01 * uKick;
        float md = length(sp - vec2(0.55, 0.1));
        col += vec3(0.95, 0.93, 0.85) * (1.0 - smoothstep(mr - 0.01, mr, md));
        col += vec3(0.8, 0.85, 1.0) * exp(-max(md - mr, 0.0) * 9.0) * (0.2 + 0.3 * uBeat);
        if (false) {
#endif
        float r = 0.30 + 0.05 * uLow + 0.02 * uKick;
        float sun = 1.0 - smoothstep(r - 0.01, r, length(sp));
        // The stripes thicken toward the bottom of the sun and scroll down.
        float stripe = step(0.5 + 0.45 * clamp(-sp.y / r, 0.0, 1.0),
                            fract(sp.y * 14.0 + uPhase * 2.0));
        float cut = sp.y < 0.0 ? 1.0 - stripe : 1.0;
        col = mix(col, mix(hot, colorAt(0.3), clamp(0.5 - sp.y / r * 0.5, 0.0, 1.0)), sun * cut);
#if VARIANT == 1
        }
#endif
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
            // Triangle waves rather than sin/cos, and the mids widen the same path rather than
            // adding a second: no trig in the 3x3 search at all (it ran the Chromecast at
            // 25 fps). tri(uTime + …) and tri(uTime * 2 + …): whole cycles over the wrap.
            vec2 seed = 0.5 + (0.38 + 0.08 * uMid)
                * vec2(tri(uTime + h), tri(uTime * 2.0 + h2 + 0.25));
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
 * Julia set: c circles the classic 0.7885 radius, so the fractal melts continuously from one
 * shape into the next. 24 iterations with smooth escape-time colouring through the palette. Bass
 * zooms in a touch, the kick shifts the colours.
 */
private const val JULIA_BODY = """
vec3 shade(vec2 p) {
    float a = uTime * PI * 2.0;
#if VARIANT == 1
    // Julia pulse: c runs round the edge of the Mandelbrot cardioid, where the shapes are
    // richest, and each kick shoves it outward for a burst of filaments.
    vec2 e1 = vec2(cos(a), sin(a));
    vec2 e2 = vec2(cos(2.0 * a), sin(2.0 * a));
    vec2 c = (0.5 * e1 - 0.25 * e2) * (1.0 + 0.05 * uKick);
#else
    vec2 c = 0.7885 * vec2(cos(a), sin(a));
#endif
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

/**
 * Shockwaves: every kick launches a ring from behind the cover that races outward and bends
 * the light it passes through, like a drop in water. The CPU times the rings (`uRings` holds
 * each one's age in seconds, -1 when idle) and launches one anyway if the music gives no kick
 * for a while.
 */
private const val SHOCKWAVE_BODY = """
vec3 shade(vec2 p) {
    // Undo FOOTER's small wander; the cover moves only with uFloat, when the effect floats.
    p += uCenter;
    float h = 0.3 + 0.012 * uKick;
    float r = length(p);

    // Each ring's profile at this radius, and a matching radial push for the refraction.
    float push = 0.0;
    vec3 rings = vec3(0.0);
    for (int i = 0; i < 4; i++) {
        float age = i == 0 ? uRings.x : (i == 1 ? uRings.y : (i == 2 ? uRings.z : uRings.w));
        if (age < 0.0) continue;
        float radius = h * 1.3 + age * 0.75;
        float x = r - radius;
        float prof = exp(-x * x * 180.0) * exp(-age * 1.1);
        push += x * exp(-x * x * 60.0) * exp(-age * 1.1);
        rings += colorAt(float(i) * 0.25 + uPhase * 0.5) * prof;
    }

    // A soft wavy field in the cover's colours — deliberately not rings, so the shockwaves read
    // as the only rings on screen — sampled where the shockwaves bend it.
    vec2 q = p * (1.0 - 0.45 * push);
    float field = 0.5 + 0.5 * sin(q.x * 5.0 + 1.6 * sin(q.y * 4.0 + uTime * PI * 2.0) + uPhase * PI * 2.0);
    field *= 0.5 + 0.5 * sin(q.y * 6.0 - 1.2 * sin(q.x * 3.0 - uTime * PI * 4.0));
    vec3 col = mix(colorAt(0.66) * 0.04, colorAt(0.33) * 0.2, field);
    col *= 0.7 + 0.5 * uLow;
    col += rings * (1.1 + 0.6 * uHigh);
    col += colorAt(0.05) * exp(-max(coverDist(p, h), 0.0) * 9.0) * (0.25 + 0.6 * uBeat);
    col *= clamp(1.3 - 0.3 * r, 0.0, 1.0);
    return withCover(col, p, h);
}
"""

/**
 * God rays: shafts of light in the cover's colours stream out from behind it, slowly turning.
 * Bass brightens them, the kick flares them, and a halo behind the cover swells into each beat.
 */
private const val GODRAYS_BODY = """
vec3 shade(vec2 p) {
    p += uCenter;
    float h = 0.3 + 0.01 * uKick;
    float r = length(p);
    float a = atan(p.y, p.x + 1e-4);

    // Three fans of rays at whole-number counts, so each wraps cleanly round the circle and
    // uSpin (period 2) turns them seamlessly.
    float rays = pow(0.5 + 0.5 * sin(a * 9.0 + uSpin * PI * 9.0), 6.0)
               + 0.7 * pow(0.5 + 0.5 * sin(a * 14.0 - uSpin * PI * 14.0 + 1.3), 10.0)
               + 0.5 * pow(0.5 + 0.5 * sin(a * 5.0 + uTime * PI * 2.0 + 0.7), 4.0);
    float fall = exp(-max(r - h, 0.0) * 1.7);
    float strength = 0.35 + 0.8 * uLow + 1.1 * uKick;
    vec3 col = colorAt(0.66) * 0.04;
    col += mix(colorAt(0.05), colorAt(0.33), 0.5 + 0.5 * sin(a * 3.0)) * rays * fall * strength;
    col += colorAt(0.05) * exp(-max(coverDist(p, h), 0.0) * 6.0) * (0.35 + 0.8 * uBeat);
    col *= clamp(1.3 - 0.3 * r, 0.0, 1.0);
    return withCover(col, p, h);
}
"""

/**
 * Spectrum sunburst: the 64-band spectrum as a ring of bars around the cover, bass at the top
 * and mirrored down both sides, so the ring stays symmetrical. Each bar has a bright tip and a
 * soft glow at its root.
 */
private const val SUNBURST_BODY = """
vec3 shade(vec2 p) {
    p += uCenter;
    float h = 0.3;
    float r = length(p);
    // 0 at the top, 1 at the bottom, the same on both sides.
    float u = abs(atan(p.x, p.y)) / PI;
    float seg = floor(u * 63.999);
    float level = band(seg);
    float inner = h * 1.5;
    float len = 0.04 + level * 0.42;
    float across = fract(u * 64.0);
    // Bars a little narrower than their slot, with soft edges.
    float barX = smoothstep(0.1, 0.2, across) * (1.0 - smoothstep(0.8, 0.9, across));
    float barR = smoothstep(inner, inner + 0.008, r) * (1.0 - smoothstep(inner + len - 0.008, inner + len, r));
    float bar = barX * barR;
    float tip = barX * exp(-abs(r - (inner + len)) * 60.0);

    vec3 hue = colorAt(u * 0.5 + uPhase * 0.5);
    vec3 col = colorAt(0.66) * 0.04;
    col += colorAt(0.05) * exp(-max(r - inner, 0.0) * 5.0) * 0.2 * (0.5 + uLow);
    col += hue * bar * (0.55 + 0.6 * level);
    col += mix(hue, vec3(1.0), 0.5) * tip * 0.8;
    col += hue * exp(-abs(r - inner) * 40.0) * (0.3 + 0.7 * uKick);
    col *= clamp(1.3 - 0.3 * r, 0.0, 1.0);
    return withCover(col, p, h);
}
"""

/**
 * Melt: the previous frame, zoomed in a touch, turned a touch and faded, with the cover drawn
 * fresh at the centre each frame — so the cover pours outward forever in a spiral of its own
 * colours. Bass speeds the zoom, mids the twist; a kick rings the cover's edge.
 */
private const val MELT_BODY = """
vec3 shade(vec2 p) {
    vec2 c = vPos * 0.5;
    c = rot(0.004 + 0.012 * uMid) * c * (0.985 - 0.012 * uLow);
    // Multiplying alone stalls in 8-bit (the rounding lands back on the same value), so a
    // small subtraction carries the fade all the way to black.
    vec3 col = max(prevAt(c + 0.5) * 0.965 - 0.003, 0.0);
    vec2 q = vec2(vPos.x * uAspect, vPos.y);
    float h = 0.2 + 0.04 * uKick;
    float inside = 1.0 - smoothstep(0.0, 0.01, coverDist(q, h));
    vec3 cover = texture2D(uTex, vec2(q.x, -q.y) / (2.0 * h) + 0.5).rgb;
    col = mix(col, cover, inside);
    col += colorAt(uPhase * 0.5) * exp(-abs(coverDist(q, h)) * 60.0) * (0.2 + 0.9 * uKick);
    return col;
}
"""

/**
 * Ink in water: the previous frame is carried along a swirling current and fades very slowly,
 * while three drops of ink in the cover's colours drift around dripping in more — each fed by
 * one band of the music, all of them by the kick.
 */
private const val INK_BODY = """
vec3 shade(vec2 p) {
    vec2 uv = vPos * 0.5 + 0.5;
    vec2 q = vec2(vPos.x * uAspect, vPos.y);
    float t = uTime * PI * 2.0;
    vec2 vel = vec2(sin(q.y * 3.0 + t) + 0.5 * sin(q.y * 7.0 - t * 2.0),
                    cos(q.x * 3.0 - t) + 0.5 * cos(q.x * 5.0 + t * 3.0));
    // Multiplying alone stalls in 8-bit (0.992 of a mid-grey rounds back to itself), so a small
    // subtraction carries the fade all the way to black.
    vec3 col = max(prevAt(uv - vel * uPx * (1.5 + 3.0 * uLow)) * 0.994 - 0.003, 0.0);
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        vec2 pos = vec2(sin(t * (1.0 + fi) + fi * 2.1) * uAspect * 0.55, cos(t * (2.0 + fi) + fi) * 0.6);
        vec2 d = q - pos;
        float level = i == 0 ? uLow : (i == 1 ? uMid : uHigh);
        float amt = exp(-dot(d, d) * 300.0) * (0.15 + 0.6 * level + 0.6 * uKick);
        col = mix(col, colorAt(fi / 3.0 + uPhase * 0.5), clamp(amt, 0.0, 1.0));
    }
    return col;
}
"""

/**
 * Oscilloscope: the live waveform bent into a glowing phosphor ring around the cover, with a
 * fainter second trace from later in the same capture. The angle is mirrored, so the trace
 * meets itself at the top instead of showing a seam. Bass swells the trace, mids widen its
 * glow, the kick lights the cover's edge.
 */
private const val OSCILLOSCOPE_BODY = """
vec3 shade(vec2 p) {
    // Undo FOOTER's small wander; the cover moves only with uFloat, when the effect floats.
    p += uCenter;
    float h = 0.3 + 0.01 * uKick;
    float r = length(p);
    float a = atan(p.y, p.x + 1e-4) / (2.0 * PI) + 0.5;
    float x = abs(a * 2.0 - 1.0);
    float base = h * 1.55;
    float amp = 0.08 + 0.12 * uLow;
    float d1 = abs(r - (base + wave(x * 0.5) * amp));
    float d2 = abs(r - (base + 0.13 + wave(0.5 + x * 0.5) * amp * 0.7));
    vec3 c1 = colorAt(0.05 + uPhase * 0.5);
    vec3 c2 = colorAt(0.4 + uPhase * 0.5);
    vec3 col = colorAt(0.66) * 0.03;
    col += c1 * (exp(-d1 * 220.0) * 1.2 + exp(-d1 * 30.0) * 0.25 * (0.6 + uMid));
    col += c2 * (exp(-d2 * 260.0) * 0.6 + exp(-d2 * 40.0) * 0.12);
    col += vec3(1.0) * exp(-d1 * 900.0) * 0.6;
    col += c1 * exp(-max(coverDist(p, h), 0.0) * 6.0) * (0.1 + 0.5 * uKick);
    col *= clamp(1.3 - 0.3 * r, 0.0, 1.0);
    return withCover(col, p, h);
}
"""

/**
 * Orbits: three tilted rings of eight particles circling the cover, the middle ring the other
 * way round. Particles on the near side of their orbit are bigger and brighter. Bass speeds the
 * orbits (they ride uPhase), highs widen their halos, the kick flashes them.
 */
private const val ORBITS_BODY = """
vec3 shade(vec2 p) {
    p += uCenter;
    float h = 0.28 + 0.01 * uKick;
    vec3 col = colorAt(0.66) * 0.035 * (1.0 - smoothstep(0.0, 1.5, length(p)));
    for (int ring = 0; ring < 3; ring++) {
        float fr = float(ring);
        float rad = h * 1.6 + fr * 0.22;
        float tilt = 0.35 + 0.18 * fr;
        float dir = ring == 1 ? -1.0 : 1.0;
        vec3 ringCol = colorAt(fr / 3.0 + uPhase * 0.5);
        vec2 q = rot(0.4 * fr + sin(uTime * PI * 2.0 + fr) * 0.15) * p;
        // In the ring's own frame the ellipse is a circle, so the pixel's angle there picks
        // out the nearest of the ring's 8 particles directly — one distance test per ring
        // instead of eight. (Testing all 24 ran the Chromecast at 6 fps.)
        vec2 qe = vec2(q.x, q.y / tilt);
        float qlen = length(qe);
        float e = qlen - rad;
        // Rational falloffs in place of exp(): the same soft shape at a fraction of the cost.
        col += ringCol * 0.06 / (1.0 + e * e * 14400.0);
        // Away from the ring there is no particle to find: skip the rest, a coherent branch.
        if (abs(e) > 0.12) continue;
        // uPhase * PI * (ring + 1): a whole number of turns over uPhase's wrap.
        float spinA = dir * uPhase * PI * (fr + 1.0);
        float a = fastAtan2(qe.y, qe.x + 1e-4) - spinA;
        // The nearest particle is at most an eighth of a turn round from the pixel's own
        // direction; turning that direction by the difference places it without cos/sin
        // (a 22.5° turn is still within ~0.1% by the small-angle series).
        float delta = floor(a / (2.0 * PI) * 8.0 + 0.5) / 8.0 * 2.0 * PI - a;
        float cd = 1.0 - delta * delta * 0.5 + delta * delta * delta * delta / 24.0;
        float sd = delta - delta * delta * delta / 6.0;
        vec2 u = qe / max(qlen, 1e-4);
        vec2 onRing = u * cd + vec2(-u.y, u.x) * sd;
        vec2 d = q - vec2(onRing.x * rad, onRing.y * rad * tilt);
        float near = onRing.y * 0.5 + 0.5;
        float sz = 0.012 + 0.012 * near + 0.01 * uKick;
        float dd = dot(d, d) / (sz * sz);
        vec3 c = mix(ringCol, vec3(1.0), 0.2 * near);
        col += c * (0.6 + 0.6 * near + 0.5 * uKick) / (1.0 + dd + 0.5 * dd * dd);
        col += c * 0.12 * (0.5 + uHigh) / (1.0 + dd / 9.0);
    }
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return withCover(col, p, h);
}
"""

/**
 * Neon skyline: a city along the bottom third whose 32 buildings are the spectrum — each one's
 * height is a band, bass on the left. Lit windows, neon trim on every roof, a starry night sky,
 * and the whole thing mirrored in a rippling wet street. Mids light more windows, highs
 * brighten them, the kick flashes the trim.
 */
private const val SKYLINE_BODY = """
// One building column at screen uv: colour, and coverage in a.
vec4 building(vec2 uv) {
    float ground = 0.3;
    float bx = uv.x * 32.0;
    float bi = floor(bx);
    float bf = fract(bx);
    float bh = 0.05 + band(bi * 2.0) * 0.42 + hash(vec2(bi, 3.0)) * 0.08;
    float top = ground + bh;
    float walls = step(0.07, bf) * step(bf, 0.93);
    float inside = walls * step(ground, uv.y) * step(uv.y, top);
    vec3 neon = colorAt(bi / 32.0 + uPhase * 0.5);
    float wx = fract(bf * 5.0);
    float wy = fract((uv.y - ground) * 110.0);
    float lit = step(0.6 - 0.35 * uMid, hash(vec2(floor(bf * 5.0) + bi * 7.0, floor((uv.y - ground) * 110.0))));
    float win = step(0.3, wx) * step(wx, 0.7) * step(0.35, wy);
    vec3 c = vec3(0.015, 0.015, 0.03) + neon * lit * win * (0.55 + 0.4 * uHigh);
    float edge = exp(-abs(uv.y - top) * 500.0) * walls
               + (exp(-abs(bf - 0.07) * 120.0) + exp(-abs(bf - 0.93) * 120.0)) * step(ground, uv.y) * step(uv.y, top) * 0.5;
    c += neon * edge * (0.7 + 0.9 * uKick);
    return vec4(c, clamp(max(inside, edge), 0.0, 1.0));
}

vec3 shade(vec2 p) {
    vec2 uv = vPos * 0.5 + 0.5;
    float ground = 0.3;
    vec3 sky = mix(colorAt(0.66) * 0.14, vec3(0.005, 0.005, 0.02), smoothstep(0.3, 1.0, uv.y));
    float st = hash(floor(uv * vec2(180.0, 100.0)));
    sky += vec3(0.9) * step(0.993, st) * smoothstep(0.55, 0.8, uv.y) * (0.6 + 0.4 * sin(st * 60.0 + uTime * PI * 8.0));
    vec3 col;
    if (uv.y >= ground) {
        vec4 b = building(uv);
        col = mix(sky, b.rgb, b.a);
    } else {
        // The street: the skyline upside down, stretched and rippling.
        float ripple = sin(uv.y * 260.0 + uTime * PI * 16.0) * 0.003;
        vec4 b = building(vec2(uv.x + ripple, ground + (ground - uv.y) * 1.2));
        col = mix(vec3(0.01, 0.01, 0.025), b.rgb * 0.4, b.a);
        col += colorAt(0.05) * 0.03;
    }
    col += colorAt(0.05) * exp(-abs(uv.y - ground) * 40.0) * (0.15 + 0.3 * uLow);
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Kaleido frame: the cover sits undistorted at the centre while a band around it shows the same
 * cover folded into mirrored wedges, turning and flowing outward. The wedge count steps every
 * few bars (uSegments); bass pushes the fold outward, mids brighten it, the kick rings the
 * cover's edge.
 */
private const val KALEIDOFRAME_BODY = """
vec3 shade(vec2 p) {
    p += uCenter;
    float h = 0.28 + 0.012 * uKick;
    float r = length(p);
    float a = atan(p.y, p.x + 1e-4) + uSpin * PI;
    float seg = 2.0 * PI / uSegments;
    a = mod(a, seg);
    a = abs(a - seg * 0.5);
    // uPhase as a mirrored texture coordinate: seamless at its wrap.
    vec2 q = vec2(cos(a), sin(a)) * r * (0.8 - 0.2 * uLow) + vec2(uPhase, 0.3 * sin(uTime * PI * 2.0));
    vec3 col = punch(texture2D(uTex, q).rgb) * (0.55 + 0.5 * uMid);
    // Strongest right around the cover, fading out toward the screen edge.
    col *= exp(-max(r - h * 1.45, 0.0) * 1.8);
    col += colorAt(uPhase * 0.5) * exp(-abs(coverDist(p, h) - 0.03) * 50.0) * (0.3 + 1.0 * uKick);
    col *= clamp(1.3 - 0.3 * r, 0.0, 1.0);
    return withCover(col, p, h);
}
"""

/**
 * Dot tunnel: twelve rings of dots flying at the viewer down a winding tunnel, each ring
 * twisted a little against the last. Each pixel only asks, per ring, which dot on that ring is
 * nearest in angle — no loop over the dots. Bass is the speed, highs grow the dots, the kick
 * flashes them; colour runs with depth.
 */
private const val DOTTUNNEL_BODY = """
vec3 shade(vec2 p) {
    vec3 col = colorAt(0.66) * 0.03;
    // Two palette colours for the whole tunnel, mixed per ring by depth. Each ring's centre and
    // depth are the same for every pixel, so the CPU works them out once a frame (`uTunnel`:
    // x, y, z). With the fast atan and the small-angle placement below the loop has no trig
    // left in it — the first version, twelve rings with a palette lookup, two exp()s and three
    // trig calls each, ran the Chromecast at 9 fps.
    vec3 nearCol = colorAt(uPhase * 0.5);
    vec3 farCol = colorAt(uPhase * 0.5 + 0.4);
    float boost = 0.9 + 0.6 * uLow;
    float spacing = 2.0 * PI / 24.0;
    for (int j = 0; j < 9; j++) {
        vec3 ring = uTunnel[j];
        float z = ring.z;
        vec2 q = p - ring.xy;
        float len = length(q);
        float R = 0.22 / z;
        float size = (0.006 + 0.004 * uHigh) / z * (1.0 + 0.3 * uKick);
        // Nearly every pixel is nowhere near this ring. Rings are bands, so neighbouring
        // pixels take the same branch and skipping the dot maths saves real work.
        if (abs(len - R) > size * 6.0) continue;
        float tw = float(j) * 0.26 + uSpin * PI;
        float a = fastAtan2(q.y, q.x + 1e-4) + tw;
        // Angle to the nearest dot, at most half a dot spacing: small enough that
        // cos ≈ 1 − δ²/2 and sin ≈ δ − δ³/6 place the dot exactly enough.
        float delta = floor(a / spacing + 0.5) * spacing - a;
        float cd = 1.0 - delta * delta * 0.5;
        float sd = delta - delta * delta * delta / 6.0;
        vec2 u = q / max(len, 1e-4);
        vec2 dotPos = (u * cd + vec2(-u.y, u.x) * sd) * R;
        vec2 d = q - dotPos;
        float dd = dot(d, d) / (size * size);
        float fog = smoothstep(1.0, 0.55, z);
        vec3 dc = mix(nearCol, farCol, fract(z * 0.6 + float(j) / 9.0));
        col += dc * (1.0 / (1.0 + dd + 0.5 * dd * dd) + 0.08 / (1.0 + dd * 0.1)) * fog * boost;
    }
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Voxel landscape: a low flight up a valley between rolling hills, Comanche-style, into a
 * setting sun. The hills nearest the camera rise and fall with the spectrum across the valley
 * floor; bass is the flying speed. Ray-marched against the heightfield in 40 growing steps,
 * with contour banding for the voxel look and fog into the sky.
 */
private const val VOXEL_BODY = """
// Terrain height: one read of a tileable heightmap built on the CPU (`uHeight`, repeating every
// 20 units, which is how far the camera moves over uPhase's wrap, so the flight never jumps),
// in place of the six sines per step that ran the Chromecast at 7 fps.
float terrain(vec2 xz) {
    return texture2D(uHeight, xz * 0.05).r * 1.6 + abs(xz.x) * 0.25;
}

vec3 shade(vec2 p) {
    float camZ = uPhase * 10.0;
    vec3 ro = vec3(sin(uTime * PI * 2.0) * 1.0, 2.2 + 0.3 * sin(uTime * PI * 2.0), camZ);
    vec3 rd = normalize(vec3(p.x, p.y - 0.25, 1.6));

    vec3 sky = mix(colorAt(0.05) * 0.5, colorAt(0.66) * 0.1, smoothstep(-0.1, 0.8, p.y));
    float sun = 1.0 / (1.0 + dot(p - vec2(0.0, 0.35), p - vec2(0.0, 0.35)) * 60.0);
    sky += colorAt(0.1) * sun * (0.8 + 0.6 * uBeat);

    // The spectrum lifts the ground nearest the camera, one band per slice of the screen,
    // looked up once per pixel rather than at every step.
    float lift = band(floor(clamp(abs(p.x) * 40.0, 0.0, 63.0))) * 0.9;

    vec3 col = sky;
    // Looking up from well above the ground, a ray never meets it: the top of the screen is
    // pure sky and skips the march entirely.
    if (rd.y > 0.08) {
        col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
        return col;
    }
    float t = 0.3;
    for (int i = 0; i < 24; i++) {
        vec3 pos = ro + rd * t;
        float h = terrain(pos.xz) + lift * max(0.0, 1.0 - t * 0.2);
        if (pos.y < h) {
            vec3 ground = colorAt(h * 0.3 + 0.1) * (0.35 + 0.25 * h);
            ground *= 0.8 + 0.2 * step(0.5, fract(h * 6.0));
            float fog = smoothstep(2.0, 15.0, t);
            col = mix(ground, sky, fog);
            break;
        }
        t += 0.12 + t * 0.09;
    }
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * LED bars: the spectrum as two banks of dot-matrix LEDs either side of the cover, bass next to
 * it and treble at the screen edges, each column topped by a peak cap that holds and then falls
 * (the peaks ride in the spectrum texture's alpha). The banks reflect in a glossy floor below.
 */
private const val LEDBARS_BODY = """
vec3 shade(vec2 p) {
    p += uCenter;
    float h = 0.26 + 0.01 * uKick;
    const float COLS = 18.0;
    const float ROWS = 22.0;
    float x0 = h + 0.1;
    float x1 = uAspect * 0.94;
    float y0 = -0.5;
    float y1 = 0.78;
    // Below the floor line the banks mirror, fading out.
    float refl = 0.0;
    vec2 q = vec2(abs(p.x), p.y);
    if (q.y < y0) { refl = 1.0; q.y = y0 + (y0 - q.y) * 1.6; }

    vec3 col = colorAt(0.66) * 0.03;
    col += colorAt(0.05) * exp(-max(coverDist(p, h), 0.0) * 5.0) * (0.15 + 0.5 * uKick);
    vec2 a = (q - vec2(x0, y0)) / vec2(x1 - x0, y1 - y0);
    if (a.x >= 0.0 && a.x < 1.0 && a.y >= 0.0 && a.y < 1.0) {
        vec2 cell = floor(a * vec2(COLS, ROWS));
        vec2 f = fract(a * vec2(COLS, ROWS)) - 0.5;
        // Bands spread log-ish across the columns: bass gets its own columns.
        float b = floor(pow(cell.x / COLS, 1.4) * 63.0);
        float level = band(b);
        float pk = peakOf(b);
        float row = (cell.y + 0.5) / ROWS;
        float lit = step(row, level);
        float cap = step(abs(floor(pk * ROWS) - cell.y), 0.5) * step(0.03, pk);
        float led = 1.0 - smoothstep(0.30, 0.40, max(abs(f.x) * 0.9, abs(f.y) * 1.25));
        vec3 hue = colorAt(row * 0.6 + uPhase * 0.5);
        vec3 c = hue * 0.07;
        c = mix(c, hue * (0.8 + 0.6 * level), lit);
        c = mix(c, mix(hue, vec3(1.0), 0.65), cap);
        col += c * led;
        // A soft bloom round the lit LEDs.
        col += hue * lit * 0.12;
    }
    col *= 1.0 - refl * (0.7 + 0.25 * clamp((y0 - p.y) * 3.0, 0.0, 1.0));
    col += colorAt(0.33) * exp(-abs(p.y - y0) * 90.0) * 0.25;
    col *= clamp(1.3 - 0.25 * length(p), 0.0, 1.0);
    return withCover(col, p, h);
}
"""

/**
 * Spectrum rings: fourteen dashed rings round the cover, like a stack of circular meters. Each
 * ring is a slice of the spectrum (bass innermost); the louder it is, the further its lit arc
 * reaches round from the top, with a bright tick at its held peak. Neighbouring rings turn
 * opposite ways.
 *
 * Variants: 1 Square meter (square rings), 2 Spiral meter (one coiled meter), 3 Radar
 * (a sweep lights the dashes as it passes).
 */
private const val SPECTRUMRINGS_BODY = """
vec3 shade(vec2 p) {
    p += uCenter;
    float h = 0.27 + 0.01 * uKick;
#if VARIANT == 1
    // Squares: each ring follows a rounded square instead of a circle.
    float r = max(abs(p.x), abs(p.y)) * 1.12;
#else
    float r = length(p);
#endif
    float inner = h * 1.45;
    const float SP = 0.048;
    vec3 col = colorAt(0.66) * 0.03;
    col += colorAt(0.05) * exp(-max(coverDist(p, h), 0.0) * 5.0) * (0.15 + 0.5 * uKick);
    float a0 = fastAtan2(p.x, p.y) / (2.0 * PI) + 0.5;      // 0..1 round from the bottom
#if VARIANT == 2
    // Spiral: one continuous meter coiling outward, a ring's width further each turn.
    float rr = (r - inner) / SP - a0;
#else
    float rr = (r - inner) / SP;
#endif
    float k = floor(rr);
    if (k >= 0.0 && k < 14.0) {
        float fr = fract(rr);
        float b = k * 4.0 + 1.0;
        float level = max(band(b - 1.0), band(b + 1.0));
        float pk = max(peakOf(b - 1.0), peakOf(b + 1.0));
        float dir = mod(k, 2.0) * 2.0 - 1.0;
#if VARIANT == 2
        float a = a0;
#else
        // 0 at the top, 0.5 at the bottom; whole turns of uSpin so the wrap never shows.
        float a = fract(a0 - 0.5 + dir * uSpin * 0.5 * (1.0 + mod(k, 3.0)));
#endif
        float reach = abs(a - 0.5) * 2.0;          // 1 at the top, 0 at the bottom
        float lit = step(1.0 - level, reach);
        float tick = exp(-abs(reach - (1.0 - pk)) * 140.0) * step(0.03, pk);
#if VARIANT == 3
        // Radar: a sweep circles once every two seconds; dashes glow as it passes and fade.
        float behind = fract(fract(uTime * 10.0) - a0);
        float glow = exp(-behind * 5.0);
        lit = max(lit * 0.35, glow * (0.3 + level));
#endif
        float segs = 24.0 + k * 4.0;
        float fd = fract(a * segs);
        float dash = smoothstep(0.08, 0.18, fd) * (1.0 - smoothstep(0.72, 0.82, fd));
        float ring = smoothstep(0.12, 0.28, fr) * (1.0 - smoothstep(0.68, 0.84, fr));
        vec3 hue = colorAt(k / 14.0 * 0.7 + uPhase * 0.5);
        col += hue * ring * dash * (0.08 + lit * (0.55 + 0.7 * level));
        col += mix(hue, vec3(1.0), 0.6) * ring * tick * 1.2;
    }
#if VARIANT == 3
    float sweep = fract(uTime * 10.0 - a0);
    col += colorAt(0.05) * exp(-min(sweep, 1.0 - sweep) * 120.0) * step(inner, r) * step(r, inner + SP * 14.0) * 0.8;
#endif
    col += colorAt(0.05) * exp(-abs(r - inner + 0.012) * 70.0) * (0.25 + 0.8 * uKick);
    col *= clamp(1.3 - 0.3 * r, 0.0, 1.0);
    return withCover(col, p, h);
}
"""

/**
 * Water ripples over a pool whose floor is the cover. Every kick drops a stone somewhere (the
 * shockwave rings' ages in `uRings`, their drop points in `uDrops`) and a train of waves spreads
 * from it; highs bring a light rain of small drops, one per cell of a grid, each on its own
 * clock. All closed form: each wave's slope is worked out directly, then bends the view of the
 * floor and catches a highlight in the cover's colours where it faces the light.
 */
private const val RIPPLES_BODY = """
// The slope a wave train adds at d from its drop point, `age` seconds after it fell.
vec2 ripple(vec2 d, float age, float speed, float amp) {
    float r = length(d) + 1e-4;
    float x = r - age * speed;
    float env = exp(-x * x * 90.0) * exp(-age * 0.8) * amp / (1.0 + r * 3.0);
    return d / r * cos(x * 70.0) * env;
}
vec3 shade(vec2 p) {
    p += uCenter;
    vec2 g = vec2(0.0);
    for (int i = 0; i < 4; i++) {
        float age = i == 0 ? uRings.x : (i == 1 ? uRings.y : (i == 2 ? uRings.z : uRings.w));
        if (age < 0.0) continue;
        g += ripple(p - uDrops[i], age, 0.55, 1.0 + uLow);
    }
    // Rain: one small drop per cell, each falling at its own moment in a 2 s cycle (whole
    // cycles of uTime, so the wrap never shows); cells sit out so it stays a light shower.
    const float CELL = 0.3;
    vec2 cell = floor(p / CELL);
    float hr = hash(cell + 17.0);
    float rAge = fract(uTime * 20.0 + hr) * 2.0;
    vec2 at = (cell + 0.25 + 0.5 * vec2(hash(cell + 3.0), hash(cell + 9.0))) * CELL;
    if (hr < 0.25 + 0.5 * uHigh) g += ripple(p - at, rAge, 0.12, 0.6);

    vec2 q = p + g * 0.05;
    float h = 0.3;
    vec3 pool = punch(texture2D(uTex, q * 0.45 + vec2(uTime, -uTime)).rgb) * (0.14 + 0.1 * uLow);
    pool = mix(pool, colorAt(0.66) * 0.08, 0.35);
    vec3 col = withCover(pool, q, h);
    float spec = max(dot(g, vec2(-0.7, 0.7)), 0.0);
    col += mix(colorAt(0.05 + uPhase * 0.5), vec3(1.0), 0.5) * spec * spec * 0.9;
    col += colorAt(0.33) * length(g) * 0.08;
    col *= clamp(1.3 - 0.25 * length(p), 0.0, 1.0);
    return col;
}
"""

/**
 * Plane deformations, after the old "deformation" intros: the cover mapped through a different
 * formula for where each pixel looks, cut to the next one every ~13 s with a flash. The flight
 * over an endless floor and under a ceiling; a five-petal flower tunnel that breathes with the
 * mids; and a whirlpool that twists harder with the bass. Bass is the forward speed.
 */
private const val DEFORM_BODY = """
vec3 shade(vec2 p) {
    float slot = uTime * 1.5;
    float m = floor(slot);
    float r = length(p);
    float a = fastAtan2(p.y, p.x + 1e-4) / PI;   // -1..1; ×whole numbers keeps the seam hidden
    p *= 1.0 - 0.12 * uKick;
    vec2 uv;
    float lightF;
    if (m < 0.5) {
        float y = p.y + 0.06 * sin(p.x * 2.0 + uTime * PI * 4.0) * (0.3 + uLow);
        float ay = abs(y) + 0.02;
        uv = vec2(p.x / ay * 0.5 + 0.3 * sin(uTime * PI * 2.0), 0.6 / ay + uPhase * 2.0);
        lightF = clamp(ay * 2.4, 0.0, 1.0);
    } else if (m < 1.5) {
        float rr = r * (1.0 + 0.3 * sin(a * PI * 5.0 + uSpin * PI * 5.0) * (0.5 + 0.8 * uMid));
        uv = vec2(a * 2.0, 0.4 / max(rr, 0.03) + uPhase * 2.0);
        lightF = clamp(rr * 2.2, 0.0, 1.0);
    } else {
        float tw = (2.0 + 1.5 * uLow) / max(r, 0.12) * 0.3;
        uv = rot(tw + uSpin * PI * 2.0) * p * 0.9 + vec2(uPhase, 0.0);
        lightF = clamp(r * 1.6, 0.15, 1.0);
    }
    vec3 col = punch(texture2D(uTex, uv).rgb) * lightF * (0.65 + 0.5 * uLow);
    col += uC0 * uKick * 0.1;
    // A flash on each cut.
    float edge = fract(slot);
    col += vivid(uC1) * exp(-edge * 40.0) * 0.8;
    col *= clamp(1.35 - 0.3 * r, 0.0, 1.0);
    return col;
}
"""

/**
 * VHS glitch: the cover on a worn tape. Rows tear sideways and blocks jump, more and harder on
 * each kick; the colour channels split; a tracking band rolls up the screen dragging noise
 * through the picture; scanlines and grain over everything. The tearing reseeds twelve times a
 * second, the jerky rate of a real deck.
 */
private const val VHS_BODY = """
vec3 tape(vec2 q, float h) {
    vec3 bg = mix(colorAt(0.66) * 0.05, colorAt(0.33) * 0.16, 0.5 + 0.5 * sin(q.y * 3.0 + uTime * PI * 2.0));
    float inside = 1.0 - smoothstep(0.0, 0.006, coverDist(q, h));
    if (inside <= 0.0) return bg;
    return mix(bg, texture2D(uTex, vec2(q.x, -q.y) / (2.0 * h) + 0.5).rgb, inside);
}
vec3 shade(vec2 p) {
    p += uCenter;
    vec2 fc = gl_FragCoord.xy;
    float seed = floor(uTime * 240.0);
    float amount = 0.35 + 0.65 * uKick;
    float row = floor(fc.y / 5.0);
    float shift = 0.0;
    if (hash(vec2(row, seed)) > 0.97 - 0.12 * amount) shift = (hash(vec2(row, seed + 7.0)) - 0.5) * 0.3 * amount;
    vec2 blk = floor(fc / vec2(48.0, 18.0));
    if (hash(blk + seed * 1.37) > 0.992 - 0.1 * uKick) shift += (hash(blk + 3.1) - 0.5) * 0.35;
    // The tracking band, rolling up the screen six times a cycle.
    float ry = fract(vPos.y * 0.5 + 0.5 - uTime * 3.0) - 0.5;
    float trk = exp(-ry * ry * 900.0);
    shift += trk * 0.03 * sin(fc.y * 0.9 + seed);

    float h = 0.36 + 0.01 * uKick;
    float split = 0.004 + 0.022 * uKick + 0.006 * uHigh;
    vec2 q = vec2(p.x + shift, p.y);
    vec3 col = vec3(tape(q + vec2(split, 0.0), h).r, tape(q, h).g, tape(q - vec2(split, 0.0), h).b);
    col = punch(col) * 0.85 + col * 0.25;
    col += trk * hash(fc * 0.5 + seed) * 0.35;
    col += (hash(fc + seed * 3.3) - 0.5) * (0.06 + 0.08 * uKick);
    col *= 0.78 + 0.22 * sin(fc.y * PI);
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
"""
