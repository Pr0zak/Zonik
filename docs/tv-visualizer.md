# Google TV visualizer

Left idle (or opened from the actions strip), the Google TV app becomes a demo-scene music visualizer: 93 OpenGL ES 2 fragment-shader effects driven by the live FFT, the waveform, a 64-band spectrum and the server's per-track BPM. Each clip below is the real shader running against a simulated 120 bpm beat, with a stand-in cover.

Settings → Visualizer picks which effects rotate, how often they change, the transition (20 wipes, or Mixed) and its speed, where the colours come from (album art, random, cycling, or mixed per effect), and whether track info sits in the centre or a corner.

## Patterns and their variations

<table>
<tr><td align="center"><img src="visualizer/hexpulse.gif" alt="Hex pulse" width="240"><br><sub>Hex pulse</sub></td><td align="center"><img src="visualizer/hexradar.gif" alt="Hex radar" width="240"><br><sub>Hex radar</sub></td><td align="center"><img src="visualizer/tripulse.gif" alt="Triangle pulse" width="240"><br><sub>Triangle pulse</sub></td></tr>
<tr><td align="center"><img src="visualizer/hexflip.gif" alt="Hex flip" width="240"><br><sub>Hex flip</sub></td><td align="center"><img src="visualizer/cellpulse.gif" alt="Cell pulse" width="240"><br><sub>Cell pulse</sub></td><td align="center"><img src="visualizer/spectrumrings.gif" alt="Spectrum rings" width="240"><br><sub>Spectrum rings</sub></td></tr>
<tr><td align="center"><img src="visualizer/spectrumsquares.gif" alt="Square meter" width="240"><br><sub>Square meter</sub></td><td align="center"><img src="visualizer/spectrumspiral.gif" alt="Spiral meter" width="240"><br><sub>Spiral meter</sub></td><td align="center"><img src="visualizer/radar.gif" alt="Radar" width="240"><br><sub>Radar</sub></td></tr>
<tr><td align="center"><img src="visualizer/apollonian.gif" alt="Apollonian" width="240"><br><sub>Apollonian</sub></td><td align="center"><img src="visualizer/aponeon.gif" alt="Neon circles" width="240"><br><sub>Neon circles</sub></td><td align="center"><img src="visualizer/apopulse.gif" alt="Circle pulse" width="240"><br><sub>Circle pulse</sub></td></tr>
<tr><td align="center"><img src="visualizer/apoglass.gif" alt="Glass circles" width="240"><br><sub>Glass circles</sub></td><td align="center"><img src="visualizer/truchet.gif" alt="Truchet maze" width="240"><br><sub>Truchet maze</sub></td><td align="center"><img src="visualizer/hextruchet.gif" alt="Hex Truchet" width="240"><br><sub>Hex Truchet</sub></td></tr>
<tr><td align="center"><img src="visualizer/maze.gif" alt="Maze" width="240"><br><sub>Maze</sub></td><td align="center"><img src="visualizer/tubes.gif" alt="Truchet tubes" width="240"><br><sub>Truchet tubes</sub></td></tr>
</table>

## Trippy and beat-driven

<table>
<tr><td align="center"><img src="visualizer/hypno.gif" alt="Hypno spiral" width="240"><br><sub>Hypno spiral</sub></td><td align="center"><img src="visualizer/hypnorings.gif" alt="Hypno rings" width="240"><br><sub>Hypno rings</sub></td><td align="center"><img src="visualizer/kifs.gif" alt="Kaleido fractal" width="240"><br><sub>Kaleido fractal</sub></td></tr>
<tr><td align="center"><img src="visualizer/basslens.gif" alt="Bass lens" width="240"><br><sub>Bass lens</sub></td><td align="center"><img src="visualizer/opart.gif" alt="Op art" width="240"><br><sub>Op art</sub></td><td align="center"><img src="visualizer/marble.gif" alt="Liquid marble" width="240"><br><sub>Liquid marble</sub></td></tr>
<tr><td align="center"><img src="visualizer/rose.gif" alt="Rose curves" width="240"><br><sub>Rose curves</sub></td><td align="center"><img src="visualizer/pulsegrid.gif" alt="Pulse grid" width="240"><br><sub>Pulse grid</sub></td><td align="center"><img src="visualizer/lightning.gif" alt="Lightning" width="240"><br><sub>Lightning</sub></td></tr>
<tr><td align="center"><img src="visualizer/sacred.gif" alt="Flower of life" width="240"><br><sub>Flower of life</sub></td><td align="center"><img src="visualizer/strobekaleido.gif" alt="Strobe kaleido" width="240"><br><sub>Strobe kaleido</sub></td><td align="center"><img src="visualizer/lasers.gif" alt="Laser show" width="240"><br><sub>Laser show</sub></td></tr>
</table>

