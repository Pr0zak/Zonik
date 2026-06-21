<script>
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import { Play, X } from 'lucide-svelte';

	const ACCENT = '#22d3ee';

	// --- reactive UI state ---
	let loading = $state(true);
	let count = $state(0);
	let mapped = $state(0);
	let hover = $state({ i: -1, x: 0, y: 0 });
	let selected = $state(-1); // index of clicked track
	let compatCount = $state(0);

	// --- imperative render state ---
	let container, canvas, ctx;
	let dpr = 1;
	let width = $state(0), height = $state(0);
	let cx = 0, cy = 0, rOuter = 0;
	let data = null;          // raw audio-features payload
	let pts = [];             // [{ i, code, num, letter, bpm, px, py, r }] in canvas coords (pre-transform-free)
	let codeOf = [];          // per-track camelot code string or null
	let numOf = [];           // per-track number 1..12 or 0
	let letterOf = [];        // per-track 'A' | 'B' | ''
	let compatSet = new Set();// indices compatible with `selected`
	let rafId = 0, ro = null;

	// Camelot lookups. Normalise enharmonics to a canonical pitch-class name.
	const ENHARM = {
		'C': 'C', 'B#': 'C', 'Dbb': 'C',
		'C#': 'C#', 'Db': 'C#',
		'D': 'D',
		'D#': 'D#', 'Eb': 'D#',
		'E': 'E', 'Fb': 'E',
		'F': 'F', 'E#': 'F',
		'F#': 'F#', 'Gb': 'F#',
		'G': 'G',
		'G#': 'G#', 'Ab': 'G#',
		'A': 'A',
		'A#': 'A#', 'Bb': 'A#',
		'B': 'B', 'Cb': 'B'
	};
	const MAJOR = { 'C': 8, 'G': 9, 'D': 10, 'A': 11, 'E': 12, 'B': 1, 'F#': 2, 'C#': 3, 'G#': 4, 'D#': 5, 'A#': 6, 'F': 7 };
	const MINOR = { 'C': 5, 'G': 6, 'D': 7, 'A': 8, 'E': 9, 'B': 10, 'F#': 11, 'C#': 12, 'G#': 1, 'D#': 2, 'A#': 3, 'F': 4 };

	function normKey(k) {
		if (!k) return null;
		let s = String(k).trim();
		if (!s) return null;
		// Capitalise the letter, keep accidental as-is (handle unicode sharp/flat just in case).
		s = s.replace('♯', '#').replace('♭', 'b');
		const letter = s[0].toUpperCase();
		const acc = s.slice(1);
		const cand = letter + acc;
		return ENHARM[cand] ?? ENHARM[letter] ?? null;
	}
	function camelot(key, scale) {
		const pc = normKey(key);
		if (!pc) return null;
		const minor = String(scale || '').toLowerCase().startsWith('min');
		const num = minor ? MINOR[pc] : MAJOR[pc];
		if (!num) return null;
		const letter = minor ? 'A' : 'B';
		return { code: num + letter, num, letter };
	}

	// Sector angle for a Camelot number: 1 at top (−90°), clockwise.
	function sectorAngle(num) { return -Math.PI / 2 + (num - 1) * (Math.PI / 6); }

	// Deterministic jitter from track index so dots don't dance between redraws.
	function rand(seed) {
		const s = Math.sin(seed * 12.9898) * 43758.5453;
		return s - Math.floor(s);
	}

	function isCompat(num, letter, snum, sletter) {
		if (num === snum && letter === sletter) return true;          // exact
		if (letter === sletter) {                                      // ±1 same letter, wrap 12→1
			const up = (snum % 12) + 1;
			const down = ((snum - 2 + 12) % 12) + 1;
			if (num === up || num === down) return true;
		}
		if (num === snum && letter !== sletter) return true;           // relative major/minor
		return false;
	}

	function recomputeCompat() {
		compatSet = new Set();
		if (selected < 0) { compatCount = 0; return; }
		const snum = numOf[selected], sletter = letterOf[selected];
		for (let i = 0; i < count; i++) {
			if (!numOf[i]) continue;
			if (isCompat(numOf[i], letterOf[i], snum, sletter)) compatSet.add(i);
		}
		compatCount = compatSet.size;
	}

	function buildGeometry() {
		// place each track dot in its sector + band
		cx = width / 2;
		cy = height / 2;
		const pad = 34;
		rOuter = Math.max(40, Math.min(width, height) / 2 - pad);
		const rInner = rOuter * 0.30;        // empty hub
		const rMid = rOuter * 0.65;          // boundary A(inner)/B(outer)
		const half = Math.PI / 12 * 0.82;    // angular half-width usable inside a sector

		// bpm range for radial mapping within a band
		let bMin = Infinity, bMax = -Infinity;
		for (let i = 0; i < count; i++) {
			const b = data.bpm?.[i];
			if (b && b > 0) { if (b < bMin) bMin = b; if (b > bMax) bMax = b; }
		}
		if (!isFinite(bMin)) { bMin = 60; bMax = 180; }
		const span = bMax - bMin || 1;

		pts = [];
		for (let i = 0; i < count; i++) {
			const num = numOf[i];
			if (!num) continue;
			const letter = letterOf[i];
			const base = sectorAngle(num);
			// jitter angle within sector
			const a = base + (rand(i + 1) * 2 - 1) * half;
			// band radial extents
			const lo = letter === 'A' ? rInner : rMid;
			const hi = letter === 'A' ? rMid : rOuter;
			// bpm drives position within band; jitter so equal-bpm tracks don't overlap on one ring
			const bpm = data.bpm?.[i] || 0;
			let t = bpm > 0 ? (bpm - bMin) / span : rand(i + 7);
			t = t * 0.82 + rand(i + 31) * 0.18; // small jitter
			const rr = lo + (hi - lo) * (0.12 + 0.76 * t);
			pts.push({
				i, num, letter, bpm,
				px: cx + Math.cos(a) * rr,
				py: cy + Math.sin(a) * rr
			});
		}
	}

	function requestDraw() { if (!rafId) rafId = requestAnimationFrame(() => { rafId = 0; draw(); }); }

	function draw() {
		if (!ctx || !data) return;
		ctx.clearRect(0, 0, width, height);
		if (!rOuter) return;

		const rInner = rOuter * 0.30;
		const rMid = rOuter * 0.65;

		// --- rings ---
		ctx.lineWidth = 1;
		for (const rr of [rInner, rMid, rOuter]) {
			ctx.beginPath();
			ctx.arc(cx, cy, rr, 0, 6.2832);
			ctx.strokeStyle = 'rgba(148,163,184,0.18)';
			ctx.stroke();
		}

		// --- sector dividers + rim labels ---
		ctx.font = '600 12px Inter, sans-serif';
		ctx.textAlign = 'center';
		ctx.textBaseline = 'middle';
		for (let n = 1; n <= 12; n++) {
			const a = sectorAngle(n) - Math.PI / 12; // divider sits between sectors
			ctx.beginPath();
			ctx.moveTo(cx + Math.cos(a) * rInner, cy + Math.sin(a) * rInner);
			ctx.lineTo(cx + Math.cos(a) * rOuter, cy + Math.sin(a) * rOuter);
			ctx.strokeStyle = 'rgba(148,163,184,0.13)';
			ctx.stroke();

			// labels: A on the mid ring, B on the outer rim
			const la = sectorAngle(n);
			const lblA = n + 'A';
			const lblB = n + 'B';
			const rA = (rInner + rMid) / 2;
			const rB = rOuter + 14;
			const selNum = selected >= 0 ? numOf[selected] : 0;
			const selLet = selected >= 0 ? letterOf[selected] : '';
			const onA = selected >= 0 && isCompat(n, 'A', selNum, selLet);
			const onB = selected >= 0 && isCompat(n, 'B', selNum, selLet);
			ctx.fillStyle = selected >= 0 ? (onA ? ACCENT : 'rgba(148,163,184,0.35)') : 'rgba(203,213,225,0.55)';
			ctx.fillText(lblA, cx + Math.cos(la) * rA, cy + Math.sin(la) * rA);
			ctx.fillStyle = selected >= 0 ? (onB ? ACCENT : 'rgba(148,163,184,0.55)') : 'rgba(226,232,240,0.85)';
			ctx.font = '700 13px Inter, sans-serif';
			ctx.fillText(lblB, cx + Math.cos(la) * rB, cy + Math.sin(la) * rB);
			ctx.font = '600 12px Inter, sans-serif';
		}

		// --- dots ---
		const dimming = selected >= 0;
		for (const p of pts) {
			const isSel = p.i === selected;
			const isCompatDot = compatSet.has(p.i);
			const isHover = p.i === hover.i;
			let alpha, fill, r;
			if (isSel) { alpha = 1; fill = '#fff'; r = 5; }
			else if (dimming && isCompatDot) { alpha = 0.95; fill = ACCENT; r = 3.2; }
			else if (dimming) { alpha = 0.10; fill = '#64748b'; r = 2; }
			else { alpha = isHover ? 1 : 0.7; fill = ACCENT; r = isHover ? 4.2 : 2.4; }
			if (isHover && !isSel) { alpha = 1; r += 1.5; fill = '#fff'; }
			ctx.globalAlpha = alpha;
			ctx.fillStyle = fill;
			ctx.beginPath();
			ctx.arc(p.px, p.py, r, 0, 6.2832);
			ctx.fill();
		}
		ctx.globalAlpha = 1;

		// ring on the selected dot
		if (selected >= 0) {
			const sp = pts.find((p) => p.i === selected);
			if (sp) {
				ctx.beginPath();
				ctx.arc(sp.px, sp.py, 9, 0, 6.2832);
				ctx.strokeStyle = '#fff';
				ctx.lineWidth = 2;
				ctx.stroke();
			}
		}

		// center label
		ctx.fillStyle = 'rgba(148,163,184,0.45)';
		ctx.font = '600 11px Inter, sans-serif';
		ctx.fillText('inner A · outer B', cx, cy - 6);
		ctx.fillText('1 top → clockwise', cx, cy + 8);
	}

	function nearest(mx, my) {
		let best = -1, bd = 144; // 12px hit radius²
		for (const p of pts) {
			const d = (p.px - mx) ** 2 + (p.py - my) ** 2;
			if (d < bd) { bd = d; best = p.i; }
		}
		return best;
	}

	function onMove(ev) {
		const rect = canvas.getBoundingClientRect();
		const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
		const i = nearest(mx, my);
		if (i !== hover.i) { hover = { i, x: mx, y: my }; requestDraw(); }
		else hover = { i, x: mx, y: my };
	}
	function onLeave() { if (hover.i !== -1) { hover = { i: -1, x: 0, y: 0 }; requestDraw(); } }
	function onClick(ev) {
		const rect = canvas.getBoundingClientRect();
		const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
		const i = nearest(mx, my);
		if (i >= 0) {
			selected = i;
			recomputeCompat();
			requestDraw();
		}
	}

	function clearSelection() {
		selected = -1;
		compatSet = new Set();
		compatCount = 0;
		requestDraw();
	}

	function trackObj(i) {
		return { id: data.ids[i], title: data.title[i], artist: data.artist[i], album_id: data.album_id[i] };
	}

	function playHarmonicRun() {
		if (selected < 0) return;
		const idxs = [...compatSet];
		// ensure selected is in there; sort by ascending bpm (tracks w/o bpm last)
		idxs.sort((a, b) => {
			const ba = data.bpm?.[a] || Infinity, bb = data.bpm?.[b] || Infinity;
			return ba - bb;
		});
		const queue = idxs.map(trackObj);
		if (!queue.length) return;
		storePlayTrack(queue[0], queue);
		addToast(`Playing harmonic run — ${queue.length} tracks`, 'success');
	}

	function resize() {
		if (!container || !canvas) return;
		const rect = container.getBoundingClientRect();
		width = Math.max(100, rect.width);
		height = Math.max(100, rect.height);
		dpr = window.devicePixelRatio || 1;
		canvas.width = width * dpr;
		canvas.height = height * dpr;
		canvas.style.width = width + 'px';
		canvas.style.height = height + 'px';
		ctx = canvas.getContext('2d');
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		if (data) { buildGeometry(); requestDraw(); }
	}

	async function loadData() {
		try {
			const d = await api.getAudioFeatures();
			data = d;
			count = d.count || (d.ids ? d.ids.length : 0);
			codeOf = new Array(count).fill(null);
			numOf = new Array(count).fill(0);
			letterOf = new Array(count).fill('');
			let n = 0;
			for (let i = 0; i < count; i++) {
				const c = camelot(d.key?.[i], d.scale?.[i]);
				if (c) { codeOf[i] = c.code; numOf[i] = c.num; letterOf[i] = c.letter; n++; }
			}
			mapped = n;
			buildGeometry();
			requestDraw();
			if (!n) addToast('No tracks have musical key analysis yet', 'info');
		} catch {
			addToast('Failed to load harmonic data', 'error');
		} finally {
			loading = false;
		}
	}

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

	const hoverTrack = $derived.by(() => {
		if (hover.i < 0 || !data) return null;
		return {
			title: data.title[hover.i],
			artist: data.artist[hover.i] || 'Unknown',
			code: codeOf[hover.i] || '—',
			bpm: data.bpm?.[hover.i] ? Math.round(data.bpm[hover.i]) : null
		};
	});
	const selTrack = $derived.by(() => {
		if (selected < 0 || !data) return null;
		return { title: data.title[selected], artist: data.artist[selected] || 'Unknown', code: codeOf[selected] || '—' };
	});
