<script>
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import { Map as MapIcon } from 'lucide-svelte';
	import Explore from '../../components/map/Explore.svelte';
	import SonicAdventure from '../../components/map/SonicAdventure.svelte';
	import GemsView from '../../components/map/GemsView.svelte';
	import ListeningView from '../../components/map/ListeningView.svelte';

	const TABS = [
		{ id: 'explore', label: 'Explore', subtitle: 'Your library laid out by key, tempo and sound — select tracks and save them as a playlist' },
		{ id: 'journey', label: 'Journey', subtitle: 'A playlist that moves gradually from one track’s sound to another’s' },
		{ id: 'listening', label: 'Listening', subtitle: 'How your listening moves: genres over the year, what follows what, and what’s in rotation' },
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

	<div class="inline-flex gap-1 bg-[var(--surface-container-low)] p-1.5 rounded-xl ghost-border overflow-x-auto max-w-full" role="tablist">
		{#each TABS as t (t.id)}
			{@const isActive = tab.id === t.id}
			<button role="tab" aria-selected={isActive} onclick={() => show(t.id)}
				class="px-3.5 py-1.5 text-xs font-semibold rounded-lg whitespace-nowrap transition-all {isActive ? 'bg-[#22d3ee] text-black shadow-sm' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-high)]'}">{t.label}</button>
		{/each}
	</div>

	{#if tab.id === 'explore'}
		<Explore />
	{:else if tab.id === 'journey'}
		<div class="mt-4"><SonicAdventure /></div>
	{:else if tab.id === 'listening'}
		<div class="mt-4"><ListeningView /></div>
	{:else}
		<div class="mt-4"><GemsView /></div>
	{/if}
</div>
