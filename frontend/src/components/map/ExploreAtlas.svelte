<script>
	// Sound atlas: every embedded track placed so that tracks that sound alike
	// sit close together (CLAP embeddings → t-SNE). Scroll to zoom. In Select
	// mode dragging draws a box; in Pan mode it moves the map.
	import { onMount, onDestroy } from 'svelte';
	import * as d3 from 'd3';
	import { ACCENT, flowOrder, fitCanvas, frameScheduler, pointerPos, familyColor } from './explore.js';
	import HoverCard from './HoverCard.svelte';
	import { MousePointerSquareDashed, Hand, Tag } from 'lucide-svelte';

	let { points, visible, selected, colorOf, onselect, pin = null } = $props();

	const PAD = 24;
	let container, canvas, ctx;
	let width = $state(0), height = $state(0);
	let scale = 1, offX = 0, offY = 0;
	let transform = d3.zoomIdentity;
	let zoom;
	let mode = $state('select'); // select | pan
	let showLabels = $state(true);
	let hover = $state({ i: -1, x: 0, y: 0 });
	let box = null, drag = null;

	const onMap = (p) => p.x != null && p.y != null;
	const bx = (x) => offX + x * scale;
	const by = (y) => offY + (1 - y) * scale;
	const sx = (x) => transform.applyX(bx(x));
	const sy = (y) => transform.applyY(by(y));

	// One label per genre family, placed on the family's densest patch of the
	// map rather than its average position (averages all land in the middle).
	const labels = $derived.by(() => {
		const G = 16, cells = new Map(), totals = new Map();
		for (const p of points) {
			if (!onMap(p) || !visible[p.i] || p.family === 'Unknown' || p.family === 'Other') continue;
			const key = p.family + '|' + Math.min(G - 1, Math.floor(p.x * G)) + '|' + Math.min(G - 1, Math.floor(p.y * G));
			cells.set(key, (cells.get(key) || 0) + 1);
			totals.set(p.family, (totals.get(p.family) || 0) + 1);
		}
		const best = new Map();
		for (const [key, n] of cells) {
			const [fam, gx, gy] = key.split('|');
			if (!best.has(fam) || best.get(fam).n < n) best.set(fam, { n, x: (+gx + 0.5) / G, y: (+gy + 0.5) / G });
		}
		return [...best.entries()]
			.map(([family, b]) => ({ family, x: b.x, y: b.y, total: totals.get(family) }))
			.filter((l) => l.total >= 15)
			.sort((a, b) => b.total - a.total);
	});

	function fit() {
		const s = Math.max(40, Math.min(width, height) - PAD * 2);
		scale = s; offX = (width - s) / 2; offY = (height - s) / 2;
	}

	function draw() {
		if (!ctx) return;
		ctx.clearRect(0, 0, width, height);
		const dim = selected.size > 0;
		const r = Math.max(1.6, 2.1 * Math.sqrt(transform.k));
		for (const p of points) {
			if (!visible[p.i] || !onMap(p)) continue;
			const x = sx(p.x), y = sy(p.y);
			if (x < -6 || x > width + 6 || y < -6 || y > height + 6) continue;
			const sel = selected.has(p.i), hov = p.i === hover.i;
			ctx.globalAlpha = hov ? 1 : dim ? (sel ? 0.95 : 0.08) : 0.75;
			ctx.fillStyle = hov ? '#fff' : colorOf(p);
			ctx.beginPath(); ctx.arc(x, y, hov ? r + 3 : sel ? r + 0.8 : r, 0, 6.2832); ctx.fill();
		}
		ctx.globalAlpha = 1;

		if (showLabels) {
			// Greedy placement: biggest families first, skip a label that would overlap one already drawn.
			const placed = [];
			ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
			for (const l of labels) {
				const x = sx(l.x), y = sy(l.y);
				const size = Math.min(17, 10 + Math.log2(l.total));
				ctx.font = `700 ${size}px Inter, sans-serif`;
				const w = ctx.measureText(l.family).width + 12, h = size + 8;
				const rect = { x0: x - w / 2, x1: x + w / 2, y0: y - h / 2, y1: y + h / 2 };
				if (rect.x1 < 0 || rect.x0 > width || rect.y1 < 0 || rect.y0 > height) continue;
				if (placed.some((q) => !(rect.x1 < q.x0 || rect.x0 > q.x1 || rect.y1 < q.y0 || rect.y0 > q.y1))) continue;
				placed.push(rect);
				ctx.fillStyle = 'rgba(8,12,20,0.72)';
				ctx.fillRect(rect.x0, rect.y0, w, h);
				ctx.fillStyle = familyColor(l.family);
				ctx.fillText(l.family, x, y + 1);
			}
		}

		if (pin) {
			const x = sx(pin.x), y = sy(pin.y);
			ctx.beginPath(); ctx.arc(x, y, 11, 0, 6.2832); ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 3; ctx.stroke();
			ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 6.2832); ctx.fillStyle = '#f59e0b'; ctx.fill();
		}

		if (box) {
			const x = Math.min(box.x0, box.x1), y = Math.min(box.y0, box.y1);
			ctx.fillStyle = 'rgba(34,211,238,0.08)'; ctx.strokeStyle = ACCENT; ctx.lineWidth = 1;
			ctx.fillRect(x, y, Math.abs(box.x1 - box.x0), Math.abs(box.y1 - box.y0));
			ctx.strokeRect(x, y, Math.abs(box.x1 - box.x0), Math.abs(box.y1 - box.y0));
		}
	}

	const requestDraw = frameScheduler(draw);
	$effect(() => { points; visible; selected; colorOf; labels; showLabels; pin; requestDraw(); });

	// Fly to a new vibe pin.
	$effect(() => {
		if (!pin || !zoom || !width) return;
		const t = d3.zoomIdentity.translate(width / 2, height / 2).scale(4).translate(-bx(pin.x), -by(pin.y));
		d3.select(canvas).transition().duration(600).call(zoom.transform, t);
	});

	function nearest(x, y) {
		let best = -1, bd = 144;
		for (const p of points) {
			if (!visible[p.i] || !onMap(p)) continue;
			const d = (sx(p.x) - x) ** 2 + (sy(p.y) - y) ** 2;
			if (d < bd) { bd = d; best = p.i; }
		}
		return best;
	}

	function onDown(ev) {
		if (mode !== 'select' || ev.button !== 0) return;
		const { x, y } = pointerPos(canvas, ev);
		drag = { x, y, moved: false };
	}
	function onMove(ev) {
		const { x, y } = pointerPos(canvas, ev);
		if (drag) {
			if (Math.abs(x - drag.x) + Math.abs(y - drag.y) > 4) drag.moved = true;
			if (drag.moved) { box = { x0: drag.x, y0: drag.y, x1: x, y1: y }; requestDraw(); return; }
		}
		const i = nearest(x, y);
		if (i !== hover.i) { hover = { i, x, y }; requestDraw(); } else hover = { i, x, y };
	}
	function onUp(ev) {
		if (mode !== 'select' || !drag) { drag = null; return; }
		const { x, y } = pointerPos(canvas, ev);
		if (drag.moved && box) {
			const xa = Math.min(box.x0, box.x1), xb = Math.max(box.x0, box.x1);
			const ya = Math.min(box.y0, box.y1), yb = Math.max(box.y0, box.y1);
			const idxs = points.filter((p) => {
				if (!visible[p.i] || !onMap(p)) return false;
				const px = sx(p.x), py = sy(p.y);
				return px >= xa && px <= xb && py >= ya && py <= yb;
			}).map((p) => p.i);
			if (idxs.length) {
				const ordered = flowOrder(idxs, (i) => points[i].x, (i) => points[i].y);
				onselect(ordered, `Sound region · ${dominantFamily(idxs)}`, { add: ev.shiftKey });
			}
		} else {
			const i = nearest(x, y);
			if (i >= 0) onselect([i], points[i].title, { toggle: true });
		}
		drag = null; box = null; requestDraw();
	}

	function dominantFamily(idxs) {
		const c = new Map();
		for (const i of idxs) c.set(points[i].family, (c.get(points[i].family) || 0) + 1);
		return [...c.entries()].sort((a, b) => b[1] - a[1])[0][0];
	}

	let cleanup;
	onMount(() => {
		zoom = d3.zoom().scaleExtent([0.7, 24])
			// In select mode only the wheel zooms; dragging draws the selection box.
			.filter((ev) => ev.type === 'wheel' || ev.type === 'dblclick' || mode === 'pan')
			.on('zoom', (ev) => { transform = ev.transform; requestDraw(); });
		d3.select(canvas).call(zoom);
		cleanup = fitCanvas(container, canvas, (w, h, c) => { width = w; height = h; ctx = c; fit(); requestDraw(); });
	});
	onDestroy(() => { cleanup?.(); requestDraw.cancel(); });

	const unmapped = $derived(points.filter((p) => visible[p.i] && !onMap(p)).length);
