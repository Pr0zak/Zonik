<script>
	import { onDestroy } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { downloadAndPoll } from '$lib/download.js';
	import { formatRelativeTime, parseUTC } from '$lib/utils.js';
	import { Loader2, RefreshCw, Music, Radar, Calendar, Check, Download, X, Shuffle } from 'lucide-svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import FilterPills from '../../components/ui/FilterPills.svelte';

	let { trackStatus = $bindable({}) } = $props();

	let mode = $state('tailored');
	let tracks = $state([]);
	let loading = $state(false);
	let fetchedAt = $state(null);
	let lastRefreshed = $state(null);
	let message = $state(null);
	let runningRefresh = $state(false);
	let bulkDownloading = $state(false);

	let _destroyed = false;
	onDestroy(() => { _destroyed = true; });

	function trackKey(t) {
		return `${t.artist}::${t.track}`.toLowerCase();
	}

	let total = $derived(tracks.length);
	let inLibraryCount = $derived(tracks.filter(t => t.in_library).length);
	let missingCount = $derived(
		tracks.filter(t => !t.in_library && !trackStatus[trackKey(t)]).length
	);

	async function load() {
		loading = true;
		message = null;
		try {
			const data = await fetch(`/api/discovery/weekly-radar?mode=${mode}`).then(r => r.json());
			tracks = data.tracks || [];
			fetchedAt = data.fetched_at;
			lastRefreshed = data.last_refreshed;
			message = data.message || null;
		} catch (e) {
			addToast('Failed to load Weekly Radar', 'error');
			tracks = [];
		} finally {
			loading = false;
		}
	}

	async function setMode(next) {
		if (next === mode) return;
		mode = next;
		tracks = [];
		message = null;
		lastRefreshed = null;
		await load();
	}

	async function regenerate() {
		runningRefresh = true;
		try {
			const res = await fetch('/api/schedule/recommendation_refresh/run', { method: 'POST' });
			const data = await res.json();
			if (data.error) {
				addToast(data.error, 'error');
				runningRefresh = false;
				return;
			}
			addToast('Refreshing recommendations — check Logs for progress', 'success');
			pollUntilFresh(data.job_id);
		} catch {
			addToast('Failed to start refresh', 'error');
			runningRefresh = false;
		}
	}

	async function pollUntilFresh(jobId) {
		for (let i = 0; i < 60; i++) {
			if (_destroyed) return;
			await new Promise(r => setTimeout(r, 3000));
			if (_destroyed) return;
			try {
				const job = await fetch(`/api/jobs/${jobId}`).then(r => r.json());
				if (job.status === 'completed') {
					await load();
					runningRefresh = false;
					return;
				}
				if (job.status === 'failed') {
					addToast('Refresh failed', 'error');
					runningRefresh = false;
					return;
				}
			} catch {}
		}
		runningRefresh = false;
	}

	async function downloadOne(t) {
		const key = trackKey(t);
		await downloadAndPoll({
			artist: t.artist,
			track: t.track,
			source: mode === 'tailored' ? 'recommendation' : 'weekly-radar',
			key,
			onStatus: (k, s) => { trackStatus[k] = s; },
			isDestroyed: () => _destroyed,
		});
	}

	async function downloadAllMissing() {
		const missing = tracks.filter(t => !t.in_library && !trackStatus[trackKey(t)]);
		if (!missing.length) return;
		bulkDownloading = true;
		for (const t of missing) trackStatus[trackKey(t)] = 'queued';
		let started = 0;
		const source = mode === 'tailored' ? 'recommendation' : 'weekly-radar';
		for (const t of missing) {
			try {
				const res = await fetch('/api/download/trigger', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ artist: t.artist, track: t.track, source }),
				});
				const data = await res.json();
				if (data.error) { trackStatus[trackKey(t)] = 'failed'; continue; }
				trackStatus[trackKey(t)] = 'downloading';
				started++;
			} catch {
				trackStatus[trackKey(t)] = 'failed';
			}
		}
		addToast(`Queued ${started} downloads`, 'success');
		bulkDownloading = false;
	}

	function formatDate(iso) {
		if (!iso) return '—';
		try {
			return parseUTC(iso).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
		} catch { return iso; }
	}

	$effect(() => { if (!tracks.length && !loading && !message) load(); });
