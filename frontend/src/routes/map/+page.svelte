<script>
	import { onMount, onDestroy } from 'svelte';
	import * as d3 from 'd3';
	import { api } from '$lib/api.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Button from '../../components/ui/Button.svelte';
	import { Map as MapIcon, Search, RefreshCw, Play, X } from 'lucide-svelte';

	// --- reactive UI state ---
	let loading = $state(true);
	let computing = $state(false);
	let info = $state({ count: 0, total: 0 });
	let colorMode = $state('genre'); // genre | energy | recency
	let searchQuery = $state('');
	let searching = $state(false);
	let pinTracks = $state([]);
	let hover = $state({ i: -1, x: 0, y: 0 });

	// --- imperative (non-reactive) render state ---
	let container, canvas, ctx;
	let dpr = 1, width = 0, height = 0;
	let data = null;                 // soundscape arrays
	let transform = d3.zoomIdentity;
	let zoomBehavior = null;
	let baseX = null, baseY = null;  // data[0,1] -> base px
	let genreColors = new Map();
	let pin = null;                  // {x,y}
	let dragged = false;
	let rafId = 0, pollTimer = 0;

	const PAD = 28;

	function buildScales() {
		baseX = d3.scaleLinear().domain([0, 1]).range([PAD, width - PAD]);
		baseY = d3.scaleLinear().domain([0, 1]).range([height - PAD, PAD]); // flip y
	}

	function setupGenreColors() {
		const counts = new Map();
		for (const g of data.genre) {
			const k = ((g || '').split(';')[0] || '').trim() || 'Unknown';
			counts.set(k, (counts.get(k) || 0) + 1);
		}
		const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12).map((e) => e[0]);
		const palette = [...d3.schemeTableau10, ...d3.schemeSet2];
		genreColors = new Map(top.map((g, i) => [g, palette[i % palette.length]]));
	}

	function colorFor(i) {
		if (colorMode === 'energy') {
			const e = data.energy[i];
			return e == null ? '#3f4654' : d3.interpolateViridis(e);
		}
		if (colorMode === 'recency') {
			const r = data.recency_days[i];
			if (r == null) return '#2b3242'; // never played — dim
			const t = Math.max(0, 1 - Math.min(r, 180) / 180); // recent → 1
			return d3.interpolateInferno(0.25 + t * 0.6);
		}
		const g = ((data.genre[i] || '').split(';')[0] || '').trim();
		return genreColors.get(g) || '#5b6675';
	}

	function requestDraw() {
		if (rafId) return;
		rafId = requestAnimationFrame(() => { rafId = 0; draw(); });
	}

	function draw() {
		if (!ctx || !data || !baseX) return;
		ctx.clearRect(0, 0, width, height);
		const r = Math.max(1.6, 2.1 * Math.sqrt(transform.k));
		const n = data.count;
		for (let i = 0; i < n; i++) {
			const sx = transform.applyX(baseX(data.x[i]));
			const sy = transform.applyY(baseY(data.y[i]));
			if (sx < -6 || sx > width + 6 || sy < -6 || sy > height + 6) continue;
			ctx.beginPath();
			ctx.fillStyle = colorFor(i);
			ctx.globalAlpha = hover.i === i ? 1 : 0.72;
			ctx.arc(sx, sy, hover.i === i ? r + 3 : r, 0, 6.2832);
			ctx.fill();
		}
		ctx.globalAlpha = 1;
		if (pin) {
			const px = transform.applyX(baseX(pin.x));
			const py = transform.applyY(baseY(pin.y));
			ctx.beginPath(); ctx.arc(px, py, 11, 0, 6.2832);
			ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 3; ctx.stroke();
			ctx.beginPath(); ctx.arc(px, py, 3.5, 0, 6.2832);
			ctx.fillStyle = '#f59e0b'; ctx.fill();
		}
	}

	function nearest(mx, my) {
		if (!data) return -1;
		let best = -1, bd = 169; // 13px radius²
		for (let i = 0; i < data.count; i++) {
			const sx = transform.applyX(baseX(data.x[i]));
			const sy = transform.applyY(baseY(data.y[i]));
			const d = (sx - mx) ** 2 + (sy - my) ** 2;
			if (d < bd) { bd = d; best = i; }
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
		if (dragged) return;
		const rect = canvas.getBoundingClientRect();
		const i = nearest(ev.clientX - rect.left, ev.clientY - rect.top);
		if (i >= 0) playIndex(i);
	}

	function playIndex(i) {
		storePlayTrack({ id: data.ids[i], title: data.title[i], artist: data.artist[i], album_id: data.album_id[i] });
		addToast(`Playing ${data.title[i]}`, 'success');
	}

	function setColor(mode) { colorMode = mode; requestDraw(); }

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
		buildScales();
		requestDraw();
	}

	function setupZoom() {
		zoomBehavior = d3.zoom().scaleExtent([0.6, 18])
			.on('start', () => { dragged = false; })
			.on('zoom', (ev) => {
				if (ev.sourceEvent && ev.sourceEvent.type !== 'wheel') dragged = true;
				transform = ev.transform; requestDraw();
			});
		d3.select(canvas).call(zoomBehavior);
	}

	function centerOn(x, y, scale = 4) {
		if (!zoomBehavior || !baseX) return;
		const px = baseX(x), py = baseY(y);
		const t = d3.zoomIdentity.translate(width / 2, height / 2).scale(scale).translate(-px, -py);
		d3.select(canvas).transition().duration(600).call(zoomBehavior.transform, t);
	}

	async function loadData(firstTime = false) {
		try {
			const d = await api.getSoundscape();
			info = { count: d.count, total: d.total_tracks };
			computing = d.computing;
			if (d.count > 0) {
				data = d; setupGenreColors(); requestDraw();
			}
			if (d.computing) startPolling();
			else if (d.count === 0 && firstTime) await recompute();
		} catch (e) {
			addToast('Failed to load sound map', 'error');
		} finally {
			loading = false;
		}
	}

	function startPolling() {
		if (pollTimer) return;
		pollTimer = setInterval(async () => {
			try {
				const d = await api.getSoundscape();
				computing = d.computing;
				info = { count: d.count, total: d.total_tracks };
				if (d.count > 0 && !d.computing) {
					clearInterval(pollTimer); pollTimer = 0;
					data = d; setupGenreColors(); requestDraw();
					addToast(`Sound map ready — ${d.count} tracks`, 'success');
				}
			} catch {}
		}, 5000);
	}

	async function recompute() {
		try {
			computing = true;
			await api.recomputeSoundscape();
			addToast('Building the sound map… (~1–2 min)', 'info');
			startPolling();
		} catch { computing = false; addToast('Failed to start projection', 'error'); }
	}

	async function doSearch() {
		const q = searchQuery.trim();
		if (!q) return;
		searching = true;
		try {
			const r = await api.locateSoundscape(q, 18);
			if (r.error) { addToast(r.error, 'error'); return; }
			pin = { x: r.x, y: r.y };
			pinTracks = r.tracks || [];
			centerOn(r.x, r.y);
			requestDraw();
		} catch { addToast('Search failed', 'error'); }
		finally { searching = false; }
	}

	function clearSearch() { pin = null; pinTracks = []; searchQuery = ''; requestDraw(); }

	function playPinTracks() {
		if (!pinTracks.length) return;
		const q = pinTracks.map((t) => ({ id: t.track_id, title: t.title, artist: t.artist }));
		storePlayTrack(q[0], q);
		addToast(`Playing ${q.length} tracks from “${searchQuery.trim()}”`, 'success');
	}

	let ro;
	onMount(() => {
		resize();
		setupZoom();
		ro = new ResizeObserver(resize);
		ro.observe(container);
		loadData(true);
	});
	onDestroy(() => {
		if (ro) ro.disconnect();
		if (pollTimer) clearInterval(pollTimer);
		if (rafId) cancelAnimationFrame(rafId);
	});

	const legend = $derived.by(() => {
		if (colorMode === 'genre') return [...genreColors.entries()].map(([label, color]) => ({ label, color }));
		if (colorMode === 'energy') return [{ label: 'low', color: d3.interpolateViridis(0) }, { label: 'mid', color: d3.interpolateViridis(0.5) }, { label: 'high', color: d3.interpolateViridis(1) }];
		return [{ label: 'recent', color: d3.interpolateInferno(0.85) }, { label: 'older', color: d3.interpolateInferno(0.35) }, { label: 'never', color: '#2b3242' }];
	});
