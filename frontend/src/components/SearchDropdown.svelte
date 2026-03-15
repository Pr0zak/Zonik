<script>
	import { goto } from '$app/navigation';
	import { Search, Play, Download, Check, Loader2 } from 'lucide-svelte';
	import { api } from '$lib/api.js';
	import { playTrack, addToast } from '$lib/stores.js';
	import { formatSize } from '$lib/utils.js';
	import FormatBadge from './ui/FormatBadge.svelte';
	import Skeleton from './ui/Skeleton.svelte';

	let { query = '', onclose = () => {}, onnavigate = () => {} } = $props();

	let libraryResults = $state([]);
	let lastfmResults = $state([]);
	let p2pResults = $state([]);
	let libraryLoading = $state(false);
	let lastfmLoading = $state(false);
	let p2pLoading = $state(false);
	let downloadingKeys = $state(new Set());
	let selectedIndex = $state(-1);
	let abortController = $state(null);

	// Simple NL detection (mirrors TopBar)
	function looksLikeNL(q) {
		if (q.length < 8) return false;
		const nlWords = /\b(find|show|get|give|play)\b.*\b(me|some|all)\b/i;
		const moodWords = /\b(chill|upbeat|energetic|mellow|dark|happy|sad|relaxing|ambient)\b.*\b(track|song|music)\b/i;
		const timeWords = /\bfrom\s+(last|this)\s+(week|month|year)\b/i;
		const topWords = /\b(top|best|most)\s+(played|rated|popular)\b/i;
		return nlWords.test(q) || moodWords.test(q) || timeWords.test(q) || topWords.test(q) || (q.split(' ').length > 4 && !q.includes(' - '));
	}

	// Flat list of all results for keyboard nav
	let allResults = $derived([
		...libraryResults.map(t => ({ type: 'library', data: t })),
		...lastfmResults.map(t => ({ type: 'lastfm', data: t })),
		...p2pResults.map(t => ({ type: 'p2p', data: t })),
	]);

	// Deduplicate: hide Last.fm results that are already in library results
	let filteredLastfm = $derived(() => {
		const libraryKeys = new Set(libraryResults.map(t =>
			`${(t.artist || '').toLowerCase()}|${(t.title || '').toLowerCase()}`
		));
		return lastfmResults.filter(t => {
			const key = `${(t.artist || '').toLowerCase()}|${(t.name || '').toLowerCase()}`;
			return !libraryKeys.has(key);
		});
	});

	let anyLoading = $derived(libraryLoading || lastfmLoading || p2pLoading);
	let hasResults = $derived(libraryResults.length > 0 || filteredLastfm().length > 0 || p2pResults.length > 0);

	// Re-derive flat results with deduped lastfm
	let flatResults = $derived([
		...libraryResults.map(t => ({ type: 'library', data: t })),
		...filteredLastfm().map(t => ({ type: 'lastfm', data: t })),
		...p2pResults.map(t => ({ type: 'p2p', data: t })),
	]);

	$effect(() => {
		const q = query.trim();
		if (!q) {
			libraryResults = [];
			lastfmResults = [];
			p2pResults = [];
			selectedIndex = -1;
			return;
		}

		// Debounce
		const timer = setTimeout(() => doSearch(q), 300);
		return () => clearTimeout(timer);
	});

	async function doSearch(q) {
		// Cancel previous
		if (abortController) abortController.abort();
		const ac = new AbortController();
		abortController = ac;
		selectedIndex = -1;

		const isNL = looksLikeNL(q);

		// Lane 1: Library (instant)
		libraryLoading = true;
		(async () => {
			try {
				if (isNL) {
					const data = await api.aiSearch(q, 5, ac.signal);
					if (!ac.signal.aborted) libraryResults = data.tracks || [];
				} else {
					const data = await api.getTracks({ search: q, limit: 5 }, ac.signal);
					if (!ac.signal.aborted) libraryResults = (data.tracks || data || []).slice(0, 5);
				}
			} catch (e) {
				if (e.name !== 'AbortError' && !ac.signal.aborted) libraryResults = [];
			} finally {
				if (!ac.signal.aborted) libraryLoading = false;
			}
		})();

		// Lane 2: Last.fm (1-3s)
		if (q.length >= 3) {
			lastfmLoading = true;
			(async () => {
				try {
					const data = await api.discoverySearch(q, 5, ac.signal);
					if (!ac.signal.aborted) lastfmResults = (data.tracks || []).slice(0, 5);
				} catch (e) {
					if (e.name !== 'AbortError' && !ac.signal.aborted) lastfmResults = [];
				} finally {
					if (!ac.signal.aborted) lastfmLoading = false;
				}
			})();
		} else {
			lastfmResults = [];
			lastfmLoading = false;
		}

		// Lane 3: P2P (10-25s) — only if query looks like "Artist - Track"
		if (q.length >= 5 && q.includes(' - ')) {
			p2pLoading = true;
			(async () => {
				try {
					const data = await api.p2pSearch({ query: q, timeout: 10 }, ac.signal);
					if (!ac.signal.aborted) p2pResults = (data.results || []).slice(0, 3);
				} catch (e) {
					if (e.name !== 'AbortError' && !ac.signal.aborted) p2pResults = [];
				} finally {
					if (!ac.signal.aborted) p2pLoading = false;
				}
			})();
		} else {
			p2pResults = [];
			p2pLoading = false;
		}
	}

	function formatListeners(count) {
		if (!count) return '';
		if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
		if (count >= 1_000) return `${(count / 1_000).toFixed(0)}K`;
		return String(count);
	}

	function shortFilename(path) {
		if (!path) return '';
		const name = path.split(/[/\\]/).pop() || path;
		return name.length > 40 ? name.slice(0, 37) + '...' : name;
	}

	async function downloadLastfm(track) {
		const key = `lastfm:${track.artist}:${track.name}`;
		if (downloadingKeys.has(key)) return;
		downloadingKeys = new Set([...downloadingKeys, key]);
		try {
			await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ artist: track.artist, track: track.name, source: 'search' }),
			});
			addToast(`Downloading ${track.artist} — ${track.name}`, 'success');
		} catch {
			addToast('Download failed', 'error');
		}
	}

	async function downloadP2P(result) {
		const key = `p2p:${result.username}:${result.filename}`;
		if (downloadingKeys.has(key)) return;
		downloadingKeys = new Set([...downloadingKeys, key]);
		// Parse artist/track from query
		const parts = query.trim().split(/\s*[-–—]\s*/);
		const artist = parts[0] || '';
		const track = parts.slice(1).join(' ') || '';
		try {
			await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					artist, track,
					username: result.username,
					filename: result.filename,
					source: 'search',
				}),
			});
			addToast(`Downloading from ${result.username}`, 'success');
		} catch {
			addToast('Download failed', 'error');
		}
	}

	function handlePlay(track) {
		playTrack(track);
		onclose();
	}

	function goToDownloads() {
		const q = query.trim();
		if (q) {
			const parts = q.split(/\s*[-–—]\s*/);
			if (parts.length >= 2) {
				onnavigate(`/downloads?artist=${encodeURIComponent(parts[0])}&track=${encodeURIComponent(parts.slice(1).join(' '))}`);
			} else {
				onnavigate(`/downloads?search=${encodeURIComponent(q)}`);
			}
		} else {
			onnavigate('/downloads');
		}
	}

	export function handleKeydown(e) {
		const total = flatResults.length;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			selectedIndex = selectedIndex < total - 1 ? selectedIndex + 1 : 0;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			selectedIndex = selectedIndex > 0 ? selectedIndex - 1 : total - 1;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (selectedIndex >= 0 && selectedIndex < total) {
				const item = flatResults[selectedIndex];
				if (item.type === 'library') handlePlay(item.data);
				else if (item.type === 'lastfm') downloadLastfm(item.data);
				else if (item.type === 'p2p') downloadP2P(item.data);
			} else {
				goToDownloads();
			}
		}
	}
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="absolute top-full left-0 right-0 mt-1 w-full max-w-80 sm:max-w-none bg-[var(--bg-secondary)] border border-[var(--border-subtle)] rounded-lg shadow-xl z-50 overflow-hidden animate-fade-slide-in max-h-[70vh] overflow-y-auto">
	<!-- Library Section -->
	{#if libraryLoading && !libraryResults.length}
		<div class="px-3 py-1.5 text-xs uppercase tracking-wider text-[var(--text-disabled)] border-b border-[var(--border-subtle)]">In Your Library</div>
		<div class="px-3 py-2 space-y-2">
			<Skeleton class="h-4 w-3/4" />
			<Skeleton class="h-4 w-1/2" />
		</div>
	{:else if libraryResults.length}
		<div class="px-3 py-1.5 text-xs uppercase tracking-wider text-[var(--text-disabled)] border-b border-[var(--border-subtle)] flex items-center justify-between">
			<span>In Your Library</span>
			<span class="text-[var(--text-disabled)]">{libraryResults.length}</span>
		</div>
		{#each libraryResults as track, i}
			{@const flatIdx = i}
			<button onclick={() => handlePlay(track)}
				class="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-[var(--bg-hover)] transition-colors group {selectedIndex === flatIdx ? 'bg-[var(--bg-hover)]' : ''}">
				<div class="flex-1 min-w-0">
					<p class="text-sm text-[var(--text-primary)] truncate">{track.title}</p>
					<p class="text-xs text-[var(--text-muted)] truncate">{track.artist || ''}</p>
				</div>
				{#if track.extension || track.format}
					<FormatBadge format={track.extension || track.format || ''} />
				{/if}
				<Play class="w-3.5 h-3.5 text-[var(--text-disabled)] group-hover:text-[var(--color-accent)] flex-shrink-0" />
			</button>
		{/each}
	{/if}

	<!-- Last.fm Section -->
	{#if lastfmLoading && !filteredLastfm().length}
		<div class="px-3 py-1.5 text-xs uppercase tracking-wider text-[var(--color-discovery)] border-b border-[var(--border-subtle)]">Last.fm</div>
		<div class="px-3 py-2 space-y-2">
			<Skeleton class="h-4 w-3/4" />
			<Skeleton class="h-4 w-1/2" />
		</div>
	{:else if filteredLastfm().length}
		<div class="px-3 py-1.5 text-xs uppercase tracking-wider text-[var(--color-discovery)] border-b border-[var(--border-subtle)] flex items-center justify-between">
			<span>Last.fm</span>
			<span class="text-[var(--text-disabled)]">{filteredLastfm().length}</span>
		</div>
		{#each filteredLastfm() as track, i}
			{@const flatIdx = libraryResults.length + i}
			{@const key = `lastfm:${track.artist}:${track.name}`}
			<div class="w-full flex items-center gap-3 px-3 py-2 hover:bg-[var(--bg-hover)] transition-colors {selectedIndex === flatIdx ? 'bg-[var(--bg-hover)]' : ''}">
				<div class="flex-1 min-w-0">
					<p class="text-sm text-[var(--text-primary)] truncate">{track.name}</p>
					<p class="text-xs text-[var(--text-muted)] truncate">{track.artist || ''}</p>
				</div>
				{#if track.listeners}
					<span class="text-xs text-[var(--text-disabled)] font-mono flex-shrink-0">{formatListeners(track.listeners)}</span>
				{/if}
				{#if track.in_library}
					<Check class="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
				{:else if downloadingKeys.has(key)}
					<Loader2 class="w-3.5 h-3.5 text-[var(--color-downloads)] animate-spin flex-shrink-0" />
				{:else}
					<button onclick={() => downloadLastfm(track)}
						class="p-1 rounded hover:bg-[var(--bg-tertiary)] text-[var(--text-disabled)] hover:text-[var(--color-downloads)] transition-colors flex-shrink-0"
						title="Download">
						<Download class="w-3.5 h-3.5" />
					</button>
				{/if}
			</div>
		{/each}
	{/if}

	<!-- P2P Section -->
	{#if p2pLoading && !p2pResults.length}
		<div class="px-3 py-1.5 text-xs uppercase tracking-wider text-[var(--color-downloads)] border-b border-[var(--border-subtle)]">P2P Sources</div>
		<div class="px-3 py-2 space-y-2">
			<Skeleton class="h-4 w-full" />
			<Skeleton class="h-4 w-2/3" />
		</div>
	{:else if p2pResults.length}
		<div class="px-3 py-1.5 text-xs uppercase tracking-wider text-[var(--color-downloads)] border-b border-[var(--border-subtle)] flex items-center justify-between">
			<span>P2P Sources</span>
			<span class="text-[var(--text-disabled)]">{p2pResults.length}</span>
		</div>
		{#each p2pResults as result, i}
			{@const flatIdx = libraryResults.length + filteredLastfm().length + i}
			{@const key = `p2p:${result.username}:${result.filename}`}
			<div class="w-full flex items-center gap-2 px-3 py-2 hover:bg-[var(--bg-hover)] transition-colors {selectedIndex === flatIdx ? 'bg-[var(--bg-hover)]' : ''}">
				<div class="flex-1 min-w-0">
					<p class="text-sm text-[var(--text-primary)] truncate font-mono text-xs">{shortFilename(result.filename)}</p>
					<p class="text-xs text-[var(--text-muted)] truncate">{result.username}</p>
				</div>
				{#if result.extension}
					<FormatBadge format={result.extension} />
				{/if}
				<span class="text-xs text-[var(--text-disabled)] font-mono flex-shrink-0">{formatSize(result.size)}</span>
				{#if downloadingKeys.has(key)}
					<Loader2 class="w-3.5 h-3.5 text-[var(--color-downloads)] animate-spin flex-shrink-0" />
				{:else}
					<button onclick={() => downloadP2P(result)}
						class="p-1 rounded hover:bg-[var(--bg-tertiary)] text-[var(--text-disabled)] hover:text-[var(--color-downloads)] transition-colors flex-shrink-0"
						title="Download">
						<Download class="w-3.5 h-3.5" />
					</button>
				{/if}
			</div>
		{/each}
	{/if}

	<!-- Footer: always visible when there's a query -->
	{#if query.trim()}
		<button onclick={goToDownloads}
			class="w-full flex items-center gap-2 px-3 py-2.5 text-left border-t border-[var(--border-subtle)] hover:bg-[var(--bg-hover)] transition-colors text-[var(--color-downloads)]">
			<Search class="w-3.5 h-3.5" />
			<span class="text-sm">Search all sources for "{query.trim()}"</span>
		</button>
	{/if}
</div>
