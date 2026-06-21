<script>
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import { Play, Search, X, Route, Flag, MapPin, Loader2, ArrowDown } from 'lucide-svelte';

	const ACCENT = '#22d3ee';

	// --- endpoint pickers ---
	// each endpoint = { id, title, artist } | null
	let start = $state(null);
	let dest = $state(null);

	// query strings + their dropdown results
	let startQuery = $state('');
	let destQuery = $state('');
	let startResults = $state([]);
	let destResults = $state([]);
	let startOpen = $state(false);
	let destOpen = $state(false);
	let startSearching = $state(false);
	let destSearching = $state(false);

	// --- journey ---
	let building = $state(false);
	let path = $state(null); // array of { track_id, title, artist, album_id } | null

	// debounce + in-flight cancellation per picker
	let startTimer = 0, destTimer = 0;
	let startCtrl = null, destCtrl = null;

	const SEARCH_DEBOUNCE = 250;

	function normalize(res) {
		const items = res?.items ?? res ?? [];
		return Array.isArray(items) ? items : [];
	}

	async function runSearch(which) {
		const q = (which === 'start' ? startQuery : destQuery).trim();
		if (!q) {
			if (which === 'start') { startResults = []; startOpen = false; }
			else { destResults = []; destOpen = false; }
			return;
		}
		// cancel previous in-flight request for this picker
		if (which === 'start') { startCtrl?.abort(); startCtrl = new AbortController(); }
		else { destCtrl?.abort(); destCtrl = new AbortController(); }
		const ctrl = which === 'start' ? startCtrl : destCtrl;

		if (which === 'start') startSearching = true; else destSearching = true;
		try {
			const res = await api.getTracks({ search: q, limit: 8 }, ctrl.signal);
			const items = normalize(res);
			if (which === 'start') { startResults = items; startOpen = true; }
			else { destResults = items; destOpen = true; }
		} catch (e) {
			if (e?.name !== 'AbortError') addToast('Track search failed', 'error');
		} finally {
			if (which === 'start') startSearching = false; else destSearching = false;
		}
	}

	function onInput(which, value) {
		if (which === 'start') {
			startQuery = value;
			start = null; // editing invalidates a previous selection
			clearTimeout(startTimer);
			startTimer = setTimeout(() => runSearch('start'), SEARCH_DEBOUNCE);
		} else {
			destQuery = value;
			dest = null;
			clearTimeout(destTimer);
			destTimer = setTimeout(() => runSearch('dest'), SEARCH_DEBOUNCE);
		}
	}

	function pick(which, t) {
		const ep = { id: t.id, title: t.title, artist: t.artist };
		if (which === 'start') {
			start = ep;
			startQuery = t.title;
			startOpen = false;
			startResults = [];
		} else {
			dest = ep;
			destQuery = t.title;
			destOpen = false;
			destResults = [];
		}
	}

	function clearEndpoint(which) {
		if (which === 'start') { start = null; startQuery = ''; startResults = []; startOpen = false; }
		else { dest = null; destQuery = ''; destResults = []; destOpen = false; }
	}

	const canBuild = $derived(!!start && !!dest && !building);

	async function buildJourney() {
		if (!start || !dest) return;
		building = true;
		path = null;
		try {
			const res = await api.sonicPath(start.id, dest.id, 12);
			if (res?.error) {
				addToast(res.error, 'error');
				return;
			}
			const p = res?.path ?? [];
			if (!p.length) {
				addToast('No path found between those two tracks', 'error');
				return;
			}
			path = p;
		} catch {
			addToast('Failed to build journey', 'error');
		} finally {
			building = false;
		}
	}

	function pathToQueue() {
		return (path || []).map((t) => ({
			id: t.track_id,
			title: t.title,
			artist: t.artist,
			album_id: t.album_id,
		}));
	}

	function playJourney() {
		const list = pathToQueue();
		if (!list.length) return;
		storePlayTrack(list[0], list);
		addToast(`Playing journey — ${list.length} tracks`, 'success');
	}

	function playOne(t) {
		storePlayTrack({ id: t.track_id, title: t.title, artist: t.artist, album_id: t.album_id });
		addToast(`Playing ${t.title}`, 'success');
	}

	// close dropdowns on outside click
	let rootEl;
	function onDocClick(ev) {
		if (rootEl && !rootEl.contains(ev.target)) { startOpen = false; destOpen = false; }
	}
	onMount(() => { document.addEventListener('mousedown', onDocClick); });
	onDestroy(() => {
		document.removeEventListener('mousedown', onDocClick);
		clearTimeout(startTimer); clearTimeout(destTimer);
		startCtrl?.abort(); destCtrl?.abort();
	});
