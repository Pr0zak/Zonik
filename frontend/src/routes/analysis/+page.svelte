<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';

	let stats = $state(null);
	let vibeQuery = $state('');
	let vibeResults = $state([]);
	let searching = $state(false);
	let runningAnalysis = $state(false);
	let runningEmbeddings = $state(false);
	let runningEnrichment = $state(false);

	onMount(async () => {
		try {
			stats = await fetch('/api/analysis/stats').then(r => r.json());
		} catch (e) {
			console.error('Failed to load stats:', e);
		}
	});

	async function startAnalysis() {
		runningAnalysis = true;
		try {
			const data = await fetch('/api/analysis/start', { method: 'POST' }).then(r => r.json());
			addToast('Audio analysis started', 'success');
		} catch (e) {
			addToast('Failed to start analysis', 'error');
		} finally {
			runningAnalysis = false;
		}
	}

	async function startEmbeddings() {
		runningEmbeddings = true;
		try {
			const data = await fetch('/api/analysis/embeddings/start', { method: 'POST' }).then(r => r.json());
			addToast('Vibe embedding generation started', 'success');
		} catch (e) {
			addToast('Failed to start embeddings', 'error');
		} finally {
			runningEmbeddings = false;
		}
	}

	async function startEnrichment() {
		runningEnrichment = true;
		try {
			const data = await fetch('/api/analysis/enrich', { method: 'POST' }).then(r => r.json());
			addToast('Metadata enrichment started', 'success');
		} catch (e) {
			addToast('Failed to start enrichment', 'error');
		} finally {
			runningEnrichment = false;
		}
	}

	async function vibeSearch() {
		if (!vibeQuery.trim()) return;
		searching = true;
		try {
			const data = await fetch('/api/analysis/vibe-search', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ query: vibeQuery.trim() })
			}).then(r => r.json());
			vibeResults = data.results || [];
			if (!vibeResults.length) addToast('No vibe matches found', 'warning');
		} catch (e) {
			addToast('Vibe search failed', 'error');
		} finally {
			searching = false;
		}
	}
</script>

<div class="max-w-6xl">
	<h1 class="text-2xl font-bold mb-6">Analysis</h1>

	{#if stats}
		<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
			<div class="bg-gray-900 rounded-xl border border-gray-800 p-4">
				<p class="text-2xl font-bold">{stats.analyzed} <span class="text-sm text-gray-400 font-normal">/ {stats.total_tracks}</span></p>
				<p class="text-sm text-gray-400">Audio Analyzed ({stats.analysis_pct}%)</p>
				<div class="mt-2 h-1.5 bg-gray-800 rounded-full">
					<div class="h-full bg-accent-500 rounded-full transition-all" style="width: {stats.analysis_pct}%"></div>
				</div>
			</div>
			<div class="bg-gray-900 rounded-xl border border-gray-800 p-4">
				<p class="text-2xl font-bold">{stats.with_embeddings} <span class="text-sm text-gray-400 font-normal">/ {stats.total_tracks}</span></p>
				<p class="text-sm text-gray-400">Vibe Embeddings ({stats.embedding_pct}%)</p>
				<div class="mt-2 h-1.5 bg-gray-800 rounded-full">
					<div class="h-full bg-purple-500 rounded-full transition-all" style="width: {stats.embedding_pct}%"></div>
				</div>
			</div>
			<div class="bg-gray-900 rounded-xl border border-gray-800 p-4 flex flex-col gap-2">
				<button on:click={startAnalysis} disabled={runningAnalysis}
					class="px-3 py-1.5 bg-accent-600 hover:bg-accent-700 rounded-lg text-sm disabled:opacity-50 transition">
					{runningAnalysis ? 'Running...' : 'Run Analysis'}
				</button>
				<button on:click={startEmbeddings} disabled={runningEmbeddings}
					class="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm disabled:opacity-50 transition">
					{runningEmbeddings ? 'Running...' : 'Generate Embeddings'}
				</button>
				<button on:click={startEnrichment} disabled={runningEnrichment}
					class="px-3 py-1.5 bg-green-700 hover:bg-green-800 rounded-lg text-sm disabled:opacity-50 transition">
					{runningEnrichment ? 'Running...' : 'Enrich Metadata'}
				</button>
			</div>
		</div>
	{/if}

	<div class="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-6">
		<h2 class="text-lg font-semibold mb-4">Vibe Search</h2>
		<p class="text-sm text-gray-400 mb-4">Search by text description (requires CLAP embeddings)</p>
		<div class="flex gap-3">
			<input type="text" placeholder="e.g., chill ambient beats, energetic dance music..."
				bind:value={vibeQuery}
				on:keydown={(e) => { if (e.key === 'Enter') vibeSearch(); }}
				class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
					focus:outline-none focus:border-accent-500" />
			<button on:click={vibeSearch} disabled={searching || !vibeQuery}
				class="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-medium
					disabled:opacity-50 transition">
				{searching ? 'Searching...' : 'Search Vibes'}
			</button>
		</div>

		{#if vibeResults.length}
			<div class="mt-4 border border-gray-800 rounded-lg divide-y divide-gray-800/50">
				{#each vibeResults as r, i}
					<div class="px-4 py-3 flex items-center justify-between hover:bg-gray-800/50">
						<div>
							<span class="font-medium">{r.title}</span>
							<span class="text-gray-400 text-sm ml-2">{r.artist || ''}</span>
						</div>
						<span class="text-xs text-gray-500">{(r.similarity * 100).toFixed(1)}% match</span>
					</div>
				{/each}
			</div>
		{/if}
	</div>

	<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
		<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
			<h2 class="text-lg font-semibold mb-2">Echo Match</h2>
			<p class="text-sm text-gray-400">Find tracks with similar vibes to any track in your library. Use the vibe search above with a track ID, or click "Echo Match" on any track in the library.</p>
		</div>
		<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
			<h2 class="text-lg font-semibold mb-2">Steady Vibes</h2>
			<p class="text-sm text-gray-400">Generate a playlist that maintains consistent energy and mood from a seed track. Uses CLAP embeddings to walk through vibe space.</p>
		</div>
	</div>
</div>
