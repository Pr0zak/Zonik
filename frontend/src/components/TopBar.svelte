<script>
	import { goto } from '$app/navigation';
	import { Search, X, RefreshCw, Bell } from 'lucide-svelte';
	import { api } from '$lib/api.js';
	import { activeJobs, addToast } from '$lib/stores.js';
	import SearchDropdown from './SearchDropdown.svelte';

	let query = $state('');
	let showResults = $state(false);
	let showNotifications = $state(false);
	let syncing = $state(false);
	let inputEl;
	let dropdownRef;

	let runningJobs = $derived($activeJobs.filter(j => j.status === 'running'));

	function onInput() {
		if (!query.trim()) {
			showResults = false;
			return;
		}
		showResults = true;
	}

	function onKeydown(e) {
		if (e.key === 'Escape') {
			showResults = false;
			query = '';
			inputEl?.blur();
		} else if (showResults && dropdownRef) {
			dropdownRef.handleKeydown(e);
		} else if (e.key === 'Enter' && query.trim()) {
			showResults = true;
		}
	}

	function onBlur() {
		setTimeout(() => { showResults = false; }, 200);
	}

	function handleClose() {
		showResults = false;
		query = '';
	}

	function handleNavigate(url) {
		showResults = false;
		query = '';
		goto(url);
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
			placeholder="Search music across all sources..."
			bind:value={query}
			oninput={onInput}
			onkeydown={onKeydown}
			onfocus={() => { if (query.trim()) showResults = true; }}
			onblur={onBlur}
			class="w-full bg-[var(--surface-lowest)] ghost-border rounded-lg pl-9 pr-8 py-2 text-sm text-[var(--text-body)]
				placeholder-[var(--text-disabled)] focus:outline-none focus:border-[var(--border-focus)] focus:ring-1 focus:ring-[var(--color-primary)]/15 ghost-border-focus"
		/>
		{#if query}
			<button onclick={() => { query = ''; showResults = false; }}
				class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-disabled)] hover:text-[var(--text-muted)] transition-colors">
				<X class="w-3.5 h-3.5" />
			</button>
		{/if}
	</div>

	{#if showResults && query.trim()}
		<SearchDropdown bind:this={dropdownRef} {query} onclose={handleClose} onnavigate={handleNavigate} />
	{/if}
</div>

<!-- Action icons -->
<div class="flex items-center gap-1">
	<!-- Sync library -->
	<button onclick={syncLibrary}
		class="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-high)] transition-colors"
		title="Sync library">
		<RefreshCw class="w-4 h-4 {syncing ? 'animate-spin' : ''}" />
	</button>

	<!-- Notifications / Activity -->
	<div class="relative">
		<button onclick={() => showNotifications = !showNotifications}
			class="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-high)] transition-colors relative"
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
			<div class="absolute top-full right-0 mt-1 w-[calc(100vw-2rem)] sm:w-80 glass rounded-lg shadow-float z-50 overflow-hidden animate-fade-slide-in">
				<div class="px-3 py-2 flex items-center justify-between">
					<span class="text-xs font-medium text-[var(--text-primary)] uppercase tracking-wider">Activity</span>
					<button onclick={() => showNotifications = false} class="text-[var(--text-disabled)] hover:text-[var(--text-muted)]">
						<X class="w-3.5 h-3.5" />
					</button>
				</div>
				{#if runningJobs.length}
					{#each runningJobs as job}
						<button onclick={() => { showNotifications = false; goto(`/logs?job=${job.id}`); }}
							class="w-full text-left px-3 py-2.5  hover:bg-[var(--surface-container-high)] transition-colors cursor-pointer">
							<div class="flex items-center gap-2">
								<span class="inline-block w-1.5 h-1.5 rounded-full bg-[var(--color-downloads)] animate-pulse flex-shrink-0"></span>
								<p class="text-sm text-[var(--text-primary)] truncate flex-1">{job.description || job.type}</p>
							</div>
							{#if job.total > 0}
								<div class="mt-1.5 h-1 bg-[var(--border-interactive)] rounded-full overflow-hidden">
									<div class="h-full bg-[var(--color-downloads)] rounded-full transition-all duration-300"
										style="width: {((job.progress || 0) / job.total) * 100}%"></div>
								</div>
								<p class="text-xs text-[var(--text-muted)] mt-1">{job.progress || 0}/{job.total}</p>
							{/if}
						</button>
					{/each}
				{:else}
					<div class="px-3 py-6 text-center">
						<p class="text-sm text-[var(--text-muted)]">No active tasks</p>
					</div>
				{/if}
				<button onclick={() => { showNotifications = false; goto('/logs'); }}
					class="w-full px-3 py-2 mt-1 text-xs text-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-high)] transition-colors">
					View all jobs
				</button>
			</div>
		{/if}
	</div>
</div>
