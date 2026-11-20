package com.zonik.app.ui.tv

/**
 * The Journey worlds: procedural 3D spaces the camera flies through on one shared, winding
 * path. Each world is a `VARIANT` of [JOURNEY_BODY], and because they share the path, the camera
 * and the timing, a switch between two of them keeps the flight continuous: the renderer opens
 * an iris from the vanishing point as the camera passes a glowing gate, and the next world is
 * simply there on the other side.
 *
 * 0. Gyroid flight: the gyroid sheet, sin x·cos y + sin y·cos z + sin z·cos x = 0.
 * 1. Schwarz chambers: the Schwarz-P sheet, cos x + cos y + cos z = 0: rounded cubic rooms,
 *    tiled, each room its own colour, the tile seams glowing on the beat.
 * 2. Bubble flight: a lattice of glassy spheres, each cell its own size, swelling on the kick.
 * 3. Pillar hall: square pillars between a glowing grid floor and ceiling.
 * 4. Fractal temple: a Menger sponge, cell after cell of square halls pierced by smaller and
 *    smaller square passages, its carvings lit by the spectrum. (The slot was Megastructures,
 *    removed in app 1.62.)
 * 5. Canyon: rough walls in strata lit by the spectrum, a glowing river below, sky above.
 * 6. Sea stacks: low over water that mirrors a sunset, between columns of rock.
 * 7. Night city: down a street between towers whose windows flicker with the hi-hats.
 * 8. Orbital station: through square frames and along girders, over a planet.
 * 9. Asteroid field: between rough rocks whose cracks glow on the kick.
 * 10. Branching caves: a winding tunnel that opens into caverns, side tunnels branching off,
 *    crystal veins glowing with the spectrum.
 * 11. Abyss: along a channel between rough boulder walls on the sea floor, kelp swaying in
 *    the current, caustics on the rock pulsing with the bass, light shafts from the surface,
 *    drifting specks, rock arches to pass under, and schools of fish (JourneyFlock).
 * 12. Lava canyon: black basalt walls cracked with magma veins that glow on the bass, a river
 *    of lava below, embers rising, a smoky red sky.
 * 13. Coral reef: shallow bright water over coral mounds in the palette's colours, caustics,
 *    light shafts and schools of fish.
 * 14. Cyber highway: a dark void with streams of light running along the path on two
 *    cylinders round it, each lane lit by its own spectrum band, packets racing down them.
 *    Not marched at all: the ray is intersected with the cylinders in closed form.
 * 15. Aurora tundra: low over snow dunes between ice spires, under curtains of aurora that
 *    move with the spectrum.
 * 16. Bioluminescent deep: the black of the deep sea over a floor speckled with glowing life,
 *    jellyfish drifting (JourneyFlock's jelly style), marine snow.
 * 17. Synthwave road: a neon grid road under a striped sun and a wireframe skyline.
 * The floors of 16 and 17 are planes met in closed form: neither is marched.
 * 19. Twisted temple: the Fractal temple slowly revolving round the flight, each level of the
 *    sponge turned 45 degrees from the last, so the passages cross at angles.
 * 20. Breathing lattice: the sponge with its passages opened wide, a scaffold of thin beams
 *    that thins further with the bass.
 * 18. Tesseract: a corridor of glowing cube frames round the path, each holding a smaller cube
 *    turning one way and that a smaller one turning another, breathing on the beat, their
 *    edges lit by the spectrum. The camera threads every one.
 *
 * Landmarks (uMarks, placed by JourneyLandmarks on the CPU) appear in the open worlds: big
 * structures timed so the camera reaches them on a downbeat or a drop. The enclosed worlds
 * have none, and no landmark code is compiled into them.
 *
 * Every world carves a tube of radius 0.42 around the path, so the camera never meets a wall,
 * and draws neon where that tube cuts through it, lit by the spectrum (bass on the floor, treble
 * overhead). Light rings race along the tube on the beat. Distance-field march at half
 * resolution, 20 steps, normals in closed form (no extra evaluations of the scene).
 *
 * Cost: the path is read from a CPU-built texture (`uPath`, see DemoRenderer.uploadPath) rather
 * than worked out with three sines at every step; with `uPathOn` at 0 (the web previews) the
 * shader falls back to the same path in closed form.
 *
 * Wrap rule: the camera travels 3π per unit of `uPhase`, so one 0..2 wrap is 6π of z. Every
 * world repeats within that: the path (sin z/3), both sheets (period 2π/3 at scale 3), the
 * bubble cells (6π/20) and pillar cells (6π/12, cell hashes taken modulo the cell count), the
 * rings (sin 4z) and the colour drift (z / 6π).
 *
 * Precision: some TV GPUs (the Mali-400/470 family) have only 16-bit floats in fragment shaders,
 * which step every 0.016 at z = 20 and work sines out badly for large angles. So the scene is
 * built round the camera: the camera sits at z = 0, every position is relative to it and stays
 * within a few units, and the camera's place along the world comes in as phase offsets the CPU
 * works out in full precision (`uCam`, `uCell`, see DemoRenderer.setJourneyCamera). Every trig
 * argument is wrapped to ±π first, and the march's hit threshold is wider without highp.
 *
 * Over the song (uMood, worked out on the CPU, all "off" at 0): x shifts the colours round the
 * wheel at phrases, y fades each world between its two looks ([jSurfaceA] / [jSurfaceB]), z is
 * the current bar's energy (louder bars, thicker walls) and w banks the camera into the path's
 * turns. The path itself is rebuilt on the CPU with a sharp turn now and then (JourneyPath).
 *
 * Uniforms only these worlds read, all meaning "off" at 0: `uGate` (world units to the next
 * portal's gate, 0 when none), `uSeed` (x: hue shift, y: density, both per track), and with
 * `uPathOn` set, `uCam` (x: camera z / 6π, wrapped; y: 3·z and z: 4·z, each wrapped to 2π;
 * w: camera z within the world's cell) and `uCell` (the camera's cell, modulo the world's cell
 * count). With `uPathOn` at 0 (the web previews, which have highp) the shader works these out
 * from `uPhase` itself.
 */
