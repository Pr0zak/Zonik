<script>
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import { Play, X } from 'lucide-svelte';

	const ACCENT = '#22d3ee';

	// --- reactive UI state ---
	let loading = $state(true);
	let hover = $state({ i: -1, x: 0, y: 0 });
	let selection = $state([]); // indices captured by the lasso
	let dragRect = $state(null); // { x0, y0, x1, y1 } in CSS px while dragging

	// --- imperative render state ---
	let container, canvas, ctx;
	let dpr = 1, width = 0, height = 0;
	let data = null;
	let rafId = 0, ro = null;

	// data extents + medians
	let bpmMin = 0, bpmMax = 1, bpmMed = 0;
	let dbMin = -30, dbMax = 0, dbMed = -15;

	// plot area insets (room for axis labels)
	const PAD = { top: 24, right: 18, bottom: 36, left: 48 };

	let dragging = false;
	let dragStart = null; // { x, y } CSS px
	let dragMoved = false;

	// ---- scales (data → CSS px) ----
	const plotW = () => Math.max(1, width - PAD.left - PAD.right);
	const plotH = () => Math.max(1, height - PAD.top - PAD.bottom);
	function sx(bpm) {
		const t = (bpm - bpmMin) / (bpmMax - bpmMin || 1);
		return PAD.left + t * plotW();
	}
	function sy(db) {
		// LOUD at top → invert
		const t = (db - dbMin) / (dbMax - dbMin || 1);
		return PAD.top + (1 - t) * plotH();
	}

	function median(arr) {
		if (!arr.length) return 0;
		const s = [...arr].sort((a, b) => a - b);
		const m = Math.floor(s.length / 2);
		return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
	}

	// subtle gradient by BPM: slow = cool indigo, fast = cyan→amber
	function colorForBpm(bpm) {
		const t = Math.min(1, Math.max(0, (bpm - bpmMin) / (bpmMax - bpmMin || 1)));
		// interpolate indigo (99,102,241) → cyan (34,211,238) → amber (251,191,36)
		let r, g, b;
		if (t < 0.5) {
			const u = t / 0.5;
			r = 99 + (34 - 99) * u;
			g = 102 + (211 - 102) * u;
			b = 241 + (238 - 241) * u;
		} else {
			const u = (t - 0.5) / 0.5;
			r = 34 + (251 - 34) * u;
			g = 211 + (191 - 211) * u;
			b = 238 + (36 - 238) * u;
		}
		return `rgb(${r | 0},${g | 0},${b | 0})`;
	}

	function computeExtents() {
		const bpms = [], dbs = [];
		for (let i = 0; i < data.count; i++) {
			const bp = data.bpm[i], ld = data.loudness[i];
			if (bp != null) bpms.push(bp);
			if (ld != null) dbs.push(ld);
		}
		if (bpms.length) {
			bpmMin = Math.min(...bpms);
			bpmMax = Math.max(...bpms);
			bpmMed = median(bpms);
		}
		if (dbs.length) {
			const lo = Math.min(...dbs), hi = Math.max(...dbs);
			// clamp to a sensible dB window but keep data inside
			dbMin = Math.min(-30, Math.floor(lo));
			dbMax = Math.max(0, Math.ceil(hi));
			dbMed = median(dbs);
		}
	}

	function requestDraw() {
		if (!rafId) rafId = requestAnimationFrame(() => { rafId = 0; draw(); });
	}

	function draw() {
		if (!ctx || !data || !width || !height) return;
		ctx.clearRect(0, 0, width, height);

		const px0 = PAD.left, px1 = width - PAD.right;
		const py0 = PAD.top, py1 = height - PAD.bottom;

		// --- quadrant divider lines at the medians ---
		const mx = sx(bpmMed), my = sy(dbMed);
		ctx.save();
		ctx.strokeStyle = 'rgba(148,163,184,0.18)';
		ctx.lineWidth = 1;
		ctx.setLineDash([4, 4]);
		ctx.beginPath();
		ctx.moveTo(mx, py0); ctx.lineTo(mx, py1);
		ctx.moveTo(px0, my); ctx.lineTo(px1, my);
		ctx.stroke();
		ctx.setLineDash([]);
		ctx.restore();

		// --- corner labels ---
		ctx.save();
		ctx.font = '700 11px Inter, sans-serif';
		ctx.fillStyle = 'rgba(148,163,184,0.5)';
		ctx.textBaseline = 'top';
		ctx.textAlign = 'right';
		ctx.fillText('BANGERS', px1 - 6, py0 + 4); // fast + loud (top-right)
		ctx.textAlign = 'left';
		ctx.fillText('GROOVE', px0 + 6, py0 + 4); // slow + loud (top-left)
		ctx.textBaseline = 'bottom';
		ctx.fillText('LAID-BACK', px0 + 6, py1 - 4); // slow + soft (bottom-left)
		ctx.textAlign = 'right';
		ctx.fillText('DRIVING', px1 - 6, py1 - 4); // fast + soft (bottom-right)
		ctx.restore();

		// --- selection set for highlight ---
		const selSet = selection.length ? new Set(selection) : null;

		// --- dots ---
		const r = 2.6;
		for (let i = 0; i < data.count; i++) {
			const bp = data.bpm[i], ld = data.loudness[i];
			if (bp == null || ld == null) continue;
			const x = sx(bp), y = sy(ld);
			if (x < px0 - 6 || x > px1 + 6 || y < py0 - 6 || y > py1 + 6) continue;
			const isHover = hover.i === i;
			const isSel = selSet ? selSet.has(i) : true;
			ctx.beginPath();
			ctx.fillStyle = colorForBpm(bp);
			ctx.globalAlpha = isHover ? 1 : (selSet ? (isSel ? 0.92 : 0.12) : 0.6);
			ctx.arc(x, y, isHover ? r + 2.5 : (isSel && selSet ? r + 0.6 : r), 0, 6.2832);
			ctx.fill();
		}
		ctx.globalAlpha = 1;

		// --- axes labels ---
		ctx.save();
		ctx.fillStyle = 'rgba(148,163,184,0.7)';
		ctx.font = '600 11px Inter, sans-serif';
		ctx.textAlign = 'center';
		ctx.textBaseline = 'bottom';
		ctx.fillText('BPM  slow → fast', (px0 + px1) / 2, height - 8);
		// y label rotated
		ctx.translate(14, (py0 + py1) / 2);
		ctx.rotate(-Math.PI / 2);
		ctx.textBaseline = 'top';
		ctx.fillText('Loudness  soft → loud', 0, 0);
		ctx.restore();

		// --- axis tick values ---
		ctx.save();
		ctx.fillStyle = 'rgba(100,116,139,0.7)';
		ctx.font = '10px Inter, sans-serif';
		ctx.textAlign = 'left';
		ctx.textBaseline = 'bottom';
		ctx.fillText(Math.round(bpmMin) + '', px0, py1 + 16);
		ctx.textAlign = 'right';
		ctx.fillText(Math.round(bpmMax) + '', px1, py1 + 16);
		ctx.textAlign = 'right';
		ctx.textBaseline = 'top';
		ctx.fillText(dbMax + ' dB', px0 - 6, py0);
		ctx.textBaseline = 'bottom';
		ctx.fillText(dbMin + ' dB', px0 - 6, py1);
		ctx.restore();

		// --- lasso rectangle ---
		if (dragRect) {
			const x = Math.min(dragRect.x0, dragRect.x1);
			const y = Math.min(dragRect.y0, dragRect.y1);
			const w = Math.abs(dragRect.x1 - dragRect.x0);
			const h = Math.abs(dragRect.y1 - dragRect.y0);
			ctx.save();
			ctx.fillStyle = 'rgba(34,211,238,0.10)';
			ctx.strokeStyle = ACCENT;
			ctx.lineWidth = 1;
			ctx.setLineDash([5, 3]);
			ctx.fillRect(x, y, w, h);
			ctx.strokeRect(x, y, w, h);
			ctx.restore();
		}
	}

	function nearest(mx, my) {
		if (!data) return -1;
		let best = -1, bd = 100; // 10px radius²
		for (let i = 0; i < data.count; i++) {
			const bp = data.bpm[i], ld = data.loudness[i];
			if (bp == null || ld == null) continue;
			const dx = sx(bp) - mx, dy = sy(ld) - my;
			const d = dx * dx + dy * dy;
			if (d < bd) { bd = d; best = i; }
		}
		return best;
	}

	function pointInRect(i, x0, y0, x1, y1) {
		const bp = data.bpm[i], ld = data.loudness[i];
		if (bp == null || ld == null) return false;
		const x = sx(bp), y = sy(ld);
		return x >= x0 && x <= x1 && y >= y0 && y <= y1;
	}

	// ---- pointer handlers ----
	function pos(ev) {
		const rect = canvas.getBoundingClientRect();
		return { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
	}

	function onDown(ev) {
		if (ev.button !== 0) return;
		const p = pos(ev);
		dragging = true;
		dragMoved = false;
		dragStart = p;
		dragRect = null;
		canvas.setPointerCapture?.(ev.pointerId);
	}

	function onMove(ev) {
		const p = pos(ev);
		if (dragging && dragStart) {
			const dx = p.x - dragStart.x, dy = p.y - dragStart.y;
			if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragMoved = true;
			if (dragMoved) {
				dragRect = { x0: dragStart.x, y0: dragStart.y, x1: p.x, y1: p.y };
				if (hover.i !== -1) hover = { i: -1, x: 0, y: 0 };
				requestDraw();
			}
			return;
		}
		const i = nearest(p.x, p.y);
		if (i !== hover.i) { hover = { i, x: p.x, y: p.y }; requestDraw(); }
		else hover = { i, x: p.x, y: p.y };
	}

	function onUp(ev) {
		if (!dragging) return;
		dragging = false;
		canvas.releasePointerCapture?.(ev.pointerId);
		if (dragMoved && dragRect) {
			const x0 = Math.min(dragRect.x0, dragRect.x1);
			const y0 = Math.min(dragRect.y0, dragRect.y1);
			const x1 = Math.max(dragRect.x0, dragRect.x1);
			const y1 = Math.max(dragRect.y0, dragRect.y1);
			const picked = [];
			for (let i = 0; i < data.count; i++) {
				if (pointInRect(i, x0, y0, x1, y1)) picked.push(i);
			}
			selection = picked;
			dragRect = null;
			if (!picked.length) addToast('No tracks in that box', 'info');
			requestDraw();
		} else {
			// treat as a click
			dragRect = null;
			const i = nearest(ev ? pos(ev).x : 0, ev ? pos(ev).y : 0);
			if (i >= 0) playIndex(i);
		}
		dragStart = null;
		dragMoved = false;
	}

	function onLeave() {
		if (hover.i !== -1) { hover = { i: -1, x: 0, y: 0 }; requestDraw(); }
	}

	function playIndex(i) {
		storePlayTrack({ id: data.ids[i], title: data.title[i], artist: data.artist[i], album_id: data.album_id[i] });
		addToast(`Playing ${data.title[i]}`, 'success');
	}

	function playSelection() {
		if (!selection.length) return;
		const list = selection
			.map((i) => ({ id: data.ids[i], title: data.title[i], artist: data.artist[i], album_id: data.album_id[i], bpm: data.bpm[i] }))
			.sort((a, b) => a.bpm - b.bpm)
			.map(({ bpm, ...t }) => t);
		storePlayTrack(list[0], list);
		addToast(`Playing ${list.length} tracks (BPM ↑)`, 'success');
	}

	function clearSelection() {
		selection = [];
		requestDraw();
	}

	function resize() {
		if (!container || !canvas) return;
		const rect = container.getBoundingClientRect();
		width = Math.max(100, rect.width);
		height = Math.max(100, rect.height);
		dpr = window.devicePixelRatio || 1;
		canvas.width = Math.round(width * dpr);
		canvas.height = Math.round(height * dpr);
		canvas.style.width = width + 'px';
		canvas.style.height = height + 'px';
		ctx = canvas.getContext('2d');
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		requestDraw();
	}

	async function loadData() {
		try {
			const d = await api.getAudioFeatures();
			if (d && d.count > 0) {
				data = d;
				computeExtents();
				requestDraw();
			}
		} catch {
			addToast('Failed to load audio features', 'error');
		} finally {
			loading = false;
		}
	}

	const hoverTrack = $derived(
		data && hover.i >= 0
			? {
					title: data.title[hover.i],
					artist: data.artist[hover.i] || 'Unknown',
					bpm: Math.round(data.bpm[hover.i]),
					db: data.loudness[hover.i] != null ? data.loudness[hover.i].toFixed(1) : '—'
			  }
			: null
	);

	onMount(() => {
		resize();
		ro = new ResizeObserver(resize);
		ro.observe(container);
		loadData();
	});
	onDestroy(() => {
		if (ro) ro.disconnect();
		if (rafId) cancelAnimationFrame(rafId);
	});
</script>

<div bind:this={container} class="relative w-full h-full">
	<canvas
		bind:this={canvas}
		onpointerdown={onDown}
		onpointermove={onMove}
		onpointerup={onUp}
		onpointerleave={onLeave}
		class="block w-full h-full touch-none cursor-crosshair"
	></canvas>

	<!-- hover tooltip -->
	{#if hoverTrack}
		<div
			class="absolute pointer-events-none z-10 px-2.5 py-1.5 rounded-md bg-black/85 text-white text-xs max-w-[260px] shadow-lg"
			style="left:{Math.min(hover.x + 14, width - 200)}px; top:{Math.max(hover.y - 38, 4)}px;"
		>
			<div class="font-medium truncate">{hoverTrack.title}</div>
			<div class="text-white/60 truncate">{hoverTrack.artist}</div>
			<div class="text-white/45 mt-0.5 font-mono text-[10px]">{hoverTrack.bpm} BPM · {hoverTrack.db} dB</div>
		</div>
	{/if}

	<!-- selection action bar -->
	{#if selection.length}
		<div class="absolute top-3 right-3 z-10 flex items-center gap-2 rounded-lg bg-[var(--surface-container-high)]/90 backdrop-blur border border-[var(--border-subtle)] px-2.5 py-1.5 shadow-lg">
			<span class="text-xs text-[var(--text-secondary)]">{selection.length} selected</span>
			<button
				onclick={playSelection}
				class="flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-md bg-[#22d3ee] text-black hover:brightness-110 transition"
			>
				<Play class="w-3.5 h-3.5" /> Play {selection.length}
			</button>
			<button
				onclick={clearSelection}
				class="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container)] transition"
				title="Clear selection"
			>
				<X class="w-3.5 h-3.5" />
			</button>
		</div>
	{/if}

	<!-- hint -->
	{#if data && !selection.length && !loading}
		<div class="absolute bottom-3 right-3 z-0 pointer-events-none text-[10px] text-[var(--text-disabled)] bg-[var(--surface-container)]/70 backdrop-blur rounded px-2 py-1">
			click a dot to play · drag a box to select
		</div>
	{/if}

	<!-- loading -->
	{#if loading}
		<div class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[var(--surface-base)]/80">
			<div class="w-7 h-7 border-2 border-[#22d3ee] border-t-transparent rounded-full animate-spin"></div>
			<p class="text-sm text-[var(--text-secondary)]">Loading audio features…</p>
		</div>
	{/if}

	<!-- empty -->
	{#if !loading && (!data || !data.count)}
		<div class="absolute inset-0 flex items-center justify-center">
			<p class="text-sm text-[var(--text-muted)]">No analyzed tracks with BPM + loudness yet.</p>
		</div>
	{/if}
</div>
