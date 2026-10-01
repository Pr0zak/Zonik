<script>
	// Sound atlas: every embedded track placed so that tracks that sound alike
	// sit close together (CLAP embeddings → t-SNE). Scroll to zoom. In Select
	// mode dragging draws a box; in Pan mode it moves the map.
	import { onMount, onDestroy } from 'svelte';
	import * as d3 from 'd3';
	import { ACCENT, flowOrder, fitCanvas, frameScheduler, pointerPos, familyColor, heatRadius, drawHeat } from './explore.js';
	import HoverCard from './HoverCard.svelte';
	import { MousePointerSquareDashed, Hand, Tag } from 'lucide-svelte';

	let { points, visible, selected, colorOf, onselect, onfocus = () => {}, heat = false, pin = null, trail = null, territory = false } = $props();

	// Explored territory: the atlas cut into a G×G grid, each cell holding its
	// visible tracks and how many of them have been played.
	const G = 24;
	const cells = $derived.by(() => {
		if (!territory) return null;
		const m = new Map();
		for (const p of points) {
			if (!visible[p.i] || p.x == null || p.y == null) continue;
			const gx = Math.min(G - 1, Math.max(0, Math.floor(p.x * G))), gy = Math.min(G - 1, Math.max(0, Math.floor(p.y * G)));
			const k = gx * G + gy;
			let c = m.get(k);
			if (!c) { c = { gx, gy, n: 0, played: 0, unplayed: [] }; m.set(k, c); }
			c.n++;
			if (p.plays) c.played++; else c.unplayed.push(p.i);
		}
		return m;
	});
	const explored = $derived.by(() => {
		if (!cells) return null;
		let n = 0, played = 0;
		for (const c of cells.values()) { n += c.n; played += c.played; }
		return n ? Math.round((played / n) * 100) : 0;
	});
	let hoverCell = $state(null);

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

	function drawTerritory() {
		const step = 1 / G;
		for (const c of cells.values()) {
			const x0 = sx(c.gx * step), x1 = sx((c.gx + 1) * step);
			const y0 = sy((c.gy + 1) * step), y1 = sy(c.gy * step);
			if (x1 < 0 || x0 > width || y1 < 0 || y0 > height) continue;
			const pct = c.played / c.n;
			ctx.fillStyle = `rgba(34,211,238,${(0.05 + pct * 0.55).toFixed(3)})`;
			ctx.fillRect(x0 + 1, y0 + 1, x1 - x0 - 2, y1 - y0 - 2);
			if (hoverCell && hoverCell.gx === c.gx && hoverCell.gy === c.gy) {
				ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 2;
				ctx.strokeRect(x0 + 1, y0 + 1, x1 - x0 - 2, y1 - y0 - 2);
			}
			if (x1 - x0 > 30 && c.n >= 3) {
				ctx.font = '600 10px Inter, sans-serif';
				ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
				ctx.fillStyle = pct > 0.5 ? 'rgba(255,255,255,0.85)' : 'rgba(203,213,225,0.55)';
				ctx.fillText(Math.round(pct * 100) + '%', (x0 + x1) / 2, (y0 + y1) / 2);
			}
		}
	}

	function drawTrail() {
		const { steps, now, next } = trail;
		const xy = (i) => [sx(points[i].x), sy(points[i].y)];
		const n = steps.length;
		ctx.lineCap = 'round';
		// Shuffle jumps all over the map, so only the most recent hops are drawn
		// as a path; older plays stay as fading dots.
		const HOPS = 25, first = Math.max(1, n - HOPS);
		for (let k = first; k < n; k++) {
			const [ax, ay] = xy(steps[k - 1].i), [bx2, by2] = xy(steps[k].i);
			ctx.globalAlpha = 0.12 + 0.88 * ((k - first + 1) / (n - first));
			ctx.strokeStyle = ACCENT; ctx.lineWidth = 1.8;
			ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx2, by2); ctx.stroke();
		}
		for (let k = 0; k < n; k++) {
			const [x, y] = xy(steps[k].i);
			ctx.globalAlpha = k < n - HOPS ? 0.25 : 0.4 + 0.6 * ((k + 1) / n);
			ctx.fillStyle = ACCENT;
			ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 6.2832); ctx.fill();
		}
		ctx.globalAlpha = 1;
		// Queue: dashed from the current track (or the last play) through what's next.
		const from = now ?? (n ? steps[n - 1].i : null);
		if (from != null && next.length) {
			ctx.setLineDash([5, 4]); ctx.strokeStyle = 'rgba(230,237,243,0.75)'; ctx.lineWidth = 1.6;
			ctx.beginPath();
			const [fx, fy] = xy(from); ctx.moveTo(fx, fy);
			for (const i of next) { const [x, y] = xy(i); ctx.lineTo(x, y); }
			ctx.stroke(); ctx.setLineDash([]);
			ctx.font = '600 10px Inter, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
			next.forEach((i, k) => {
				const [x, y] = xy(i);
				ctx.fillStyle = '#0d1117'; ctx.strokeStyle = 'rgba(230,237,243,0.9)'; ctx.lineWidth = 1.4;
				ctx.beginPath(); ctx.arc(x, y, 5, 0, 6.2832); ctx.fill(); ctx.stroke();
				ctx.fillStyle = 'rgba(230,237,243,0.9)'; ctx.fillText('+' + (k + 1), x + 8, y);
			});
		}
		if (now != null) {
			const [x, y] = xy(now);
			ctx.fillStyle = 'rgba(34,211,238,0.3)'; ctx.beginPath(); ctx.arc(x, y, 12, 0, 6.2832); ctx.fill();
			ctx.fillStyle = ACCENT; ctx.beginPath(); ctx.arc(x, y, 6, 0, 6.2832); ctx.fill();
			ctx.font = '700 11px Inter, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
			ctx.fillStyle = 'rgba(8,12,20,0.75)';
			const label = 'Now · ' + (points[now].title || '');
			ctx.fillRect(x + 14, y - 9, ctx.measureText(label).width + 10, 18);
			ctx.fillStyle = ACCENT; ctx.fillText(label, x + 19, y);
		}
	}

	function draw() {
		if (!ctx) return;
		ctx.clearRect(0, 0, width, height);
		if (cells) drawTerritory();
		const dim = selected.size > 0;
		const quiet = trail && (trail.steps.length || trail.now != null);
		const r = Math.max(1.6, 2.1 * Math.sqrt(transform.k));
		const vis = [];
		for (const p of points) {
			if (!visible[p.i] || !onMap(p)) continue;
			const x = sx(p.x), y = sy(p.y);
			if (x < -6 || x > width + 6 || y < -6 || y > height + 6) continue;
			vis.push([p, x, y]);
		}
		if (heat && !dim) for (const [p, x, y] of vis) drawHeat(ctx, p, x, y, heatRadius(p, r), colorOf(p), true);
		for (const [p, x, y] of vis) {
			const sel = selected.has(p.i), hov = p.i === hover.i;
			ctx.globalAlpha = hov ? 1 : dim ? (sel ? 0.95 : 0.08) : quiet ? 0.3 : cells ? 0.55 : 0.75;
			ctx.fillStyle = hov ? '#fff' : colorOf(p);
			const pr = heat ? heatRadius(p, r) : r;
			ctx.beginPath(); ctx.arc(x, y, hov ? pr + 3 : sel ? pr + 0.8 : pr, 0, 6.2832); ctx.fill();
			if (heat && !dim) drawHeat(ctx, p, x, y, pr, null, false);
		}
		ctx.globalAlpha = 1;
		if (quiet) drawTrail();

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
	$effect(() => { points; visible; selected; colorOf; labels; showLabels; pin; heat; trail; cells; hoverCell; requestDraw(); });

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
		hoverCell = cells && i < 0 ? cellAt(x, y) : null;
	}
	function cellAt(x, y) {
		const bxv = (transform.invertX(x) - offX) / scale, byv = 1 - (transform.invertY(y) - offY) / scale;
		if (bxv < 0 || bxv >= 1 || byv < 0 || byv >= 1) return null;
		return cells.get(Math.floor(bxv * G) * G + Math.floor(byv * G)) || null;
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
			if (i >= 0) { onselect([i], points[i].title, { toggle: true }); onfocus(i); }
			else if (cells) {
				const c = cellAt(x, y);
				if (c?.unplayed.length) {
					const ordered = flowOrder(c.unplayed, (k) => points[k].x, (k) => points[k].y);
					onselect(ordered, `Unexplored · ${dominantFamily(c.unplayed)}`, { add: ev.shiftKey });
				}
			}
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
		onmouseleave={() => { drag = null; box = null; hover = { i: -1, x: 0, y: 0 }; hoverCell = null; requestDraw(); }}
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
		{#if explored != null}<br /><span class="text-[#22d3ee]">{explored}% of these tracks played.</span> Brighter cells are better explored; click a cell's empty space to select its unplayed tracks.{/if}
	</p>
	{#if hoverCell && hover.i < 0}
		<div class="absolute pointer-events-none z-10 px-2 py-1 rounded bg-black/85 text-white text-xs" style="left:{Math.min(hover.x + 14, width - 200)}px; top:{Math.max(hover.y - 30, 4)}px;">
			{hoverCell.played} of {hoverCell.n} played · <span class="text-amber-400">{hoverCell.unplayed.length} to explore</span>
		</div>
	{/if}
	{#if hover.i >= 0}<HoverCard p={points[hover.i]} x={hover.x} y={hover.y} {width} />{/if}
</div>
