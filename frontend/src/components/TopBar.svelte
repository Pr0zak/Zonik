<script>
	import { goto } from '$app/navigation';
	import { Search, X, Settings, RefreshCw, Bell } from 'lucide-svelte';
	import { api } from '$lib/api.js';
	import { activeJobs, addToast } from '$lib/stores.js';

	let query = $state('');
	let results = $state([]);
	let showResults = $state(false);
	let showNotifications = $state(false);
	let loading = $state(false);
	let syncing = $state(false);
	let debounceTimer;
	let inputEl;

	let activeDownloads = $derived(
		$activeJobs.filter(j => j.type === 'download' || j.type === 'bulk_download')
	);
	let runningJobs = $derived($activeJobs.filter(j => j.status === 'running'));

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
		goto(`/library?search=${encodeURIComponent(track.title)}`);
	}

	function goToDownloads() {
		const q = query.trim();
		showResults = false;
		query = '';
		if (q) {
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
		setTimeout(() => { showResults = false; }, 200);
	}

	async function syncLibrary() {
		syncing = true;
		try {
			await api.scanLibrary();
			addToast('Library scan started', 'success');
		} catch {
			addToast('Scan failed', 'error');
		} finally {
			setTimeout(() => syncing = false, 2000);
		}
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

<!-- Action icons -->
<div class="flex items-center gap-1">
	<!-- Sync library -->
	<button onclick={syncLibrary}
		class="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
		title="Sync library">
		<RefreshCw class="w-4 h-4 {syncing ? 'animate-spin' : ''}" />
	</button>

	<!-- Notifications / Activity -->
	<div class="relative">
		<button onclick={() => showNotifications = !showNotifications}
			class="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors relative"
			title="Activity">
			<Bell class="w-4 h-4" />
			{#if runningJobs.length > 0}
				<span class="absolute top-1 right-1 w-2 h-2 rounded-full bg-[var(--color-downloads)] animate-pulse"></span>
			{/if}
		</button>

		{#if showNotifications}
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div class="fixed inset-0 z-40" onclick={() => showNotifications = false}></div>
			<div class="absolute top-full right-0 mt-1 w-80 bg-[var(--bg-secondary)] border border-[var(--border-subtle)] rounded-lg shadow-xl z-50 overflow-hidden animate-fade-slide-in">
				<div class="px-3 py-2 border-b border-[var(--border-subtle)] flex items-center justify-between">
					<span class="text-xs font-medium text-[var(--text-primary)] uppercase tracking-wider">Activity</span>
					<button onclick={() => showNotifications = false} class="text-[var(--text-disabled)] hover:text-[var(--text-muted)]">
						<X class="w-3.5 h-3.5" />
					</button>
				</div>
				{#if runningJobs.length}
					{#each runningJobs as job}
						<button onclick={() => { showNotifications = false; goto(`/logs?job=${job.id}`); }}
							class="w-full text-left px-3 py-2.5 border-b border-[var(--border-subtle)] hover:bg-[var(--bg-hover)] transition-colors cursor-pointer">
							<div class="flex items-center gap-2">
								<span class="inline-block w-1.5 h-1.5 rounded-full bg-[var(--color-downloads)] animate-pulse flex-shrink-0"></span>
								<p class="text-sm text-[var(--text-primary)] truncate flex-1">{job.description || job.type}</p>
							</div>
							{#if job.total > 0}
								<div class="mt-1.5 h-1 bg-[var(--border-interactive)] rounded-full overflow-hidden">
									<div class="h-full bg-[var(--color-downloads)] rounded-full transition-all duration-300"
										style="width: {((job.progress || 0) / job.total) * 100}%"></div>
								</div>
								<p class="text-[10px] text-[var(--text-muted)] mt-1">{job.progress || 0}/{job.total}</p>
							{/if}
						</button>
					{/each}
				{:else}
					<div class="px-3 py-6 text-center">
						<p class="text-sm text-[var(--text-muted)]">No active tasks</p>
					</div>
				{/if}
				<button onclick={() => { showNotifications = false; goto('/logs'); }}
					class="w-full px-3 py-2 text-xs text-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors border-t border-[var(--border-subtle)]">
					View all jobs
				</button>
			</div>
		{/if}
	</div>

	<!-- Settings -->
	<button onclick={() => goto('/settings')}
		class="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
		title="Settings">
		<Settings class="w-4 h-4" />
	</button>
</div>