</script>

<div bind:this={rootEl} class="h-full w-full flex flex-col overflow-hidden">
	<!-- header / blurb -->
	<div class="px-4 sm:px-6 pt-4 pb-3 shrink-0">
		<div class="flex items-center gap-2 text-[var(--text-primary)]">
			<Route class="w-5 h-5" style="color:{ACCENT}" />
			<h2 class="text-base sm:text-lg font-semibold">Sonic Adventure</h2>
		</div>
		<p class="text-xs sm:text-sm text-[var(--text-muted)] mt-1">
			Build a queue that morphs from one track's sound into another's — a guided path through your library.
		</p>
	</div>

	<!-- pickers -->
	<div class="px-4 sm:px-6 pb-3 shrink-0 grid grid-cols-1 md:grid-cols-2 gap-3">
		<!-- START -->
		<div class="relative">
			<label class="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-[var(--text-muted)] mb-1">
				<Flag class="w-3.5 h-3.5" style="color:{ACCENT}" /> Start
			</label>
			<div class="relative">
				<Search class="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
				<input
					type="text"
					value={startQuery}
					oninput={(e) => onInput('start', e.currentTarget.value)}
					onfocus={() => { if (startResults.length) startOpen = true; }}
					placeholder="Search a starting track…"
					class="w-full pl-8 pr-8 py-2 text-sm rounded-md bg-[var(--surface-lowest)] text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] border {start ? 'border-[#22d3ee]/50' : 'border-[var(--border-subtle)]'} focus:outline-none focus:ring-2 focus:ring-[#22d3ee]/30" />
				{#if startSearching}
					<Loader2 class="w-4 h-4 absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] animate-spin" />
				{:else if startQuery}
					<button onclick={() => clearEndpoint('start')} class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)]" aria-label="Clear start">
						<X class="w-4 h-4" />
					</button>
				{/if}
			</div>
			{#if startOpen && startResults.length}
				<ul class="absolute z-30 mt-1 w-full max-h-64 overflow-auto rounded-md border border-[var(--border-subtle)] bg-[var(--surface-container)] shadow-xl">
					{#each startResults as t (t.id)}
						<li>
							<button onclick={() => pick('start', t)} class="w-full text-left px-3 py-2 hover:bg-[var(--surface-container-high)] transition-colors">
								<span class="text-sm text-[var(--text-primary)] truncate block">{t.title}</span>
								<span class="text-xs text-[var(--text-muted)] truncate block">{t.artist || 'Unknown'}</span>
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		<!-- DESTINATION -->
		<div class="relative">
			<label class="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-[var(--text-muted)] mb-1">
				<MapPin class="w-3.5 h-3.5" style="color:{ACCENT}" /> Destination
			</label>
			<div class="relative">
				<Search class="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
				<input
					type="text"
					value={destQuery}
					oninput={(e) => onInput('dest', e.currentTarget.value)}
					onfocus={() => { if (destResults.length) destOpen = true; }}
					placeholder="Search a destination track…"
					class="w-full pl-8 pr-8 py-2 text-sm rounded-md bg-[var(--surface-lowest)] text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] border {dest ? 'border-[#22d3ee]/50' : 'border-[var(--border-subtle)]'} focus:outline-none focus:ring-2 focus:ring-[#22d3ee]/30" />
				{#if destSearching}
					<Loader2 class="w-4 h-4 absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] animate-spin" />
				{:else if destQuery}
					<button onclick={() => clearEndpoint('dest')} class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)]" aria-label="Clear destination">
						<X class="w-4 h-4" />
					</button>
				{/if}
			</div>
			{#if destOpen && destResults.length}
				<ul class="absolute z-30 mt-1 w-full max-h-64 overflow-auto rounded-md border border-[var(--border-subtle)] bg-[var(--surface-container)] shadow-xl">
					{#each destResults as t (t.id)}
						<li>
							<button onclick={() => pick('dest', t)} class="w-full text-left px-3 py-2 hover:bg-[var(--surface-container-high)] transition-colors">
								<span class="text-sm text-[var(--text-primary)] truncate block">{t.title}</span>
								<span class="text-xs text-[var(--text-muted)] truncate block">{t.artist || 'Unknown'}</span>
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</div>

	<!-- actions -->
	<div class="px-4 sm:px-6 pb-3 shrink-0 flex flex-wrap items-center gap-2">
		<button
			onclick={buildJourney}
			disabled={!canBuild}
			class="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed text-black"
			style="background:{ACCENT}">
			{#if building}
				<Loader2 class="w-4 h-4 animate-spin" /> Building…
			{:else}
				<Route class="w-4 h-4" /> Build journey
			{/if}
		</button>
		{#if path?.length}
			<button onclick={playJourney}
				class="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium rounded-md border border-[#22d3ee]/40 text-[#22d3ee] hover:bg-[#22d3ee]/10 transition-colors">
				<Play class="w-4 h-4" /> Play journey ({path.length})
			</button>
		{/if}
	</div>

	<!-- result list -->
	<div class="flex-1 min-h-0 overflow-auto px-4 sm:px-6 pb-5">
		{#if building}
			<div class="h-full flex flex-col items-center justify-center gap-3 text-[var(--text-secondary)]">
				<div class="w-8 h-8 border-2 rounded-full animate-spin" style="border-color:{ACCENT}; border-top-color:transparent"></div>
				<p class="text-sm">Charting a path through your sound…</p>
			</div>
		{:else if path?.length}
			<ol class="relative max-w-2xl mx-auto">
				{#each path as t, i (t.track_id + '-' + i)}
					<li class="relative pl-10">
						<!-- connecting line -->
						{#if i < path.length - 1}
							<span class="absolute left-[15px] top-7 bottom-[-8px] w-px" style="background:linear-gradient(to bottom, {ACCENT}, {ACCENT}55)"></span>
						{/if}
						<!-- node dot -->
						<span class="absolute left-2 top-2.5 flex items-center justify-center">
							<span class="w-3 h-3 rounded-full ring-2 ring-[var(--surface-base)]"
								style="background:{i === 0 || i === path.length - 1 ? ACCENT : 'var(--surface-container-high)'}; box-shadow:0 0 0 1px {ACCENT}66"></span>
						</span>

						<button onclick={() => playOne(t)}
							class="group w-full text-left flex items-center gap-3 px-3 py-2 my-1 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-lowest)] hover:bg-[var(--surface-container-high)] transition-colors">
							<span class="text-xs font-mono w-6 shrink-0" style="color:{i === 0 || i === path.length - 1 ? ACCENT : 'var(--text-disabled)'}">{i + 1}</span>
							<span class="min-w-0 flex-1">
								<span class="text-sm text-[var(--text-primary)] truncate block">{t.title}</span>
								<span class="text-xs text-[var(--text-muted)] truncate block">{t.artist || 'Unknown'}</span>
							</span>
							{#if i === 0}
								<span class="text-[10px] uppercase tracking-wide font-medium px-1.5 py-0.5 rounded shrink-0" style="background:{ACCENT}22; color:{ACCENT}">Start</span>
							{:else if i === path.length - 1}
								<span class="text-[10px] uppercase tracking-wide font-medium px-1.5 py-0.5 rounded shrink-0" style="background:{ACCENT}22; color:{ACCENT}">End</span>
							{/if}
							<Play class="w-4 h-4 text-[var(--text-muted)] group-hover:text-[var(--text-primary)] shrink-0" />
						</button>
					</li>
				{/each}
			</ol>
		{:else}
			<div class="h-full flex flex-col items-center justify-center gap-3 text-center px-6">
				<div class="flex items-center gap-2 text-[var(--text-disabled)]">
					<Flag class="w-5 h-5" />
					<ArrowDown class="w-4 h-4 rotate-[-90deg]" />
					<MapPin class="w-5 h-5" />
				</div>
				<p class="text-sm text-[var(--text-secondary)]">Pick a <span style="color:{ACCENT}">start</span> and a <span style="color:{ACCENT}">destination</span> track, then build the journey.</p>
				<p class="text-xs text-[var(--text-disabled)] max-w-sm">Zonik finds intermediate tracks whose sound gradually shifts from the first to the last, so the queue eases between the two moods.</p>
			</div>
		{/if}
	</div>
</div>
