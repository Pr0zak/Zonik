<script>
	import { onMount, onDestroy } from 'svelte';
	import * as d3 from 'd3';
	import { api } from '$lib/api.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Button from '../../components/ui/Button.svelte';
	import { Map as MapIcon, Search, RefreshCw, Play, X } from 'lucide-svelte';
	import CamelotWheel from '../../components/map/CamelotWheel.svelte';
	import TempoPunch from '../../components/map/TempoPunch.svelte';
	import StreakCalendar from '../../components/map/StreakCalendar.svelte';
	import SonicAdventure from '../../components/map/SonicAdventure.svelte';

	// --- view + reactive UI state ---
	let view = $state('wheel'); // wheel | tempo | calendar | adventure | atlas | clock | gems
	let atlasMode = $state('territories'); // dots | territories | hexbins
	let loading = $state(true);
	let computing = $state(false);
	let info = $state({ count: 0, total: 0 });
	let colorMode = $state('genre'); // genre | energy | recency
	let searchQuery = $state('');
	let searching = $state(false);
	let pinTracks = $state([]);
	let hover = $state({ i: -1, x: 0, y: 0 });
	let clock = $state(null);
	let clockByGenre = $state(false);
	let gems = $state(null);

	// --- imperative render state ---
	let container, canvas, ctx;
	let dpr = 1, width = 0, height = 0;
	let data = null;
	let transform = d3.zoomIdentity;
	let zoomBehavior = null;
	let scale = 1, offX = 0, offY = 0; // uniform square fit of [0,1]² into the canvas
	let genreColors = new Map();
	let regions = [];
	let hexbins = [];
	let pin = null;
	let dragged = false;
	let rafId = 0, pollTimer = 0;

	const PAD = 30;
	const bx = (x) => offX + x * scale;
	const by = (y) => offY + (1 - y) * scale; // flip y

	function buildScales() {
		const s = Math.max(40, Math.min(width, height) - PAD * 2);
		scale = s;
		offX = (width - s) / 2;
		offY = (height - s) / 2;
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

	function topGenre(i) { return ((data.genre[i] || '').split(';')[0] || '').trim(); }

	function colorFor(i) {
		if (colorMode === 'energy') {
			const e = data.energy[i];
			return e == null ? '#3f4654' : d3.interpolateViridis(e);
		}
		if (colorMode === 'recency') {
			const r = data.recency_days[i];
			if (r == null) return '#2b3242';
			const t = Math.max(0, 1 - Math.min(r, 180) / 180);
			return d3.interpolateInferno(0.25 + t * 0.6);
		}
		return genreColors.get(topGenre(i)) || '#5b6675';
	}

	function computeRegions() {
		const groups = new Map();
		for (let i = 0; i < data.count; i++) {
			const g = topGenre(i);
			if (!genreColors.has(g)) continue;
			let r = groups.get(g);
			if (!r) { r = { sx: 0, sy: 0, n: 0 }; groups.set(g, r); }
			r.sx += data.x[i]; r.sy += data.y[i]; r.n++;
		}
		regions = [...groups.entries()].map(([g, r]) => ({ genre: g, x: r.sx / r.n, y: r.sy / r.n, n: r.n, color: genreColors.get(g) }))
			.sort((a, b) => b.n - a.n);
	}

	function computeHexbins() {
		// hexbin in data space (radius in [0,1] units) → zoom-stable tiles
		const R = 0.028;
		const dx = R * 2 * Math.sin(Math.PI / 3), dy = R * 1.5;
		const bins = new Map();
		for (let k = 0; k < data.count; k++) {
			const x = data.x[k], y = data.y[k];
			let py = y / dy, pj = Math.round(py);
			let px = x / dx - (pj & 1 ? 0.5 : 0), pi = Math.round(px);
			const key = pi + '-' + pj;
			let b = bins.get(key);
			if (!b) { b = { cx: (pi + (pj & 1 ? 0.5 : 0)) * dx, cy: pj * dy, n: 0, g: new Map(), idx: [] }; bins.set(key, b); }
			b.n++; if (b.idx.length < 60) b.idx.push(k);
			const g = topGenre(k); if (g) b.g.set(g, (b.g.get(g) || 0) + 1);
		}
		let mx = 0;
		hexbins = [...bins.values()].map((b) => {
			mx = Math.max(mx, b.n);
			const dom = b.g.size ? [...b.g.entries()].sort((a, c) => c[1] - a[1])[0][0] : null;
			return { ...b, color: genreColors.get(dom) || '#5b6675' };
		});
		hexbins.forEach((b) => (b.t = b.n / (mx || 1)));
		hexR = R;
	}
	let hexR = 0.028;

	function requestDraw() { if (!rafId) rafId = requestAnimationFrame(() => { rafId = 0; draw(); }); }

	function draw() {
		if (!ctx || !data || !scale) return;
		ctx.clearRect(0, 0, width, height);
		const sx = (x) => transform.applyX(bx(x));
		const sy = (y) => transform.applyY(by(y));

		if (atlasMode === 'hexbins') {
			const rpx = hexR * scale * transform.k;
			for (const b of hexbins) {
				const cx = sx(b.cx), cy = sy(b.cy);
				if (cx < -rpx || cx > width + rpx || cy < -rpx || cy > height + rpx) continue;
				ctx.beginPath();
				for (let a = 0; a < 6; a++) {
					const ang = Math.PI / 6 + a * Math.PI / 3;
					const px = cx + rpx * Math.cos(ang), py = cy + rpx * Math.sin(ang);
					a === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
				}
				ctx.closePath();
				ctx.fillStyle = b.color; ctx.globalAlpha = 0.18 + 0.8 * b.t; ctx.fill();
				ctx.globalAlpha = 0.25; ctx.strokeStyle = '#0b0f17'; ctx.lineWidth = 1; ctx.stroke();
			}
			ctx.globalAlpha = 1;
			return;
		}

		// dots / territories both draw the points
		const r = Math.max(1.5, 2.0 * Math.sqrt(transform.k));
		const alpha = atlasMode === 'territories' ? 0.45 : 0.72;
		for (let i = 0; i < data.count; i++) {
			const px = sx(data.x[i]), py = sy(data.y[i]);
			if (px < -6 || px > width + 6 || py < -6 || py > height + 6) continue;
			ctx.beginPath();
			ctx.fillStyle = atlasMode === 'territories' ? (genreColors.get(topGenre(i)) || '#46506180') : colorFor(i);
			ctx.globalAlpha = hover.i === i ? 1 : alpha;
			ctx.arc(px, py, hover.i === i ? r + 3 : r, 0, 6.2832);
			ctx.fill();
		}
		ctx.globalAlpha = 1;

		if (atlasMode === 'territories') {
			ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
			for (const reg of regions) {
				const px = sx(reg.x), py = sy(reg.y);
				if (px < 0 || px > width || py < 0 || py > height) continue;
				const label = reg.genre;
				ctx.font = '700 ' + Math.min(20, 11 + Math.log2(reg.n)) + 'px Inter, sans-serif';
				const w = ctx.measureText(label).width;
				ctx.fillStyle = 'rgba(8,12,20,0.7)';
				ctx.fillRect(px - w / 2 - 6, py - 11, w + 12, 22);
				ctx.fillStyle = reg.color; ctx.fillText(label, px, py + 1);
			}
		}

		if (pin) {
			const px = sx(pin.x), py = sy(pin.y);
			ctx.beginPath(); ctx.arc(px, py, 11, 0, 6.2832); ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 3; ctx.stroke();
			ctx.beginPath(); ctx.arc(px, py, 3.5, 0, 6.2832); ctx.fillStyle = '#f59e0b'; ctx.fill();
		}
	}

	function nearest(mx, my) {
		if (!data) return -1;
		let best = -1, bd = 169;
		for (let i = 0; i < data.count; i++) {
			const px = transform.applyX(bx(data.x[i])), py = transform.applyY(by(data.y[i]));
			const d = (px - mx) ** 2 + (py - my) ** 2;
			if (d < bd) { bd = d; best = i; }
		}
		return best;
	}

	function onMove(ev) {
		if (atlasMode === 'hexbins') return;
		const rect = canvas.getBoundingClientRect();
		const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
		const i = nearest(mx, my);
		if (i !== hover.i) { hover = { i, x: mx, y: my }; requestDraw(); } else hover = { i, x: mx, y: my };
	}
	function onLeave() { if (hover.i !== -1) { hover = { i: -1, x: 0, y: 0 }; requestDraw(); } }
	function onClick(ev) {
		if (dragged) return;
		const rect = canvas.getBoundingClientRect();
		const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
		if (atlasMode === 'hexbins') {
			// play a random track from the nearest hex
			let best = null, bd = Infinity;
			for (const b of hexbins) {
				const d = (transform.applyX(bx(b.cx)) - mx) ** 2 + (transform.applyY(by(b.cy)) - my) ** 2;
				if (d < bd) { bd = d; best = b; }
			}
			if (best && best.idx.length) {
				const i = best.idx[Math.floor(d3.randomUniform(0, best.idx.length)())];
				playIndex(i);
			}
			return;
		}
		const i = nearest(mx, my);
		if (i >= 0) playIndex(i);
	}
	function playIndex(i) {
		storePlayTrack({ id: data.ids[i], title: data.title[i], artist: data.artist[i], album_id: data.album_id[i] });
		addToast(`Playing ${data.title[i]}`, 'success');
	}
	function setMode(m) { atlasMode = m; if (m === 'territories' && data && !regions.length) computeRegions(); if (m === 'hexbins' && data && !hexbins.length) computeHexbins(); requestDraw(); }
	function setColor(m) { colorMode = m; requestDraw(); }

	function resize() {
		if (!container || !canvas) return;
		const rect = container.getBoundingClientRect();
		width = Math.max(100, rect.width); height = Math.max(100, rect.height);
		dpr = window.devicePixelRatio || 1;
		canvas.width = width * dpr; canvas.height = height * dpr;
		canvas.style.width = width + 'px'; canvas.style.height = height + 'px';
		ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		buildScales(); requestDraw();
	}
	function setupZoom() {
		zoomBehavior = d3.zoom().scaleExtent([0.7, 20])
			.on('start', () => { dragged = false; })
			.on('zoom', (ev) => { if (ev.sourceEvent && ev.sourceEvent.type !== 'wheel') dragged = true; transform = ev.transform; requestDraw(); });
		d3.select(canvas).call(zoomBehavior);
	}
	function centerOn(x, y, k = 5) {
		if (!zoomBehavior) return;
		const t = d3.zoomIdentity.translate(width / 2, height / 2).scale(k).translate(-bx(x), -by(y));
		d3.select(canvas).transition().duration(600).call(zoomBehavior.transform, t);
	}

	async function loadData(first = false) {
		try {
			const d = await api.getSoundscape();
			info = { count: d.count, total: d.total_tracks };
			computing = d.computing;
			if (d.count > 0) { data = d; setupGenreColors(); computeRegions(); requestDraw(); }
			if (d.computing) startPolling();
			else if (d.count === 0 && first) await recompute();
		} catch { addToast('Failed to load sound map', 'error'); }
		finally { loading = false; }
	}
	function startPolling() {
		if (pollTimer) return;
		pollTimer = setInterval(async () => {
			try {
				const d = await api.getSoundscape();
				computing = d.computing; info = { count: d.count, total: d.total_tracks };
				if (d.count > 0 && !d.computing) {
					clearInterval(pollTimer); pollTimer = 0;
					data = d; setupGenreColors(); computeRegions(); hexbins = []; requestDraw();
					addToast(`Sound map ready — ${d.count} tracks`, 'success');
				}
			} catch {}
		}, 5000);
	}
	async function recompute() {
		try { computing = true; await api.recomputeSoundscape(); addToast('Building the sound map… (~1–2 min)', 'info'); startPolling(); }
		catch { computing = false; addToast('Failed to start projection', 'error'); }
	}
	async function doSearch() {
		const q = searchQuery.trim(); if (!q) return;
		searching = true;
		try {
			const r = await api.locateSoundscape(q, 18);
			if (r.error) { addToast(r.error, 'error'); return; }
			pin = { x: r.x, y: r.y }; pinTracks = r.tracks || []; centerOn(r.x, r.y); requestDraw();
		} catch { addToast('Search failed', 'error'); } finally { searching = false; }
	}
	function clearSearch() { pin = null; pinTracks = []; searchQuery = ''; requestDraw(); }
	function playPinTracks() {
		if (!pinTracks.length) return;
		const q = pinTracks.map((t) => ({ id: t.track_id, title: t.title, artist: t.artist }));
		storePlayTrack(q[0], q); addToast(`Playing ${q.length} tracks`, 'success');
	}

	async function openClock() {
		view = 'clock';
		if (clock) return;
		try { clock = await api.getListeningClock(); } catch { addToast('Failed to load clock', 'error'); }
	}
	async function openGems() {
		view = 'gems';
		if (gems) return;
		try { gems = (await api.getNeglectedGems(48)).gems || []; } catch { addToast('Failed to load gems', 'error'); }
	}
	function playGems() {
		if (!gems?.length) return;
		const q = gems.map((g) => ({ id: g.track_id, title: g.title, artist: g.artist, album_id: g.album_id }));
		storePlayTrack(q[0], q); addToast(`Playing ${q.length} neglected gems`, 'success');
	}

	const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
	function cellStyle(wd, hr) {
		if (!clock) return 'background:var(--surface-lowest)';
		const c = clock.grid[wd][hr];
		if (!c) return 'background:var(--surface-lowest)';
		const t = c / (clock.max || 1);
		const op = (0.12 + 0.88 * t).toFixed(2);
		if (clockByGenre) {
			const g = clock.genre_grid[wd][hr];
			const col = genreColors.get(((g || '').split(';')[0] || '').trim()) || '#22d3ee';
			return `background:${col};opacity:${op}`;
		}
		return `background:rgba(34,211,238,${op})`;
	}

	let ro;
	onMount(() => { resize(); setupZoom(); ro = new ResizeObserver(resize); ro.observe(container); loadData(true); });
	onDestroy(() => { if (ro) ro.disconnect(); if (pollTimer) clearInterval(pollTimer); if (rafId) cancelAnimationFrame(rafId); });

	const legend = $derived.by(() => {
		if (atlasMode === 'hexbins' || atlasMode === 'territories' || colorMode === 'genre')
			return [...genreColors.entries()].map(([label, color]) => ({ label, color }));
		if (colorMode === 'energy') return [0, 0.5, 1].map((v, i) => ({ label: ['low', 'mid', 'high'][i], color: d3.interpolateViridis(v) }));
		return [{ label: 'recent', color: d3.interpolateInferno(0.85) }, { label: 'older', color: d3.interpolateInferno(0.35) }, { label: 'never', color: '#2b3242' }];
	});
</script>

<div class="px-3 sm:px-6 py-5 max-w-[1600px] mx-auto">
	<PageHeader title="Music Map" icon={MapIcon} color="#22d3ee"
		subtitle={info.count ? `${info.count} of ${info.total} tracks mapped by sound` : 'A map of your library by sound'} />

	<!-- view tabs -->
	<div class="flex gap-1 mt-4 border-b border-[var(--border-subtle)] overflow-x-auto">
		{#each [['wheel', 'Camelot Wheel'], ['tempo', 'Tempo × Punch'], ['calendar', 'Streak Calendar'], ['adventure', 'Sonic Adventure'], ['gems', 'Neglected Gems'], ['clock', 'Listening Clock'], ['atlas', 'Sound Atlas']] as [v, label]}
			<button onclick={() => v === 'clock' ? openClock() : v === 'gems' ? openGems() : (view = v)}
				class="px-3 py-2 text-sm whitespace-nowrap border-b-2 -mb-px transition-colors {view === v ? 'border-[#22d3ee] text-[var(--text-primary)] font-medium' : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}">{label}</button>
		{/each}
	</div>

	<!-- atlas toolbar -->
	{#if view === 'atlas'}
		<div class="flex flex-wrap items-center gap-2 mt-3 mb-3">
			<div class="relative flex-1 min-w-[180px] max-w-sm">
				<Search class="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
				<input type="text" bind:value={searchQuery} placeholder="Find a vibe… e.g. “rainy lo-fi jazz”"
					onkeydown={(e) => e.key === 'Enter' && doSearch()}
					class="pl-8 pr-3 py-1.5 text-sm rounded-md bg-[var(--surface-lowest)] text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] w-full focus:outline-none focus:ring-2 focus:ring-[#22d3ee]/30" />
			</div>
			<Button variant="primary" size="sm" loading={searching} onclick={doSearch}>Locate</Button>
			{#if pin}<Button variant="secondary" size="sm" onclick={clearSearch}><X class="w-3.5 h-3.5" /></Button>{/if}

			<div class="flex rounded-md overflow-hidden border border-[var(--border-subtle)] ml-auto text-xs">
				{#each [['dots', 'Dots'], ['territories', 'Territories'], ['hexbins', 'Hexbins']] as [m, label]}
					<button onclick={() => setMode(m)} class="px-2.5 py-1.5 {atlasMode === m ? 'bg-[#22d3ee] text-black font-medium' : 'bg-[var(--surface-lowest)] text-[var(--text-secondary)] hover:bg-[var(--surface-container-high)]'}">{label}</button>
				{/each}
			</div>
			{#if atlasMode === 'dots'}
				<div class="flex rounded-md overflow-hidden border border-[var(--border-subtle)] text-xs">
					{#each [['genre', 'Genre'], ['energy', 'Energy'], ['recency', 'Recency']] as [m, label]}
						<button onclick={() => setColor(m)} class="px-2.5 py-1.5 {colorMode === m ? 'bg-[var(--color-primary)] text-white' : 'bg-[var(--surface-lowest)] text-[var(--text-secondary)] hover:bg-[var(--surface-container-high)]'}">{label}</button>
					{/each}
				</div>
			{/if}
			<Button variant="secondary" size="sm" loading={computing} onclick={recompute} title="Rebuild the projection"><RefreshCw class="w-3.5 h-3.5" /></Button>
		</div>
	{/if}

	<!-- main stage (canvas always mounted; clock/gems overlay it) -->
	<div bind:this={container} class="relative rounded-xl overflow-hidden border border-[var(--border-subtle)] bg-[var(--surface-base)] {view === 'atlas' ? '' : 'mt-3'}" style="height: 72vh;">
		<canvas bind:this={canvas} onmousemove={onMove} onmouseleave={onLeave} onclick={onClick} class="block cursor-crosshair" class:hidden={view !== 'atlas'}></canvas>

		{#if view === 'atlas' && data && legend.length}
			<div class="absolute bottom-3 left-3 bg-[var(--surface-container)]/85 backdrop-blur rounded-lg px-3 py-2 text-xs max-w-[240px] max-h-[40%] overflow-auto">
				<p class="text-[var(--text-muted)] mb-1 uppercase tracking-wide text-[10px]">{atlasMode === 'dots' ? colorMode : 'genre'}</p>
				<div class="flex flex-wrap gap-x-2 gap-y-1">
					{#each legend as l}<span class="flex items-center gap-1 text-[var(--text-secondary)]"><span class="w-2.5 h-2.5 rounded-full flex-shrink-0" style="background:{l.color}"></span>{l.label}</span>{/each}
				</div>
			</div>
		{/if}
		{#if view === 'atlas' && data && hover.i >= 0}
			<div class="absolute pointer-events-none z-10 px-2 py-1 rounded bg-black/85 text-white text-xs max-w-[220px] truncate" style="left:{Math.min(hover.x + 12, width - 180)}px; top:{Math.max(hover.y - 30, 4)}px;">
				<span class="font-medium">{data.title[hover.i]}</span><span class="text-white/60"> · {data.artist[hover.i] || 'Unknown'}</span>
			</div>
		{/if}
		{#if view === 'atlas' && (loading || (computing && !data))}
			<div class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[var(--surface-base)]/80">
				<div class="w-8 h-8 border-2 border-[#22d3ee] border-t-transparent rounded-full animate-spin"></div>
				<p class="text-sm text-[var(--text-secondary)]">{computing ? 'Building the sound map… (~1–2 min)' : 'Loading…'}</p>
			</div>
		{/if}

		<!-- CLOCK overlay -->
		{#if view === 'clock'}
			<div class="absolute inset-0 overflow-auto p-4 sm:p-6 bg-[var(--surface-base)]">
				<div class="flex items-center justify-between mb-4 flex-wrap gap-2">
					<p class="text-sm text-[var(--text-secondary)]">When you listen · {clock ? clock.total : 0} plays (local time)</p>
					<label class="text-xs text-[var(--text-muted)] flex items-center gap-1.5 cursor-pointer">
						<input type="checkbox" bind:checked={clockByGenre} class="accent-[#22d3ee]" /> color by genre
					</label>
				</div>
				{#if !clock}
					<p class="text-sm text-[var(--text-muted)]">Loading…</p>
				{:else}
					<div class="inline-grid gap-[3px]" style="grid-template-columns: 34px repeat(24, minmax(14px, 1fr));">
						<div></div>
						{#each Array(24) as _, hr}<div class="text-[9px] text-[var(--text-disabled)] text-center">{hr % 6 === 0 ? (hr === 0 ? '12a' : hr === 12 ? '12p' : hr > 12 ? (hr - 12) + 'p' : hr + 'a') : ''}</div>{/each}
						{#each DAYS as day, wd}
							<div class="text-[10px] text-[var(--text-muted)] flex items-center pr-1">{day}</div>
							{#each Array(24) as _, hr}
								<div class="aspect-square rounded-sm min-h-[14px]" style={cellStyle(wd, hr)}
									title="{day} {hr}:00 · {clock.grid[wd][hr]} plays{clock.genre_grid[wd][hr] ? ' · ' + clock.genre_grid[wd][hr] : ''}"></div>
							{/each}
						{/each}
					</div>
					<p class="text-xs text-[var(--text-disabled)] mt-4">Darker = more plays. Hover a cell for the count + top genre.</p>
				{/if}
			</div>
		{/if}

		<!-- GEMS overlay -->
		{#if view === 'gems'}
			<div class="absolute inset-0 overflow-auto p-4 sm:p-6 bg-[var(--surface-base)]">
				<div class="flex items-center justify-between mb-3 flex-wrap gap-2">
					<p class="text-sm text-[var(--text-secondary)]">Owned but never played — ranked by how close they sound to your taste</p>
					{#if gems?.length}<Button variant="primary" size="sm" onclick={playGems}><Play class="w-3.5 h-3.5 mr-1" /> Play all</Button>{/if}
				</div>
				{#if !gems}
					<p class="text-sm text-[var(--text-muted)]">Loading…</p>
				{:else if !gems.length}
					<p class="text-sm text-[var(--text-muted)]">No neglected gems found.</p>
				{:else}
					<div class="grid grid-cols-1 md:grid-cols-2 gap-1.5">
						{#each gems as g, i}
							<button onclick={() => storePlayTrack({ id: g.track_id, title: g.title, artist: g.artist, album_id: g.album_id })}
								class="flex items-center gap-3 text-left px-3 py-2 rounded-lg hover:bg-[var(--surface-container-high)] transition-colors border border-[var(--border-subtle)]">
								<span class="text-xs font-mono text-[var(--text-disabled)] w-6">{i + 1}</span>
								<span class="min-w-0 flex-1">
									<span class="text-sm text-[var(--text-primary)] truncate block">{g.title}</span>
									<span class="text-xs text-[var(--text-muted)] truncate block">{g.artist || 'Unknown'}</span>
								</span>
								<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400">{Math.round((g.match || 0) * 100)}%</span>
								<span class="text-[10px] font-mono text-[var(--text-disabled)]">{(g.format || '').toUpperCase()}</span>
								<Play class="w-4 h-4 text-[var(--text-muted)] flex-shrink-0" />
							</button>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

			{#if view === 'wheel'}<div class="absolute inset-0 bg-[var(--surface-base)]"><CamelotWheel /></div>{/if}
			{#if view === 'tempo'}<div class="absolute inset-0 bg-[var(--surface-base)]"><TempoPunch /></div>{/if}
			{#if view === 'calendar'}<div class="absolute inset-0 overflow-auto bg-[var(--surface-base)]"><StreakCalendar /></div>{/if}
			{#if view === 'adventure'}<div class="absolute inset-0 overflow-auto bg-[var(--surface-base)]"><SonicAdventure /></div>{/if}
	</div>

	<!-- atlas search results -->
	{#if view === 'atlas' && pinTracks.length}
		<div class="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3">
			<div class="flex items-center justify-between mb-2">
				<p class="text-sm font-medium text-[var(--text-primary)]">Nearest to “{searchQuery.trim()}”</p>
				<Button variant="primary" size="sm" onclick={playPinTracks}><Play class="w-3.5 h-3.5 mr-1" /> Play {pinTracks.length}</Button>
			</div>
			<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
				{#each pinTracks as t}
					<button onclick={() => storePlayTrack({ id: t.track_id, title: t.title, artist: t.artist })} class="flex items-center gap-2 text-left px-2 py-1.5 rounded hover:bg-[var(--surface-container-high)] transition-colors">
						<Play class="w-3.5 h-3.5 text-[var(--text-muted)] flex-shrink-0" />
						<span class="min-w-0 flex-1"><span class="text-sm text-[var(--text-primary)] truncate block">{t.title}</span><span class="text-xs text-[var(--text-muted)] truncate block">{t.artist || 'Unknown'}</span></span>
						<span class="text-[10px] font-mono text-[var(--text-disabled)]">{Math.round((t.similarity || 0) * 100)}%</span>
					</button>
				{/each}
			</div>
		</div>
	{/if}

	{#if view === 'atlas' && data && info.count < info.total}
		<p class="text-xs text-[var(--text-disabled)] mt-2">{info.total - info.count} tracks aren't mapped yet (no audio analysis).</p>
	{/if}
</div>