</script>

<div bind:this={container} class="relative w-full h-full">
	<canvas bind:this={canvas} onmousedown={onDown} onmousemove={onMove} onmouseup={onUp}
		onmouseleave={() => { drag = null; box = null; hover = { i: -1, x: 0, y: 0 }; requestDraw(); }}
		class="block select-none {mode === 'pan' ? 'cursor-grab' : 'cursor-crosshair'}"></canvas>

	<div class="absolute top-3 right-3 flex items-center gap-1 rounded-md bg-[var(--surface-container)]/90 backdrop-blur p-0.5 text-xs">
		<button onclick={() => (mode = 'select')} title="Drag to select" aria-pressed={mode === 'select'}
			class="flex items-center gap-1 px-2 py-1 rounded {mode === 'select' ? 'bg-[#22d3ee] text-black' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'}"><MousePointerSquareDashed class="w-3.5 h-3.5" /> Select</button>
		<button onclick={() => (mode = 'pan')} title="Drag to move the map" aria-pressed={mode === 'pan'}
			class="flex items-center gap-1 px-2 py-1 rounded {mode === 'pan' ? 'bg-[#22d3ee] text-black' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'}"><Hand class="w-3.5 h-3.5" /> Pan</button>
		<button onclick={() => (showLabels = !showLabels)} title="Genre labels" aria-pressed={showLabels}
			class="flex items-center gap-1 px-2 py-1 rounded {showLabels ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"><Tag class="w-3.5 h-3.5" /> Labels</button>
	</div>
	<p class="absolute top-3 left-3 text-xs text-[var(--text-muted)] max-w-[260px] leading-snug pointer-events-none">
		Close together = sounds alike. Scroll to zoom. {mode === 'select' ? 'Drag a box to select; Shift adds.' : 'Drag to move.'}
		{#if unmapped}<br /><span class="text-amber-400/80">{unmapped.toLocaleString()} matching tracks aren't on the atlas yet.</span>{/if}
	</p>
	{#if hover.i >= 0}<HoverCard p={points[hover.i]} x={hover.x} y={hover.y} {width} />{/if}
</div>
