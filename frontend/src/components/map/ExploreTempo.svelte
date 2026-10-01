<script>
	// Tempo against loudness. Axes span the 1st–99th percentile so a few bad
	// readings can't squash everything else; tracks outside that range are
	// pinned to the edge as rings. Drag a box to select, click a track to
	// toggle it.
	import { onMount, onDestroy } from 'svelte';
	import { percentile, fitCanvas, frameScheduler, pointerPos, heatRadius, drawHeat } from './explore.js';
	import HoverCard from './HoverCard.svelte';

	let { points, visible, selected, colorOf, onselect, onfocus = () => {}, heat = false } = $props();

	// The top band holds a tempo histogram: share of tracks owned against share of plays.
	const STRIP = 56;
	const PAD = { top: 20 + STRIP, right: 20, bottom: 38, left: 52 };
	let container, canvas, ctx;
	let width = $state(0), height = $state(0);
	let hover = $state({ i: -1, x: 0, y: 0 });
	let box = $state(null); // { x0, y0, x1, y1 } while dragging
	let drag = null;

	const ext = $derived.by(() => {
		const b = [], l = [];
		for (const p of points) { if (p.bpm > 0) b.push(p.bpm); if (p.loudness != null) l.push(p.loudness); }
		b.sort((m, n) => m - n); l.sort((m, n) => m - n);
		const pad = (lo, hi) => { const d = (hi - lo) * 0.04 || 1; return [lo - d, hi + d]; };
		const [bLo, bHi] = pad(percentile(b, 0.01), percentile(b, 0.99));
		const [lLo, lHi] = pad(percentile(l, 0.01), percentile(l, 0.99));
		return { bLo, bHi, lLo, lHi, bMed: percentile(b, 0.5), lMed: percentile(l, 0.5) };
	});

	const pw = () => Math.max(1, width - PAD.left - PAD.right);
	const ph = () => Math.max(1, height - PAD.top - PAD.bottom);
	const clamp01 = (t) => Math.min(1, Math.max(0, t));
	const tx = (bpm) => (bpm - ext.bLo) / (ext.bHi - ext.bLo);
	const ty = (db) => (db - ext.lLo) / (ext.lHi - ext.lLo);
	const sx = (bpm) => PAD.left + clamp01(tx(bpm)) * pw();
	const sy = (db) => PAD.top + (1 - clamp01(ty(db))) * ph();
	const plotted = (p) => p.bpm > 0 && p.loudness != null;

	const BINS = 24;
	const hist = $derived.by(() => {
		const own = new Array(BINS).fill(0), play = new Array(BINS).fill(0);
		let no = 0, np = 0;
		for (const p of points) {
			if (!visible[p.i] || !(p.bpm > 0)) continue;
			const b = Math.min(BINS - 1, Math.max(0, Math.floor(clamp01(tx(p.bpm)) * BINS)));
			own[b]++; no++;
			play[b] += p.plays || 0; np += p.plays || 0;
		}
		return { own: own.map((v) => (no ? v / no : 0)), play: play.map((v) => (np ? v / np : 0)), np };
	});

	function drawStrip() {
		const x0 = PAD.left, w = pw() / BINS, base = PAD.top - 14, h = STRIP - 18;
		const mx = Math.max(0.0001, ...hist.own, ...hist.play);
		for (let b = 0; b < BINS; b++) {
			const x = x0 + b * w;
			ctx.fillStyle = 'rgba(148,163,184,0.35)';
			const ho = (hist.own[b] / mx) * h;
			ctx.fillRect(x + 1, base - ho, w / 2 - 1, ho);
			ctx.fillStyle = 'rgba(34,211,238,0.8)';
			const hp = (hist.play[b] / mx) * h;
			ctx.fillRect(x + w / 2, base - hp, w / 2 - 1, hp);
		}
		ctx.font = '10px Inter, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
		ctx.fillStyle = 'rgba(148,163,184,0.75)';
		ctx.fillText('Share by tempo:', 8, 6);
		ctx.fillStyle = 'rgba(148,163,184,0.9)'; ctx.fillRect(92, 8, 8, 8);
		ctx.fillText('tracks owned', 104, 6);
		ctx.fillStyle = '#22d3ee'; ctx.fillRect(176, 8, 8, 8);
		ctx.fillStyle = 'rgba(148,163,184,0.75)';
		ctx.fillText(hist.np ? 'plays' : 'plays (none yet)', 188, 6);
		ctx.strokeStyle = 'rgba(148,163,184,0.15)'; ctx.beginPath(); ctx.moveTo(x0, base + 0.5); ctx.lineTo(width - PAD.right, base + 0.5); ctx.stroke();
	}
	
	function draw() {
		if (!ctx) return;
		ctx.clearRect(0, 0, width, height);
		const x0 = PAD.left, x1 = width - PAD.right, y0 = PAD.top, y1 = height - PAD.bottom;
		drawStrip();

		// grid + ticks
		ctx.font = '10px Inter, sans-serif';
		ctx.fillStyle = 'rgba(148,163,184,0.6)';
		ctx.strokeStyle = 'rgba(148,163,184,0.08)';
		ctx.lineWidth = 1;
		ctx.textAlign = 'center'; ctx.textBaseline = 'top';
		for (let b = Math.ceil(ext.bLo / 20) * 20; b <= ext.bHi; b += 20) {
			const x = sx(b);
			ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y1); ctx.stroke();
			ctx.fillText(String(b), x, y1 + 6);
		}
		ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
		const step = ext.lHi - ext.lLo > 12 ? 3 : 1;
		for (let d = Math.ceil(ext.lLo / step) * step; d <= ext.lHi; d += step) {
			const y = sy(d);
			ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
			ctx.fillText(d + ' dB', x0 - 6, y);
		}
		ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
		ctx.fillText('Tempo (BPM) →', (x0 + x1) / 2, height - 2);
		ctx.save(); ctx.translate(12, (y0 + y1) / 2); ctx.rotate(-Math.PI / 2); ctx.textBaseline = 'middle';
		ctx.fillText('Loudness →', 0, 0); ctx.restore();

		// medians
		ctx.setLineDash([4, 4]); ctx.strokeStyle = 'rgba(148,163,184,0.2)';
		ctx.beginPath();
		ctx.moveTo(sx(ext.bMed), y0); ctx.lineTo(sx(ext.bMed), y1);
		ctx.moveTo(x0, sy(ext.lMed)); ctx.lineTo(x1, sy(ext.lMed));
		ctx.stroke(); ctx.setLineDash([]);

		const dim = selected.size > 0;
		for (const p of points) {
			if (!visible[p.i] || !plotted(p)) continue;
			const x = sx(p.bpm), y = sy(p.loudness);
			const sel = selected.has(p.i), hov = p.i === hover.i;
			ctx.globalAlpha = hov ? 1 : dim ? (sel ? 0.95 : 0.1) : 0.7;
			if (p.bad) {
				ctx.strokeStyle = '#f87171';
				ctx.lineWidth = 1.5;
				ctx.beginPath(); ctx.arc(x, y, 4, 0, 6.2832); ctx.stroke();
			} else {
				ctx.fillStyle = hov ? '#fff' : colorOf(p);
				const r = heat ? heatRadius(p, 2.5) : 2.5;
				ctx.beginPath(); ctx.arc(x, y, hov ? r + 2 : r, 0, 6.2832); ctx.fill();
				if (heat && !dim) drawHeat(ctx, p, x, y, r, null, false);
			}
		}
		ctx.globalAlpha = 1;

		if (box) {
			ctx.fillStyle = 'rgba(34,211,238,0.08)'; ctx.strokeStyle = '#22d3ee'; ctx.lineWidth = 1;
			const bx = Math.min(box.x0, box.x1), by = Math.min(box.y0, box.y1);
			ctx.fillRect(bx, by, Math.abs(box.x1 - box.x0), Math.abs(box.y1 - box.y0));
			ctx.strokeRect(bx, by, Math.abs(box.x1 - box.x0), Math.abs(box.y1 - box.y0));
		}
	}

	const requestDraw = frameScheduler(draw);
	$effect(() => { points; visible; selected; colorOf; ext; hist; heat; requestDraw(); });

	function nearest(x, y) {
		let best = -1, bd = 64;
		for (const p of points) {
			if (!visible[p.i] || !plotted(p)) continue;
			const d = (sx(p.bpm) - x) ** 2 + (sy(p.loudness) - y) ** 2;
			if (d < bd) { bd = d; best = p.i; }
		}
		return best;
	}

	function onDown(ev) { const { x, y } = pointerPos(canvas, ev); drag = { x, y, moved: false }; }
	function onMove(ev) {
		const { x, y } = pointerPos(canvas, ev);
		if (drag) {
			if (Math.abs(x - drag.x) + Math.abs(y - drag.y) > 4) drag.moved = true;
			if (drag.moved) { box = { x0: drag.x, y0: drag.y, x1: x, y1: y }; hover = { i: -1, x, y }; requestDraw(); return; }
		}
		const i = nearest(x, y);
		if (i !== hover.i) { hover = { i, x, y }; requestDraw(); } else hover = { i, x, y };
	}
	function onUp(ev) {
		if (!drag) return;
		const { x, y } = pointerPos(canvas, ev);
		if (drag.moved && box) {
			const xa = Math.min(box.x0, box.x1), xb = Math.max(box.x0, box.x1);
			const ya = Math.min(box.y0, box.y1), yb = Math.max(box.y0, box.y1);
			const idxs = points.filter((p) => {
				if (!visible[p.i] || !plotted(p)) return false;
				const px = sx(p.bpm), py = sy(p.loudness);
				return px >= xa && px <= xb && py >= ya && py <= yb;
			}).map((p) => p.i).sort((a, b) => points[a].bpm - points[b].bpm);
			const inv = (px) => ext.bLo + ((px - PAD.left) / pw()) * (ext.bHi - ext.bLo);
			if (idxs.length) onselect(idxs, `${Math.round(inv(xa))}–${Math.round(inv(xb))} BPM`, { add: ev.shiftKey });
		} else {
			const i = nearest(x, y);
			if (i >= 0) { onselect([i], points[i].title, { toggle: true }); onfocus(i); }
		}
		drag = null; box = null; requestDraw();
	}

	let cleanup;
	onMount(() => {
		cleanup = fitCanvas(container, canvas, (w, h, c) => { width = w; height = h; ctx = c; requestDraw(); });
	});
	onDestroy(() => { cleanup?.(); requestDraw.cancel(); });
</script>

<div bind:this={container} class="relative w-full h-full">
	<canvas bind:this={canvas} onmousedown={onDown} onmousemove={onMove} onmouseup={onUp}
		onmouseleave={() => { drag = null; box = null; hover = { i: -1, x: 0, y: 0 }; requestDraw(); }}
		class="block cursor-crosshair select-none"></canvas>
	<p class="absolute top-1 right-4 text-xs text-[var(--text-muted)] pointer-events-none">
		Drag to select a region · click a track to toggle it · <span class="text-red-400">○</span> bad loudness reading
	</p>
	{#if hover.i >= 0}<HoverCard p={points[hover.i]} x={hover.x} y={hover.y} {width} />{/if}
</div>
