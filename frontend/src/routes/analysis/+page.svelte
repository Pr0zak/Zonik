<script>
	import { onMount } from 'svelte';
	import { addToast, activeJobs } from '$lib/stores.js';
	import { AudioWaveform, Sparkles, Database, Search, Clock } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import ScheduleControl from '../../components/ui/ScheduleControl.svelte';

	let stats = $state(null);
	let loading = $state(true);
	let vibeQuery = $state('');
	let vibeResults = $state([]);
	let searching = $state(false);
	let schedTasks = $state({});
	let schedRunning = $state({});
	let startingAnalysis = $state(false);
	let startingEmbeddings = $state(false);
	let startingEnrichment = $state(false);

	// Derive running state from activeJobs store
	let analysisJob = $derived($activeJobs.find(j => j.type === 'audio_analysis'));
	let embeddingsJob = $derived($activeJobs.find(j => j.type === 'vibe_embeddings'));
	let enrichmentJob = $derived($activeJobs.find(j => j.type === 'enrichment'));

	let prevAnalysis = $state(false);
	let prevEmbeddings = $state(false);
	let prevEnrichment = $state(false);

	// Auto-refresh stats when jobs complete
	$effect(() => {
		if (prevAnalysis && !analysisJob) { refreshStats(); addToast('Audio analysis complete', 'success'); }
		prevAnalysis = !!analysisJob;
	});
	$effect(() => {
		if (prevEmbeddings && !embeddingsJob) { refreshStats(); addToast('Vibe embeddings complete', 'success'); }
		prevEmbeddings = !!embeddingsJob;
	});
	$effect(() => {
		if (prevEnrichment && !enrichmentJob) { refreshStats(); addToast('Metadata enrichment complete', 'success'); }
		prevEnrichment = !!enrichmentJob;
	});

	async function refreshStats() {
		try { stats = await fetch('/api/analysis/stats').then(r => r.json()); } catch (e) { console.error('Stats refresh failed:', e); }
	}

	onMount(async () => {
		try {
			stats = await fetch('/api/analysis/stats').then(r => r.json());
		} catch (e) {
			console.error('Failed to load stats:', e);
		} finally {
			loading = false;
		}
		try {
			const tasks = await fetch('/api/schedule').then(r => r.json());
			for (const t of tasks) schedTasks[t.task_name] = t;
		} catch (e) { console.error('Schedule load failed:', e); }
	});

	async function pollForJob(type, timeout = 10000) {
		const start = Date.now();
		while (Date.now() - start < timeout) {
			await new Promise(r => setTimeout(r, 1000));
			try {
				const jobs = await fetch('/api/jobs/active').then(r => r.json());
				const found = jobs.find(j => j.type === type);
				if (found) {
					activeJobs.update(current => {
						if (!current.find(j => j.id === found.id)) current.push(found);
						return current;
					});
					return;
				}
			} catch {}
		}
	}

	async function startAnalysis() {
		startingAnalysis = true;
		try {
			await fetch('/api/analysis/start', { method: 'POST' }).then(r => r.json());
			addToast('Audio analysis started', 'success');
			pollForJob('audio_analysis');
		} catch (e) {
			addToast('Failed to start analysis', 'error');
		} finally {
			setTimeout(() => startingAnalysis = false, 3000);
		}
	}

	async function startEmbeddings() {
		startingEmbeddings = true;
		try {
			await fetch('/api/analysis/embeddings/start', { method: 'POST' }).then(r => r.json());
			addToast('Vibe embedding generation started', 'success');
			pollForJob('vibe_embeddings');
		} catch (e) {
			addToast('Failed to start embeddings', 'error');
		} finally {
			setTimeout(() => startingEmbeddings = false, 3000);
		}
	}

	async function startEnrichment() {
		startingEnrichment = true;
		try {
			await fetch('/api/analysis/enrich', { method: 'POST' }).then(r => r.json());
			addToast('Metadata enrichment started', 'success');
			pollForJob('enrichment');
		} catch (e) {
			addToast('Failed to start enrichment', 'error');
		} finally {
			setTimeout(() => startingEnrichment = false, 3000);
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

	async function toggleSched(name) {
		const t = schedTasks[name];
		if (!t) return;
		const newEnabled = !t.enabled;
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: newEnabled }) });
		schedTasks[name] = { ...t, enabled: newEnabled };
	}
	async function updateSched(name, updates) {
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updates) });
		schedTasks[name] = { ...schedTasks[name], ...updates };
	}
	async function runSched(name) {
		schedRunning[name] = true;
		try {
			await fetch(`/api/schedule/${name}/run`, { method: 'POST' });
			addToast('Task started', 'success');
		} catch { addToast('Failed to run task', 'error'); }
		finally { schedRunning[name] = false; }
	}

	async function toggleAutoAfterScan(name) {
		const t = schedTasks[name];
		if (!t) return;
		const current = t.config?.auto_after_scan || false;
		const newConfig = { auto_after_scan: !current };
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ config: newConfig }) });
		schedTasks[name] = { ...t, config: { ...t.config, ...newConfig } };
	}

	function progressPct(job) {
		if (!job || !job.total) return 0;
		return Math.round((job.progress / job.total) * 100);
	}

	// Show progress relative to total library size (aligns with stats card)
	function analysisProgress(job) {
		if (!stats || !job) return { done: 0, total: 0, pct: 0 };
		const done = (stats.analyzed || 0) + (job.progress || 0);
		const total = stats.total_tracks || 0;
		return { done, total, pct: total > 0 ? Math.round(done / total * 100) : 0 };
	}
	function embeddingsProgress(job) {
		if (!stats || !job) return { done: 0, total: 0, pct: 0 };
		const done = (stats.with_embeddings || 0) + (job.progress || 0);
		const total = stats.total_tracks || 0;
		return { done, total, pct: total > 0 ? Math.round(done / total * 100) : 0 };
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
			<!-- Audio Analysis Card -->
			<Card padding="p-4">
				<div class="flex items-center gap-2 mb-2">
					<AudioWaveform class="w-4 h-4 text-[var(--color-accent)]" />
					<span class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">Audio Analyzed</span>
				</div>
				<p class="text-2xl font-bold text-[var(--text-primary)]">{stats.analyzed} <span class="text-sm text-[var(--text-muted)] font-normal">/ {stats.total_tracks}</span></p>
				<div class="mt-2 h-1.5 bg-[var(--border-interactive)] rounded-full">
					<div class="h-full bg-[var(--color-accent)] rounded-full transition-all" style="width: {stats.analysis_pct}%"></div>
				</div>
				{#if analysisJob}
					{@const ap = analysisProgress(analysisJob)}
					<div class="mt-3 p-2 rounded bg-[var(--bg-primary)] border border-[var(--border-subtle)]">
						<div class="flex items-center justify-between mb-1">
							<span class="text-xs text-[var(--color-info)] font-medium animate-pulse">Running...</span>
							<span class="text-xs text-[var(--text-muted)] font-mono">{ap.done}/{ap.total}</span>
						</div>
						<div class="h-1 bg-[var(--border-interactive)] rounded-full">
							<div class="h-full bg-[var(--color-info)] rounded-full transition-all" style="width: {ap.pct}%"></div>
						</div>
					</div>
				{:else}
					<Button variant="primary" size="sm" class="mt-3 w-full" onclick={startAnalysis} loading={startingAnalysis}>
						<AudioWaveform class="w-3.5 h-3.5" />
						{startingAnalysis ? 'Starting...' : 'Run Analysis'}
					</Button>
				{/if}
			</Card>

			<!-- Vibe Embeddings Card -->
			<Card padding="p-4">
				<div class="flex items-center gap-2 mb-2">
					<Sparkles class="w-4 h-4 text-[var(--color-analysis)]" />
					<span class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">Vibe Embeddings</span>
				</div>
				<p class="text-2xl font-bold text-[var(--text-primary)]">{stats.with_embeddings} <span class="text-sm text-[var(--text-muted)] font-normal">/ {stats.total_tracks}</span></p>
				<div class="mt-2 h-1.5 bg-[var(--border-interactive)] rounded-full">
					<div class="h-full bg-[var(--color-analysis)] rounded-full transition-all" style="width: {stats.embedding_pct}%"></div>
				</div>
				{#if embeddingsJob}
					{@const ep = embeddingsProgress(embeddingsJob)}
					<div class="mt-3 p-2 rounded bg-[var(--bg-primary)] border border-[var(--border-subtle)]">
						<div class="flex items-center justify-between mb-1">
							<span class="text-xs text-[var(--color-analysis)] font-medium animate-pulse">Running...</span>
							<span class="text-xs text-[var(--text-muted)] font-mono">{ep.done}/{ep.total}</span>
						</div>
						<div class="h-1 bg-[var(--border-interactive)] rounded-full">
							<div class="h-full bg-[var(--color-analysis)] rounded-full transition-all" style="width: {ep.pct}%"></div>
						</div>
					</div>
				{:else}
					<Button variant="secondary" size="sm" class="mt-3 w-full" onclick={startEmbeddings} loading={startingEmbeddings}>
						<Sparkles class="w-3.5 h-3.5 text-[var(--color-analysis)]" />
						{startingEmbeddings ? 'Starting...' : 'Generate Embeddings'}
					</Button>
				{/if}
			</Card>

			<!-- Enrichment Card -->
			<Card padding="p-4">
				<div class="flex items-center gap-2 mb-2">
					<Database class="w-4 h-4 text-emerald-400" />
					<span class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">Enrichment</span>
				</div>
				<p class="text-sm text-[var(--text-muted)] mb-1">Fill missing genres, cover art, and metadata from online sources.</p>
				{#if enrichmentJob}
					<div class="mt-2 p-2 rounded bg-[var(--bg-primary)] border border-[var(--border-subtle)]">
						<div class="flex items-center justify-between mb-1">
							<span class="text-xs text-emerald-400 font-medium animate-pulse">Enriching...</span>
							<span class="text-xs text-[var(--text-muted)] font-mono">{enrichmentJob.progress}/{enrichmentJob.total}</span>
						</div>
						<div class="h-1 bg-[var(--border-interactive)] rounded-full">
							<div class="h-full bg-emerald-500 rounded-full transition-all" style="width: {progressPct(enrichmentJob)}%"></div>
						</div>
					</div>
				{:else}
					<Button variant="success" size="sm" class="mt-2 w-full" onclick={startEnrichment} loading={startingEnrichment}>
						<Database class="w-3.5 h-3.5" />
						{startingEnrichment ? 'Starting...' : 'Enrich Metadata'}
					</Button>
				{/if}
			</Card>
		</div>
	{/if}

	<Card padding="p-4" class="mb-6">
		<div class="flex items-center gap-2 mb-1">
			<Search class="w-4 h-4 text-[var(--color-analysis)]" />
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
				<Sparkles class="w-3.5 h-3.5 text-[var(--color-analysis)]" />
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

	<Card padding="p-4" class="mb-6">
		<div class="flex items-center gap-2 mb-2">
			<Clock class="w-4 h-4 text-[var(--text-muted)]" />
			<span class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">Schedule</span>
		</div>
		{#if schedTasks.audio_analysis}
			<ScheduleControl
				taskName="audio_analysis"
				label="Audio Analysis"
				enabled={schedTasks.audio_analysis.enabled}
				intervalHours={schedTasks.audio_analysis.interval_hours}
				runAt={schedTasks.audio_analysis.run_at}
				lastRunAt={schedTasks.audio_analysis.last_run_at}
				running={schedRunning.audio_analysis}
				onToggle={() => toggleSched('audio_analysis')}
				onUpdate={(u) => updateSched('audio_analysis', u)}
				onRun={() => runSched('audio_analysis')}
			/>
		{/if}
		{#if schedTasks.enrichment}
			<ScheduleControl
				taskName="enrichment"
				label="Enrichment"
				enabled={schedTasks.enrichment.enabled}
				intervalHours={schedTasks.enrichment.interval_hours}
				runAt={schedTasks.enrichment.run_at}
				lastRunAt={schedTasks.enrichment.last_run_at}
				running={schedRunning.enrichment}
				onToggle={() => toggleSched('enrichment')}
				onUpdate={(u) => updateSched('enrichment', u)}
				onRun={() => runSched('enrichment')}
			/>
		{/if}

		<!-- Auto-run after scan toggles -->
		<div class="mt-3 pt-3 border-t border-[var(--border-subtle)]">
			<span class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">Auto-run after Library Scan</span>
			<div class="mt-2 space-y-2">
				{#if schedTasks.audio_analysis}
					<label class="flex items-center gap-2 cursor-pointer">
						<button onclick={() => toggleAutoAfterScan('audio_analysis')}
							class="w-8 h-5 rounded-full transition-colors relative flex-shrink-0
								{schedTasks.audio_analysis.config?.auto_after_scan ? 'bg-[var(--color-accent)]' : 'bg-[var(--border-interactive)]'}">
							<span class="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow-sm
								{schedTasks.audio_analysis.config?.auto_after_scan ? 'left-[14px]' : 'left-0.5'}"></span>
						</button>
						<span class="text-xs text-[var(--text-secondary)]">Audio Analysis</span>
					</label>
				{/if}
				{#if schedTasks.enrichment}
					<label class="flex items-center gap-2 cursor-pointer">
						<button onclick={() => toggleAutoAfterScan('enrichment')}
							class="w-8 h-5 rounded-full transition-colors relative flex-shrink-0
								{schedTasks.enrichment.config?.auto_after_scan ? 'bg-[var(--color-accent)]' : 'bg-[var(--border-interactive)]'}">
							<span class="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow-sm
								{schedTasks.enrichment.config?.auto_after_scan ? 'left-[14px]' : 'left-0.5'}"></span>
						</button>
						<span class="text-xs text-[var(--text-secondary)]">Metadata Enrichment</span>
					</label>
				{/if}
			</div>
			<p class="text-[10px] text-[var(--text-disabled)] mt-1">When enabled, these tasks will automatically run after a library scan finds new tracks.</p>
		</div>
	</Card>

	<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
		<Card padding="p-4">
			<h2 class="text-base font-semibold text-[var(--text-primary)] mb-2">Echo Match</h2>
			<p class="text-sm text-[var(--text-muted)]">Find tracks with similar vibes to any track in your library. Use the vibe search above with a track ID, or click "Echo Match" on any track in the library.</p>
		</Card>
		<Card padding="p-4">
			<h2 class="text-base font-semibold text-[var(--text-primary)] mb-2">Steady Vibes</h2>
			<p class="text-sm text-[var(--text-muted)]">Generate a playlist that maintains consistent energy and mood from a seed track. Uses CLAP embeddings to walk through vibe space.</p>
		</Card>
	</div>
</div>
