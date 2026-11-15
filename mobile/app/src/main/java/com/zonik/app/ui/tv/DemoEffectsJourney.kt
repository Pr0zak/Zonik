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
 *    rings, tunnels and hollow spheres to fly through, arches, monoliths and crystals to pass,
 *    more of them standing off the path, and giant towers and rings on the horizon.
 * 5. Canyon: rough walls in strata lit by the spectrum, a glowing river below, sky above.
 * 6. Sea stacks: low over water that mirrors a sunset, between columns of rock.
 * 7. Night city: down a street between towers whose windows flicker with the hi-hats.
 * 8. Orbital station: through square frames and along girders, over a planet.
 * 9. Asteroid field: between rough rocks whose cracks glow on the kick.
 * 10. Branching caves: a winding tunnel that opens into caverns, side tunnels branching off,
 *    crystal veins glowing with the spectrum.
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

// Landmarks: up to eight objects the CPU places along the route (JourneyLandmarks), from small
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
float jReach[8];
vec2 jSp;      // this pixel's point on screen, for the scenery's circles
float jAny;
float jAnyS;   // scenery (type + 10) this pixel can reach: intersected, not marched
float jFar;    // past this distance along z no landmark this pixel can reach remains

// The radius of a sphere round each shape (JourneyLandmarks.bound on the CPU): orb, crystal
// and cube, ring and hollow sphere, monolith, arch.
float jBound(vec4 a, vec4 b) {
    float ty = a.y;
    float k = ty < 2.5 ? 1.74 : (ty < 3.5 || (ty > 5.5 && ty < 6.5)) ? 1.0 : ty < 5.5 ? 2.3 : 1.7;
    return a.z * k + b.z + 0.45;
}