</script>

{#snippet trackRow(t, i)}
	{@const status = trackStatus[trackKey(t)]}
	<div class="px-4 py-3 flex items-center gap-3 hover:bg-[var(--surface-container-high)] transition-colors
		{t.in_library ? 'opacity-70' : ''}
		{status === 'completed' ? 'bg-green-500/5' : ''}
		{status === 'failed' ? 'bg-red-500/5' : ''}">
		<span class="text-[var(--text-disabled)] font-mono text-xs w-6 text-right flex-shrink-0">{i + 1}</span>
		<div class="flex-shrink-0 w-10 h-10 rounded overflow-hidden bg-[var(--surface-container-high)]">
			{#if t.cover_url}
				<img src={t.cover_url} alt="" class="w-full h-full object-cover" loading="lazy" />
			{:else}
				<div class="w-full h-full flex items-center justify-center">
					<Music class="w-4 h-4 text-[var(--text-disabled)]" />
				</div>
			{/if}
		</div>
		<div class="flex-1 min-w-0">
			<div class="font-medium text-sm truncate {t.in_library ? 'text-[var(--text-secondary)]' : 'text-[var(--text-primary)]'}">{t.track}</div>
			<div class="text-xs text-[var(--text-secondary)] truncate">
				{t.artist}
				{#if t.album}
					<span class="text-[var(--text-muted)]"> &middot; {t.album}</span>
				{/if}
				{#if t.year}
					<span class="text-[var(--text-disabled)]"> &middot; {t.year}</span>
				{/if}
				{#if mode === 'tailored' && t.score != null}
					<span class="text-[var(--text-disabled)]"> &middot; score {t.score.toFixed(2)}</span>
				{/if}
			</div>
		</div>
		<div class="flex items-center gap-2 flex-shrink-0">
			{#if t.in_library}
				<Badge variant="success">
					<Check class="w-3 h-3" />
					In Library
				</Badge>
			{:else if status === 'completed'}
				<span class="inline-flex items-center gap-1 text-green-400 text-xs font-medium">
					<Check class="w-3.5 h-3.5" /> Downloaded
				</span>
			{:else if status === 'failed'}
				<span class="inline-flex items-center gap-2">
					<span class="text-red-400 text-xs font-medium inline-flex items-center gap-1">
						<X class="w-3.5 h-3.5" /> Failed
					</span>
					<button onclick={() => downloadOne(t)}
						class="text-[var(--text-muted)] hover:text-white text-xs underline">retry</button>
				</span>
			{:else if status === 'downloading' || status === 'queued'}
				<span class="inline-flex items-center gap-1.5 text-blue-400 text-xs font-medium">
					<Loader2 class="w-3.5 h-3.5 animate-spin" />
					{status === 'queued' ? 'Queued' : 'Downloading'}
				</span>
			{:else}
				<Button variant="success" size="sm" onclick={() => downloadOne(t)}>
					<Download class="w-3 h-3" />
					Get
				</Button>
			{/if}
		</div>
	</div>
{/snippet}

<!-- Header card with subtitle -->
<Card padding="p-4" class="mb-4">
	<div class="flex flex-wrap items-start gap-3">
		<div class="flex items-start gap-3 flex-1 min-w-0">
			<div class="w-10 h-10 rounded-lg bg-[var(--color-discover)]/15 text-[var(--color-discover)] flex items-center justify-center flex-shrink-0">
				{#if mode === 'tailored'}
					<Radar class="w-5 h-5" />
				{:else}
					<Shuffle class="w-5 h-5" />
				{/if}
			</div>
			<div class="min-w-0">
				<div class="flex items-center gap-2 flex-wrap">
					<span class="font-semibold text-[var(--text-primary)]">Weekly Radar</span>
					{#if mode === 'tailored'}
						<span class="text-xs text-[var(--text-muted)]">Refreshes weekly</span>
					{:else}
						<span class="text-xs text-[var(--text-muted)]">Mixed new music — explore freely</span>
					{/if}
				</div>
				<div class="text-xs text-[var(--text-secondary)] mt-0.5">
					{#if mode === 'tailored'}
						Taste-driven picks from your AI recommender — tracks similar to what you already love that aren't in your library yet.
					{:else}
						Broader discovery — Spotify new releases and Last.fm chart movers, filtered to tracks you don't have yet.
					{/if}
				</div>
				<div class="mt-1 flex items-center gap-3 text-xs text-[var(--text-muted)]">
					{#if mode === 'tailored'}
						<span class="inline-flex items-center gap-1">
							<Calendar class="w-3 h-3" />
							Last refreshed: <span class="font-mono text-[var(--text-secondary)] ml-1">{formatDate(lastRefreshed)}</span>
							{#if lastRefreshed}
								<span class="text-[var(--text-disabled)]">({formatRelativeTime(lastRefreshed)})</span>
							{/if}
						</span>
					{/if}
					{#if total > 0}
						{#if mode === 'tailored'}<span>&middot;</span>{/if}
						<span>{missingCount} missing</span>
						{#if inLibraryCount > 0}
							<span>&middot;</span>
							<span>{inLibraryCount} in library</span>
						{/if}
					{/if}
				</div>
			</div>
		</div>
		<div class="flex items-center gap-2">
			<Button variant="default" size="sm" onclick={load} loading={loading} disabled={runningRefresh}>
				<RefreshCw class="w-3.5 h-3.5" />
				Reload
			</Button>
			{#if missingCount > 0}
				<Button variant="success" size="sm" onclick={downloadAllMissing} loading={bulkDownloading}>
					<Download class="w-3.5 h-3.5" />
					Download {missingCount}
				</Button>
			{/if}
			{#if mode === 'tailored'}
				<Button variant="primary" size="sm" onclick={regenerate} loading={runningRefresh}>
					<Radar class="w-3.5 h-3.5" />
					Regenerate
				</Button>
			{/if}
		</div>
	</div>
	<div class="mt-3">
		<FilterPills
			variant="outline"
			value={mode}
			onchange={setMode}
			options={[
				{ value: 'tailored', label: 'Tailored', color: 'discover' },
				{ value: 'general', label: 'General', color: 'discover' },
			]}
		/>
	</div>
</Card>

{#if loading && !tracks.length}
	<Card padding="p-0">
		<div class="space-y-0.5">
			{#each Array(8) as _}
				<div class="px-4 py-3 flex items-center gap-4">
					<Skeleton class="h-4 w-8" />
					<Skeleton class="h-10 w-10 rounded" />
					<div class="flex-1 space-y-1.5">
						<Skeleton class="h-4 w-40" />
						<Skeleton class="h-3 w-28" />
					</div>
					<Skeleton class="h-5 w-16 rounded-full" />
				</div>
			{/each}
		</div>
	</Card>
{:else if message}
	<Card>
		<EmptyState title="No tailored picks yet" description={message}>
			{#snippet icon()}<Radar class="w-12 h-12" />{/snippet}
		</EmptyState>
		{#if mode === 'tailored'}
			<div class="flex justify-center mt-3">
				<Button variant="primary" size="sm" onclick={regenerate} loading={runningRefresh}>
					<Radar class="w-3.5 h-3.5" />
					Regenerate now
				</Button>
			</div>
		{/if}
	</Card>
{:else if !tracks.length}
	<Card>
		<EmptyState title="Nothing to show" description={mode === 'tailored' ? 'No pending recommendations match — try Regenerate.' : 'No new tracks found right now. Reload in a bit.'}>
			{#snippet icon()}<Music class="w-12 h-12" />{/snippet}
		</EmptyState>
	</Card>
{:else}
	<Card padding="p-0">
		<div class="space-y-0.5">
			{#each tracks as t, i}
				{@render trackRow(t, i)}
			{/each}
		</div>
	</Card>
{/if}
