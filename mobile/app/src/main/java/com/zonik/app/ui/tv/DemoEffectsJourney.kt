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
 * 4. Megastructures: open sky over a glowing grid, with nothing but the landmarks in it: giant
 *    rings, tunnels and hollow spheres to fly through, arches, monoliths and crystals to pass.
 *
 * Landmarks (uMarks, placed by JourneyLandmarks on the CPU) appear in every world: in the
 * enclosed ones only small objects inside the tube, now and then at random; in the open sky
 * the big structures too, timed so the camera reaches them on a downbeat or a drop.
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
internal const val JOURNEY_BODY = """
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
#elif VARIANT == 3
const float JCELL = 1.5707963;  // 6π / 12
const float JCELLS = 12.0;
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

// Landmarks: up to six objects the CPU places along the route (JourneyLandmarks), from small
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

// The nearest landmark's distance, and which slot it is in.
float jMarks(vec3 q, vec2 off, out float idx) {
    float d = 9.0;
    idx = -1.0;
    for (int i = 0; i < 6; i++) {
        vec4 a = uMarks[2 * i];
        vec4 b = uMarks[2 * i + 1];
        if (a.y < 0.0) continue;
        // Far along z from it, the gap in z is a safe step and the shape need not be worked out.
        float ext = (a.y > 3.5 && a.y < 4.5) ? a.w + 0.1 : a.z * 1.3 + b.z + 0.3;
        float dz = abs(q.z - a.x) - ext;
        float m = dz > 0.0 ? dz + 0.02 : jMarkD(q, off, a, b);
        if (m < d) {
            d = m;
            idx = float(i);
        }
    }
    return d;
}

vec4 jMarkA(float idx) {
    vec4 a = vec4(0.0);
    for (int i = 0; i < 6; i++) if (float(i) == idx) a = uMarks[2 * i];
    return a;
}

vec4 jMarkB(float idx) {
    vec4 b = vec4(0.0);
    for (int i = 0; i < 6; i++) if (float(i) == idx) b = uMarks[2 * i + 1];
    return b;
}

// A landmark's look at a hit: small ones lit from within by their own band of the spectrum,
// rings blazing, the big structures dark with glowing rims and light racing round them.
vec3 jMarkShade(vec3 q, vec2 off, vec3 rd, float idx, float hue) {
    vec4 a = jMarkA(idx);
    vec4 b = jMarkB(idx);
    const vec2 k = vec2(1.0, -1.0);
    const float h = 0.02;
    vec3 n = normalize(k.xyy * jMarkD(q + k.xyy * h, off + k.xy * h, a, b)
                     + k.yyx * jMarkD(q + k.yyx * h, off + k.yy * h, a, b)
                     + k.yxy * jMarkD(q + k.yxy * h, off + k.yx * h, a, b)
                     + k.xxx * jMarkD(q + k.xxx * h, off + k.xx * h, a, b));
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

// The camera's place, frame and this pixel's ray.
void jCamera(vec2 p, out vec3 ro, out vec3 fw, out vec3 rt, out vec3 up, out vec2 sp, out vec3 rd) {
    if (uPathOn > 0.5) {
        jCam = uCam;
        jCell = uCell;
        jCamZ = 0.0;
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
#if VARIANT == 3
    // A hall has a floor: bank gently instead of rolling right round.
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
    vec2 centre = vec2(dot(rel, rt), dot(rel, up)) * 1.3 / depth;
    float radius = 0.5 * 1.3 / depth;
    float ringD = abs(length(sp - centre) - radius);
    float seen = (hit && t < depth) ? 0.0 : 1.0;
    // The same colour as the iris rim that follows it, so gate and portal read as one ring.
    vec3 gc = vivid(uC0);
    col += gc * seen * (exp(-ringD * 120.0) * 1.4 + exp(-ringD * 14.0) * 0.25) * (0.7 + 0.8 * uBeat);
    col += gc * seen * smoothstep(radius, 0.0, length(sp - centre)) * 0.08;
    return col;
}

#if VARIANT == 4
// Megastructures: open sky. A dusk gradient, stars, an aurora along the horizon lit by the
// spectrum and a glowing grid far below, with nothing in the way but the landmarks.
vec3 jSky(vec3 ro, vec3 rd, float hue) {
    vec3 col = mix(colorAt(hue * 2.0 + 0.1) * 0.14, colorAt(hue * 2.0 + 0.6) * 0.02, smoothstep(-0.15, 0.6, rd.y));
    float a = abs(fastAtan2(rd.x, rd.z)) / PI;
    col += colorAt(a + hue * 2.0) * band(floor(a * 63.0)) * exp(-abs(rd.y - 0.04) * 14.0) * 0.55;
    vec2 sv = rd.xy / max(rd.z, 0.25) * 22.0;
    float st = hash(floor(sv));
    col += vec3(1.0) * step(0.975, st) * smoothstep(0.35, 0.0, length(fract(sv) - 0.5)) * (0.35 + 0.65 * uHigh);
    if (rd.y < -0.01) {
        float tp = (-4.5 - ro.y) / rd.y;
        if (tp < 60.0) {
            vec2 g = vec2(ro.x + rd.x * tp, rd.z * tp + jCam.w);
            vec2 gg = abs(fract(g / (JCELL * 0.5)) - 0.5);
            float line = exp(-min(gg.x, gg.y) * 26.0);
            col += colorAt(hue * 2.0 + 0.3) * line * (0.12 + 0.6 * uLow) * exp(-tp * 0.045);
        }
    }
    return col;
}

vec3 shade(vec2 p) {
    vec3 ro; vec3 fw; vec3 rt; vec3 up; vec2 sp; vec3 rd;
    jCamera(p, ro, fw, rt, up, sp, rd);
    float t = 0.05;
    float idx = -1.0;
    float steps = 0.0;
    bool hit = false;
    for (int i = 0; i < 24; i++) {
        vec3 q = ro + rd * t;
        float d = jMarks(q, q.xy - jPath(q.z), idx);
        if (d < JEPS + JEPS * t) { hit = true; break; }
        t += d;
        steps += 1.0;
        if (t > 18.0) break;
    }
    float hue = jCam.x + uSeed.x + uMood.x;
    vec3 sky = jSky(ro, rd, hue);
    vec3 col = sky;
    if (hit) {
        vec3 q = ro + rd * t;
        col = jMarkShade(q, q.xy - jPath(q.z), rd, idx, hue + q.z / JZ);
        col = mix(col, sky, smoothstep(10.0, 18.0, t));
    }
    // Rays that grazed a structure took more steps: a glow round its edges.
    col += colorAt(hue * 2.0 + 0.15) * smoothstep(8.0, 24.0, steps) * 0.12 * (0.5 + 1.5 * uKick);
    col = jGate(col, sp, ro, fw, rt, up, hit, t);
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
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
    float obj = 1.0;
    float objId = 0.0;
    float steps = 0.0;
    bool hit = false;
    for (int i = 0; i < 20; i++) {
        vec3 q = ro + rd * t;
        vec2 off = q.xy - jPath(q.z);
        sheet = jWorld(q, th);
        tube = 0.42 - length(off);
        obj = jMarks(q, off, objId);
        float d = min(max(sheet, tube), obj);
        if (d < JEPS + JEPS * t) { hit = true; break; }
        t += d;
        steps += 1.0;
        if (t > 5.0) break;
    }

    vec3 haze = colorAt(0.66) * 0.025;
    vec3 col = haze;
    vec3 q = ro + rd * t;
    float hue = jCam.x + q.z / JZ + uSeed.x + uMood.x;
    if (hit && obj < max(sheet, tube)) {
        col = jMarkShade(q, q.xy - jPath(q.z), rd, objId, hue);
    } else if (hit) {
        vec2 off = q.xy - jPath(q.z);
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

    col = jGate(col, sp, ro, fw, rt, up, hit, t);
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
#endif
"""