void jCull(vec2 sp) {
    jSp = sp;
    jAny = 0.0;
    jAnyS = 0.0;
    jFar = 0.0;
    for (int i = 0; i < 8; i++) {
        vec4 c = uMarkScr[i];
        vec4 a = uMarks[2 * i];
        float on = uPathOn > 0.5 ? (length(sp - c.xy) < c.z ? 1.0 : 0.0) : (a.y >= 0.0 ? 1.0 : 0.0);
        if (a.y > 9.5) {
            jAnyS += on;
            on = 0.0;
        }
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
    for (int i = 0; i < 8; i++) {
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
    for (int i = 0; i < 8; i++) if (float(i) == idx) a = uMarks[2 * i];
    return a;
}

vec4 jMarkB(float idx) {
    vec4 b = vec4(0.0);
    for (int i = 0; i < 8; i++) if (float(i) == idx) b = uMarks[2 * i + 1];
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

// Scenery: big structures well off the path (type + 10 in uMarks), never flown through. Rather
// than marched, each pixel's ray is intersected with them once in closed form, which costs
// next to nothing: marched, three of them in view took the Mali-470 three times as long as
// the whole sky. Boxes (monolith, the arch's posts and lintel), the crystal as four slabs, the
// sphere solved round the ray's nearest point (so 16-bit floats stay small), and the ring as
// a flat band.

#if VARIANT == 4
// Where along the ray |o + d·t| <= h holds: (entry, exit).
vec2 jSlab(float o, float d, float h) {
    float inv = 1.0 / (abs(d) < 0.001 ? 0.001 : d);
    float t1 = (-h - o) * inv;
    float t2 = (h - o) * inv;
    return vec2(min(t1, t2), max(t1, t2));
}

// The scenery's nearest hit along the ray (99 for none), its normal and slot.
float jScenery(vec3 ro, vec3 rd, out vec3 nrm, out float idx) {
    float best = 99.0;
    nrm = vec3(0.0, 0.0, -1.0);
    idx = -1.0;
    for (int i = 0; i < 8; i++) {
        vec4 a = uMarks[2 * i];
        if (a.y < 9.5) continue;
        if (uPathOn > 0.5 && length(jSp - uMarkScr[i].xy) >= uMarkScr[i].z) continue;
        vec4 b = uMarks[2 * i + 1];
        float ty = a.y - 10.0;
        float s = a.z;
        vec3 o = ro - vec3(b.xy, a.x);
        vec2 cs = vec2(cos(wrapA(a.w)), sin(wrapA(a.w)));
        // Into the shape's own frame (the spin jMarkD applies), and the normal back out.
        vec3 lo = vec3(o.x * cs.x - o.y * cs.y, o.x * cs.y + o.y * cs.x, o.z);
        vec3 ld = vec3(rd.x * cs.x - rd.y * cs.y, rd.x * cs.y + rd.y * cs.x, rd.z);
        float t = 99.0;
        vec3 n = vec3(0.0);
        if (ty > 5.5 && ty < 6.5) {
            // Sphere (seen from outside, a hollow one looks solid).
            float tc = -dot(o, rd);
            vec3 pc = o + rd * tc;
            float disc = s * s - dot(pc, pc);
            if (disc > 0.0) {
                t = tc - sqrt(disc);
                n = normalize(o + rd * t);
            }
        } else if (ty > 2.5 && ty < 3.5) {
            // Ring: a flat band facing along z.
            float tp = -o.z / (abs(rd.z) < 0.001 ? 0.001 : rd.z);
            vec3 pp = o + rd * tp;
            if (tp > 0.0 && abs(length(pp.xy) - s) < b.z * 2.0) {
                t = tp;
                n = vec3(0.0, 0.0, -sign(rd.z));
            }
        } else if (ty > 0.5 && ty < 1.5) {
            // Crystal: |x| + |y| + |z| <= s, the meeting of four slabs.
            vec3 n0 = vec3(1.0, 1.0, 1.0); vec3 n1 = vec3(1.0, 1.0, -1.0);
            vec3 n2 = vec3(1.0, -1.0, 1.0); vec3 n3 = vec3(-1.0, 1.0, 1.0);
            vec2 s0 = jSlab(dot(n0, lo), dot(n0, ld), s);
            vec2 s1 = jSlab(dot(n1, lo), dot(n1, ld), s);
            vec2 s2 = jSlab(dot(n2, lo), dot(n2, ld), s);
            vec2 s3 = jSlab(dot(n3, lo), dot(n3, ld), s);
            float tin = max(max(s0.x, s1.x), max(s2.x, s3.x));
            float tout = min(min(s0.y, s1.y), min(s2.y, s3.y));
            if (tin < tout && tin > 0.0) {
                t = tin;
                vec3 ln = tin == s0.x ? n0 * -sign(dot(n0, ld)) : tin == s1.x ? n1 * -sign(dot(n1, ld))
                        : tin == s2.x ? n2 * -sign(dot(n2, ld)) : n3 * -sign(dot(n3, ld));
                n = ln * 0.57735;
            }
        } else {
            // Boxes: a monolith, or an arch's two posts and lintel.
            for (int k = 0; k < 3; k++) {
                if (ty < 6.0 && k > 0) break;
                vec3 c = ty < 6.0 ? vec3(0.0) : (k == 2 ? vec3(0.0, s * 1.2, 0.0) : vec3(k == 0 ? -s : s, 0.0, 0.0));
                vec3 h = ty < 6.0 ? vec3(s * 0.35, s * 2.2, s * 0.35) : (k == 2 ? vec3(s + 0.22, 0.22, 0.22) : vec3(0.22, s * 1.2, 0.22));
                vec3 bo = lo - c;
                vec2 sx = jSlab(bo.x, ld.x, h.x);
                vec2 sy = jSlab(bo.y, ld.y, h.y);
                vec2 sz = jSlab(bo.z, ld.z, h.z);
                float tin = max(sx.x, max(sy.x, sz.x));
                float tout = min(sx.y, min(sy.y, sz.y));
                if (tin < tout && tin > 0.0 && tin < t) {
                    t = tin;
                    n = tin == sx.x ? vec3(-sign(ld.x), 0.0, 0.0) : tin == sy.x ? vec3(0.0, -sign(ld.y), 0.0) : vec3(0.0, 0.0, -sign(ld.z));
                }
            }
        }
        if (t < best) {
            best = t;
            idx = float(i);
            // Back to the world's frame: the spin's inverse.
            nrm = (ty > 2.5 && ty < 3.5) || (ty > 5.5 && ty < 6.5) ? n
                : vec3(n.x * cs.x + n.y * cs.y, -n.x * cs.y + n.y * cs.x, n.z);
        }
    }
    return best;
}
#endif

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
        sp = p;
        rd = normalize(fw * 1.3 + rt * p.x + up * p.y);
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
#if VARIANT == 3 || VARIANT == 4 || VARIANT == 5 || VARIANT == 6 || VARIANT == 7
    // A hall, the sky, a canyon, the sea or a city has a floor: bank gently, never roll over.
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

#if VARIANT >= 4
// ---- The open worlds ----------------------------------------------------------------------
// Each has a backdrop (jBack), a scene to fly through (jEnv: the distance to it, positive in
// the air, 9 for none) and a look for it (jEnvShade). shade() marches the scene, then the
// landmarks on their own as far as the scene was hit (see the enclosed worlds for why), and
// fogs everything into the backdrop towards JFAR.

#if VARIANT == 10
const float JFAR = 8.0;
#elif VARIANT == 9 || VARIANT == 5 || VARIANT == 7 || VARIANT == 8
const float JFAR = 14.0;
#else
const float JFAR = 17.0;
#endif

// Stars on the sky at a direction.
float jStars(vec3 rd) {
    vec2 sv = rd.xy / max(rd.z, 0.25) * 22.0;
    return step(0.975, hash(floor(sv))) * smoothstep(0.35, 0.0, length(fract(sv) - 0.5)) * (0.35 + 0.65 * uHigh);
}

#if VARIANT == 4
// Megastructures' horizon: giant towers and two standing rings, so far off they never come
// nearer, dark against the aurora with rims and bands of light from the spectrum. Worked out
// from the direction alone, so they cost a few operations a pixel and nothing in the march.
vec3 jHorizon(vec3 col, vec3 rd, float hue) {
    float az = fastAtan2(rd.x, rd.z) / PI;            // -1..1 round the horizon, 0 ahead
    float el = rd.y / max(length(rd.xz), 0.2);         // height above the horizon
    // Below -0.075 the grid floor (60 units out) is in front of them.
    if (el > 0.3 || el < -0.075) return col;
    float u = az * 16.0;
    float cell = floor(u);
    float f = fract(u) - 0.5;
    float h = hash(vec2(cell, 4.7));
    float w = 0.12 + 0.22 * hash(vec2(cell, 1.3));
    float top = 0.03 + 0.14 * smoothstep(0.4, 1.0, h);
    // A tower: dark, with a glowing rim and bands of windows lit by its own band.
    float tower = h > 0.4 ? step(abs(f), w) * step(el, top) : 0.0;
    float lvl = band(floor(fract(h * 7.3) * 63.0));
    float rim = tower * (exp(-(w - abs(f)) * 60.0) + exp(-(top - el) * 160.0));
    float rows = step(0.75, fract(el * 40.0)) * step(0.3, abs(f) / w) * step(abs(f), w * 0.8);
    // Two rings standing on the horizon, a little to either side.
    vec2 rc = vec2(abs(az) - 0.3, el - 0.05);
    float rr = abs(length(rc * vec2(PI, 1.0)) - 0.1);
    float ring = step(rr, 0.012);
    float ringRim = exp(-rr * 90.0);
    vec3 dark = colorAt(hue * 2.0 + 0.6) * 0.015;
    float solid = max(tower, ring);
    col = mix(col, dark, solid);
    vec3 c = colorAt(hue * 2.0 + h * 0.4 + 0.2);
    col += c * rim * (0.25 + 0.6 * lvl) * 0.6;
    col += c * rows * tower * lvl * 0.35;
    col += colorAt(hue * 2.0 + 0.5) * ringRim * (0.15 + 0.5 * uLow + 0.3 * uKick);
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
#else
    // Open sky (Megastructures, and above the canyon): dusk, stars, an aurora on the horizon
    // lit by the spectrum, and for Megastructures a glowing grid far below.
    vec3 col = mix(colorAt(hue * 2.0 + 0.1) * 0.14, colorAt(hue * 2.0 + 0.6) * 0.02, smoothstep(-0.15, 0.6, rd.y));
    float a = abs(fastAtan2(rd.x, rd.z)) / PI;
    col += colorAt(a + hue * 2.0) * band(floor(a * 63.0)) * exp(-abs(rd.y - 0.04) * 14.0) * 0.55;
    col += vec3(1.0) * jStars(rd);
#if VARIANT == 4
    col = jHorizon(col, rd, hue);
    if (rd.y < -0.01) {
        float tp = (-4.5 - ro.y) / rd.y;
        if (tp < 60.0) {
            vec2 g = vec2(ro.x + rd.x * tp, rd.z * tp + jCam.w);
            vec2 gg = abs(fract(g / (JCELL * 0.5)) - 0.5);
            float line = exp(-min(gg.x, gg.y) * 26.0);
            col += colorAt(hue * 2.0 + 0.3) * line * (0.12 + 0.6 * uLow) * exp(-tp * 0.045);
        }
    }
#endif
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
    float waves = 0.04 * sin(wrapA(3.0 * q.x + uTime * PI * 6.0)) * sin(wrapA(3.0 * q.z + jCam.y)) * (1.0 + 2.0 * uLow);
    return min(min(stack, JCELL * 0.45), q.y + 1.1 - waves);
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
    // Water mirrors the sky; the stacks are dark rock with a light at their tops.
    if (q.y < -0.95) {
        vec3 rr = reflect(rd, normalize(n + vec3(0.0, 2.0, 0.0)));
        return jBack(q, rr, hue) * 0.55 + colorAt(hue * 2.0 + 0.1) * pow(facing, 30.0) * 0.2;
    }
    vec3 col = colorAt(hue * 2.0 + 0.35) * (0.03 + 0.3 * facing * facing);
    return col + colorAt(hue * 2.0 + 0.1) * pow(1.0 - facing, 3.0) * (0.2 + 0.6 * uBeat);
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
#else
    return vec3(0.0);
#endif
}

vec3 shade(vec2 p) {
    vec3 ro; vec3 fw; vec3 rt; vec3 up; vec2 sp; vec3 rd;
    jCamera(p, ro, fw, rt, up, sp, rd);
    jCull(sp);
    float t = 0.05;
    float steps = 0.0;
    bool hit = false;
#if VARIANT != 4
    for (int i = 0; i < 22; i++) {
        vec3 q = ro + rd * t;
        float d = jEnv(q, q.xy - jPath(q.z));
        if (d < JEPS + JEPS * t) { hit = true; break; }
        t += d;
        steps += 1.0;
        if (t > JFAR) break;
    }
#endif
    float tEnv = hit ? t : JFAR;
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
    vec3 nS;
    float idxS;
#if VARIANT == 4
    float tS = jAnyS > 0.5 ? jScenery(ro, rd, nS, idxS) : 99.0;
#else
    // Only Megastructures has scenery (JourneyWorld.scenery).
    float tS = 99.0;
    nS = vec3(0.0);
    idxS = -1.0;
#endif
    float tObj = objHit && to < tEnv ? to : 99.0;
    if (tS < tEnv && tS < tObj) {
        vec3 q = ro + rd * tS;
        vec4 a = jMarkA(idxS);
        col = jMarkLook(q, nS, rd, vec4(a.x, a.y - 10.0, a.zw), jMarkB(idxS), hue + q.z / JZ);
        tHit = tS;
    } else if (tObj < 99.0) {
        vec3 q = ro + rd * to;
        col = jMarkShade(q, q.xy - jPath(q.z), rd, idx, hue + q.z / JZ);
        tHit = to;
    } else if (hit) {
        vec3 q = ro + rd * t;
        col = jEnvShade(q, q.xy - jPath(q.z), ro, rd, hue + q.z / JZ);
        tHit = t;
    }
    col = mix(col, back, smoothstep(JFAR * 0.55, JFAR, tHit));
    // Rays that grazed something took more steps: a glow round its edges.
    col += colorAt(hue * 2.0 + 0.15) * smoothstep(8.0, 22.0, steps) * 0.1 * (0.5 + 1.5 * uKick);
    col = jGate(col, sp, ro, fw, rt, up, tHit < JFAR, tHit);
    col *= clamp(1.3 - 0.3 * length(p), 0.0, 1.0);
    return col;
}
#else
vec3 shade(vec2 p) {
    vec3 ro; vec3 fw; vec3 rt; vec3 up; vec2 sp; vec3 rd;
    jCamera(p, ro, fw, rt, up, sp, rd);
    jCull(sp);

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
        sheet = jWorld(q, th);
        tube = 0.42 - length(q.xy - jPath(q.z));
        float d = max(sheet, tube);
        if (d < JEPS + JEPS * t) { hit = true; break; }
        t += d;
        steps += 1.0;
        if (t > 5.0) break;
    }
    // The landmarks get a short march of their own, after the world's and only as far as the
    // world was hit. Checked inside the world's march, the Mali-470 spent three times as long
    // on them as on the world itself, culled or not. Here only small objects inside the tube
    // appear, which need no path offset.
    float objId = -1.0;
    float to = 0.05;
    bool objHit = false;
    // Most rays reach no landmark at all: they skip this march.
    if (jAny > 0.5) {
        for (int i = 0; i < 12; i++) {
            vec3 q = ro + rd * to;
            float d = jMarks(q, vec2(1.0), objId);
            if (d < JEPS + JEPS * to) { objHit = true; break; }
            to += d;
            if (to > t) break;
        }
    }
    float obj = objHit && to < t ? 0.0 : 1.0;
    if (obj < 0.5) {
        t = to;
        hit = true;
    }

    vec3 haze = colorAt(0.66) * 0.025;
    vec3 col = haze;
    vec3 q = ro + rd * t;
    float hue = jCam.x + q.z / JZ + uSeed.x + uMood.x;
    if (hit && obj < 0.5) {
        col = jMarkShade(q, vec2(1.0), rd, objId, hue);
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
