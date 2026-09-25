<script>
	// Explore: one set of tracks, three ways to lay them out (key wheel, tempo ×
	// loudness, sound atlas). Filters, colouring and the current selection are
	// shared, so a selection made on one layout can be checked on another before
	// it's saved as a playlist.
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api.js';
	import { addToast } from '$lib/stores.js';
	import Button from '../ui/Button.svelte';
	import Toggle from '../ui/Toggle.svelte';
	import SelectionBar from './SelectionBar.svelte';
	import ExploreWheel from './ExploreWheel.svelte';
	import ExploreTempo from './ExploreTempo.svelte';
	import ExploreAtlas from './ExploreAtlas.svelte';
	import { camelot, familyColor, FAMILY_COLORS } from './explore.js';
	import { Search, X, RefreshCw, TriangleAlert, Loader2 } from 'lucide-svelte';

	const LAYOUTS = [['wheel', 'Key wheel'], ['tempo', 'Tempo × loudness'], ['atlas', 'Sound atlas']];

	let layout = $state(load('zonik.map.layout', 'wheel'));
	let colorMode = $state(load('zonik.map.color', 'family')); // family | plays
	let unplayedOnly = $state(false);
	let hiddenFamilies = $state(new Set());

	let loading = $state(true);
	let points = $state([]);
	let health = $state(null);
	let rebuilding = $state(false);
	let analysing = $state(false);
	let pollTimer = 0;

	let sel = $state({ idxs: [], name: '' });
	const selected = $derived(new Set(sel.idxs));

	let vibe = $state('');
	let vibeBusy = $state(false);
	let pin = $state(null);

	function load(k, d) { try { return localStorage.getItem(k) || d; } catch { return d; } }
	function save(k, v) { try { localStorage.setItem(k, v); } catch {} }
	$effect(() => save('zonik.map.layout', layout));
	$effect(() => save('zonik.map.color', colorMode));

	// --- data ---
	async function loadAll() {
		const [feat, atlas, h] = await Promise.all([
			api.getAudioFeatures().catch(() => null),
			api.getSoundscape().catch(() => null),
			api.getMapHealth().catch(() => null),
		]);
		health = h;
		if (atlas?.computing) { rebuilding = true; poll(); }
		const byId = new Map();
		const get = (id) => {
			let p = byId.get(id);
			if (!p) { p = { id, cam: null, bpm: null, loudness: null, x: null, y: null, plays: 0, family: 'Unknown' }; byId.set(id, p); }
			return p;
		};
		if (feat) for (let k = 0; k < feat.count; k++) {
			const p = get(feat.ids[k]);
			Object.assign(p, {
				title: feat.title[k], artist: feat.artist[k], album_id: feat.album_id[k],
				cam: camelot(feat.key[k], feat.scale[k]), bpm: feat.bpm[k], loudness: feat.loudness[k],
				family: feat.family[k], plays: feat.play_count[k] || 0,
			});
		}
		if (atlas) for (let k = 0; k < atlas.count; k++) {
			const p = get(atlas.ids[k]);
			p.x = atlas.x[k]; p.y = atlas.y[k];
			p.title ??= atlas.title[k]; p.artist ??= atlas.artist[k]; p.album_id ??= atlas.album_id[k];
			if (!feat) { p.family = atlas.family[k]; p.plays = atlas.play_count[k] || 0; }
		}
		const bad = new Set((h?.loudness_outliers || []).map((o) => o.track_id));
		points = [...byId.values()].map((p, i) => ({ ...p, i, bad: bad.has(p.id) }));
		sel = { idxs: [], name: '' };
		loading = false;
	}

	function poll() {
		if (pollTimer) return;
		pollTimer = setInterval(async () => {
			try {
				const s = await api.getSoundscape();
				if (!s.computing) {
					clearInterval(pollTimer); pollTimer = 0; rebuilding = false;
					addToast(`Sound atlas rebuilt — ${s.count.toLocaleString()} tracks`, 'success');
					await loadAll();
				}
			} catch {}
		}, 5000);
	}

	async function rebuildAtlas() {
		try { rebuilding = true; await api.recomputeSoundscape(); addToast('Rebuilding the sound atlas… (a few minutes)', 'info'); poll(); }
		catch { rebuilding = false; addToast('Could not start the rebuild', 'error'); }
	}

	async function analyse() {
		analysing = true;
		try {
			await api.startAnalysis();
			await api.startEmbeddings();
			addToast('Analysis queued — follow it on the Analysis page', 'success');
		} catch (e) { addToast(`Could not start analysis: ${e.message}`, 'error'); }
		finally { analysing = false; }
	}

	function selectOutliers() {
		const ids = new Set((health?.loudness_outliers || []).map((o) => o.track_id));
		const idxs = points.filter((p) => ids.has(p.id)).map((p) => p.i);
		layout = 'tempo';
		sel = { idxs, name: 'Bad loudness readings' };
	}

	// --- filtering + colour ---
	const familyCounts = $derived.by(() => {
		const c = new Map();
		for (const p of points) c.set(p.family, (c.get(p.family) || 0) + 1);
		return [...c.entries()].sort((a, b) => (a[0] === 'Unknown') - (b[0] === 'Unknown') || b[1] - a[1]);
	});

	const visible = $derived.by(() => {
		const v = new Uint8Array(points.length);
		for (const p of points) v[p.i] = !hiddenFamilies.has(p.family) && (!unplayedOnly || !p.plays) ? 1 : 0;
		return v;
	});
	const visibleCount = $derived(visible.reduce((a, b) => a + b, 0));

	const colorOf = $derived(colorMode === 'plays'
		? (p) => (p.plays ? `rgba(34,211,238,${Math.min(1, 0.35 + Math.log2(1 + p.plays) / 5).toFixed(2)})` : '#f59e0b')
		: (p) => familyColor(p.family));

	function toggleFamily(f, only) {
		if (only) {
			const all = familyCounts.map(([k]) => k);
			const soloed = hiddenFamilies.size === all.length - 1 && !hiddenFamilies.has(f);
			hiddenFamilies = soloed ? new Set() : new Set(all.filter((k) => k !== f));
			return;
		}
		const next = new Set(hiddenFamilies);
		next.has(f) ? next.delete(f) : next.add(f);
		hiddenFamilies = next;
	}

	// --- selection ---
	function onselect(idxs, name, { add = false, toggle = false } = {}) {
		if (toggle && idxs.length === 1) {
			const i = idxs[0];
			sel = selected.has(i)
				? { idxs: sel.idxs.filter((k) => k !== i), name: sel.name }
				: { idxs: [...sel.idxs, i], name: sel.idxs.length ? sel.name : name };
			return;
		}
		if (add && sel.idxs.length) {
			const seen = new Set(sel.idxs);
			sel = { idxs: [...sel.idxs, ...idxs.filter((i) => !seen.has(i))], name: `${sel.name} + ${name}` };
		} else {
			sel = { idxs, name };
		}
	}
	const selTracks = $derived(sel.idxs.map((i) => points[i]).filter(Boolean));

	async function findVibe() {
		const q = vibe.trim();
		if (!q) return;
		vibeBusy = true;
		try {
			const r = await api.locateSoundscape(q, 40);
			if (r.error && !r.tracks) { addToast(r.error, 'error'); return; }
			const byId = new Map(points.map((p) => [p.id, p.i]));
			const idxs = (r.tracks || []).map((t) => byId.get(t.track_id)).filter((i) => i != null);
			sel = { idxs, name: `Vibe: ${q}` };
			pin = r.x != null ? { x: r.x, y: r.y } : null;
			if (!idxs.length) addToast('No tracks match that vibe', 'info');
		} catch { addToast('Vibe search failed', 'error'); }
		finally { vibeBusy = false; }
	}
	function clearVibe() { vibe = ''; pin = null; }

	onMount(loadAll);
	onDestroy(() => { if (pollTimer) clearInterval(pollTimer); });

	// Health items worth a banner, each with a fix.
	const issues = $derived.by(() => {
		if (!health) return [];
		const out = [];
		if (health.unprojected > 0) out.push({ key: 'atlas', text: `${health.unprojected.toLocaleString()} analysed tracks aren't on the sound atlas yet`, action: 'Rebuild atlas', run: rebuildAtlas, busy: rebuilding });
		const pending = Math.max(health.unanalysed, health.no_embedding);
		if (pending > 0) out.push({ key: 'analyse', text: `${pending.toLocaleString()} tracks haven't been analysed, so they're missing from the map`, action: 'Analyse', run: analyse, busy: analysing });
		if (health.loudness_outliers?.length) out.push({ key: 'loud', text: `${health.loudness_outliers.length} tracks have impossible loudness readings (above 0 dB) — likely broken files`, action: 'Show them', run: selectOutliers });
		if (health.no_genre > 0) out.push({ key: 'genre', text: `${health.no_genre.toLocaleString()} tracks have no genre and show as Unknown`, action: 'Open library', href: '/library' });
		return out;
	});
