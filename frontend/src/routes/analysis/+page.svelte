<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { AudioWaveform, Sparkles, Database, Search } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import Badge from '../../components/ui/Badge.svelte';

	let stats = $state(null);
	let loading = $state(true);
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
		} finally {
			loading = false;
		}
	});

	async function startAnalysis() {
		runningAnalysis = true;
		try {
			await fetch('/api/analysis/start', { method: 'POST' }).then(r => r.json());
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
			await fetch('/api/analysis/embeddings/start', { method: 'POST' }).then(r => r.json());
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
			await fetch('/api/analysis/enrich', { method: 'POST' }).then(r => r.json());
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
	<PageHeader title="Analysis" color="var(--color-analysis)" />

	{#if loading}
		<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
			{#each Array(3) as _}
				<Skeleton class="h-28 rounded-lg" />
			{/each}
		</div>
	{:else if stats}
		<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
			<Card padding="p-4">
				<div class="flex items-center gap-2 mb-2">
					<AudioWaveform class="w-4 h-4 text-[var(--color-accent)]" />
					<span class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">Audio Analyzed</span>
				</div>
				<p class="text-2xl font-bold text-[var(--text-primary)]">{stats.analyzed} <span class="text-sm text-[var(--text-muted)] font-normal">/ {stats.total_tracks}</span></p>
				<div class="mt-2 h-1.5 bg-[var(--border-interactive)] rounded-full">
					<div class="h-full bg-[var(--color-accent)] rounded-full transition-all" style="width: {stats.analysis_pct}%"></div>
				</div>
			</Card>
			<Card padding="p-4">
				<div class="flex items-center gap-2 mb-2">
					<Sparkles class="w-4 h-4 text-purple-400" />
					<span class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">Vibe Embeddings</span>
				</div>
				<p class="text-2xl font-bold text-[var(--text-primary)]">{stats.with_embeddings} <span class="text-sm text-[var(--text-muted)] font-normal">/ {stats.total_tracks}</span></p>
				<div class="mt-2 h-1.5 bg-[var(--border-interactive)] rounded-full">
					<div class="h-full bg-purple-500 rounded-full transition-all" style="width: {stats.embedding_pct}%"></div>
				</div>
			</Card>
			<Card padding="p-4" class="flex flex-col gap-2">
				<Button variant="primary" size="sm" loading={runningAnalysis} onclick={startAnalysis}>
					<AudioWaveform class="w-3.5 h-3.5" />
					{runningAnalysis ? 'Running...' : 'Run Analysis'}
				</Button>
				<Button variant="secondary" size="sm" loading={runningEmbeddings} onclick={startEmbeddings}>
					<Sparkles class="w-3.5 h-3.5 text-purple-400" />
					{runningEmbeddings ? 'Running...' : 'Generate Embeddings'}
				</Button>
				<Button variant="success" size="sm" loading={runningEnrichment} onclick={startEnrichment}>
					<Database class="w-3.5 h-3.5" />
					{runningEnrichment ? 'Running...' : 'Enrich Metadata'}
				</Button>
			</Card>
		</div>
	{/if}

	<Card padding="p-6" class="mb-6">
		<div class="flex items-center gap-2 mb-1">
			<Search class="w-4 h-4 text-purple-400" />
			<h2 class="text-base font-semibold text-[var(--text-primary)]">Vibe Search</h2>
		</div>
		<p class="text-sm text-[var(--text-muted)] mb-4">Search by text description (requires CLAP embeddings)</p>
		<div class="flex gap-3">
			<input type="text" placeholder="e.g., chill ambient beats, energetic dance music..."
				bind:value={vibeQuery}
				onkeydown={(e) => { if (e.key === 'Enter') vibeSearch(); }}
				class="flex-1 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm text-[var(--text-body)] placeholder-[var(--text-disabled)]
					focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
			<Button variant="secondary" loading={searching} disabled={!vibeQuery}
				onclick={vibeSearch}>
				<Sparkles class="w-3.5 h-3.5 text-purple-400" />
				Search Vibes
			</Button>
		</div>

		{#if vibeResults.length}
			<div class="mt-4 border border-[var(--border-subtle)] rounded-lg divide-y divide-[var(--border-subtle)]">
				{#each vibeResults as r}
					<div class="px-4 py-3 flex items-center justify-between hover:bg-[var(--bg-hover)] transition-colors">
						<div>
							<span class="font-medium text-[var(--text-primary)]">{r.title}</span>
							<span class="text-[var(--text-secondary)] text-sm ml-2">{r.artist || ''}</span>
						</div>
						<Badge variant="success">{(r.similarity * 100).toFixed(1)}%</Badge>
					</div>
				{/each}
			</div>
		{/if}
	</Card>

	<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
		<Card padding="p-5">
			<h2 class="text-base font-semibold text-[var(--text-primary)] mb-2">Echo Match</h2>
			<p class="text-sm text-[var(--text-muted)]">Find tracks with similar vibes to any track in your library. Use the vibe search above with a track ID, or click "Echo Match" on any track in the library.</p>
		</Card>
		<Card padding="p-5">
			<h2 class="text-base font-semibold text-[var(--text-primary)] mb-2">Steady Vibes</h2>
			<p class="text-sm text-[var(--text-muted)]">Generate a playlist that maintains consistent energy and mood from a seed track. Uses CLAP embeddings to walk through vibe space.</p>
		</Card>
	</div>
</div>
