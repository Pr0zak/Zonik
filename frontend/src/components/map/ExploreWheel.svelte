<script>
	// Camelot wheel: 12 keys around, minor (A) inside, major (B) outside; a
	// dot's distance from the hub within its ring is its tempo. Click a dot to
	// select everything that mixes harmonically with it, or an empty part of a
	// key segment to select that whole key.
	import { onMount, onDestroy } from 'svelte';
	import { ACCENT, isCompat, rand, fitCanvas, frameScheduler, pointerPos } from './explore.js';
	import HoverCard from './HoverCard.svelte';

	let { points, visible, selected, colorOf, onselect } = $props();

	let container, canvas, ctx;
	let width = $state(0), height = $state(0);
	let cx = 0, cy = 0, rOuter = 0, rInner = 0, rMid = 0;
	let pos = new Float32Array(0); // x,y per point (NaN when unkeyed)
	let hover = $state({ i: -1, seg: null, x: 0, y: 0 });

	const code = (seg) => seg.num + seg.letter;
	const sectorAngle = (num) => -Math.PI / 2 + (num - 1) * (Math.PI / 6);

	// Tracks per key among the visible set, for segment shading + hover counts.
	const counts = $derived.by(() => {
		const c = {};
		for (const p of points) if (p.cam && visible[p.i]) c[p.cam.num + p.cam.letter] = (c[p.cam.num + p.cam.letter] || 0) + 1;
		return c;
	});

	function layout() {
		cx = width / 2; cy = height / 2;
		rOuter = Math.max(40, Math.min(width, height) / 2 - 34);
		rInner = rOuter * 0.3; rMid = rOuter * 0.65;
		const half = (Math.PI / 12) * 0.82;
		let bMin = Infinity, bMax = -Infinity;
		for (const p of points) if (p.bpm > 0) { bMin = Math.min(bMin, p.bpm); bMax = Math.max(bMax, p.bpm); }
		const span = bMax - bMin || 1;
		pos = new Float32Array(points.length * 2).fill(NaN);
		for (const p of points) {
			if (!p.cam) continue;
			const a = sectorAngle(p.cam.num) + (rand(p.i + 1) * 2 - 1) * half;
			const lo = p.cam.letter === 'A' ? rInner : rMid, hi = p.cam.letter === 'A' ? rMid : rOuter;
			const t = (p.bpm > 0 ? (p.bpm - bMin) / span : rand(p.i + 7)) * 0.82 + rand(p.i + 31) * 0.18;
			const r = lo + (hi - lo) * (0.1 + 0.8 * t);
			pos[p.i * 2] = cx + Math.cos(a) * r;
			pos[p.i * 2 + 1] = cy + Math.sin(a) * r;
		}
	}

	function segmentAt(x, y) {
		const dx = x - cx, dy = y - cy, r = Math.hypot(dx, dy);
		if (r < rInner || r > rOuter) return null;
		const a = Math.atan2(dy, dx) + Math.PI / 2;
		const num = ((Math.round(a / (Math.PI / 6)) % 12) + 12) % 12 + 1;
		return { num, letter: r < rMid ? 'A' : 'B' };
	}

	function annular(num, r0, r1) {
		const a0 = sectorAngle(num) - Math.PI / 12, a1 = sectorAngle(num) + Math.PI / 12;
		ctx.beginPath();
		ctx.arc(cx, cy, r1, a0, a1);
		ctx.arc(cx, cy, r0, a1, a0, true);
		ctx.closePath();
	}

	function draw() {
		if (!ctx) return;
		ctx.clearRect(0, 0, width, height);
		const max = Math.max(1, ...Object.values(counts));

		// segment shading: busier keys glow brighter
		for (let n = 1; n <= 12; n++) {
			for (const letter of ['A', 'B']) {
				const c = counts[n + letter] || 0;
				annular(n, letter === 'A' ? rInner : rMid, letter === 'A' ? rMid : rOuter);
				ctx.fillStyle = `rgba(34,211,238,${(0.02 + 0.16 * (c / max)).toFixed(3)})`;
				ctx.fill();
				if (hover.seg && hover.i < 0 && hover.seg.num === n && hover.seg.letter === letter) {
					ctx.strokeStyle = ACCENT; ctx.lineWidth = 1.5; ctx.stroke();
				}
			}
		}
		ctx.lineWidth = 1;
		ctx.strokeStyle = 'rgba(148,163,184,0.18)';
		for (const r of [rInner, rMid, rOuter]) { ctx.beginPath(); ctx.arc(cx, cy, r, 0, 6.2832); ctx.stroke(); }

		ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
		for (let n = 1; n <= 12; n++) {
			const d = sectorAngle(n) - Math.PI / 12;
			ctx.beginPath();
			ctx.moveTo(cx + Math.cos(d) * rInner, cy + Math.sin(d) * rInner);
			ctx.lineTo(cx + Math.cos(d) * rOuter, cy + Math.sin(d) * rOuter);
			ctx.strokeStyle = 'rgba(148,163,184,0.13)'; ctx.stroke();
			const a = sectorAngle(n);
			ctx.font = '700 13px Inter, sans-serif';
			ctx.fillStyle = 'rgba(226,232,240,0.85)';
			ctx.fillText(n + 'B', cx + Math.cos(a) * (rOuter + 16), cy + Math.sin(a) * (rOuter + 16));
			ctx.font = '600 11px Inter, sans-serif';
			ctx.fillStyle = 'rgba(203,213,225,0.5)';
			ctx.fillText(n + 'A', cx + Math.cos(a) * (rInner - 12), cy + Math.sin(a) * (rInner - 12));
		}

		const dim = selected.size > 0;
		for (const p of points) {
			const x = pos[p.i * 2];
			if (!visible[p.i] || Number.isNaN(x)) continue;
			const y = pos[p.i * 2 + 1];
			const sel = selected.has(p.i), hov = p.i === hover.i;
			ctx.globalAlpha = hov ? 1 : dim ? (sel ? 0.95 : 0.1) : 0.75;
			ctx.fillStyle = hov ? '#fff' : colorOf(p);
			ctx.beginPath();
			ctx.arc(x, y, hov ? 4.5 : sel ? 3 : 2.3, 0, 6.2832);
			ctx.fill();
		}
		ctx.globalAlpha = 1;

		ctx.fillStyle = 'rgba(148,163,184,0.5)';
		ctx.font = '600 11px Inter, sans-serif';
		ctx.fillText('inner: minor · outer: major', cx, cy - 7);
		ctx.fillText('further out = faster', cx, cy + 8);
	}

	const requestDraw = frameScheduler(draw);
	$effect(() => { points; visible; selected; colorOf; counts; requestDraw(); });
	$effect(() => { points; if (width) { layout(); requestDraw(); } });

	function nearest(x, y) {
		let best = -1, bd = 100;
		for (const p of points) {
			if (!visible[p.i]) continue;
			const px = pos[p.i * 2];
			if (Number.isNaN(px)) continue;
			const d = (px - x) ** 2 + (pos[p.i * 2 + 1] - y) ** 2;
			if (d < bd) { bd = d; best = p.i; }
		}
		return best;
	}

	function onMove(ev) {
		const { x, y } = pointerPos(canvas, ev);
		const i = nearest(x, y);
		const seg = segmentAt(x, y);
		const changed = i !== hover.i || (seg && code(seg)) !== (hover.seg && code(hover.seg));
		hover = { i, seg, x, y };
		if (changed) requestDraw();
	}
	function onLeave() { hover = { i: -1, seg: null, x: 0, y: 0 }; requestDraw(); }

	function byTempo(idxs) { return idxs.sort((a, b) => (points[a].bpm || 999) - (points[b].bpm || 999)); }

	function onClick(ev) {
		const { x, y } = pointerPos(canvas, ev);
		const i = nearest(x, y);
		const add = ev.shiftKey;
		if (i >= 0 && points[i].cam) {
			const { num, letter } = points[i].cam;
			const idxs = points.filter((p) => visible[p.i] && p.cam && isCompat(p.cam.num, p.cam.letter, num, letter)).map((p) => p.i);
			onselect(byTempo(idxs), `Harmonic mix · ${num}${letter} (${points[i].title})`, { add });
			return;
		}
		const seg = segmentAt(x, y);
		if (seg) {
			const idxs = points.filter((p) => visible[p.i] && p.cam && p.cam.num === seg.num && p.cam.letter === seg.letter).map((p) => p.i);
			onselect(byTempo(idxs), `Key ${code(seg)}`, { add });
		}
	}

	let cleanup;
	onMount(() => {
		cleanup = fitCanvas(container, canvas, (w, h, c) => { width = w; height = h; ctx = c; layout(); requestDraw(); });
	});
	onDestroy(() => { cleanup?.(); requestDraw.cancel(); });
</script>

<div bind:this={container} class="relative w-full h-full">
	<canvas bind:this={canvas} onmousemove={onMove} onmouseleave={onLeave} onclick={onClick} class="block cursor-pointer"></canvas>
	<p class="absolute top-3 left-3 text-xs text-[var(--text-muted)] max-w-[220px] leading-snug pointer-events-none">
		Click a track to select everything that mixes with it. Click an empty part of a key to take the whole key. Shift adds.
	</p>
	{#if hover.i >= 0}
		<HoverCard p={points[hover.i]} x={hover.x} y={hover.y} {width} />
	{:else if hover.seg}
		<div class="absolute pointer-events-none z-10 px-2 py-1 rounded bg-black/85 text-white text-xs" style="left:{Math.min(hover.x + 14, width - 140)}px; top:{Math.max(hover.y - 30, 4)}px;">
			<span class="font-mono text-[#22d3ee]">{code(hover.seg)}</span> · {(counts[code(hover.seg)] || 0).toLocaleString()} tracks
		</div>
	{/if}
</div>
