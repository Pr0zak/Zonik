<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { ListMusic } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let playlists = $state([]);
	let loading = $state(true);

	onMount(async () => {
		try {
			playlists = await api.getPlaylists();
		} catch (e) {
			console.error('Failed to load playlists:', e);
		} finally {
			loading = false;
		}
	});
</script>

<div class="max-w-6xl">
	<PageHeader title="Playlists" color="var(--color-playlists)" />

	{#if loading}
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
			{#each Array(6) as _}
				<Skeleton class="h-20 rounded-lg" />
			{/each}
		</div>
	{:else if playlists.length}
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
			{#each playlists as playlist}
				<Card hover padding="p-4" class="cursor-pointer group">
					<div class="flex items-center gap-3">
						<div class="w-10 h-10 rounded-lg bg-[var(--bg-tertiary)] flex items-center justify-center group-hover:bg-amber-500/10 transition-colors">
							<ListMusic class="w-5 h-5 text-[var(--text-disabled)] group-hover:text-amber-400 transition-colors" />
						</div>
						<div>
							<h3 class="font-medium text-[var(--text-primary)]">{playlist.name}</h3>
							<p class="text-xs text-[var(--text-muted)]">{playlist.track_count} tracks</p>
						</div>
					</div>
				</Card>
			{/each}
		</div>
	{:else}
		<Card>
			<EmptyState
				title="No playlists yet"
				description="Create playlists in Symfonium to see them here."
			>
				{#snippet icon()}<ListMusic class="w-10 h-10" />{/snippet}
			</EmptyState>
		</Card>
	{/if}
</div>