## Tunnels and flight

<table>
<tr><td align="center"><img src="visualizer/tunnel.gif" alt="Tunnel" width="240"><br><sub>Tunnel</sub></td><td align="center"><img src="visualizer/warptunnel.gif" alt="Warp tunnel" width="240"><br><sub>Warp tunnel</sub></td><td align="center"><img src="visualizer/wormhole.gif" alt="Wormhole" width="240"><br><sub>Wormhole</sub></td></tr>
<tr><td align="center"><img src="visualizer/hextunnel.gif" alt="Hex tunnel" width="240"><br><sub>Hex tunnel</sub></td><td align="center"><img src="visualizer/squaretunnel.gif" alt="Square tunnel" width="240"><br><sub>Square tunnel</sub></td><td align="center"><img src="visualizer/tritunnel.gif" alt="Triangle tunnel" width="240"><br><sub>Triangle tunnel</sub></td></tr>
<tr><td align="center"><img src="visualizer/octotunnel.gif" alt="Octagon tunnel" width="240"><br><sub>Octagon tunnel</sub></td><td align="center"><img src="visualizer/benttube.gif" alt="Bent tube" width="240"><br><sub>Bent tube</sub></td><td align="center"><img src="visualizer/dottunnel.gif" alt="Dot tunnel" width="240"><br><sub>Dot tunnel</sub></td></tr>
<tr><td align="center"><img src="visualizer/starfield.gif" alt="Starfield" width="240"><br><sub>Starfield</sub></td><td align="center"><img src="visualizer/nebula.gif" alt="Nebula stars" width="240"><br><sub>Nebula stars</sub></td><td align="center"><img src="visualizer/hyperspace.gif" alt="Hyperspace" width="240"><br><sub>Hyperspace</sub></td></tr>
<tr><td align="center"><img src="visualizer/rainbowwarp.gif" alt="Rainbow warp" width="240"><br><sub>Rainbow warp</sub></td><td align="center"><img src="visualizer/flyingcovers.gif" alt="Flying covers" width="240"><br><sub>Flying covers</sub></td><td align="center"><img src="visualizer/synthwave.gif" alt="Synthwave" width="240"><br><sub>Synthwave</sub></td></tr>
<tr><td align="center"><img src="visualizer/nightdrive.gif" alt="Night drive" width="240"><br><sub>Night drive</sub></td><td align="center"><img src="visualizer/voxel.gif" alt="Voxel hills" width="240"><br><sub>Voxel hills</sub></td><td align="center"><img src="visualizer/ocean.gif" alt="Ocean flyover" width="240"><br><sub>Ocean flyover</sub></td></tr>
<tr><td align="center"><img src="visualizer/moonlight.gif" alt="Moonlit ocean" width="240"><br><sub>Moonlit ocean</sub></td><td align="center"><img src="visualizer/city.gif" alt="City at night" width="240"><br><sub>City at night</sub></td><td align="center"><img src="visualizer/clouds.gif" alt="Cloud flight" width="240"><br><sub>Cloud flight</sub></td></tr>
<tr><td align="center"><img src="visualizer/planet.gif" alt="Planet flyby" width="240"><br><sub>Planet flyby</sub></td><td align="center"><img src="visualizer/skyline.gif" alt="Neon skyline" width="240"><br><sub>Neon skyline</sub></td><td align="center"><img src="visualizer/checker.gif" alt="Checkerboard" width="240"><br><sub>Checkerboard</sub></td></tr>
</table>

## Zooms and fractals

<table>
<tr><td align="center"><img src="visualizer/rotozoom.gif" alt="Rotozoomer" width="240"><br><sub>Rotozoomer</sub></td><td align="center"><img src="visualizer/kaleidoscope.gif" alt="Kaleidoscope" width="240"><br><sub>Kaleidoscope</sub></td><td align="center"><img src="visualizer/kaleidozoom.gif" alt="Kaleido zoom" width="240"><br><sub>Kaleido zoom</sub></td></tr>
<tr><td align="center"><img src="visualizer/kaleidoframe.gif" alt="Kaleido frame" width="240"><br><sub>Kaleido frame</sub></td><td align="center"><img src="visualizer/julia.gif" alt="Julia" width="240"><br><sub>Julia</sub></td><td align="center"><img src="visualizer/juliapulse.gif" alt="Julia pulse" width="240"><br><sub>Julia pulse</sub></td></tr>
<tr><td align="center"><img src="visualizer/mandelbrot.gif" alt="Mandelbrot" width="240"><br><sub>Mandelbrot</sub></td><td align="center"><img src="visualizer/droste.gif" alt="Droste zoom" width="240"><br><sub>Droste zoom</sub></td><td align="center"><img src="visualizer/drostespiral.gif" alt="Droste spiral" width="240"><br><sub>Droste spiral</sub></td></tr>
<tr><td align="center"><img src="visualizer/mosaic.gif" alt="Cover mosaic" width="240"><br><sub>Cover mosaic</sub></td><td align="center"><img src="visualizer/kaliset.gif" alt="Kaliset" width="240"><br><sub>Kaliset</sub></td><td align="center"><img src="visualizer/tilezoom.gif" alt="Tile zoom" width="240"><br><sub>Tile zoom</sub></td></tr>
<tr><td align="center"><img src="visualizer/deform.gif" alt="Deformations" width="240"><br><sub>Deformations</sub></td></tr>
</table>