internal const val JOURNEY_BODY_A = """
// The distance to what this pixel shows, / 20, for the fish (see FLOCK_FRAGMENT): 1 for open
// water. Only the worlds with fish (JourneyWorld.flock) write it.
#if VARIANT == 6 || VARIANT == 11 || VARIANT == 13 || VARIANT == 16
#define J_DEPTH
float gDepth;
#endif
const float JDEPTH = 20.0;     // JourneyFlock.DEPTH_RANGE
const float JZ = 18.8495559;   // 6π: one wrap of the flight, the period of everything below
const float TAU = 6.2831853;
const float JRANGE = 4.0;      // path coordinates are packed as -4..4 (JourneyPath.RANGE)
#ifdef GL_FRAGMENT_PRECISION_HIGH
const float JEPS = 0.002;
#else
const float JEPS = 0.007;
#endif
#if VARIANT == 2
const float JCELL = 0.9424778;  // 6π / 20
const float JCELLS = 20.0;
#elif VARIANT == 3 || VARIANT == 11
const float JCELL = 1.5707963;  // 6π / 12: pillars, kelp
const float JCELLS = 12.0;
#elif VARIANT == 6
const float JCELL = 3.1415927;  // 6π / 6: sea stacks
const float JCELLS = 6.0;
#elif VARIANT == 7 || VARIANT == 8
const float JCELL = 2.3561945;  // 6π / 8: city blocks, station frames
const float JCELLS = 8.0;
#elif VARIANT == 9
const float JCELL = 2.6927937;  // 6π / 7: asteroid cells
const float JCELLS = 7.0;
#elif VARIANT == 10
const float JCELL = 3.7699112;  // 6π / 5: side tunnels in the caves
const float JCELLS = 5.0;
#else
const float JCELL = 2.0943951;  // 2π / 3: the sheets' period, 9 to a wrap
const float JCELLS = 9.0;
#endif

// The camera's place along the world (see the class comment). Set once per pixel in shade().
vec4 jCam;
float jCell;
float jCamZ;   // absolute camera z, for the web previews' closed-form path only

// An angle wrapped to ±π, so a 16-bit sine never sees a large argument.
float wrapA(float a) { return a - TAU * floor(a / TAU + 0.5); }
vec3 wrapA(vec3 a) { return a - TAU * floor(a / TAU + 0.5); }

// The flight path at z relative to the camera.
vec2 jPath(float z) {
    if (uPathOn > 0.5) {
        // Two 16-bit values packed hi/lo into RGBA; linear filtering of hi and lo separately is
        // still exact, because the value is a linear function of them. Decoded in two small
        // parts: 16-bit floats on the Mali-400/470 stop at 2^15, so building the whole 0..65535
        // value first overflowed there and every point of the path came out as (-4, -4).
        vec4 s = texture2D(uPath, vec2(jCam.x + z / JZ, 0.5));
        vec2 hi = s.rg * (65280.0 / 65535.0 * 2.0 * JRANGE);
        vec2 lo = s.ba * (255.0 / 65535.0 * 2.0 * JRANGE);
        return hi + lo - JRANGE;
    }
    float a = z + jCamZ;
    return vec2(0.7 * sin(a / 3.0) + 0.2 * sin(a), 0.5 * cos(a / 3.0));
}

// Sines and cosines of the lattice at q (camera-relative), scale 3, wrapped.
vec3 jArg(vec3 q) { return wrapA(vec3(3.0 * q.x, 3.0 * q.y, 3.0 * q.z + jCam.y)); }

// q with z moved into the camera's cell frame, and the absolute cell index of a cell number.
vec3 jCellPos(vec3 q) { return vec3(q.x, q.y, q.z + jCam.w); }
float jCellZ(float c) { return mod(c + jCell, JCELLS); }

#if VARIANT == 4 || VARIANT == 19 || VARIANT == 20
// A Menger sponge filling each cell: three levels of square passages, each a third the size of
// the last. Worked in cell units (-1..1), so every level repeats with the cell and the wrap.
float jSponge(vec3 q) {
    vec3 cq = jCellPos(q);
    vec3 p = (cq - floor(cq / JCELL + 0.5) * JCELL) / (JCELL * 0.5);
    float d = -1.0;
    float s = 1.0;
#if VARIANT == 20
    // The breathing lattice: the passages widen with the bass and the kick.
    float hole = 1.15 + 0.3 * uLow + 0.2 * uKick;
#else
    float hole = 1.0;
#endif
#if VARIANT == 19
    // The halls turn slowly round the flight, a turn every few bars.
    float spin = wrapA(uTime * PI * 0.6);
    vec2 cs = vec2(cos(spin), sin(spin));
    p.xy = vec2(p.x * cs.x - p.y * cs.y, p.x * cs.y + p.y * cs.x);
#endif
    for (int m = 0; m < 3; m++) {
#if VARIANT == 19
        // The twisted temple: each level turned 45 degrees round the flight from the last.
        if (m > 0) p.xy = vec2(p.x - p.y, p.x + p.y) * 0.70710678;
#endif
        vec3 a = mod(p * s + 1.0, 2.0) - 1.0;
        s *= 3.0;
        vec3 r = abs(1.0 - 3.0 * abs(a));
        float c = (min(max(r.x, r.y), min(max(r.y, r.z), max(r.z, r.x))) - hole) / s;
        d = max(d, c);
    }
    return d * JCELL * 0.5;
}
#endif


#if VARIANT >= 21 && VARIANT <= 25
// ---- The tunnel worlds (21-25) ------------------------------------------------------------
// A wall at a radius round the path that changes with the angle round it and with z. Along z
// only through 3z plus the camera's phase (jCam.y) times whole numbers, so it repeats with the
// wrap. jOff is the point's offset from the path, set by the march (it already has it).
vec2 jOff;

// The gears' tick: one tooth further on each kick, eased as the kick fades.
float jTick() { return mod(uKicks, 12.0) - uKick * uKick; }

float jTun(vec3 q, vec2 off) {
    float r = length(off);
    float ang = fastAtan2(off.y, off.x);
    float zz = 3.0 * q.z + jCam.y;
#if VARIANT == 21
    // Ice: faceted walls twisting along the flight.
    float R = 0.86 + 0.07 * abs(sin(wrapA(6.0 * ang + zz))) + 0.05 * sin(wrapA(2.0 * zz + 3.0 * ang));
    return (R - r) * 0.7;
#elif VARIANT == 22
    // Organic: soft walls with ribs, swelling and squeezing like a heartbeat with the kick.
    float R = 0.8 + 0.1 * sin(wrapA(zz)) + 0.06 * sin(wrapA(5.0 * ang + 2.0 * zz))
            - 0.08 * smoothstep(0.7, 1.0, sin(wrapA(3.0 * zz))) + 0.08 * uLow - 0.1 * uKick;
    return (R - r) * 0.7;
#elif VARIANT == 23
    // Data stream: a cylinder of 24 lanes with gaps between them to see out through.
    float g = abs(fract(ang / TAU * 24.0) - 0.5);
    float gap = (g - 0.42) * TAU * 1.05 / 24.0;
    return max(1.05 - r, gap) * 0.8;
#elif VARIANT == 24
    // Crystal cave: walls of broad facets.
    float R = 0.92 + 0.12 * abs(sin(wrapA(7.0 * ang + zz))) + 0.08 * abs(sin(wrapA(5.0 * ang - 2.0 * zz + 1.0)));
    return (R - r) * 0.6;
#else
    // Clockwork: rings of gears round the flight, each turning a tooth per kick, the rings in
    // turn the other way, with gaps between them.
    float ring = floor(jCellPos(q).z / JCELL + 0.5);
    float dir = mod(jCellZ(ring), 2.0) < 0.5 ? 1.0 : -1.0;
    float tooth = abs(fract(ang / TAU * 12.0 + dir * jTick() / 12.0) - 0.5);
    float R = 0.98 - 0.11 * smoothstep(0.18, 0.26, tooth) + 0.3 * smoothstep(0.4, 0.46, abs(fract(zz / TAU) - 0.5));
    return (R - r) * 0.6;
#endif
}
#endif

// The world's distance alone, before the tube is carved out of it.
float jWorld(vec3 q, float th) {
#if VARIANT == 1
    vec3 c = cos(jArg(q));
    // |grad| reaches 3·√3, so 0.19 keeps the step from overshooting.
    return (abs(c.x + c.y + c.z) - th) * 0.19;
#elif VARIANT == 2
    const float C = JCELL;
    vec3 cq = jCellPos(q);
    vec3 cell = floor(cq / C + 0.5);
    vec3 r3 = cq - cell * C;
    float h = hash(cell.xy + jCellZ(cell.z) * vec2(7.31, 3.17));
    float r = (0.13 + 0.12 * h) * (1.0 + 0.25 * uLow + 0.35 * uKick + 0.3 * uSeed.y);
    // Capped: near a cell's edge a neighbour's sphere can be closer than this one's.
    return min(length(r3) - r, 0.25);
#elif VARIANT == 3
    const float C = JCELL;
    vec2 cq = jCellPos(q).xz;
    vec2 cell = floor(cq / C + 0.5);
    vec2 r2 = cq - cell * C;
    float h = hash(vec2(cell.x, jCellZ(cell.y)) + 4.7);
    float b = (0.13 + 0.08 * h) * (1.0 + 0.2 * uKick + 0.3 * uSeed.y);
    vec2 dd = abs(r2) - b;
    float pillar = min(length(max(dd, 0.0)) + min(max(dd.x, dd.y), 0.0), 0.5);
    float slab = min(q.y + 1.05, 1.05 - q.y);
    return min(pillar, slab);
#elif VARIANT == 4 || VARIANT == 19 || VARIANT == 20
    return jSponge(q);
#elif VARIANT >= 21 && VARIANT <= 25
    return jTun(q, jOff);
#else
    vec3 a = jArg(q);
    vec3 s = sin(a);
    vec3 c = cos(a);
    // |grad| peaks near 1.5 and the scale triples it, so 0.24 keeps the step from overshooting.
    return (abs(dot(s, c.yzx)) - th) * 0.24;
#endif
}

// The world's surface normal at a hit, in closed form.
vec3 jNormal(vec3 q, float th) {
#if VARIANT == 1
    vec3 a = jArg(q);
    vec3 c = cos(a);
    return normalize(-sin(a) * sign(c.x + c.y + c.z));
#elif VARIANT == 2
    const float C = JCELL;
    vec3 cq = jCellPos(q);
    return normalize(cq - floor(cq / C + 0.5) * C);
#elif VARIANT == 3
    const float C = JCELL;
    if (abs(q.y) > 0.98) return vec3(0.0, -sign(q.y), 0.0);
    vec2 cq = jCellPos(q).xz;
    vec2 r2 = cq - floor(cq / C + 0.5) * C;
    return abs(r2.x) > abs(r2.y) ? vec3(sign(r2.x), 0.0, 0.0) : vec3(0.0, 0.0, sign(r2.y));
#elif VARIANT == 4 || VARIANT == 19 || VARIANT == 20
    // The sponge's faces are all square: the gradient, worked out once per pixel.
    const vec2 k = vec2(1.0, -1.0);
    const float h = 0.01;
    return normalize(k.xyy * jSponge(q + k.xyy * h) + k.yyx * jSponge(q + k.yyx * h)
                   + k.yxy * jSponge(q + k.yxy * h) + k.xxx * jSponge(q + k.xxx * h));
#elif VARIANT >= 21 && VARIANT <= 25
    const vec2 k = vec2(1.0, -1.0);
    const float h = 0.01;
    return normalize(k.xyy * jTun(q + k.xyy * h, jOff + k.xy * h) + k.yyx * jTun(q + k.yyx * h, jOff + k.yy * h)
                   + k.yxy * jTun(q + k.yxy * h, jOff + k.yx * h) + k.xxx * jTun(q + k.xxx * h, jOff + k.xx * h));
#else
    vec3 a = jArg(q);
    vec3 s = sin(a);
    vec3 c = cos(a);
    float g = dot(s, c.yzx);
    return normalize(vec3(c.x * c.y - s.z * s.x, c.y * c.z - s.x * s.y, c.z * c.x - s.y * s.z) * sign(g));
#endif
}

// The world's own colour at a hit: how its surfaces take the light.
// The world's first look.
vec3 jSurfaceA(vec3 q, vec3 n, vec3 rd, float hue) {
    float facing = clamp(dot(n, -rd), 0.0, 1.0);
#if VARIANT == 1
    // Schwarz chambers: dark tiled walls, the tile seams glowing on the beat, each room
    // (one lattice cell) its own colour.
    vec3 cq = jCellPos(q);
    vec3 cellId = floor(cq / JCELL);
    float room = hash(cellId.xy + jCellZ(cellId.z) * vec2(5.3, 1.7));
    vec3 tq = abs(fract(cq * (6.0 / PI)) - 0.5);
    float seam = exp(-min(min(tq.x, tq.y), tq.z) * 30.0);
    vec3 col = colorAt(hue * 2.0 + room * 0.4) * (0.03 + 0.35 * facing * facing);
    col += colorAt(hue * 2.0 + room * 0.4 + 0.5) * seam * (0.25 + 0.9 * uBeat) * facing;
    col += colorAt(0.1) * pow(1.0 - facing, 3.0) * 0.25;
    return col;
#elif VARIANT == 2
    // Bubble flight: glass, dark through the middle and bright at the rim, each its own hue.
    const float C = JCELL;
    vec3 cell = floor(jCellPos(q) / C + 0.5);
    float h = hash(cell.yx + jCellZ(cell.z) * vec2(3.9, 8.3));
    float rim = pow(1.0 - facing, 2.5);
    vec3 col = colorAt(hue * 2.0 + h * 0.6) * (0.04 + 0.9 * rim);
    col += vec3(1.0) * pow(facing, 40.0) * 0.6;
    return col;
#elif VARIANT == 3
    // Pillar hall: a glowing grid on floor and ceiling, pillars banded with light.
    const float C = JCELL;
    if (abs(q.y) > 0.98) {
        vec2 g = abs(fract(jCellPos(q).xz / C * 2.0) - 0.5);
        float line = exp(-min(g.x, g.y) * 40.0);
        float lvl = band(floor(clamp(abs(q.x) * 20.0, 0.0, 63.0)));
        return colorAt(hue * 2.0 + 0.3) * (0.03 + line * (0.5 + 1.2 * lvl));
    }
    float bands = smoothstep(0.85, 1.0, sin(wrapA(q.y * 6.0 + uTime * PI * 8.0)));
    vec3 col = colorAt(hue * 2.0) * (0.02 + 0.22 * facing * facing);
    col += colorAt(hue * 2.0 + 0.5) * bands * (0.3 + 0.8 * uBeat);
    return col;
#elif VARIANT == 4 || VARIANT == 19 || VARIANT == 20
    // Fractal temple, stone: pale stone lit by the facing, the passage edges carved with light
    // from the spectrum, a level of the sponge to each band.
    vec3 cq = jCellPos(q);
    vec3 p = (cq - floor(cq / JCELL + 0.5) * JCELL) / (JCELL * 0.5);
    vec3 a = abs(mod(p * 9.0 + 1.0, 2.0) - 1.0);
    float groove = exp(-min(min(abs(a.x - 0.333), abs(a.y - 0.333)), abs(a.z - 0.333)) * 30.0);
    float lvl = band(floor(fract(dot(floor(cq / JCELL), vec3(0.37, 0.21, 0.13))) * 48.0) + 4.0);
    vec3 col = mix(vec3(0.5, 0.45, 0.38), colorAt(hue * 2.0 + 0.1), 0.35) * (0.04 + 0.35 * facing * facing);
    return col + colorAt(hue * 2.0 + 0.55) * groove * (0.1 + 1.0 * lvl + 0.4 * uBeat);
#elif VARIANT >= 21 && VARIANT <= 25
    float ang = fastAtan2(jOff.y, jOff.x);
    float zz = 3.0 * q.z + jCam.y;
#if VARIANT == 21
    // Ice: glassy blue, cracks racing out along the walls from the camera on each kick and
    // freezing over again as it fades.
    vec3 ice = mix(vec3(0.5, 0.8, 1.0), colorAt(hue * 2.0 + 0.55), 0.3);
    vec3 col = ice * (0.05 + 0.25 * facing) + ice * pow(1.0 - facing, 3.0) * 0.6;
    float crack = exp(-abs(sin(wrapA(9.0 * ang + 2.0 * sin(wrapA(zz)))) * sin(wrapA(2.0 * zz + 3.0 * ang))) * 22.0);
    float front = smoothstep(0.0, 0.8, (1.0 - uKick) * 7.0 - q.z);
    return col + mix(vec3(0.8, 0.95, 1.0), colorAt(hue * 2.0 + 0.5), 0.4) * crack * (0.08 + 1.6 * uKick * front);
#elif VARIANT == 22
    // Organic: wet, flesh-toned, its veins glowing with the bass.
    vec3 flesh = mix(vec3(0.55, 0.08, 0.12), colorAt(hue * 2.0 + 0.05), 0.35);
    float vein = exp(-abs(sin(wrapA(4.0 * ang + 1.5 * sin(wrapA(zz))))) * 12.0);
    vec3 col = flesh * (0.07 + 0.5 * facing * facing) + vec3(1.0, 0.9, 0.9) * pow(facing, 30.0) * 0.35;
    return col + colorAt(hue * 2.0 + 0.5) * vein * (0.15 + 1.2 * uLow + 0.5 * uKick);
#elif VARIANT == 23
    // Data stream: each lane a band of the spectrum, blocks of light streaming past in it,
    // more of them the louder its band.
    float li = floor(ang / TAU * 24.0 + 12.0);
    float lvl = band(floor(mod(li * 2.7, 48.0)) + 4.0);
    float row = floor(jCellPos(q).z / JCELL * 6.0 + uTime * 8.0);
    float h = hash(vec2(li, mod(row + jCell * 6.0, JCELLS * 6.0)));
    float lit = step(1.0 - (0.15 + 0.7 * lvl), h);
    vec3 col = colorAt(hue * 2.0 + 0.6) * (0.02 + 0.08 * facing);
    return col + colorAt(hue * 2.0 + li / 24.0) * lit * (0.3 + 1.1 * lvl + 0.4 * uKick);
#elif VARIANT == 24
    // Crystal cave: each facet catching the light, lit from within by the hi-hats.
    float facet = floor(7.0 * ang / TAU + 3.5) + floor(zz / TAU * 2.0) * 7.0;
    float hf = hash(vec2(facet, 3.0));
    float lvl = band(36.0 + floor(hf * 24.0));
    vec3 c = colorAt(hue * 2.0 + hf * 0.5);
    vec3 col = c * (0.05 + 0.3 * facing * facing) + vec3(1.0) * pow(facing, 24.0) * 0.3;
    return col + c * pow(1.0 - facing, 2.0) * (0.2 + 1.0 * lvl + 0.6 * uHigh);
#else
    // Clockwork: brass, polished where it faces the light, the tooth tips lit on the kick.
    vec3 brass = mix(vec3(0.62, 0.45, 0.2), colorAt(hue * 2.0 + 0.1), 0.25);
    float tip = smoothstep(0.9, 1.0, length(jOff));
    vec3 col = brass * (0.05 + 0.6 * pow(facing, 3.0)) + vec3(1.0, 0.9, 0.7) * pow(facing, 40.0) * 0.4;
    return col + colorAt(hue * 2.0 + 0.5) * tip * (0.1 + 0.9 * uKick + 0.3 * uBeat);
#endif
#else
    // Gyroid flight: coloured by depth and by which side of the sheet it is.
    vec3 a = jArg(q);
    vec3 s = sin(a);
    vec3 c = cos(a);
    float g = dot(s, c.yzx);
    vec3 col = colorAt(hue * 2.0 + 0.25 * sign(g)) * (0.04 + 0.5 * facing * facing);
    col += colorAt(0.1) * pow(1.0 - facing, 4.0) * 0.25;
    return col;
#endif
}

// The world's second look, which the renderer fades to and from over the song (uMood.y).
vec3 jSurfaceB(vec3 q, vec3 n, vec3 rd, float hue) {
    float facing = clamp(dot(n, -rd), 0.0, 1.0);
#if VARIANT == 1
    // Schwarz chambers, lit rooms: no seams, bands of light running down each room, coloured
    // by the spectrum.
    vec3 cq = jCellPos(q);
    float room = hash(floor(cq.xy / JCELL) + jCellZ(floor(cq.z / JCELL)) * vec2(5.3, 1.7));
    float stripe = smoothstep(0.35, 0.5, abs(fract(cq.z * 2.0 + room) - 0.5));
    float lvl = band(floor(room * 63.0));
    vec3 col = colorAt(hue * 2.0 + room * 0.4 + 0.25) * (0.03 + 0.16 * facing * facing);
    col += colorAt(hue * 2.0 + room * 0.4 + 0.6) * stripe * (0.1 + 0.8 * lvl) * facing;
    return col;
#elif VARIANT == 2
    // Bubble flight, neon: solid glowing cores, each bubble lit by its own band of the spectrum.
    const float C = JCELL;
    vec3 cell = floor(jCellPos(q) / C + 0.5);
    float h = hash(cell.yx + jCellZ(cell.z) * vec2(3.9, 8.3));
    float lvl = band(floor(h * 63.0));
    vec3 col = colorAt(hue * 2.0 + h * 0.6 + 0.3) * (0.15 + 0.8 * facing) * (0.35 + 1.3 * lvl);
    col += vec3(1.0) * pow(1.0 - facing, 6.0) * 0.4;
    return col;
#elif VARIANT == 3
    // Pillar hall, outlined: dark pillars with neon on their edges, the floor a solid glow
    // that pulses with the bass.
    const float C = JCELL;
    if (abs(q.y) > 0.98) {
        vec2 g = abs(fract(jCellPos(q).xz / C) - 0.5);
        return colorAt(hue * 2.0 + 0.8) * (0.04 + (0.1 + 0.5 * uLow) * smoothstep(0.2, 0.5, max(g.x, g.y)));
    }
    vec2 cq = jCellPos(q).xz;
    vec2 r2 = abs(cq - floor(cq / C + 0.5) * C);
    float edge = exp(-abs(r2.x - r2.y) * 60.0);
    vec3 col = colorAt(hue * 2.0 + 0.4) * 0.03;
    col += colorAt(hue * 2.0 + 0.9) * edge * (0.4 + 1.0 * uBeat);
    return col;
#elif VARIANT == 4 || VARIANT == 19 || VARIANT == 20
    // Fractal temple, neon: dark halls outlined in light where the faces meet.
    float rim = pow(1.0 - facing, 4.0);
    vec3 cq = jCellPos(q);
    float glow = 0.5 + 0.5 * sin(wrapA(3.0 * q.z + jCam.y - uTime * PI * 8.0));
    vec3 col = colorAt(hue * 2.0 + 0.7) * (0.02 + 0.08 * facing);
    return col + colorAt(hue * 2.0 + 0.2 + rim * 0.3) * rim * (0.4 + 0.9 * uBeat) * (0.5 + 0.5 * glow);
#elif VARIANT >= 21 && VARIANT <= 25
    float ang = fastAtan2(jOff.y, jOff.x);
    float zz = 3.0 * q.z + jCam.y;
    float rim = pow(1.0 - facing, 3.0);
#if VARIANT == 21
    // Frost: white, glittering with the treble.
    float glit = step(0.985, hash(floor(vec2(ang * 30.0, zz * 6.0)))) * (0.3 + 0.9 * uHigh);
    return vec3(0.7, 0.8, 0.9) * (0.06 + 0.3 * facing) + colorAt(hue * 2.0 + 0.6) * rim * 0.4 + vec3(1.0) * glit;
#elif VARIANT == 22
    // Bioluminescent: dark, its pores glowing and pulsing with the kick.
    vec2 g = vec2(ang * 6.0, zz * 2.0);
    float pore = smoothstep(0.3, 0.0, length(fract(g) - 0.5)) * step(0.5, hash(floor(g)));
    return colorAt(hue * 2.0 + 0.7) * 0.03 + colorAt(hue * 2.0 + 0.4) * pore * (0.3 + 1.2 * uKick) + rim * colorAt(hue * 2.0 + 0.1) * 0.3;
#elif VARIANT == 23
    // Scanlines: the lanes dark, a bright line racing round them on the beat.
    float scan = exp(-abs(fract(zz / TAU * 4.0 - uTime * 4.0) - 0.5) * 30.0);
    return colorAt(hue * 2.0 + 0.3) * (0.03 + scan * (0.4 + 0.8 * uBeat)) + colorAt(hue * 2.0) * rim * 0.3;
#elif VARIANT == 24
    // Dark crystal with glowing facet edges.
    float e = exp(-min(abs(fract(7.0 * ang / TAU) - 0.5), abs(fract(zz / TAU * 2.0) - 0.5)) * 30.0);
    return colorAt(hue * 2.0 + 0.6) * 0.03 + colorAt(hue * 2.0 + 0.2) * (e * (0.4 + 1.0 * uHigh) + rim * 0.3);
#else
    // Dark steel, the gear teeth outlined in neon.
    float edge = exp(-abs(length(jOff) - 0.9) * 40.0);
    return vec3(0.03, 0.035, 0.04) * (0.5 + facing) + colorAt(hue * 2.0 + 0.3) * edge * (0.5 + 1.0 * uKick);
#endif
#else
    // Gyroid flight, contours: a dark sheet drawn over with glowing contour lines.
    vec3 a = jArg(q);
    vec3 s = sin(a);
    vec3 c = cos(a);
    float g = dot(s.yzx, c.zxy);
    float line = exp(-abs(fract(g * 3.0) - 0.5) * 18.0);
    vec3 col = colorAt(hue * 2.0 + 0.5) * (0.03 + 0.15 * facing);
    col += colorAt(hue * 2.0 + g * 0.3) * line * (0.35 + 0.8 * uBeat) * facing;
    return col;
#endif
}

vec3 jSurface(vec3 q, vec3 n, vec3 rd, float hue) {
    // The look in between is only worked out while the renderer is fading between the two.
    if (uMood.y < 0.01) return jSurfaceA(q, n, rd, hue);
    if (uMood.y > 0.99) return jSurfaceB(q, n, rd, hue);
    return mix(jSurfaceA(q, n, rd, hue), jSurfaceB(q, n, rd, hue), uMood.y);
}

// Landmarks: up to four objects the CPU places along the route (JourneyLandmarks), from small
// orbs, crystals and cubes just off the path to giant rings, tunnels and hollow spheres the
// camera flies through. Two vec4 each in uMarks: a = (z ahead of the camera, type, size,
// spin or half length), b = (centre x, centre y, wall thickness, hue). Type -1 is an empty
// slot. `off` is the point's offset from the path at its own z, for the shapes that follow it.
float jBox(vec3 r, vec3 h) {
    vec3 d = abs(r) - h;
    return length(max(d, 0.0)) + min(max(d.x, max(d.y, d.z)), 0.0);
}

float jMarkD(vec3 q, vec2 off, vec4 a, vec4 b) {
    vec3 r = vec3(q.xy - b.xy, q.z - a.x);
    float ty = a.y;
    if (ty < 0.5) return length(r) - a.z;                                       // orb
    vec2 cs = vec2(cos(wrapA(a.w)), sin(wrapA(a.w)));
    vec3 rr = vec3(r.x * cs.x - r.y * cs.y, r.x * cs.y + r.y * cs.x, r.z);
    if (ty < 1.5) return (abs(rr.x) + abs(rr.y) + abs(rr.z) - a.z) * 0.577;     // crystal
    if (ty < 2.5) return jBox(rr, vec3(a.z));                                   // cube
    if (ty < 3.5) return length(vec2(length(r.xy) - a.z, r.z)) - b.z;           // ring
    if (ty < 4.5) {                                                              // tunnel
        float shell = abs(length(off) - a.z - b.z) - b.z;
        return max(shell, abs(r.z) - a.w);
    }
    if (ty < 5.5) return jBox(rr, vec3(a.z * 0.35, a.z * 2.2, a.z * 0.35));      // monolith
    if (ty < 6.5) return max(abs(length(r) - a.z) - b.z, 0.75 - length(off));    // hollow sphere
    // Arch: two posts and a lintel, the path running between the posts.
    float post = jBox(vec3(abs(rr.x) - a.z, rr.y, rr.z), vec3(0.22, a.z * 1.2, 0.22));
    float lintel = jBox(vec3(rr.x, rr.y - a.z * 1.2, rr.z), vec3(a.z + 0.22, 0.22, 0.22));
    return min(post, lintel);
}

// Which landmarks this pixel's ray can reach at all, worked out once before the march: the CPU
// projects each one's bounding sphere to a circle on screen (uMarkScr: centre, radius; radius 0
// for an empty slot or one behind the camera), so the test per pixel is a single distance. Most
// rays reach no landmark, and the march then costs almost nothing extra; on the Mali-470
// checking every one at every step halved the frame rate. The web previews, without the
// circles, test every landmark. (Copying out the nearest few for the march instead was tried:
// the extra values per pixel made every world three times slower on the Mali-470.)
float jReach[4];
float jAny;
float jFar;    // past this distance along z no landmark this pixel can reach remains

// The radius of a sphere round each shape (JourneyLandmarks.bound on the CPU): orb, crystal
// and cube, ring and hollow sphere, monolith, arch.
float jBound(vec4 a, vec4 b) {
    float ty = a.y;
    float k = ty < 2.5 ? 1.74 : (ty < 3.5 || (ty > 5.5 && ty < 6.5)) ? 1.0 : ty < 5.5 ? 2.3 : 1.7;
    return a.z * k + b.z + 0.45;
}

void jCull(vec2 sp) {
    jAny = 0.0;
    jFar = 0.0;
    for (int i = 0; i < 4; i++) {
        vec4 c = uMarkScr[i];
        vec4 a = uMarks[2 * i];
        float on = uPathOn > 0.5 ? (length(sp - c.xy) < c.z ? 1.0 : 0.0) : (a.y >= 0.0 ? 1.0 : 0.0);
        jReach[i] = on;
        jAny += on;
        float ext = (a.y > 3.5 && a.y < 4.5) ? a.w : jBound(a, uMarks[2 * i + 1]);
        if (on > 0.5) jFar = max(jFar, a.x + ext);
    }
}

// The nearest landmark's distance, and which slot it is in. Only the ones jCull kept.
float jMarks(vec3 q, vec2 off, out float idx) {
    float d = 9.0;
    idx = -1.0;
    for (int i = 0; i < 4; i++) {
        if (jReach[i] < 0.5) continue;
        vec4 a = uMarks[2 * i];
        vec4 b = uMarks[2 * i + 1];
        // Away from it, the gap to its bounds is a safe step and the shape need not be worked
        // out: the gap in z, and (all but tunnels, which follow the path) the gap to a sphere
        // round it, so a ray passing a structure far off to the side is not slowed by it.
        bool tunnel = a.y > 3.5 && a.y < 4.5;
        float ext = tunnel ? a.w + 0.1 : a.z * 1.3 + b.z + 0.3;
        float gap = abs(q.z - a.x) - ext;
        if (!tunnel) gap = max(gap, length(vec3(q.xy - b.xy, q.z - a.x)) - jBound(a, b));
        // Close to the bounds the shape itself is worked out, so a ray grazing them never runs
        // out of steps there and gets taken for a hit.
        float m = gap > 0.25 ? gap : jMarkD(q, off, a, b);
        if (m < d) {
            d = m;
            idx = float(i);
        }
    }
    return d;
}

vec4 jMarkA(float idx) {
    vec4 a = vec4(0.0);
    for (int i = 0; i < 4; i++) if (float(i) == idx) a = uMarks[2 * i];
    return a;
}

vec4 jMarkB(float idx) {
    vec4 b = vec4(0.0);
    for (int i = 0; i < 4; i++) if (float(i) == idx) b = uMarks[2 * i + 1];
    return b;
}

// A landmark's look at a hit: small ones lit from within by their own band of the spectrum,
// rings blazing, the big structures dark with glowing rims and light racing round them.
vec3 jMarkLook(vec3 q, vec3 n, vec3 rd, vec4 a, vec4 b, float hue);

vec3 jMarkShade(vec3 q, vec2 off, vec3 rd, float idx, float hue) {
    vec4 a = jMarkA(idx);
    vec4 b = jMarkB(idx);
    const vec2 k = vec2(1.0, -1.0);
    const float h = 0.02;
    vec3 n = normalize(k.xyy * jMarkD(q + k.xyy * h, off + k.xy * h, a, b)
                     + k.yyx * jMarkD(q + k.yyx * h, off + k.yy * h, a, b)
                     + k.yxy * jMarkD(q + k.yxy * h, off + k.yx * h, a, b)
                     + k.xxx * jMarkD(q + k.xxx * h, off + k.xx * h, a, b));
    return jMarkLook(q, n, rd, a, b, hue);
}

vec3 jMarkLook(vec3 q, vec3 n, vec3 rd, vec4 a, vec4 b, float hue) {
    float facing = clamp(abs(dot(n, rd)), 0.0, 1.0);
    float lvl = band(floor(fract(b.w) * 63.0));
    vec3 c = colorAt(hue * 2.0 + b.w);
    if (a.y < 2.5) {
        vec3 col = c * (0.12 + 0.5 * facing) * (0.5 + 1.1 * lvl + 0.6 * uKick);
        col += c * pow(1.0 - facing, 2.0) * (0.4 + 0.8 * lvl);
        return col + vec3(1.0) * pow(facing, 24.0) * 0.35;
    }
    if (a.y < 3.5) return c * (0.6 + 1.4 * lvl + 0.9 * uKick) + vec3(0.3) * pow(facing, 8.0);
    // Light racing round the big structures, a quarter-period apart, brightest on the beat.
    float race = pow(0.5 + 0.5 * sin(wrapA(q.z * 4.0 + jCam.z - uTime * PI * 16.0)), 16.0);
    vec3 col = c * (0.03 + 0.22 * facing * facing);
    col += c * pow(1.0 - facing, 3.0) * (0.35 + 1.0 * lvl);
    col += colorAt(hue * 2.0 + b.w + 0.5) * race * (0.25 + 0.8 * uBeat + 0.6 * uKick);
    return col;
}

// The director's lens: 1 normal, below it wider; 0 (unset, the web previews) is normal.
float jLens() { return uLens > 0.0 ? uLens : 1.0; }

// The camera's place, frame and this pixel's ray. On the TV the CPU works the camera out in
// full precision and smooths it (JourneyCamera: position on the path, heading eased toward a
// point further ahead, roll and bank folded into rt/up), so it never shakes with 16-bit noise
// or the path's small wiggles. The web previews work it out here.
void jCamera(vec2 p, out vec3 ro, out vec3 fw, out vec3 rt, out vec3 up, out vec2 sp, out vec3 rd) {
    if (uPathOn > 0.5) {
        jCam = uCam;
        jCell = uCell;
        jCamZ = 0.0;
        ro = uCamRo;
        fw = uCamFw;
        rt = uCamRt;
        up = uCamUp;
        // Mirror bars: the picture folded left onto right, or into four.
        vec2 q = p;
        if (uSky.w > 0.5) q.x = abs(q.x);
        if (uSky.w > 1.5) q.y = abs(q.y);
        sp = q;
        rd = normalize(fw * 1.3 * jLens() + rt * q.x + up * q.y);
        return;
    } else {
        // The web previews: highp, so the camera's place can be worked out here.
        jCamZ = uPhase * 3.0 * PI;
        jCam = vec4(fract(jCamZ / JZ), mod(3.0 * jCamZ, TAU), mod(4.0 * jCamZ, TAU), mod(jCamZ, JCELL));
        jCell = mod(floor(jCamZ / JCELL), JCELLS);
    }
    // The camera sits at z = 0; everything below is relative to it.
    ro = vec3(jPath(0.0), 0.0);
    fw = normalize(vec3(jPath(1.2), 1.2) - ro);
    rt = normalize(cross(vec3(0.0, 1.0, 0.0), fw));
    up = cross(fw, rt);
#if VARIANT == 3 || VARIANT == 5 || VARIANT == 6 || VARIANT == 7 || VARIANT == 11 || VARIANT == 12 || VARIANT == 13 || VARIANT == 15 || VARIANT == 16 || VARIANT == 17 || VARIANT == 26 || VARIANT == 27 || VARIANT == 28 || VARIANT == 29
    // A hall, the sky, a canyon, the sea, a city or the sea floor has a floor: bank gently, never roll over.
    sp = rot(0.25 * sin(wrapA(uSpin * PI)) + 0.08 * sin(wrapA(uTime * PI * 2.0)) + uMood.w) * p;
#else
    sp = rot(wrapA(uSpin * PI + 0.08 * sin(wrapA(uTime * PI * 2.0))) + uMood.w) * p;
#endif
    rd = normalize(fw * 1.3 + rt * sp.x + up * sp.y);
}

// The portal gate: a ring round the path, uGate units ahead, drawn where nothing nearer hides
// it. It sweeps out to the screen edge as the camera reaches it.
vec3 jGate(vec3 col, vec2 sp, vec3 ro, vec3 fw, vec3 rt, vec3 up, bool hit, float t) {
    if (uGate <= 0.0) return col;
    float gz = uGate;
    vec3 rel = vec3(jPath(gz), gz) - ro;
    float depth = max(dot(rel, fw), 0.05);
    vec2 centre = vec2(dot(rel, rt), dot(rel, up)) * 1.3 * jLens() / depth;
    float radius = 0.5 * 1.3 * jLens() / depth;
    float ringD = abs(length(sp - centre) - radius);
    float seen = (hit && t < depth) ? 0.0 : 1.0;
    // The same colour as the iris rim that follows it, so gate and portal read as one ring.
    vec3 gc = vivid(uC0);
    col += gc * seen * (exp(-ringD * 120.0) * 1.4 + exp(-ringD * 14.0) * 0.25) * (0.7 + 0.8 * uBeat);
    col += gc * seen * smoothstep(radius, 0.0, length(sp - centre)) * 0.08;
    return col;
}

// A billboard beside the path (JourneyBoard): the album cover in a glowing frame, or the
// track's title in light. Closed form, like the rings: where the ray crosses the board's plane.
vec3 jBoard(vec3 col, vec3 ro, vec3 rd, float tHit, float hue, float far) {
    if (uBoard.w <= 0.0 || rd.z < 0.05) return col;
    float t = uBoard.x / rd.z;
    if (t > tHit) return col;
    vec2 q = ro.xy + rd.xy * t - uBoard.yz;
    bool title = uBoard2.x > 0.5;
    vec2 hb = vec2(uBoard.w, title ? uBoard.w / max(uTitleAspect, 1.0) : uBoard.w);
    float fog = 1.0 - smoothstep(far * 0.45, far * 0.95, t);
    float edge = max(abs(q.x) - hb.x, abs(q.y) - hb.y);
    vec3 glow = colorAt(hue * 2.0 + 0.3) * (0.6 + 0.8 * uKick);
    if (edge > 0.0) return col + glow * exp(-edge * 25.0) * 0.5 * fog * (title ? 0.4 : 1.0);
    vec2 uv = q / hb * 0.5 + 0.5;
    if (title) {
        float a = titleAt(uv);
        return mix(col, vec3(1.0) * (0.9 + 0.4 * uKick), a * fog) + glow * a * 0.3 * fog;
    }
    vec3 c = texture2D(uTex, vec2(uv.x, 1.0 - uv.y)).rgb * (0.85 + 0.35 * uKick);
    c += glow * exp(edge * 40.0) * 0.6;
    return mix(col, c, fog);
}

// The open worlds' time of day (JourneyLook.sky): dawn, dusk or storm light over the picture.
vec3 jSkyGrade(vec3 col, vec2 p) {
    if (uSky.x < 0.5) return col;
    float top = smoothstep(-0.3, 1.0, p.y);
    if (uSky.x < 1.5) return col * vec3(1.05, 0.9, 0.95) + vec3(0.3, 0.14, 0.2) * top * 0.25;
    if (uSky.x < 2.5) return col * vec3(1.12, 0.8, 0.66) + vec3(0.35, 0.08, 0.25) * top * 0.3;
    float l = dot(col, vec3(0.3, 0.55, 0.15));
    return mix(col, vec3(l) * vec3(0.7, 0.85, 1.0), 0.55) * 0.8 + vec3(0.6, 0.7, 0.9) * uDrop.x * 0.2;
}

// Weather over the open worlds: rain streaks, snow, or fog with distance. The fall comes from
// uFall, phases worked out on the CPU, since 16-bit floats cannot keep a time that grows.
vec3 jWeather(vec3 col, vec2 p, float tHit, float hue, float far) {
    float w = uSky.y;
    if (w < 0.5) return col;
    if (w < 1.5) {
        col *= 0.88;
        for (int k = 0; k < 2; k++) {
            float fk = float(k);
            vec2 g = vec2((p.x + p.y * 0.15) * (26.0 + fk * 17.0), p.y * (2.0 + fk) + uFall.x * (4.0 + 2.0 * fk));
            vec2 id = floor(g);
            vec2 f = fract(g);
            float h = hash(id + vec2(fk * 7.0, 3.0));
            float x = 0.2 + 0.6 * fract(h * 13.0);
            float y = fract(h * 7.0) * 0.5;
            float s = step(0.72, h) * smoothstep(0.09, 0.0, abs(f.x - x)) * step(y, f.y) * step(f.y, y + 0.45);
            col += vec3(0.55, 0.65, 0.8) * s * (0.35 - 0.12 * fk);
        }
        return col;
    }
    if (w < 2.5) {
        for (int k = 0; k < 2; k++) {
            float fk = float(k);
            vec2 g = vec2(p.x * (7.0 + fk * 5.0), p.y * (5.0 + fk * 4.0) + uFall.y * (2.0 + fk * 2.0));
            vec2 id = floor(g);
            vec2 f = fract(g);
            float h = hash(id + vec2(fk * 5.0, 1.0));
            vec2 c = vec2(0.25 + 0.5 * fract(h * 11.0) + 0.15 * sin(uFall.y * 2.0 * PI * (1.0 + fk) + h * 6.0), 0.25 + 0.5 * fract(h * 17.0));
            float r = 0.07 - 0.02 * fk;
            col += vec3(0.9, 0.93, 1.0) * step(0.45, h) * smoothstep(r, r * 0.3, length(f - c)) * (0.55 - 0.2 * fk);
        }
        return col;
    }
    vec3 haze = colorAt(hue * 2.0 + 0.6) * 0.1 + vec3(0.08);
    return mix(col, haze, smoothstep(0.0, far * 0.6, tHit) * 0.65);
}

// A drop moment (JourneyDirector): a beat in negative, a white flash and a shockwave going out.
vec3 jDrop(vec3 col, vec2 p) {
    if (uDrop.z > 0.0) col = mix(col, vec3(1.0) - min(col, vec3(1.0)), uDrop.z * 0.8);
    if (uDrop.y > 0.0 && uDrop.y < 1.0) col += vivid(uC0) * exp(-abs(length(p) - uDrop.y * 2.2) * 16.0) * (1.0 - uDrop.y) * 1.6;
    return col + vec3(uDrop.x * 0.6);
}

// The track's style over whatever world it is in (JourneyLook.style): as made; a duotone, the
// picture's brightness mapped from deep shadow in one palette colour up to another, so every
// world wears the album's colours; or night, darker and harder, with only the brightest light
// left, and that pushed brighter.
vec3 jStyle(vec3 col, float hue) {
    if (uStyle < 0.5) return col;
    float l = dot(col, vec3(0.3, 0.55, 0.15));
    if (uStyle < 1.5) {
        vec3 lo = colorAt(hue * 2.0 + 0.6) * 0.04;
        vec3 mid = colorAt(hue * 2.0 + 0.1);
        return mix(mix(lo, mid * 0.6, smoothstep(0.0, 0.35, l)), vec3(1.0, 0.95, 0.9), smoothstep(0.45, 1.2, l));
    }
    return col * col * (1.4 + 1.2 * l) + colorAt(hue * 2.0 + 0.7) * 0.004;
}

// Rings to fly through (JourneyHoops on the CPU, every world): where the ray crosses each
// ring's plane, a glowing band and a halo, nearer than whatever the world shows there. Closed
// form, so they cost a few operations a pixel and nothing in the march. Pulsing with the beat
// and the kick, each lit by its own band of the spectrum.
vec3 jHoops(vec3 col, vec3 ro, vec3 rd, float tHit, float hue, float far) {
    for (int i = 0; i < 6; i++) {
        vec4 a = uHoops[2 * i];
        if (a.w <= 0.0 || a.x < 0.05) continue;
        float t = a.x / max(rd.z, 0.05);
        if (t > tHit) continue;
        vec4 b = uHoops[2 * i + 1];
        float r = length(ro.xy + rd.xy * t - a.yz);
        float e = abs(r - a.w * (1.0 + 0.1 * uKick));
        float fog = 1.0 - smoothstep(far * 0.5, far, t);
        float lvl = band(floor(fract(b.y) * 40.0) + 4.0);
        vec3 c = colorAt(hue * 2.0 + b.y);
        col = mix(col, c * (0.7 + 1.3 * lvl + 0.8 * uKick), smoothstep(b.x, b.x * 0.3, e) * fog);
        col += c * exp(-e / (b.x * 3.0)) * (0.12 + 0.6 * uBeat + 0.5 * uKick) * fog;
    }
    return col;
}

"""

