<script>
	import { goto } from '$app/navigation';
	import { Search, X } from 'lucide-svelte';
	import { api } from '$lib/api.js';

	let query = $state('');
	let results = $state([]);
	let showResults = $state(false);
	let loading = $state(false);
	let debounceTimer;
	let inputEl;

	function onInput() {
		clearTimeout(debounceTimer);
		if (!query.trim()) {
			results = [];
			showResults = false;
			return;
		}
		debounceTimer = setTimeout(async () => {
			loading = true;
			try {
				const data = await api.getTracks({ search: query.trim(), limit: 8 });
				results = (data.tracks || data || []).slice(0, 8);
				showResults = results.length > 0;
			} catch {
				results = [];
			} finally {
				loading = false;
			}
		}, 250);
	}

	function goToTrack(track) {
		showResults = false;
		query = '';
		goto(`/library?search=${encodeURIComponent(track.title || query)}`);
	}

	function goToDownloads() {
		const q = query.trim();
		showResults = false;
		query = '';
		if (q) {
			// Try to split "Artist - Track" or just pass as search
			const parts = q.split(/\s*[-–—]\s*/);
			if (parts.length >= 2) {
				goto(`/downloads?artist=${encodeURIComponent(parts[0])}&track=${encodeURIComponent(parts.slice(1).join(' '))}`);
			} else {
				goto(`/downloads?search=${encodeURIComponent(q)}`);
			}
		} else {
			goto('/downloads');
		}
	}

	function onKeydown(e) {
		if (e.key === 'Escape') {
			showResults = false;
			query = '';
			inputEl?.blur();
		} else if (e.key === 'Enter') {
			if (query.trim()) {
				goToDownloads();
			}
		}
	}

	function onBlur() {
		// Delay to allow click on results
		setTimeout(() => { showResults = false; }, 200);
	}
</script>

<div class="relative flex-1 max-w-xl">
	<div class="relative">
		<Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-disabled)]" />
		<input
			bind:this={inputEl}
			type="text"
			data-search-input
			placeholder="Search library or P2P network..."
			bind:value={query}
			oninput={onInput}
			onkeydown={onKeydown}
			onfocus={() => { if (results.length) showResults = true; }}
			onblur={onBlur}
			class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-interactive)] rounded-lg pl-9 pr-8 py-2 text-sm text-[var(--text-body)]
				placeholder-[var(--text-disabled)] focus:outline-none focus:border-[var(--color-accent)]/50 focus:ring-1 focus:ring-[var(--color-accent)]/20"
		/>
		{#if query}
			<button onclick={() => { query = ''; results = []; showResults = false; }}
				class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-disabled)] hover:text-[var(--text-muted)] transition-colors">
				<X class="w-3.5 h-3.5" />
			</button>
		{/if}
	</div>

	{#if showResults}
		<div class="absolute top-full left-0 right-0 mt-1 bg-[var(--bg-secondary)] border border-[var(--border-subtle)] rounded-lg shadow-xl z-50 overflow-hidden animate-fade-slide-in">
			{#if results.length}
				<div class="px-3 py-1.5 text-[10px] uppercase tracking-wider text-[var(--text-disabled)] border-b border-[var(--border-subtle)]">Library</div>
				{#each results as track}
					<button onclick={() => goToTrack(track)}
						class="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-[var(--bg-hover)] transition-colors">
						<div class="flex-1 min-w-0">
							<p class="text-sm text-[var(--text-primary)] truncate">{track.title}</p>
							<p class="text-xs text-[var(--text-muted)] truncate">{track.artist || ''}</p>
						</div>
						{#if track.genre}
							<span class="text-[10px] text-[var(--text-disabled)] font-mono">{track.genre}</span>
						{/if}
					</button>
				{/each}
			{/if}
			<button onclick={goToDownloads}
				class="w-full flex items-center gap-2 px-3 py-2.5 text-left border-t border-[var(--border-subtle)] hover:bg-[var(--bg-hover)] transition-colors text-[var(--color-downloads)]">
				<Search class="w-3.5 h-3.5" />
				<span class="text-sm">Search P2P for "{query}"</span>
			</button>
		</div>
	{/if}
</div>
