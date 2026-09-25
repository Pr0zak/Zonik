<script>
	// Weekday × hour heatmap of plays (server-local time), optionally tinted by
	// the genre family you played most in each slot.
	import { onMount } from 'svelte';
	import { familyColor } from '../map/explore.js';
	import { api } from '$lib/api.js';

	let clock = $state(null);
	let failed = $state(false);
	let byGenre = $state(false);

	const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
	const hourLabel = (hr) => (hr === 0 ? '12a' : hr === 12 ? '12p' : hr > 12 ? `${hr - 12}p` : `${hr}a`);

	// Same colour per family as the Music Map; ordered by how often it tops a slot.
	const familyColors = $derived.by(() => {
		if (!clock) return new Map();
		const counts = new Map();
		for (const row of clock.genre_grid) for (const g of row) if (g) counts.set(g, (counts.get(g) || 0) + 1);
		const ordered = [...counts.entries()].sort((a, b) => b[1] - a[1]).map((e) => e[0]);
		return new Map(ordered.map((g) => [g, familyColor(g)]));
	});

	function cellStyle(wd, hr) {
		const c = clock.grid[wd][hr];
		if (!c) return 'background:var(--surface-lowest)';
		const op = (0.15 + 0.85 * (c / (clock.max || 1))).toFixed(2);
		if (byGenre) {
			const col = familyColors.get(clock.genre_grid[wd][hr]) || '#22d3ee';
			return `background:${col};opacity:${op}`;
		}
		return `background:rgba(34,211,238,${op})`;
	}

	onMount(async () => {
		try { clock = await api.getListeningClock(); } catch { failed = true; }
	});
</script>

<div>
	<div class="flex items-center justify-between mb-3 flex-wrap gap-2">
		<p class="text-xs text-[var(--text-muted)]">{clock ? clock.total.toLocaleString() : '…'} plays by weekday and hour (server time)</p>
		<label class="text-xs text-[var(--text-muted)] flex items-center gap-1.5 cursor-pointer">
			<input type="checkbox" bind:checked={byGenre} class="accent-[#22d3ee]" /> colour by genre
		</label>
	</div>
	{#if failed}
		<p class="text-sm text-[var(--text-muted)]">Couldn't load the listening clock.</p>
	{:else if !clock}
		<p class="text-sm text-[var(--text-muted)]">Loading…</p>
	{:else}
		<div class="grid gap-[3px] w-full" style="grid-template-columns: 32px repeat(24, minmax(0, 1fr));">
			<div></div>
			{#each Array(24) as _, hr}
				<div class="text-[9px] text-[var(--text-disabled)] text-center">{hr % 3 === 0 ? hourLabel(hr) : ''}</div>
			{/each}
			{#each DAYS as day, wd}
				<div class="text-[10px] text-[var(--text-muted)] flex items-center">{day}</div>
				{#each Array(24) as _, hr}
					<div class="h-6 rounded-sm" style={cellStyle(wd, hr)}
						title="{day} {hourLabel(hr)} · {clock.grid[wd][hr]} plays{clock.genre_grid[wd][hr] ? ' · mostly ' + clock.genre_grid[wd][hr] : ''}"></div>
				{/each}
			{/each}
		</div>
		<div class="flex items-center justify-between mt-3 flex-wrap gap-2">
			{#if byGenre}
				<div class="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-[var(--text-secondary)]">
					{#each [...familyColors.entries()] as [g, col]}
						<span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm" style="background:{col}"></span>{g}</span>
					{/each}
				</div>
			{:else}
				<span></span>
			{/if}
			<p class="text-[10px] text-[var(--text-disabled)]">Brighter = more plays. Hover a cell for the count.</p>
		</div>
	{/if}
</div>
