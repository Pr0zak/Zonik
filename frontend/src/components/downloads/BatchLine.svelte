<script>
	/**
	 * The running-import line above the Live list (kit .list-row on surface-container-high):
	 *   "07:02 · Playlist import · Phantom of the Opera (2026 Mix) · 60 tracks · 1 added
	 *    (Beck — Scarecrow, 07:09) · 8 live · 51 waiting"  [1 added][8 live][51 waiting]  [Cancel import]
	 * Without a batch (no registry entry) it degrades to "8 live from a playlist import".
	 *
	 * batch       DC-21 batches item | null
	 * liveCount   live rows of this source on the page (used when the batch has no `live`)
	 * sourceLabel e.g. "Playlist" (the degraded sentence)
	 * lastAdded   { title, at } of the newest completed row of the batch | null
	 * cancelling  true while the cancel request runs
	 * onCancel    (batch) => void; no button without it (or without a batch)
	 */
	import { X, ListMusic, Download, Sparkles, Compass } from 'lucide-svelte';
	import Badge from '../ui/Badge.svelte';
	import Button from '../ui/Button.svelte';
	import { clockTime } from '$lib/downloads/stage.js';

	let {
		batch = null,
		liveCount = 0,
		sourceLabel = '',
		lastAdded = null,
		cancelling = false,
		onCancel = null,
		class: className = '',
	} = $props();

	const KIND = {
		playlist: { label: 'Playlist import', icon: ListMusic, color: 'var(--color-playlists)' },
		bulk: { label: 'Download all', icon: Download, color: 'var(--color-downloads)' },
		recommendation: { label: 'Recommendations', icon: Sparkles, color: 'var(--color-discover)' },
		scheduled: { label: 'Scheduled run', icon: Compass, color: 'var(--color-discover)' },
	};

	const n = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);

	let kind = $derived(KIND[batch?.kind] || { label: 'Import', icon: Download, color: 'var(--color-downloads)' });
	let Icon = $derived(kind.icon);
	let live = $derived(batch && batch.live != null ? n(batch.live) : n(liveCount));
	let done = $derived(n(batch?.done));
	let failed = $derived(n(batch?.failed));
	let skipped = $derived(n(batch?.skipped));
	let waiting = $derived(n(batch?.pending));
	let total = $derived(n(batch?.total));
	let heading = $derived.by(() => {
		const label = (batch?.label || '').trim();
		if (!label || label.toLowerCase() === kind.label.toLowerCase()) return kind.label;
		return `${kind.label} · ${label}`;
	});
	let addedText = $derived.by(() => {
		if (!done) return '';
		if (lastAdded?.title) {
			const at = clockTime(lastAdded.at);
			return `${done} added (${lastAdded.title}${at ? `, ${at}` : ''})`;
		}
		return `${done} added`;
	});
	let tail = $derived(
		[total ? `${total} ${total === 1 ? 'track' : 'tracks'}` : '', addedText, `${live} live`, waiting ? `${waiting} waiting` : '']
			.filter(Boolean).join(' · ')
	);
	let fallback = $derived(`${live} live from ${/^[aeiou]/i.test(sourceLabel || 'import') ? 'an' : 'a'} ${(sourceLabel || '').toLowerCase()}${sourceLabel ? ' ' : ''}import`);
</script>

<div class="flex items-center flex-wrap gap-x-2.5 gap-y-1.5 rounded-lg bg-[var(--surface-container-high)] px-3 py-2 text-xs leading-4 {className}">
	<Icon class="w-3.5 h-3.5 flex-shrink-0" style="color: {kind.color}" />
	{#if batch}
		{#if batch.started_at}<span class="font-mono text-[11px] text-[var(--text-muted)] flex-shrink-0">{clockTime(batch.started_at)}</span>{/if}
		<b class="font-semibold text-[var(--text-primary)] min-w-0 truncate max-md:whitespace-normal">{heading}</b>
		<span class="flex-1 min-w-[8rem] text-[var(--text-muted)] truncate max-md:whitespace-normal max-md:basis-full">{tail}</span>
		<span class="flex flex-wrap gap-1.5 min-w-0">
			{#if done}<Badge variant="success">{done} added</Badge>{/if}
			<Badge variant="info">{live} live</Badge>
			{#if waiting}<Badge>{waiting} waiting</Badge>{/if}
			{#if failed}<Badge variant="error">{failed} failed</Badge>{/if}
			{#if skipped}<Badge>{skipped} skipped</Badge>{/if}
		</span>
		{#if onCancel}
			<Button variant="ghost" size="sm" loading={cancelling} disabled={cancelling} onclick={() => onCancel(batch)}>
				{#if !cancelling}<X class="w-3.5 h-3.5" />{/if}
				Cancel import
			</Button>
		{/if}
	{:else}
		<span class="flex-1 min-w-0 text-[var(--text-muted)]">{fallback}</span>
	{/if}
</div>