/** The second half of [JOURNEY_BODY]: the open worlds and both shade() functions. */
internal const val JOURNEY_BODY_B = """
#if (VARIANT >= 5 && VARIANT < 19) || VARIANT >= 26
// ---- The open worlds ----------------------------------------------------------------------
// Each has a backdrop (jBack), a scene to fly through (jEnv: the distance to it, positive in
// the air, 9 for none) and a look for it (jEnvShade). shade() marches the scene, then the
// landmarks on their own as far as the scene was hit (see the enclosed worlds for why), and
// fogs everything into the backdrop towards JFAR.

#if VARIANT == 10
const float JFAR = 8.0;
#elif VARIANT == 11
const float JFAR = 11.0;
#elif VARIANT == 13 || VARIANT == 16 || VARIANT == 27
const float JFAR = 12.0;
#elif VARIANT == 9 || VARIANT == 5 || VARIANT == 7 || VARIANT == 8 || VARIANT == 12 || VARIANT == 14 || VARIANT == 18 || VARIANT == 15 || VARIANT == 26 || VARIANT == 29
const float JFAR = 14.0;
#else
const float JFAR = 17.0;
#endif

// Stars on the sky at a direction.
float jStars(vec3 rd) {
    vec2 sv = rd.xy / max(rd.z, 0.25) * 22.0;
    return step(0.975, hash(floor(sv))) * smoothstep(0.35, 0.0, length(fract(sv) - 0.5)) * (0.35 + 0.65 * uHigh);
}

#if VARIANT == 17
// Synthwave sky: purple into orange, a striped sun that swells with the bass, and a wireframe
// skyline along the horizon.
vec3 jSunset(vec3 rd, float hue) {
    float az = fastAtan2(rd.x, rd.z) / PI;
    float el = rd.y / max(length(rd.xz), 0.2);
    vec3 top = mix(vec3(0.08, 0.0, 0.18), colorAt(hue * 2.0 + 0.75) * 0.1, 0.3);
    vec3 low = mix(vec3(0.9, 0.25, 0.4), colorAt(hue * 2.0 + 0.05) * 0.8, 0.3);
    vec3 col = mix(low, top, smoothstep(-0.02, 0.45, el));
    col += vec3(1.0) * jStars(rd) * smoothstep(0.2, 0.5, el);
    // The sun: bands cut out of its lower half.
    vec2 sc = vec2(az * PI, el - 0.12);
    float r = length(sc);
    float size = 0.28 + 0.05 * uLow;
    float cut = step(0.6, fract((el - 0.12) * 22.0 - uTime * 2.0)) * smoothstep(0.12, -0.05, el - 0.12);
    float sun = smoothstep(size, size - 0.01, r) * (1.0 - cut);
    col = mix(col, mix(vec3(1.0, 0.85, 0.2), vec3(1.0, 0.2, 0.55), smoothstep(0.3, -0.15, el - 0.12)), sun);
    col += vec3(1.0, 0.4, 0.5) * exp(-max(r - size, 0.0) * 9.0) * 0.25 * (1.0 - sun);
    // The skyline: mountains drawn in wireframe.
    float h = 0.07 + 0.05 * sin(wrapA(az * 9.0 + 1.0)) + 0.03 * sin(wrapA(az * 23.0)) + 0.02 * sin(wrapA(az * 51.0));
    if (el < h && el > -0.05) {
        float lines = exp(-abs(fract(el * 40.0) - 0.5) * 12.0) * 0.4 + exp(-abs(fract(az * 30.0) - 0.5) * 12.0) * 0.3;
        col = vec3(0.04, 0.0, 0.08) + colorAt(hue * 2.0 + 0.8) * lines * (0.4 + 0.8 * uMid);
        col += vec3(1.0, 0.3, 0.8) * exp(-(h - el) * 120.0) * 0.8;
    }
    return col;
}
#endif

#if VARIANT == 15
// The polar night: stars and curtains of aurora that ripple across the sky, each fold lit by
// its own band of the spectrum.
vec3 jAurora(vec3 rd, float hue) {
    float az = fastAtan2(rd.x, rd.z) / PI;
    float el = rd.y / max(length(rd.xz), 0.2);
    vec3 col = mix(colorAt(hue * 2.0 + 0.65) * 0.03, vec3(0.0, 0.005, 0.015), smoothstep(-0.1, 0.6, el));
    // Below the horizon, snow far off.
    col = mix(col, vec3(0.12, 0.15, 0.2), smoothstep(0.0, -0.08, el));
    col += vec3(1.0) * jStars(rd) * step(0.05, el);
    for (int k = 0; k < 2; k++) {
        float fk = float(k);
        float base = 0.18 + 0.14 * fk + 0.06 * sin(wrapA(az * (5.0 + 3.0 * fk) + uTime * PI * (1.0 + fk)));
        float h = el - base;
        float lvl = band(floor(fract(az * 0.5 + 0.5 + fk * 0.3) * 48.0) + 4.0);
        float folds = 0.6 + 0.4 * sin(wrapA(az * 40.0 + uTime * PI * 3.0 + fk * 2.0));
        float curtain = smoothstep(-0.02, 0.0, h) * exp(-max(h, 0.0) * (6.0 - 2.0 * lvl)) * folds;
        col += mix(vec3(0.1, 0.9, 0.5), colorAt(hue * 2.0 + 0.3 + fk * 0.35), 0.5) * curtain * (0.3 + 0.9 * lvl + 0.3 * uBeat);
    }
    return col;
}
#endif

vec3 jBack(vec3 ro, vec3 rd, float hue) {
#if VARIANT == 6
    // Sunset over the sea: a sun on the horizon that swells with the bass.
    vec3 col = mix(colorAt(hue * 2.0 + 0.05) * 0.35, colorAt(hue * 2.0 + 0.6) * 0.05, smoothstep(-0.05, 0.5, rd.y));
    float sun = 1.0 / (1.0 + dot(rd.xy - vec2(0.0, 0.06), rd.xy - vec2(0.0, 0.06)) * (260.0 - 120.0 * uLow));
    return col + colorAt(hue * 2.0 + 0.1) * sun * 0.9;
#elif VARIANT == 7
    // Night over the city: dark, with a glow along the horizon from the streets.
    vec3 col = colorAt(hue * 2.0 + 0.7) * 0.02 + colorAt(hue * 2.0 + 0.2) * exp(-abs(rd.y + 0.05) * 9.0) * 0.18;
    return col + vec3(1.0) * jStars(rd) * step(0.1, rd.y);
#elif VARIANT == 8 || VARIANT == 9
    // Space: stars, a nebula, and (for the station) a planet below.
    vec3 col = colorAt(hue * 2.0 + 0.6) * 0.02 + vec3(1.0) * jStars(rd);
    col += colorAt(hue * 2.0 + 0.3) * pow(max(0.0, 1.0 - abs(rd.y - 0.3 * rd.x)), 6.0) * 0.08;
#if VARIANT == 8
    vec3 pc = vec3(-0.3, -0.75, 0.6);
    float planet = smoothstep(0.42, 0.40, length(normalize(rd) - normalize(pc)));
    col = mix(col, colorAt(hue * 2.0 + 0.45) * (0.15 + 0.25 * band(10.0)), planet);
    col += colorAt(hue * 2.0 + 0.5) * smoothstep(0.47, 0.41, length(normalize(rd) - normalize(pc))) * (1.0 - planet) * 0.35;
#endif
    return col;
#elif VARIANT == 10
    return vec3(0.0);
#elif VARIANT == 11
    // Deep water: dark below, lighter toward the surface, a glow overhead that swells with
    // the bass.
    vec3 deep = colorAt(hue * 2.0 + 0.55) * 0.012 + vec3(0.0, 0.012, 0.025);
    vec3 top = colorAt(hue * 2.0 + 0.5) * 0.05 + vec3(0.01, 0.06, 0.08);
    vec3 col = mix(deep, top, smoothstep(-0.4, 0.9, rd.y));
    return col + vec3(0.05, 0.12, 0.13) * pow(max(rd.y, 0.0), 3.0) * (0.5 + 0.8 * uLow);
#elif VARIANT == 12
    // Smoke over the lava: dark red, glowing low down from the river.
    vec3 col = mix(vec3(0.25, 0.05, 0.01), vec3(0.02, 0.005, 0.005), smoothstep(-0.2, 0.5, rd.y));
    col = mix(col, colorAt(hue * 2.0 + 0.05) * 0.05, 0.3);
    return col + vec3(0.6, 0.15, 0.02) * exp(-abs(rd.y + 0.05) * 6.0) * (0.15 + 0.35 * uLow);
#elif VARIANT == 13
    // Shallow water: turquoise, bright toward the surface.
    vec3 deep = mix(vec3(0.0, 0.06, 0.09), colorAt(hue * 2.0 + 0.5) * 0.05, 0.3);
    vec3 top = mix(vec3(0.1, 0.35, 0.4), colorAt(hue * 2.0 + 0.45) * 0.3, 0.3);
    return mix(deep, top, smoothstep(-0.3, 0.8, rd.y)) + vec3(0.2, 0.35, 0.3) * pow(max(rd.y, 0.0), 4.0) * (0.6 + 0.6 * uLow);
#elif VARIANT == 14
    // The void.
    return colorAt(hue * 2.0 + 0.7) * 0.012;
#elif VARIANT == 15
    return jAurora(rd, hue);
#elif VARIANT == 16
    // The deep: almost black, a faint blue far above.
    return vec3(0.0, 0.006, 0.016) + vec3(0.0, 0.02, 0.05) * pow(max(rd.y, 0.0), 2.0) + colorAt(hue * 2.0 + 0.6) * 0.006;
#elif VARIANT == 17
    return jSunset(rd, hue);
#elif VARIANT == 18
    // Deep space, with faint stars.
    return colorAt(hue * 2.0 + 0.7) * 0.015 + vec3(1.0) * jStars(rd) * 0.6;
#elif VARIANT == 26 || VARIANT == 29
    // A dark hall with beams of light sweeping across it on the beat.
    vec3 col = colorAt(hue * 2.0 + 0.7) * 0.015;
    float a = fastAtan2(rd.x, rd.y);
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float beam = wrapA(a - (fi - 1.0) * 0.7 - 0.5 * sin(wrapA(uTime * PI * (2.0 + fi) + fi)));
        col += colorAt(hue * 2.0 + fi * 0.33) * exp(-abs(beam) * 30.0) * smoothstep(-0.1, 0.4, rd.y) * (0.15 + 0.5 * uBeat);
    }
    return col;
#elif VARIANT == 27
    // Night in the forest: deep blue-green, a moon's glow high up.
    vec3 col = mix(vec3(0.0, 0.02, 0.02), colorAt(hue * 2.0 + 0.5) * 0.05 + vec3(0.0, 0.03, 0.05), smoothstep(-0.1, 0.7, rd.y));
    return col + vec3(0.6, 0.7, 0.8) * exp(-length(rd.xy - vec2(0.35, 0.45)) * 18.0) * 0.6;
#elif VARIANT == 28 || VARIANT == 30
    // Open day sky: the palette washed pale toward the horizon, a sun, and wisps of cloud.
    vec3 col = mix(mix(vec3(0.9, 0.85, 0.8), colorAt(hue * 2.0 + 0.1), 0.25) * 0.55,
                   mix(vec3(0.2, 0.4, 0.75), colorAt(hue * 2.0 + 0.6), 0.25) * 0.5, smoothstep(-0.1, 0.6, rd.y));
    col += vec3(1.0, 0.9, 0.7) * pow(max(dot(rd, normalize(vec3(-0.4, 0.3, 1.0))), 0.0), 60.0) * (0.7 + 0.5 * uLow);
    vec2 cp = rd.xz / max(rd.y + 0.25, 0.1) * 2.0;
    float cl = smoothstep(0.55, 0.95, 0.5 + 0.25 * sin(wrapA(cp.x * 1.3 + cp.y * 0.7)) + 0.25 * sin(wrapA(cp.y * 2.1 - cp.x * 0.9 + 1.0)));
    return mix(col, vec3(0.95), cl * 0.5 * smoothstep(-0.05, 0.2, rd.y));
#else
    // Open sky above the canyon: dusk, stars, an aurora on the horizon lit by the spectrum.
    vec3 col = mix(colorAt(hue * 2.0 + 0.1) * 0.14, colorAt(hue * 2.0 + 0.6) * 0.02, smoothstep(-0.15, 0.6, rd.y));
    float a = abs(fastAtan2(rd.x, rd.z)) / PI;
    col += colorAt(a + hue * 2.0) * band(floor(a * 63.0)) * exp(-abs(rd.y - 0.04) * 14.0) * 0.55;
    col += vec3(1.0) * jStars(rd);
    return col;
#endif
}

// A cell along z and across x (and y), with the cell's absolute index modulo the world's count
// in z, and whether its centre is clear of the flight path (so nothing stands in the way).
vec3 jCellR(vec3 q, out vec3 cell) {
    vec3 cq = jCellPos(q);
    cell = floor(cq / JCELL + 0.5);
    return cq - cell * JCELL;
}

#if VARIANT == 11
// The abyss: a channel between walls of boulders (lumps from wrapped sines, the cheapest kind
// of rock on the Mali-470) over a rippled floor.
float jRock(vec3 q, vec2 off) {
    float lumps = 0.45 * abs(sin(wrapA(2.0 * q.y + 1.3 * q.x)) * sin(wrapA(3.0 * q.z + jCam.y)))
                + 0.25 * sin(wrapA(4.0 * q.z + jCam.z + 1.7 * q.y));
    float walls = 1.8 + lumps - abs(off.x);
    float ground = off.y + 1.4 - 0.12 * sin(wrapA(2.0 * q.x + 3.0 * q.z + jCam.y));
    return min(walls, ground) * 0.7;
}

// Kelp: one column per cell beside the path, on either side, leaning back and forth in the
// current. Not marched: each pixel's ray is intersected with the columns of the five cells
// ahead in closed form (in the march they took as long as the whole rest of the world on the
// Mali-470). Returns the distance along the ray (99 for none), the normal, and how far up the
// column and which column it hit.
float jKelp(vec3 ro, vec3 rd, float tMax, out vec3 n, out float rise, out float h) {
    float best = 99.0;
    n = vec3(0.0);
    rise = 0.0;
    h = 0.0;
    float lean = 0.1 * sin(wrapA(uTime * PI * 3.0));
    for (int k = 0; k < 5; k++) {
        float zc = float(k) * JCELL - jCam.w;
        if (zc > tMax * rd.z + 0.2) break;
        float hk = hash(vec2(jCellZ(float(k)), 3.3));
        vec2 pc = jPath(zc);
        float side = hk > 0.5 ? 1.0 : -1.0;
        float x0 = pc.x + side * (0.9 + 0.5 * fract(hk * 7.1));
        float y0 = pc.y - 1.4;
        float lk = lean * (0.6 + 0.8 * fract(hk * 5.3));
        // Sheared so the leaning column stands upright: x' = x - lean·(y - y0).
        vec2 o = vec2(ro.x - x0 - lk * (ro.y - y0), ro.z - zc);
        vec2 d = vec2(rd.x - lk * rd.y, rd.z);
        float dd = dot(d, d);
        float tc = -dot(o, d) / dd;
        vec2 pcl = o + d * tc;
        float disc = (0.0169 - dot(pcl, pcl)) / dd;      // radius 0.13
        if (disc <= 0.0) continue;
        float t = tc - sqrt(disc);
        float y = ro.y + rd.y * t - y0;
        if (t > 0.05 && t < best && y > 0.0 && y < 1.6 + 1.4 * fract(hk * 3.7)) {
            best = t;
            vec2 at = o + d * t;
            n = normalize(vec3(at.x, -lk * at.x, at.y));
            rise = y;
            h = hk;
        }
    }
    return best;
}
#endif

#if VARIANT == 18
// The edges of a box of half-size b, e thick (after Inigo Quilez's box frame).
float jFrame(vec3 p, float b, float e) {
    p = abs(p) - b;
    vec3 w = abs(p + e) - e;
    return min(min(length(max(vec3(p.x, w.y, w.z), 0.0)) + min(max(p.x, max(w.y, w.z)), 0.0),
                   length(max(vec3(w.x, p.y, w.z), 0.0)) + min(max(w.x, max(p.y, w.z)), 0.0)),
               length(max(vec3(w.x, w.y, p.z), 0.0)) + min(max(w.x, max(w.y, p.z)), 0.0));
}

// The three cubes' turns, the same in every cell, worked out once per pixel (shade()).
vec4 jTurn1;
vec4 jTurn2;

vec3 jTurnA(vec3 p, vec4 t) {
    p.xy = vec2(p.x * t.x - p.y * t.y, p.x * t.y + p.y * t.x);
    p.yz = vec2(p.y * t.z - p.z * t.w, p.y * t.w + p.z * t.z);
    return p;
}

// Each cube's distance in a cell (centre on the path at the cell's middle), into d.x, d.y, d.z.
vec3 jCubes(vec3 q, vec2 off) {
    vec3 cq = jCellPos(q);
    float zc = cq.z - floor(cq.z / JCELL + 0.5) * JCELL;
    vec3 p = vec3(off, zc);
    float breathe = 1.0 + 0.04 * uBeat;
    float big = jFrame(p, 0.95 * breathe, 0.025);
    vec3 p1 = jTurnA(p, jTurn1);
    float mid = jFrame(p1, 0.5 * breathe, 0.018);
    vec3 p2 = jTurnA(p1, jTurn2);
    float small = jFrame(p2, 0.24 * breathe, 0.012);
    return vec3(big, mid, small);
}
#endif

float jEnv(vec3 q, vec2 off) {
#if VARIANT == 5
    // Canyon: rough walls either side of the path, a floor below, open to the sky above.
    float bump = 0.18 * sin(wrapA(3.0 * q.y + 2.0 * q.x)) * sin(wrapA(3.0 * q.z + jCam.y))
               + 0.1 * sin(wrapA(4.0 * q.z + jCam.z + 2.0 * q.y));
    float walls = 1.5 + bump - abs(off.x);
    return min(walls, off.y + 1.3) * 0.7;
#elif VARIANT == 6
    // Sea stacks: columns of rock rising from the water, none in the flight's way.
    vec3 cell;
    vec3 r = jCellR(q, cell);
    float h = hash(vec2(cell.x, jCellZ(cell.z)) + 2.3);
    float clear = abs(cell.x * JCELL - (q.x - off.x));
    float stack = (h > 0.35 && clear > 1.3) ? max(length(r.xz) - (0.35 + 0.45 * h), q.y - (0.3 + 3.0 * h)) : JCELL * 0.5 - max(abs(r.x), abs(r.z)) + 0.3;
    // The sea itself is not in here: shade() works out where the ray meets it directly.
    return min(stack, JCELL * 0.45);
#elif VARIANT == 7
    // Night city: towers in blocks, the street the flight follows kept clear.
    vec3 cell;
    vec3 r = jCellR(q, cell);
    float h = hash(vec2(cell.x, jCellZ(cell.z)) + 7.1);
    float clear = abs(cell.x * JCELL - (q.x - off.x));
    float hw = 0.45 + 0.3 * hash(vec2(cell.z, cell.x) + 1.7);
    float tower = (h > 0.2 && clear > 1.3) ? jBox(vec3(r.x, q.y + 2.2 - (1.0 + 5.0 * h) * 0.5, r.z), vec3(hw, (1.0 + 5.0 * h) * 0.5, hw)) : JCELL * 0.5 - max(abs(r.x), abs(r.z)) + 0.3;
    return min(min(tower, JCELL * 0.45), q.y + 2.2);
#elif VARIANT == 8
    // Orbital station: square frames round the flight every few units, girders along it.
    vec3 cq = jCellPos(q);
    float zc = cq.z - floor(cq.z / JCELL + 0.5) * JCELL;
    vec2 a = abs(off);
    float sq = max(a.x, a.y);
    float frame = max(max(sq - 1.55, 1.3 - sq), abs(zc) - 0.1);
    float girder = length(a - 1.42) - 0.06;
    return min(frame, girder);
#elif VARIANT == 9
    // Asteroid field: rough rocks scattered through space, none in the flight's way.
    vec3 cell;
    vec3 r = jCellR(q, cell);
    float h = hash(cell.xy * 1.3 + jCellZ(cell.z) * vec2(3.1, 7.7));
    float clear = length(cell.xy * JCELL - (q.xy - off));
    float rad = 0.35 + 0.7 * (h - 0.45);
    float bumps = 0.07 * sin(wrapA(5.0 * r.x + 2.0 * r.z)) * sin(wrapA(5.0 * r.y + 3.0 * h));
    float rock = (h > 0.45 && clear > 1.4) ? (length(r) - rad + bumps) * 0.8 : JCELL * 0.5 - max(abs(r.x), max(abs(r.y), abs(r.z))) + 0.3;
    return min(rock, JCELL * 0.45);
#elif VARIANT == 10
    // Branching caves: a winding tunnel that swells into caverns, with side tunnels branching
    // off it now and then.
    vec3 cq = jCellPos(q);
    float cz = floor(cq.z / JCELL + 0.5);
    float zc = cq.z - cz * JCELL;
    float h = hash(vec2(jCellZ(cz), 5.5));
    float rad = 0.95 + 0.2 * sin(wrapA(3.0 * q.z + jCam.y)) + 0.1 * sin(wrapA(4.0 * q.z + jCam.z + 2.0 * off.x))
              + 0.7 * smoothstep(0.75, 1.0, sin(wrapA(3.0 * q.z + jCam.y + 1.3)));
    float air = length(off) - rad;
    if (h > 0.4) {
        float ang = h * 12.566;
        vec3 dir = normalize(vec3(cos(wrapA(ang)), sin(wrapA(ang)), 0.5));
        vec3 v = vec3(off, zc);
        float along = max(dot(v, dir), 0.0);
        air = min(air, length(v - dir * along) - 0.55);
    }
    return -air * 0.7;
#elif VARIANT == 11
    return jRock(q, off);
#elif VARIANT == 12
    // Lava canyon: basalt walls in ledges either side, the lava river below.
    float bump = 0.22 * sin(wrapA(3.0 * q.y + 2.0 * q.x)) * sin(wrapA(3.0 * q.z + jCam.y))
               + 0.15 * abs(sin(wrapA(4.0 * q.z + jCam.z + 1.5 * q.y)));
    float walls = 1.45 + bump + 0.25 * floor(max(off.y + 1.3, 0.0) * 1.5) - abs(off.x);
    return min(walls, off.y + 1.25) * 0.65;
#elif VARIANT == 13
    // Coral reef: a valley floor of coral mounds, rising to either side.
    float mounds = 0.55 * smoothstep(0.1, 1.0, sin(wrapA(2.3 * q.x + 0.5)) * sin(wrapA(3.0 * q.z + jCam.y)))
                 + 0.18 * sin(wrapA(4.0 * q.z + jCam.z + 3.0 * q.x));
    return (off.y + 1.2 - mounds - 0.35 * max(abs(off.x) - 0.9, 0.0)) * 0.6;
#elif VARIANT == 18
    vec3 c = jCubes(q, off);
    return min(c.x, min(c.y, c.z));
#elif VARIANT == 15
    // Aurora tundra: snow dunes, and ice spires away from the path.
    float dunes = 0.18 * sin(wrapA(1.5 * q.x + 3.0 * q.z + jCam.y)) + 0.1 * sin(wrapA(2.5 * q.x - 4.0 * q.z - jCam.z));
    // Spires: the peaks of two crossed sines, sharpened, their heights varied by a slow wave.
    float sp = max(sin(wrapA(2.0 * q.x + 1.0)) * sin(wrapA(3.0 * q.z + jCam.y + 0.7)), 0.0);
    sp *= sp;
    float tall = 0.5 + 0.5 * sin(wrapA(q.z + jCam.x * JZ + 0.8 * q.x));
    float spires = 2.2 * sp * sp * tall * smoothstep(1.0, 2.2, abs(off.x));
    // Careful steps only among the spires; near the path the dunes allow long ones.
    return (off.y + 1.3 - dunes - spires) * (abs(off.x) < 1.0 ? 0.85 : 0.4);
#elif VARIANT == 26
    // Speaker canyon: canyon walls set with speaker cones in rows, each cone pushed out
    // toward the flight on every kick.
    float bump = 0.12 * sin(wrapA(3.0 * q.y + 2.0 * q.x)) * sin(wrapA(3.0 * q.z + jCam.y));
    vec2 g = vec2(fract(q.y * 0.6) - 0.5, fract((3.0 * q.z + jCam.y) / TAU) - 0.5) * vec2(1.67, 2.09);
    float dc = length(g);
    float cone = dc < 0.75 ? (0.75 - dc) * (0.5 - 0.4 * uKick) : 0.0;
    float walls = 1.6 + bump + cone - abs(off.x);
    return min(walls, off.y + 1.3) * 0.7;
#elif VARIANT == 27
    // Neon forest: trees in a grid of cells off the path, their crowns lit from within.
    vec3 cell;
    vec3 r = jCellR(q, cell);
    float h = hash(vec2(cell.x, jCellZ(cell.z)) + 4.1);
    float clear = abs(cell.x * JCELL - (q.x - off.x));
    float ground = off.y + 1.3 - 0.08 * sin(wrapA(2.0 * q.x + 3.0 * q.z + jCam.y));
    if (clear < 1.1) return min(min(JCELL * 0.5 - max(abs(r.x), abs(r.z)) + 0.3, JCELL * 0.45), ground);
    float trunk = max(length(r.xz) - (0.08 + 0.05 * h), q.y - (0.4 + 0.6 * h));
    float crown = length(vec3(r.x, (q.y - (0.5 + 0.7 * h)) * 1.3, r.z)) - (0.5 + 0.25 * h)
                + 0.06 * sin(wrapA(9.0 * q.y)) * sin(wrapA(9.0 * r.x + 3.0 * h));
    return min(min(trunk, crown * 0.7), min(JCELL * 0.45, ground));
#elif VARIANT == 28
    // Floating islands bobbing on the bass, over a sea of cloud.
    vec3 cell;
    vec3 r = jCellR(q, cell);
    float h = hash(vec2(cell.x, jCellZ(cell.z)) + 6.3);
    float clear = abs(cell.x * JCELL - (q.x - off.x));
    float clouds = off.y + 2.6 - 0.2 * sin(wrapA(2.0 * q.x + 3.0 * q.z + jCam.y)) - 0.1 * sin(wrapA(3.0 * q.x - 4.0 * q.z - jCam.z));
    if (h < 0.3 || clear < 1.25) return min(min(JCELL * 0.5 - max(abs(r.x), abs(r.z)) + 0.3, JCELL * 0.45), clouds);
    float top = -0.5 + 1.4 * (h - 0.5) + 0.15 * (0.4 + uLow) * sin(wrapA(uTime * PI * 2.0 + h * 6.0));
    float rad = 0.6 + 0.4 * h;
    float below = clamp((top - q.y) / 1.1, 0.0, 1.0);
    float body = max(length(r.xz) - rad * (1.0 - 0.85 * below), max(q.y - top, top - 1.1 - q.y));
    return min(min(body * 0.6, JCELL * 0.45), clouds);
#elif VARIANT == 29
    // Pinball arena: a playfield floor, low rails either side, and bumpers off the path.
    vec3 cell;
    vec3 r = jCellR(q, cell);
    float h = hash(vec2(cell.x, jCellZ(cell.z)) + 8.7);
    float clear = abs(cell.x * JCELL - (q.x - off.x));
    float floorD = off.y + 1.0;
    float rail = max(2.2 - abs(off.x), off.y + 0.55);
    float bumper = (h > 0.35 && clear > 0.9) ? max(length(r.xz) - 0.28, off.y + 0.5) : JCELL * 0.5 - max(abs(r.x), abs(r.z)) + 0.3;
    return min(min(floorD, rail), min(bumper, JCELL * 0.45));
#elif VARIANT == 30
    // Ribbon sky: three long ribbons of light streaming beside, below and above the flight,
    // waving with the bass, mids and treble.
    float zz = 3.0 * q.z + jCam.y;
    float d = 9.0;
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float xc = (fi - 1.0) * 1.7;
        float yc = i == 1 ? -0.95 : 0.35 + 0.3 * fi;
        float amp = 0.2 + 0.35 * (i == 0 ? uLow : (i == 1 ? uMid : uHigh));
        float y = yc + amp * sin(wrapA(2.0 * zz + fi * 2.0));
        d = min(d, max(abs(off.y - y) * 0.6 - 0.02, abs(off.x - xc) - 0.55));
    }
    return d;
#else
    return 9.0;
#endif
}

vec3 jEnvShade(vec3 q, vec2 off, vec3 ro, vec3 rd, float hue) {
    const vec2 k = vec2(1.0, -1.0);
    const float h = 0.02;
    vec3 n = normalize(k.xyy * jEnv(q + k.xyy * h, off + k.xy * h) + k.yyx * jEnv(q + k.yyx * h, off + k.yy * h)
                     + k.yxy * jEnv(q + k.yxy * h, off + k.yx * h) + k.xxx * jEnv(q + k.xxx * h, off + k.xx * h));
    float facing = clamp(dot(n, -rd), 0.0, 1.0);
#if VARIANT == 5
    // Canyon rock in strata, the strata lit by the spectrum; a glowing river on the floor.
    if (off.y < -1.2) {
        float river = exp(-abs(off.x) * 2.5);
        return colorAt(hue * 2.0 + 0.55) * (0.05 + river * (0.3 + 0.8 * uLow));
    }
    float stratum = floor(q.y * 3.0);
    float lvl = band(floor(fract(stratum * 0.137) * 63.0));
    vec3 col = colorAt(hue * 2.0 + stratum * 0.06) * (0.05 + 0.4 * facing * facing);
    col += colorAt(hue * 2.0 + stratum * 0.06 + 0.5) * exp(-abs(fract(q.y * 3.0) - 0.5) * 30.0) * lvl * 0.9;
    return col;
#elif VARIANT == 6
    // Dark rock banded with light like the Pillar hall: bands rising up each stack, each stack
    // lit by its own band of the spectrum and flaring on the beat, its top glowing.
    vec3 cell;
    vec3 r = jCellR(q, cell);
    float hc = hash(vec2(cell.x, jCellZ(cell.z)) + 2.3);
    float lvl = band(floor(fract(hc * 7.3) * 48.0) + 4.0);
    float bands = smoothstep(0.8, 1.0, sin(wrapA(q.y * 5.0 - uTime * PI * 6.0 + hc * 6.0)));
    float top = smoothstep(-0.25, 0.0, q.y - (0.3 + 3.0 * hc));
    vec3 col = colorAt(hue * 2.0 + 0.35) * (0.03 + 0.3 * facing * facing);
    col += colorAt(hue * 2.0 + 0.1) * pow(1.0 - facing, 3.0) * (0.15 + 0.4 * uBeat);
    col += colorAt(hue * 2.0 + hc * 0.5) * bands * (0.15 + 1.1 * lvl + 0.6 * uBeat);
    return col + colorAt(hue * 2.0 + 0.1) * top * (0.3 + 0.9 * lvl);
#elif VARIANT == 7
    // Towers with lit windows that flicker with the hi-hats; the street a glowing grid.
    if (q.y < -2.15) {
        vec2 g = abs(fract(jCellPos(q).xz / JCELL * 2.0) - 0.5);
        return colorAt(hue * 2.0 + 0.3) * exp(-min(g.x, g.y) * 20.0) * (0.15 + 0.5 * uLow);
    }
    vec3 cq = jCellPos(q);
    vec2 w = vec2((abs(n.x) > 0.5 ? cq.z : cq.x) * 5.0, q.y * 6.0);
    float lit = step(0.55, hash(floor(w) + floor(cq.x / JCELL) * 3.1)) * step(0.2, fract(w.x)) * step(0.25, fract(w.y));
    vec3 col = colorAt(hue * 2.0 + 0.7) * (0.02 + 0.08 * facing);
    return col + colorAt(hue * 2.0 + hash(floor(w)) * 0.3) * lit * (0.35 + 0.8 * uHigh);
#elif VARIANT == 8
    // Station metal: panels, blinking lights, and light racing along the girders.
    vec3 cq = jCellPos(q);
    float panel = step(0.06, abs(fract(cq.z * 2.0 + off.x * 2.0) - 0.5));
    float blink = step(0.93, hash(floor(vec2(off.x * 4.0, cq.z * 4.0) + 3.0))) * (0.5 + 0.5 * uBeat);
    float race = pow(0.5 + 0.5 * sin(wrapA(4.0 * q.z + jCam.z - uTime * PI * 24.0)), 12.0);
    vec3 col = colorAt(hue * 2.0 + 0.6) * (0.04 + 0.35 * facing * facing) * (0.6 + 0.4 * panel);
    col += colorAt(hue * 2.0 + 0.1) * (blink + race * 0.5 * (0.4 + uKick));
    return col;
#elif VARIANT == 9
    // Rock lit by a sun, with cracks that glow on the kick.
    vec3 cell;
    vec3 r = jCellR(q, cell);
    float light = clamp(dot(n, normalize(vec3(0.6, 0.5, -0.4))), 0.0, 1.0);
    float crack = exp(-abs(sin(wrapA(7.0 * r.x + 5.0 * r.y)) * sin(wrapA(6.0 * r.z + 4.0 * r.x))) * 12.0);
    vec3 col = vec3(0.45, 0.42, 0.4) * (0.03 + 0.5 * light) + colorAt(hue * 2.0 + 0.1) * pow(1.0 - facing, 3.0) * 0.15;
    return col + colorAt(hue * 2.0 + hash(cell.xy) * 0.4) * crack * (0.2 + 1.2 * uKick + 0.5 * band(20.0));
#elif VARIANT == 10
    // Wet cave rock with crystal veins that glow with the spectrum.
    float vein = exp(-abs(sin(wrapA(5.0 * q.x + 3.0 * q.y)) * sin(wrapA(4.0 * q.z + jCam.z + 2.0 * q.y))) * 14.0);
    float lvl = band(floor(fract(q.y * 0.3 + 0.5) * 63.0));
    vec3 col = colorAt(hue * 2.0 + 0.6) * (0.02 + 0.2 * facing * facing) + vec3(0.5) * pow(facing, 20.0) * 0.15;
    return col + colorAt(hue * 2.0 + 0.2) * vein * (0.15 + 1.0 * lvl + 0.5 * uKick);
#elif VARIANT == 11
    // Rock lit from above, with caustics on the faces turned up, pulsing with the bass.
    float upward = clamp(n.y, 0.0, 1.0);
    float c1 = sin(wrapA(3.0 * q.x + 1.3 * sin(wrapA(3.0 * q.z + jCam.y + uTime * PI * 2.0))));
    float c2 = sin(wrapA(3.0 * q.z + jCam.y + 1.2 * sin(wrapA(2.0 * q.x - uTime * PI * 1.5))));
    float caustic = exp(-abs(c1 * c2) * 9.0);
    vec3 col = vec3(0.05, 0.09, 0.11) * (0.25 + 0.6 * upward * upward + 0.3 * facing) + colorAt(hue * 2.0 + 0.55) * 0.03;
    col += colorAt(hue * 2.0 + 0.5) * pow(1.0 - facing, 3.0) * 0.12;
    return col + mix(vec3(0.4, 0.8, 0.85), colorAt(hue * 2.0 + 0.5), 0.4) * caustic * upward * (0.15 + 0.7 * uLow + 0.4 * uKick);
#elif VARIANT == 18
    // Glowing edges: each cube its own colour and band of the spectrum (bass on the big one,
    // treble on the smallest), the light racing along them, a flash on the kick.
    vec3 c = jCubes(q, off);
    float lv = c.x < c.y && c.x < c.z ? 0.0 : (c.y < c.z ? 1.0 : 2.0);
    float lvl = band(4.0 + lv * 18.0 + floor(fract(jCellZ(floor(jCellPos(q).z / JCELL + 0.5)) * 0.37) * 10.0));
    float race = pow(0.5 + 0.5 * sin(wrapA(3.0 * q.z + jCam.y + (q.x + q.y) * 3.0 - uTime * PI * 4.0)), 8.0);
    vec3 ec = colorAt(hue * 2.0 + lv * 0.3);
    return ec * (0.12 + 0.2 * facing + 0.6 * lvl + 0.25 * uKick) + vec3(1.0) * race * (0.06 + 0.2 * uBeat);
#elif VARIANT == 12
    vec3 lava = mix(vec3(1.0, 0.32, 0.04), colorAt(hue * 2.0 + 0.05), 0.2);
    if (off.y < -1.15) {
        // The river: flowing bands of molten rock, brighter with the bass.
        float flow = 0.5 + 0.5 * sin(wrapA(3.0 * q.z + jCam.y - uTime * PI * 3.0 + 2.0 * sin(wrapA(2.0 * q.x))));
        return lava * (0.5 + 0.6 * flow + 0.6 * uLow) + vec3(1.0, 0.8, 0.3) * flow * flow * flow * 0.3;
    }
    // Basalt, lit red from below, cracked with veins that glow on the bass and the kick.
    float vein = exp(-abs(sin(wrapA(5.0 * q.y + 2.0 * q.x)) * sin(wrapA(3.0 * q.z + jCam.y + 2.0 * q.y))) * 14.0);
    float below = smoothstep(0.6, -1.2, off.y);
    vec3 col = vec3(0.04, 0.03, 0.03) * (0.3 + 0.7 * facing) + lava * below * 0.25 * (0.6 + 0.6 * uLow);
    return col + lava * vein * (0.1 + 1.1 * uLow + 0.7 * uKick);
#elif VARIANT == 13
    // Coral in the palette's colours, a colour per mound, caustics dancing on top.
    float upward = clamp(n.y, 0.0, 1.0);
    float mound = floor(2.3 * q.x / TAU + 0.5) * 0.37 + floor((3.0 * q.z + jCam.y) / TAU + 0.5) * 0.21;
    float lvl = band(floor(fract(mound) * 48.0) + 4.0);
    vec3 coral = colorAt(hue * 2.0 + fract(mound));
    float c1 = sin(wrapA(3.0 * q.x + 1.3 * sin(wrapA(3.0 * q.z + jCam.y + uTime * PI * 2.0))));
    float c2 = sin(wrapA(3.0 * q.z + jCam.y + 1.2 * sin(wrapA(2.0 * q.x - uTime * PI * 1.5))));
    float caustic = exp(-abs(c1 * c2) * 8.0);
    vec3 col = coral * (0.12 + 0.45 * upward + 0.25 * facing) * (0.7 + 0.6 * lvl);
    return col + vec3(0.6, 0.9, 0.85) * caustic * upward * (0.15 + 0.6 * uLow + 0.3 * uKick);
#elif VARIANT == 15
    // Snow lit blue-white and tinted by the aurora, glittering; ice spires glassy and lit
    // from within on the beat.
    float upward = clamp(n.y, 0.0, 1.0);
    // The aurora's light on the snow: its colour, not the whole sky worked out again.
    vec3 sky = mix(vec3(0.1, 0.9, 0.5), colorAt(hue * 2.0 + 0.3), 0.5) * (0.04 + 0.1 * band(20.0));
    float glit = step(0.994, hash(floor(vec2(q.x * 40.0, (q.z + jCam.w) * 40.0)))) * (0.2 + 0.5 * uHigh);
    if (n.y < 0.55) {
        vec3 ice = mix(vec3(0.5, 0.8, 1.0), colorAt(hue * 2.0 + 0.55), 0.35);
        return ice * (0.06 + 0.25 * facing) + ice * pow(1.0 - facing, 3.0) * (0.3 + 0.6 * uBeat);
    }
    vec3 col = vec3(0.55, 0.65, 0.8) * (0.06 + 0.3 * upward) + sky * 1.5 * upward;
    return col + vec3(1.0) * glit;
#elif VARIANT == 26
    // Speaker cones: a lit rim on each, ridges round the cone, the dust cap flashing on the
    // kick; dark grille between; a floor lit with the beat.
    if (off.y < -1.25) {
        vec2 g = abs(fract(vec2(q.x, jCellPos(q).z / JCELL * 3.0)) - 0.5);
        return colorAt(hue * 2.0 + 0.3) * exp(-min(g.x, g.y) * 25.0) * (0.15 + 0.7 * uBeat);
    }
    vec2 g = vec2(fract(q.y * 0.6) - 0.5, fract((3.0 * q.z + jCam.y) / TAU) - 0.5) * vec2(1.67, 2.09);
    float dc = length(g);
    float id = floor(q.y * 0.6) * 3.0 + jCellZ(floor(jCellPos(q).z / JCELL)) + (off.x > 0.0 ? 17.0 : 0.0);
    float lvl = band(floor(fract(id * 0.37) * 48.0) + 4.0);
    vec3 c = colorAt(hue * 2.0 + fract(id * 0.21));
    if (dc < 0.78) {
        float rim = exp(-abs(dc - 0.72) * 40.0);
        float ridge = 0.5 + 0.5 * sin(wrapA(dc * 40.0));
        vec3 col = vec3(0.04) * (0.4 + 0.6 * facing) * (0.7 + 0.3 * ridge);
        col += c * rim * (0.3 + 1.4 * lvl);
        return col + c * smoothstep(0.16, 0.1, dc) * (0.2 + 1.5 * uKick);
    }
    float grille = step(0.5, fract(q.y * 18.0)) * step(0.5, fract((3.0 * q.z + jCam.y) * 3.0));
    return vec3(0.03) * (0.3 + 0.7 * facing) * (0.7 + 0.3 * grille) + c * pow(1.0 - facing, 3.0) * 0.1;
#elif VARIANT == 27
    // Moss with glowing spots, dark bark with light running up it, crowns lit by the spectrum.
    vec3 cell;
    vec3 r = jCellR(q, cell);
    float hc = hash(vec2(cell.x, jCellZ(cell.z)) + 4.1);
    if (off.y < -1.2) {
        vec2 g = vec2(q.x * 3.0, jCellPos(q).z / JCELL * 6.0);
        float spot = smoothstep(0.3, 0.0, length(fract(g) - 0.5)) * step(0.8, hash(vec2(floor(g.x), mod(floor(g.y) + jCell * 6.0, JCELLS * 6.0))));
        return vec3(0.01, 0.03, 0.02) * (0.5 + facing) + colorAt(hue * 2.0 + 0.3) * spot * (0.3 + 0.9 * uBeat);
    }
    float lvl = band(floor(hc * 48.0) + 4.0);
    vec3 leaf = colorAt(hue * 2.0 + hc * 0.6);
    if (q.y > 0.35 + 0.6 * hc) {
        vec2 lg = vec2(r.x * 6.0 + hc * 7.0 + r.z * 3.0, q.y * 6.0);
        float flick = smoothstep(0.3, 0.0, length(fract(lg) - 0.5)) * step(0.55, hash(floor(lg)));
        return leaf * (0.08 + 0.3 * facing) * (0.5 + 1.2 * lvl) + leaf * flick * (0.2 + 1.0 * lvl) + leaf * pow(1.0 - facing, 3.0) * 0.4;
    }
    float run = exp(-abs(fract(q.y * 2.0 - uTime * 4.0) - 0.5) * 12.0);
    return vec3(0.03, 0.025, 0.02) * (0.4 + 0.6 * facing) + leaf * run * (0.2 + 0.7 * uBeat);
#elif VARIANT == 28
    // Grass on top, rock beneath with waterfalls pouring off, the cloud sea lit by the sun.
    if (off.y < -2.3) {
        return mix(vec3(0.85, 0.85, 0.9), colorAt(hue * 2.0 + 0.1), 0.2) * (0.35 + 0.4 * facing);
    }
    vec3 cell;
    vec3 r = jCellR(q, cell);
    float hc = hash(vec2(cell.x, jCellZ(cell.z)) + 6.3);
    float sun = clamp(dot(n, normalize(vec3(-0.4, 0.8, -0.3))), 0.0, 1.0);
    if (n.y > 0.55) {
        float flower = step(0.92, hash(floor(vec2(r.x, r.z) * 14.0 + hc * 9.0)));
        vec3 grass = mix(vec3(0.15, 0.5, 0.15), colorAt(hue * 2.0 + 0.3), 0.3);
        return grass * (0.35 + 0.8 * sun) * (0.8 + 0.4 * uLow) + colorAt(hue * 2.0 + hc) * flower * (0.3 + 0.8 * uBeat);
    }
    vec3 rock = mix(vec3(0.5, 0.4, 0.32), colorAt(hue * 2.0 + 0.6), 0.2) * (0.3 + 0.6 * sun);
    if (hc > 0.55) {
        float fall = step(0.45, fract(fastAtan2(r.z, r.x) * 3.0)) * (0.5 + 0.5 * step(0.5, fract(q.y * 4.0 + uTime * 8.0)));
        rock = mix(rock, vec3(0.7, 0.85, 1.0) * (0.5 + 0.3 * uLow), fall * 0.8);
    }
    return rock;
#elif VARIANT == 29
    // Playfield: dark with inserts lighting in a chase, rails in chrome, bumper caps flashing
    // when their kick comes round.
    vec3 cell;
    vec3 r = jCellR(q, cell);
    float hc = hash(vec2(cell.x, jCellZ(cell.z)) + 8.7);
    if (abs(off.x) > 2.15 && off.y > -1.0) {
        return vec3(0.6, 0.65, 0.7) * pow(facing, 2.0) * 0.4 + colorAt(hue * 2.0 + 0.5) * pow(1.0 - facing, 4.0) * 0.6;
    }
    if (off.y < -0.95) {
        vec2 g = vec2(q.x * 2.0, jCellPos(q).z / JCELL * 4.0);
        float insert = smoothstep(0.3, 0.2, length(fract(g) - 0.5));
        float row = mod(floor(g.y) + jCell * 4.0, JCELLS * 4.0);
        float chase = step(0.5, fract(row / 4.0 - uTime * 4.0)) * step(0.4, hash(vec2(floor(g.x), row)));
        float stripe = 0.5 + 0.5 * sin(wrapA(q.x * 3.0));
        return colorAt(hue * 2.0 + 0.7) * (0.06 + 0.06 * stripe) * (0.5 + facing) + colorAt(hue * 2.0 + row * 0.1) * insert * (0.12 + chase * (0.4 + 0.9 * uBeat));
    }
    float flash = abs(mod(uKicks, 3.0) - floor(hc * 3.0)) < 0.5 ? uKick : 0.0;
    vec3 c = colorAt(hue * 2.0 + hc);
    float cap = smoothstep(-0.55, -0.5, off.y);
    return c * (0.2 + 0.5 * facing) + c * cap * (0.3 + 2.0 * flash) + vec3(1.0) * pow(facing, 30.0) * 0.3;
#elif VARIANT == 30
    // Ribbons: each its own colour, bright edges, light flowing along them with the music.
    float zz = 3.0 * q.z + jCam.y;
    float best = 9.0;
    float fi = 0.0;
    for (int i = 0; i < 3; i++) {
        float d = abs(off.x - (float(i) - 1.0) * 1.7);
        if (d < best) { best = d; fi = float(i); }
    }
    float edge = smoothstep(0.4, 0.55, best);
    float flow = pow(0.5 + 0.5 * sin(wrapA(zz * 2.0 - uTime * PI * 8.0 + fi)), 6.0);
    float lvl = band(8.0 + fi * 18.0);
    vec3 c = colorAt(hue * 2.0 + fi * 0.33);
    return c * (0.12 + 0.35 * facing) * (0.6 + 0.8 * lvl) + c * edge * (0.4 + 0.8 * uBeat) + vec3(1.0) * flow * (0.15 + 0.4 * lvl);
#else
    return vec3(0.0);
#endif
}

#if VARIANT == 12 || VARIANT == 27
// Embers rising from the lava (and, green-gold, the forest's fireflies): a layer of glowing points at a fixed distance from the camera.
vec3 jEmbers(vec3 col, vec3 ro, vec3 rd, float tHit, float hue) {
    for (int k = 0; k < 2; k++) {
        float d = 1.4 + float(k) * 1.6;
        if (d > tHit) break;
        vec3 sp = ro + rd * d;
        vec3 g = vec3(sp.x * 3.0, sp.y * 3.0 - uTime * (3.0 + float(k)), (sp.z + jCam.w) * (6.0 / JCELL));
        vec3 c = floor(g);
        float h = hash(vec2(c.x + 17.0 * mod(c.z + jCell * 6.0, JCELLS * 6.0), c.y));
        float ember = smoothstep(0.2, 0.0, length(fract(g) - 0.5)) * step(0.9, h);
#if VARIANT == 27
        col += mix(vec3(0.7, 1.0, 0.3), colorAt(hue * 2.0 + 0.3), 0.3) * ember * (0.25 + 1.4 * uKick);
#else
        col += mix(vec3(1.0, 0.45, 0.1), colorAt(hue * 2.0 + 0.05), 0.2) * ember * (0.4 + 0.6 * uLow + 0.5 * uKick);
#endif
    }
    return col;
}
#endif

#if VARIANT == 14
// The cyber highway: two cylinders round the path, made of nothing but lanes of light. The
// ray is met with each in closed form (a quadratic against the path's line at the camera, then
// once more against its line where that first hit fell), and both are drawn see-through.
vec3 jCyber(vec3 ro, vec3 rd, float hue) {
    vec3 col = vec3(0.0);
    for (int k = 0; k < 2; k++) {
        float fk = float(k);
        float R = 1.1 + 1.3 * fk;
        vec2 c = jPath(0.0);
        float t = JFAR;
        for (int it = 0; it < 2; it++) {
            vec2 o = ro.xy - c;
            float a = max(dot(rd.xy, rd.xy), 0.002);
            float b = dot(o, rd.xy);
            float disc = b * b - a * (dot(o, o) - R * R);
            t = min((-b + sqrt(max(disc, 0.0))) / a, JFAR * 1.2);
            c = jPath(min(t * rd.z, JFAR));
        }
        vec3 q = ro + rd * t;
        vec2 off = q.xy - c;
        float ang = fastAtan2(off.y, off.x) / TAU + 0.5;
        float lanes = 12.0 - 5.0 * fk;
        float li = floor(ang * lanes);
        float f = abs(fract(ang * lanes) - 0.5) * R * 6.0;
        float lvl = band(floor(fract(li * 0.37 + fk * 0.5) * 48.0) + 4.0);
        float line = exp(-f * (7.0 - 2.0 * fk)) + exp(-f * 1.5) * 0.12;
        float packet = pow(0.5 + 0.5 * sin(wrapA(3.0 * q.z + jCam.y + li * 1.7 - uTime * PI * (8.0 + 4.0 * fk))), 10.0);
        float cross = exp(-abs(sin(wrapA(3.0 * q.z + jCam.y))) * 20.0) * (0.3 + 0.8 * uBeat) * (1.0 - fk);
        float fog = 1.0 - smoothstep(JFAR * 0.25, JFAR, t);
        vec3 lc = colorAt(hue * 2.0 + li / lanes + fk * 0.3);
        col += lc * (line * (0.12 + 0.9 * lvl + packet * (0.7 + 0.8 * uKick)) + cross) * fog * (1.0 - 0.5 * fk);
    }
    return col;
}
#endif

#if VARIANT == 16
// The deep floor: dark silt speckled with glowing life, each patch lit by its band of the
// spectrum and breathing with the beat.
vec3 jDeepFloor(vec3 q, vec3 rd, float hue) {
    vec2 g = vec2(q.x * 2.5, (q.z + jCam.w) * (6.0 / JCELL));
    vec2 c = floor(g);
    float h = hash(vec2(c.x, mod(c.y + jCell * 6.0, JCELLS * 6.0)));
    float spot = smoothstep(0.35, 0.0, length(fract(g) - 0.5)) * step(0.55, h);
    float lvl = band(floor(h * 48.0) + 4.0);
    vec3 col = vec3(0.01, 0.015, 0.02) * (0.5 + 0.5 * sin(wrapA(3.0 * q.x)) * sin(wrapA(3.0 * q.z + jCam.y)));
    vec3 life = mix(vec3(0.1, 0.9, 0.8), colorAt(hue * 2.0 + h), 0.5);
    // A soft glow over the floor near the lit patches, so the floor reads as a floor.
    col += life * 0.04 * (0.5 + lvl);
    return col + life * spot * (0.45 + 1.6 * lvl + 0.6 * uBeat);
}
#endif

#if VARIANT == 17
// The road: a neon grid floor, the road along the path darker with glowing edges and a dashed
// centre line racing past.
vec3 jRoad(vec3 q, float hue) {
    vec2 off = q.xy - jPath(q.z);
    vec2 g = vec2(q.x, q.z + jCam.w) / (JCELL / 3.0);
    vec2 gg = abs(fract(g) - 0.5);
    float grid = exp(-min(gg.x, gg.y) * 30.0);
    vec3 col = vec3(0.02, 0.0, 0.05) + colorAt(hue * 2.0 + 0.85) * grid * (0.35 + 0.8 * uLow);
    float road = smoothstep(0.62, 0.58, abs(off.x));
    float edge = exp(-abs(abs(off.x) - 0.6) * 40.0);
    float dash = step(0.5, fract((q.z + jCam.w) / (JCELL / 4.0))) * exp(-abs(off.x) * 60.0);
    col = mix(col, vec3(0.01, 0.0, 0.02), road * 0.85);
    return col + vec3(1.0, 0.3, 0.7) * edge * (0.5 + 0.8 * uBeat) + vec3(1.0, 0.9, 0.5) * dash * 0.8;
}
#endif

#if VARIANT == 6
// The sea: a plane at y = -1.1 with waves only in its normal (cheap, and no march steps lost
// skimming it), mirroring the sky.
vec3 jSea(vec3 q, vec3 rd, float hue) {
    float k = 0.12 * (1.0 + 2.0 * uLow);
    float a = wrapA(3.0 * q.x + uTime * PI * 6.0);
    float b = wrapA(3.0 * q.z + jCam.y);
    vec3 n = normalize(vec3(-k * cos(a) * sin(b), 1.0, -k * sin(a) * cos(b)));
    float facing = clamp(dot(n, -rd), 0.0, 1.0);
    vec3 rr = reflect(rd, normalize(n + vec3(0.0, 2.0, 0.0)));
    return jBack(q, rr, hue) * 0.55 + colorAt(hue * 2.0 + 0.1) * pow(facing, 30.0) * 0.2;
}
#endif

#if VARIANT == 11
// Kelp: dark green fronds lit along their edges, the tips glowing with their own band.
vec3 jKelpShade(vec3 n, vec3 rd, float rise, float h, float hue) {
    float facing = clamp(abs(dot(n, rd)), 0.0, 1.0);
    float lvl = band(floor(h * 40.0) + 4.0);
    vec3 col = mix(vec3(0.02, 0.07, 0.03), colorAt(hue * 2.0 + 0.3) * 0.08, 0.4) * (0.4 + 0.8 * facing);
    col += colorAt(hue * 2.0 + 0.3) * pow(1.0 - facing, 2.0) * 0.25;
    return col + colorAt(hue * 2.0 + 0.25) * smoothstep(1.2, 2.8, rise) * (0.1 + 0.9 * lvl);
}
#endif

#if VARIANT == 11 || VARIANT == 13 || VARIANT == 16
// Light shafts from the surface, slanting and drifting, brighter the more water a ray crosses
// (worked out from the direction, not marched), and specks drifting in the water, placed in
// one layer of cells at a fixed distance from the camera.
vec3 jWater(vec3 col, vec3 ro, vec3 rd, float tHit, float hue) {
    float a = rd.x / (max(rd.y, 0.0) + 0.7);
    float shaft = max(0.0, sin(wrapA(a * 7.0 + uTime * PI * 0.8)));
    shaft *= shaft;
    float depth = min(tHit, JFAR) / JFAR;
#if VARIANT == 16
    shaft *= 0.15;   // the deep: barely any light from the surface
#endif
    col += vec3(0.1, 0.2, 0.22) * shaft * shaft * smoothstep(-0.3, 0.6, rd.y) * depth * (0.6 + 0.6 * uLow);
    float d = 1.6;
    if (d < tHit) {
        vec3 sp = ro + rd * d;
        // z in cells of the world's own cell, so the specks stay put as the camera wraps a cell.
        vec3 g = vec3(sp.x * 3.0, sp.y * 3.0 + uTime * 2.0, (sp.z + jCam.w) * (6.0 / JCELL));
        vec3 c = floor(g);
        float h = hash(vec2(c.x + 17.0 * mod(c.z + jCell * 6.0, JCELLS * 6.0), c.y));
        float speck = smoothstep(0.22, 0.0, length(fract(g) - 0.5)) * step(0.93, h);
        col += mix(vec3(0.5, 0.8, 0.8), colorAt(hue * 2.0 + h), 0.4) * speck * (0.15 + 0.4 * uHigh) * (1.0 - d / 6.0);
    }
    return col;
}
#endif

vec3 shade(vec2 p) {
    vec3 ro; vec3 fw; vec3 rt; vec3 up; vec2 sp; vec3 rd;
    jCamera(p, ro, fw, rt, up, sp, rd);
    jCull(sp);
    float t = 0.05;
    float steps = 0.0;
    bool hit = false;
    float tMax = JFAR;
#if VARIANT == 18
    // Slow turns: a calm, hypnotic drift rather than a spin.
    float a1 = wrapA(uTime * PI * 0.45);
    float b1 = wrapA(uTime * PI * 0.3 + 1.0);
    float a2 = wrapA(-uTime * PI * 0.7);
    float b2 = wrapA(uTime * PI * 0.5 + 2.0);
    jTurn1 = vec4(cos(a1), sin(a1), cos(b1), sin(b1));
    jTurn2 = vec4(cos(a2), sin(a2), cos(b2), sin(b2));
#endif
#if VARIANT == 6
    float tSea = rd.y < -0.001 ? (-1.1 - ro.y) / rd.y : 99.0;
    tMax = min(tMax, tSea);
#elif VARIANT == 16 || VARIANT == 17
    float tSea = rd.y < -0.001 ? (-1.4 - ro.y) / rd.y : 99.0;
#endif
#if VARIANT != 14 && VARIANT != 16 && VARIANT != 17
    for (int i = 0; i < 22; i++) {
        vec3 q = ro + rd * t;
        float d = jEnv(q, q.xy - jPath(q.z));
        if (d < JEPS + JEPS * t) { hit = true; break; }
        t += d;
        steps += 1.0;
        if (t > tMax) break;
    }
#endif
    float tEnv = hit ? t : JFAR;
#if VARIANT == 6 || VARIANT == 16 || VARIANT == 17
    bool sea = !hit && tSea < JFAR;
    if (sea) tEnv = tSea;
#endif
    // The landmarks, as far as the scene was hit. A ray that ends its steps right at a surface
    // counts as on it: thin shells far off otherwise broke into speckle.
    float idx = -1.0;
    float to = 0.05;
    bool objHit = false;
    if (jAny > 0.5) {
        float d = 9.0;
        for (int i = 0; i < 28; i++) {
            vec3 q = ro + rd * to;
            d = jMarks(q, q.xy - jPath(q.z), idx);
            if (d < JEPS + JEPS * to) { objHit = true; break; }
            to += d;
            if (to > tEnv || to * rd.z > jFar) break;
        }
        if (!objHit && to < tEnv && to * rd.z < jFar && d < 0.02 + 0.015 * to) objHit = true;
    }
    float hue = jCam.x + uSeed.x + uMood.x;
    vec3 back = jBack(ro, rd, hue);
    vec3 col = back;
    float tHit = JFAR;
    if (objHit && to < tEnv) {
        vec3 q = ro + rd * to;
        col = jMarkShade(q, q.xy - jPath(q.z), rd, idx, hue + q.z / JZ);
        tHit = to;
    } else if (hit) {
        vec3 q = ro + rd * t;
        col = jEnvShade(q, q.xy - jPath(q.z), ro, rd, hue + q.z / JZ);
        tHit = t;
    }
#if VARIANT == 6 || VARIANT == 16 || VARIANT == 17
    else if (sea) {
        vec3 q = ro + rd * tSea;
#if VARIANT == 6
        col = jSea(q, rd, hue + q.z / JZ);
#elif VARIANT == 16
        col = jDeepFloor(q, rd, hue + q.z / JZ);
#else
        col = jRoad(q, hue + q.z / JZ);
#endif
        tHit = tSea;
    }
#endif
#if VARIANT == 11
    vec3 nK;
    float riseK;
    float hK;
    float tK = jKelp(ro, rd, min(tHit, JFAR), nK, riseK, hK);
    if (tK < tHit) {
        col = jKelpShade(nK, rd, riseK, hK, hue + tK * rd.z / JZ);
        tHit = tK;
    }
#endif
    col = mix(col, back, smoothstep(JFAR * 0.55, JFAR, tHit));
#if VARIANT == 11 || VARIANT == 13 || VARIANT == 16
    col = jWater(col, ro, rd, tHit, hue);
#elif VARIANT == 12 || VARIANT == 27
    col = jEmbers(col, ro, rd, tHit, hue);
#elif VARIANT == 14
    // The highway's lanes, dimmed where a structure stands in front of them.
    col += jCyber(ro, rd, hue) * (tHit < JFAR ? 0.35 : 1.0);
#endif
    col = jHoops(col, ro, rd, tHit, hue, JFAR);
    col = jBoard(col, ro, rd, tHit, hue, JFAR);
    // Rays that grazed something took more steps: a glow round its edges.
    col += colorAt(hue * 2.0 + 0.15) * smoothstep(8.0, 22.0, steps) * 0.1 * (0.5 + 1.5 * uKick);
    col = jStyle(col, hue);
    col = jSkyGrade(col, p);
    col = jWeather(col, p, tHit, hue, JFAR);
    col = jGate(col, sp, ro, fw, rt, up, tHit < JFAR, tHit);
#ifdef J_DEPTH
    gDepth = tHit < JFAR ? tHit / JDEPTH : 1.0;
#endif
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return jDrop(col, p);
}
#else
vec3 shade(vec2 p) {
    vec3 ro; vec3 fw; vec3 rt; vec3 up; vec2 sp; vec3 rd;
    jCamera(p, ro, fw, rt, up, sp, rd);

    float th = (0.12 + 0.2 * uLow + 0.15 * uKick) * (1.0 + 0.6 * uSeed.y);
#if VARIANT == 1
    th = th * 2.0 + 0.1;
#endif
    // Louder bars, thicker walls (uMood.z is the bar's energy, 0 when there is no grid).
    th *= uMood.z > 0.0 ? 0.7 + 0.6 * uMood.z : 1.0;
    float t = 0.05;
    float sheet = 1.0;
    float tube = 0.0;
    float steps = 0.0;
    bool hit = false;
#if VARIANT == 2
    // The bubbles are the dearest world per step and rarely need the last few.
    for (int i = 0; i < 16; i++) {
#else
    for (int i = 0; i < 20; i++) {
#endif
        vec3 q = ro + rd * t;
        vec2 o = q.xy - jPath(q.z);
#if VARIANT >= 21 && VARIANT <= 25
        jOff = o;
#endif
        sheet = jWorld(q, th);
        tube = 0.42 - length(o);
        float d = max(sheet, tube);
        if (d < JEPS + JEPS * t) { hit = true; break; }
        t += d;
        steps += 1.0;
        if (t > 5.0) break;
    }
    vec3 haze = colorAt(0.66) * 0.025;
    vec3 col = haze;
    vec3 q = ro + rd * t;
    float hue = jCam.x + q.z / JZ + uSeed.x + uMood.x;
    if (hit) {
        vec2 off = q.xy - jPath(q.z);
#if VARIANT >= 21 && VARIANT <= 25
        jOff = off;
#endif
        bool cut = tube > sheet;
        vec3 n = cut ? normalize(vec3(-off, 0.0)) : jNormal(q, th);
        if (cut) {
            // Where the tube cuts through the world: dark polished faces.
            col = colorAt(hue * 2.0 + 0.5) * (0.03 + 0.12 * clamp(dot(n, -rd), 0.0, 1.0));
        } else {
            col = jSurface(q, n, rd, hue);
        }
        // Neon along the cut edges, lit by the spectrum: bass on the floor, treble overhead.
        float a = abs(fastAtan2(off.x, -off.y)) / PI;
        float lvl = band(floor(a * 63.0));
        float edge = exp(-abs(sheet - tube) * 90.0);
        col += colorAt(a * 0.5 + hue * 2.0) * edge * (0.25 + 1.6 * lvl);
        // Rings racing forward along the tube, a quarter-period apart, brightest on the beat.
        float ring = pow(0.5 + 0.5 * sin(wrapA(q.z * 4.0 + jCam.z - uTime * PI * 16.0)), 30.0);
        col += colorAt(hue * 2.0 + 0.5) * ring * (0.15 + 0.6 * uBeat + 0.6 * uKick) * (cut ? 1.0 : 0.5);
    }
    // Rays that grazed walls took more steps: a cheap stand-in for the glow between them.
    col += colorAt(hue * 2.0 + 0.15) * smoothstep(6.0, 20.0, steps) * 0.12 * (0.5 + 1.5 * uKick);
    col = mix(col, haze, smoothstep(1.5, 5.0, t));
    col = jHoops(col, ro, rd, hit ? t : 5.0, jCam.x + uSeed.x + uMood.x, 5.0);

    col = jStyle(col, jCam.x + uSeed.x + uMood.x);
    col = jGate(col, sp, ro, fw, rt, up, hit, t);
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return jDrop(col, p);
}
#endif
"""

/**
 * The Journey's world shader, in two halves: one string literal of it outgrew the 64 KB a JVM
 * class file allows for a constant, so the halves are joined at run time.
 */
internal val JOURNEY_BODY: String = listOf(JOURNEY_BODY_A, JOURNEY_BODY_B).joinToString("")