</script>

{#if issues.length}
	<div class="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/5 divide-y divide-amber-500/10">
		{#each issues as it (it.key)}
			<div class="flex items-center gap-2 px-3 py-1.5 text-xs">
				<TriangleAlert class="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
				<span class="flex-1 text-[var(--text-secondary)]">{it.text}</span>
				{#if it.href}
					<a href={it.href} class="text-amber-400 hover:underline whitespace-nowrap">{it.action}</a>
				{:else}
					<Button variant="warning" size="sm" loading={it.busy} onclick={it.run} class="whitespace-nowrap">{it.action}</Button>
				{/if}
			</div>
		{/each}
	</div>
{/if}

<!-- toolbar -->
<div class="flex flex-wrap items-center gap-2 mt-3">
	<div class="flex rounded-md overflow-hidden border border-[var(--border-subtle)] text-xs">
		{#each LAYOUTS as [v, label]}
			<button onclick={() => (layout = v)} aria-pressed={layout === v}
				class="px-3 py-1.5 whitespace-nowrap {layout === v ? 'bg-[#22d3ee] text-black font-medium' : 'bg-[var(--surface-lowest)] text-[var(--text-secondary)] hover:bg-[var(--surface-container-high)]'}">{label}</button>
		{/each}
	</div>
	<form class="relative flex-1 min-w-[200px] max-w-sm" onsubmit={(e) => { e.preventDefault(); findVibe(); }}>
		<Search class="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
		<input type="text" bind:value={vibe} placeholder="Select by vibe… e.g. “rainy lo-fi jazz”"
			class="pl-8 pr-8 py-1.5 text-sm rounded-md bg-[var(--surface-lowest)] text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] w-full focus:outline-none focus:ring-2 focus:ring-[#22d3ee]/30" />
		{#if vibeBusy}<Loader2 class="w-4 h-4 absolute right-2.5 top-1/2 -translate-y-1/2 animate-spin text-[var(--text-muted)]" />
		{:else if vibe}<button type="button" onclick={clearVibe} class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)]" aria-label="Clear vibe"><X class="w-4 h-4" /></button>{/if}
	</form>
	<div class="flex items-center gap-3 ml-auto">
		<div class="flex rounded-md overflow-hidden border border-[var(--border-subtle)] text-xs">
			<span class="px-2 py-1.5 text-[var(--text-muted)] bg-[var(--surface-lowest)]">Colour</span>
			{#each [['family', 'Genre'], ['plays', 'Plays']] as [m, label]}
				<button onclick={() => (colorMode = m)} aria-pressed={colorMode === m}
					class="px-2.5 py-1.5 {colorMode === m ? 'bg-[var(--color-primary)] text-white' : 'bg-[var(--surface-lowest)] text-[var(--text-secondary)] hover:bg-[var(--surface-container-high)]'}">{label}</button>
			{/each}
		</div>
		<Toggle size="sm" checked={unplayedOnly} onchange={(v) => (unplayedOnly = v)} label="Never played" color="#f59e0b" />
		{#if layout === 'atlas'}
			<Button variant="icon" size="sm" loading={rebuilding} onclick={rebuildAtlas} title="Rebuild the sound atlas" aria-label="Rebuild the sound atlas"><RefreshCw class="w-3.5 h-3.5" /></Button>
		{/if}
	</div>
</div>

<div class="mt-2 min-h-[44px]">
	{#if selTracks.length}
		<SelectionBar tracks={selTracks} name={sel.name} onclear={() => (sel = { idxs: [], name: '' })} />
	{:else}
		<p class="text-xs text-[var(--text-muted)] py-3">
			{visibleCount.toLocaleString()} of {points.length.toLocaleString()} tracks shown. Select tracks on the map to save them as a playlist for your phone.
		</p>
	{/if}
</div>

<div class="relative mt-2 rounded-xl overflow-hidden border border-[var(--border-subtle)] bg-[var(--surface-base)]" style="height: 64vh; min-height: 420px;">
	{#if loading}
		<div class="absolute inset-0 flex items-center justify-center gap-2 text-sm text-[var(--text-secondary)]">
			<Loader2 class="w-5 h-5 animate-spin text-[#22d3ee]" /> Loading the map…
		</div>
	{:else if layout === 'wheel'}
		<ExploreWheel {points} {visible} {selected} {colorOf} {onselect} />
	{:else if layout === 'tempo'}
		<ExploreTempo {points} {visible} {selected} {colorOf} {onselect} />
	{:else}
		<ExploreAtlas {points} {visible} {selected} {colorOf} {onselect} {pin} />
	{/if}
</div>

<!-- legend doubles as the genre filter -->
<div class="flex flex-wrap items-center gap-1.5 mt-3 text-xs">
	{#if colorMode === 'plays'}
		<span class="flex items-center gap-1 text-[var(--text-secondary)] mr-2"><span class="w-2.5 h-2.5 rounded-full bg-[#f59e0b]"></span>never played</span>
		<span class="flex items-center gap-1 text-[var(--text-secondary)] mr-3"><span class="w-2.5 h-2.5 rounded-full bg-[#22d3ee]"></span>played (brighter = more)</span>
	{/if}
	<span class="text-[var(--text-muted)] mr-1">Genres:</span>
	{#each familyCounts as [f, n] (f)}
		<button onclick={(e) => toggleFamily(f, e.altKey || e.metaKey)} title="Click to hide/show · Alt-click to show only this"
			class="flex items-center gap-1.5 px-2 py-1 rounded-md border transition-colors {hiddenFamilies.has(f) ? 'border-transparent text-[var(--text-disabled)] line-through' : 'border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--surface-container-high)]'}">
			<span class="w-2.5 h-2.5 rounded-full flex-shrink-0" style="background:{FAMILY_COLORS[f] || familyColor(f)}; opacity:{hiddenFamilies.has(f) ? 0.3 : 1}"></span>{f}<span class="text-[var(--text-disabled)]">{n.toLocaleString()}</span>
		</button>
	{/each}
	{#if hiddenFamilies.size}<button onclick={() => (hiddenFamilies = new Set())} class="px-2 py-1 text-[#22d3ee] hover:underline">Show all</button>{/if}
</div>