</script>

<div bind:this={container} class="relative w-full h-full">
	<canvas
		bind:this={canvas}
		onmousemove={onMove}
		onmouseleave={onLeave}
		onclick={onClick}
		class="block cursor-pointer"
	></canvas>

	<!-- legend / help -->
	<div class="absolute top-3 left-3 bg-[var(--surface-container)]/85 backdrop-blur rounded-lg px-3 py-2 text-xs max-w-[230px] pointer-events-none">
		<p class="text-[#22d3ee] font-medium mb-1">Camelot Wheel</p>
		<p class="text-[var(--text-muted)] leading-snug">
			{mapped} of {count} tracks keyed. Click a dot to light up its harmonic matches, then play the run.
		</p>
	</div>

	<!-- hover tooltip -->
	{#if hoverTrack}
		<div
			class="absolute pointer-events-none z-10 px-2 py-1 rounded bg-black/85 text-white text-xs max-w-[240px]"
			style="left:{Math.min(hover.x + 14, width - 200)}px; top:{Math.max(hover.y - 34, 4)}px;"
		>
			<span class="font-medium truncate block">{hoverTrack.title}</span>
			<span class="text-white/60">{hoverTrack.artist}</span>
			<span class="text-[#22d3ee] font-mono"> · {hoverTrack.code}</span>{#if hoverTrack.bpm}<span class="text-white/50 font-mono"> · {hoverTrack.bpm} BPM</span>{/if}
		</div>
	{/if}

	<!-- selection panel -->
	{#if selTrack}
		<div class="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-[var(--surface-container-high)]/95 backdrop-blur border border-[var(--border-subtle)] rounded-full pl-3 pr-1.5 py-1.5 shadow-lg max-w-[92%]">
			<span class="text-xs min-w-0 truncate">
				<span class="font-mono text-[#22d3ee]">{selTrack.code}</span>
				<span class="text-[var(--text-secondary)] truncate"> · {selTrack.title}</span>
			</span>
			<button
				onclick={playHarmonicRun}
				disabled={compatCount === 0}
				class="flex items-center gap-1 text-xs font-medium px-3 py-1.5 rounded-full bg-[#22d3ee] text-black hover:brightness-110 transition disabled:opacity-40"
			>
				<Play class="w-3.5 h-3.5" /> Play harmonic run ({compatCount})
			</button>
			<button
				onclick={clearSelection}
				class="flex items-center justify-center w-7 h-7 rounded-full text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container)] transition"
				title="Clear selection"
			>
				<X class="w-4 h-4" />
			</button>
		</div>
	{/if}

	<!-- loading -->
	{#if loading}
		<div class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[var(--surface-base)]/80">
			<div class="w-8 h-8 border-2 border-[#22d3ee] border-t-transparent rounded-full animate-spin"></div>
			<p class="text-sm text-[var(--text-secondary)]">Loading harmonic data…</p>
		</div>
	{/if}
</div>
