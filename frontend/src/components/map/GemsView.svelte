<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import Button from '../ui/Button.svelte';
	import SelectionBar from './SelectionBar.svelte';
	import { Play, Shuffle, X, Gem } from 'lucide-svelte';

	let gems = $state(null); // null = loading
	let meta = $state({ deduped: 0, hidden_seasonal: 0, has_centroid: true });
	let loading = $state(false);

	const today = new Date().toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
	const tracks = $derived((gems || []).map((g) => ({ id: g.track_id, title: g.title, artist: g.artist, album_id: g.album_id })));

	const note = $derived.by(() => {
		const parts = [];
		if (meta.deduped) parts.push(`${meta.deduped.toLocaleString()} duplicate or already-played ${meta.deduped === 1 ? 'copy' : 'copies'} skipped`);
		if (meta.hidden_seasonal) parts.push(`${meta.hidden_seasonal} holiday ${meta.hidden_seasonal === 1 ? 'song' : 'songs'} hidden until November`);
		return parts.join(' · ');
	});

	async function load() {
		loading = true;
		try {
			const r = await api.getNeglectedGems(48);
			gems = r.gems || [];
			meta = { deduped: r.deduped || 0, hidden_seasonal: r.hidden_seasonal || 0, has_centroid: r.has_centroid !== false };
		} catch {
			gems = gems || [];
			addToast('Failed to load gems', 'error');
		} finally {
			loading = false;
		}
	}

	async function dismiss(g) {
		gems = gems.filter((x) => x.track_id !== g.track_id);
		try {
			await api.dismissGem(g.track_id);
		} catch {
			addToast(`Couldn't dismiss “${g.title}”`, 'error');
		}
	}

	onMount(load);
</script>

<div class="space-y-3">
	<div class="flex items-start justify-between gap-3 flex-wrap">
		<div class="min-w-0">
			<p class="text-sm text-[var(--text-secondary)]">
				Owned but never played, ranked by how close they sound to what you do play.
				{#if !meta.has_centroid}<span class="text-amber-400">No taste profile yet, so the order is arbitrary.</span>{/if}
			</p>
			{#if note}<p class="text-xs text-[var(--text-disabled)] mt-0.5">{note}</p>{/if}
		</div>
		<Button variant="secondary" size="sm" loading={loading} onclick={load} class="whitespace-nowrap" title="Draw a different set">
			<Shuffle class="w-3.5 h-3.5" /> Shuffle
		</Button>
	</div>

	<SelectionBar {tracks} name="Neglected gems — {today}" />

	{#if gems === null}
		<p class="text-sm text-[var(--text-muted)]">Loading…</p>
	{:else if !gems.length}
		<div class="flex items-center gap-2 text-sm text-[var(--text-muted)] py-6">
			<Gem class="w-4 h-4" /> No neglected gems found.
		</div>
	{:else}
		<div class="grid grid-cols-1 md:grid-cols-2 gap-1.5">
			{#each gems as g, i (g.track_id)}
				<div class="group flex items-center gap-1 rounded-lg border border-[var(--border-subtle)] hover:bg-[var(--surface-container-high)] transition-colors">
					<button onclick={() => storePlayTrack({ id: g.track_id, title: g.title, artist: g.artist, album_id: g.album_id })}
						class="flex items-center gap-3 text-left pl-3 py-2 min-w-0 flex-1" title="Play here">
						<span class="text-xs font-mono text-[var(--text-disabled)] w-6">{i + 1}</span>
						<span class="min-w-0 flex-1">
							<span class="text-sm text-[var(--text-primary)] truncate block">{g.title}</span>
							<span class="text-xs text-[var(--text-muted)] truncate block">{g.artist || 'Unknown'}</span>
						</span>
						<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400">{Math.round((g.match || 0) * 100)}%</span>
						<span class="text-[10px] font-mono text-[var(--text-disabled)] w-9">{(g.format || '').toUpperCase()}</span>
						<Play class="w-4 h-4 text-[var(--text-muted)] flex-shrink-0" />
					</button>
					<button onclick={() => dismiss(g)} title="Not interested — never suggest again" aria-label="Dismiss {g.title}"
						class="p-2 mr-1 rounded text-[var(--text-disabled)] hover:text-red-400 hover:bg-red-500/10 transition-colors">
						<X class="w-3.5 h-3.5" />
					</button>
				</div>
			{/each}
		</div>
	{/if}
</div>