</script>

<div class="px-3 sm:px-6 py-5 max-w-[1600px] mx-auto">
	<PageHeader title="Music Map" icon={MapIcon} color="#22d3ee"
		subtitle={info.count ? `${info.count} of ${info.total} tracks placed by how they sound · click a dot to play` : 'A map of your library by sound'} />

	<!-- Toolbar -->
	<div class="flex flex-wrap items-center gap-2 mt-4 mb-3">
		<div class="relative flex-1 min-w-[180px] max-w-sm">
			<Search class="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
			<input type="text" bind:value={searchQuery} placeholder="Find a vibe… e.g. “rainy lo-fi jazz”"
				onkeydown={(e) => e.key === 'Enter' && doSearch()}
				class="pl-8 pr-3 py-1.5 text-sm rounded-md bg-[var(--surface-lowest)] text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] w-full focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/30" />
		</div>
		<Button variant="primary" size="sm" loading={searching} onclick={doSearch}>Locate</Button>
		{#if pin}<Button variant="secondary" size="sm" onclick={clearSearch}><X class="w-3.5 h-3.5" /></Button>{/if}

		<div class="flex rounded-md overflow-hidden border border-[var(--border-subtle)] ml-auto">
			{#each [['genre', 'Genre'], ['energy', 'Energy'], ['recency', 'Recency']] as [mode, label]}
				<button onclick={() => setColor(mode)}
					class="px-2.5 py-1.5 text-xs {colorMode === mode ? 'bg-[var(--color-primary)] text-white' : 'bg-[var(--surface-lowest)] text-[var(--text-secondary)] hover:bg-[var(--surface-container-high)]'}">{label}</button>
			{/each}
		</div>
		<Button variant="secondary" size="sm" loading={computing} onclick={recompute} title="Rebuild the projection">
			<RefreshCw class="w-3.5 h-3.5" />
		</Button>
	</div>

	<!-- Canvas -->
	<div bind:this={container} class="relative rounded-xl overflow-hidden border border-[var(--border-subtle)] bg-[var(--surface-base)]" style="height: 72vh;">
		<canvas bind:this={canvas} onmousemove={onMove} onmouseleave={onLeave} onclick={onClick} class="block cursor-crosshair"></canvas>

		<!-- legend -->
		{#if data && legend.length}
			<div class="absolute bottom-3 left-3 bg-[var(--surface-container)]/85 backdrop-blur rounded-lg px-3 py-2 text-xs max-w-[220px]">
				<p class="text-[var(--text-muted)] mb-1 uppercase tracking-wide text-[10px]">{colorMode}</p>
				<div class="flex flex-wrap gap-x-2 gap-y-1">
					{#each legend as l}
						<span class="flex items-center gap-1 text-[var(--text-secondary)]">
							<span class="w-2.5 h-2.5 rounded-full flex-shrink-0" style="background:{l.color}"></span>{l.label}
						</span>
					{/each}
				</div>
			</div>
		{/if}

		<!-- hover tooltip -->
		{#if data && hover.i >= 0}
			<div class="absolute pointer-events-none z-10 px-2 py-1 rounded bg-black/85 text-white text-xs max-w-[220px] truncate"
				style="left:{Math.min(hover.x + 12, width - 180)}px; top:{Math.max(hover.y - 30, 4)}px;">
				<span class="font-medium">{data.title[hover.i]}</span>
				<span class="text-white/60"> · {data.artist[hover.i] || 'Unknown'}</span>
			</div>
		{/if}

		<!-- loading / building overlay -->
		{#if loading || (computing && !data)}
			<div class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[var(--surface-base)]/80">
				<div class="w-8 h-8 border-2 border-[var(--color-primary)] border-t-transparent rounded-full animate-spin"></div>
				<p class="text-sm text-[var(--text-secondary)]">{computing ? 'Building the sound map… (~1–2 min)' : 'Loading…'}</p>
			</div>
		{/if}
	</div>

	<!-- search results -->
	{#if pinTracks.length}
		<div class="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3">
			<div class="flex items-center justify-between mb-2">
				<p class="text-sm font-medium text-[var(--text-primary)]">Nearest to “{searchQuery.trim()}”</p>
				<Button variant="primary" size="sm" onclick={playPinTracks}><Play class="w-3.5 h-3.5 mr-1" /> Play {pinTracks.length}</Button>
			</div>
			<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
				{#each pinTracks as t}
					<button onclick={() => storePlayTrack({ id: t.track_id, title: t.title, artist: t.artist })}
						class="flex items-center gap-2 text-left px-2 py-1.5 rounded hover:bg-[var(--surface-container-high)] transition-colors">
						<Play class="w-3.5 h-3.5 text-[var(--text-muted)] flex-shrink-0" />
						<span class="min-w-0 flex-1">
							<span class="text-sm text-[var(--text-primary)] truncate block">{t.title}</span>
							<span class="text-xs text-[var(--text-muted)] truncate block">{t.artist || 'Unknown'}</span>
						</span>
						<span class="text-[10px] font-mono text-[var(--text-disabled)]">{Math.round((t.similarity || 0) * 100)}%</span>
					</button>
				{/each}
			</div>
		</div>
	{/if}

	{#if data && info.count < info.total}
		<p class="text-xs text-[var(--text-disabled)] mt-2">{info.total - info.count} tracks aren't mapped yet (no audio analysis). Run analysis on them, then rebuild the map.</p>
	{/if}
</div>
