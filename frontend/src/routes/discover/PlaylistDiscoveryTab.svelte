<script>
	import { addToast } from '$lib/stores.js';
	import { api } from '$lib/api.js';
	import { Loader2, RefreshCw, ListMusic, ExternalLink } from 'lucide-svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let playlists = $state([]);
	let loading = $state(false);
	let queries = $state([]);

	async function loadPlaylists() {
		loading = true;
		try {
			const data = await api.discoverPlaylists(20);
			playlists = data.playlists || [];
			queries = data.queries || [];
			if (playlists.length > 1) {
				try {
					const ranked = await api.aiRankPlaylists(playlists);
					if (ranked.playlists) playlists = ranked.playlists;
				} catch {}
			}
		} catch (e) { addToast('Failed to discover playlists: ' + e.message, 'error'); }
		finally { loading = false; }
	}
</script>

<div class="flex items-center gap-3 mb-4">
	<Button variant="ghost" onclick={loadPlaylists} disabled={loading}>
		{#if loading}<Loader2 class="w-4 h-4 animate-spin" />{:else}<RefreshCw class="w-4 h-4" />{/if}
		Discover
	</Button>
	{#if queries.length}
		<span class="text-xs text-[var(--text-muted)]">Based on: {queries.join(', ')}</span>
	{/if}
</div>

{#if loading}
	<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
		{#each Array(6) as _}
			<Skeleton class="h-20 rounded-lg" />
		{/each}
	</div>
{:else if playlists.length}
	<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
		{#each playlists as pl}
			<a href="/playlists" class="block">
				<Card hover padding="p-3">
					<div class="flex items-center gap-3">
						{#if pl.image_url}
							<img src={pl.image_url} alt="" class="w-12 h-12 rounded-lg object-cover flex-shrink-0" />
						{:else}
							<div class="w-12 h-12 rounded-lg bg-[var(--bg-secondary)] flex items-center justify-center flex-shrink-0">
								<ListMusic class="w-5 h-5 text-[var(--text-disabled)]" />
							</div>
						{/if}
						<div class="flex-1 min-w-0">
							<p class="text-sm font-medium text-[var(--text-primary)] truncate">{pl.name}</p>
							<p class="text-xs text-[var(--text-muted)] truncate">
								{pl.owner} &middot; {pl.track_count} tracks &middot;
								<span class="capitalize">{pl.source.replace('_', ' ')}</span>
							</p>
							{#if pl.matched_query}
								<span class="text-xs text-[var(--text-disabled)]">matched: {pl.matched_query}</span>
							{/if}
						</div>
						{#if pl.ai_score}
							<div class="flex flex-col items-end flex-shrink-0">
								<span class="text-xs font-mono {pl.ai_score >= 0.7 ? 'text-emerald-400' : pl.ai_score >= 0.4 ? 'text-amber-400' : 'text-[var(--text-muted)]'}">{Math.round(pl.ai_score * 100)}%</span>
								{#if pl.ai_reason}
									<span class="text-[9px] text-[var(--text-disabled)] max-w-28 truncate" title={pl.ai_reason}>{pl.ai_reason}</span>
								{/if}
							</div>
						{:else}
							<ExternalLink class="w-3.5 h-3.5 text-[var(--text-disabled)] flex-shrink-0" />
						{/if}
					</div>
				</Card>
			</a>
		{/each}
	</div>
{:else}
	<Card>
		<EmptyState title="No playlists discovered" description="Click Discover to find playlists matching your library taste.">
			{#snippet icon()}<ListMusic class="w-12 h-12" />{/snippet}
		</EmptyState>
	</Card>
{/if}
