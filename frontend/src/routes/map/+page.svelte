<script>
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import { Map as MapIcon } from 'lucide-svelte';
	import Explore from '../../components/map/Explore.svelte';
	import SonicAdventure from '../../components/map/SonicAdventure.svelte';
	import GemsView from '../../components/map/GemsView.svelte';

	const TABS = [
		{ id: 'explore', label: 'Explore', subtitle: 'Your library laid out by key, tempo and sound — select tracks and save them as a playlist' },
		{ id: 'journey', label: 'Journey', subtitle: 'A playlist that moves gradually from one track’s sound to another’s' },
		{ id: 'gems', label: 'Gems', subtitle: 'Tracks you own but have never played, closest to your taste first' },
	];

	const tab = $derived(TABS.find((t) => t.id === $page.url.searchParams.get('tab')) || TABS[0]);

	function show(id) {
		const url = new URL($page.url);
		if (id === 'explore') url.searchParams.delete('tab'); else url.searchParams.set('tab', id);
		goto(url, { replaceState: true, noScroll: true, keepFocus: true });
	}
</script>

<div class="max-w-[1600px]">
	<PageHeader title="Music Map" icon={MapIcon} color="#22d3ee" subtitle={tab.subtitle} />

	<div class="flex gap-1 mt-4 border-b border-[var(--border-subtle)] overflow-x-auto" role="tablist">
		{#each TABS as t (t.id)}
			<button role="tab" aria-selected={tab.id === t.id} onclick={() => show(t.id)}
				class="px-3 py-2 text-sm whitespace-nowrap border-b-2 -mb-px transition-colors {tab.id === t.id ? 'border-[#22d3ee] text-[var(--text-primary)] font-medium' : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}">{t.label}</button>
		{/each}
	</div>

	{#if tab.id === 'explore'}
		<Explore />
	{:else if tab.id === 'journey'}
		<div class="mt-4"><SonicAdventure /></div>
	{:else}
		<div class="mt-4"><GemsView /></div>
	{/if}
</div>