## Spectrum and scopes

<table>
<tr><td align="center"><img src="visualizer/sunburst.gif" alt="Sunburst" width="240"><br><sub>Sunburst</sub></td><td align="center"><img src="visualizer/oscilloscope.gif" alt="Oscilloscope" width="240"><br><sub>Oscilloscope</sub></td><td align="center"><img src="visualizer/ledbars.gif" alt="LED bars" width="240"><br><sub>LED bars</sub></td></tr>
<tr><td align="center"><img src="visualizer/waterfall.gif" alt="Waterfall" width="240"><br><sub>Waterfall</sub></td><td align="center"><img src="visualizer/lissajous.gif" alt="Lissajous" width="240"><br><sub>Lissajous</sub></td><td align="center"><img src="visualizer/shockwave.gif" alt="Shockwaves" width="240"><br><sub>Shockwaves</sub></td></tr>
<tr><td align="center"><img src="visualizer/tracker.gif" alt="Tracker" width="240"><br><sub>Tracker</sub></td></tr>
</table>

## Classic demo

<table>
<tr><td align="center"><img src="visualizer/plasma.gif" alt="Plasma" width="240"><br><sub>Plasma</sub></td><td align="center"><img src="visualizer/acidplasma.gif" alt="Acid plasma" width="240"><br><sub>Acid plasma</sub></td><td align="center"><img src="visualizer/smoothplasma.gif" alt="Soft plasma" width="240"><br><sub>Soft plasma</sub></td></tr>
<tr><td align="center"><img src="visualizer/metaballs.gif" alt="Metaballs" width="240"><br><sub>Metaballs</sub></td><td align="center"><img src="visualizer/copper.gif" alt="Copper bars" width="240"><br><sub>Copper bars</sub></td><td align="center"><img src="visualizer/moire.gif" alt="Moiré" width="240"><br><sub>Moiré</sub></td></tr>
<tr><td align="center"><img src="visualizer/fire.gif" alt="Fire" width="240"><br><sub>Fire</sub></td><td align="center"><img src="visualizer/voronoi.gif" alt="Crystal" width="240"><br><sub>Crystal</sub></td><td align="center"><img src="visualizer/aurora.gif" alt="Aurora" width="240"><br><sub>Aurora</sub></td></tr>
<tr><td align="center"><img src="visualizer/shadebobs.gif" alt="Shadebobs" width="240"><br><sub>Shadebobs</sub></td><td align="center"><img src="visualizer/orbits.gif" alt="Orbits" width="240"><br><sub>Orbits</sub></td></tr>
</table>

## Cover treatments and feedback

<table>
<tr><td align="center"><img src="visualizer/godrays.gif" alt="God rays" width="240"><br><sub>God rays</sub></td><td align="center"><img src="visualizer/melt.gif" alt="Melt" width="240"><br><sub>Melt</sub></td><td align="center"><img src="visualizer/ink.gif" alt="Ink" width="240"><br><sub>Ink</sub></td></tr>
<tr><td align="center"><img src="visualizer/ripples.gif" alt="Water ripples" width="240"><br><sub>Water ripples</sub></td><td align="center"><img src="visualizer/vhs.gif" alt="VHS glitch" width="240"><br><sub>VHS glitch</sub></td><td align="center"><img src="visualizer/bump.gif" alt="Bump-mapped" width="240"><br><sub>Bump-mapped</sub></td></tr>
<tr><td align="center"><img src="visualizer/halftone.gif" alt="Halftone" width="240"><br><sub>Halftone</sub></td><td align="center"><img src="visualizer/ascii.gif" alt="ASCII" width="240"><br><sub>ASCII</sub></td><td align="center"><img src="visualizer/milkdrop.gif" alt="Milkdrop warp" width="240"><br><sub>Milkdrop warp</sub></td></tr>
</table>
