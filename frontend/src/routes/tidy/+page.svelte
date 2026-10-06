<script>
	import { FolderTree, Loader2, ShieldCheck, Search } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import { inputClass } from '$lib/utils.js';

	const COLOR = 'var(--color-tidy)';
	// Rendering all ~7,000 rows at once stalls the page; the search narrows it instead.
	const SHOW = 300;

	let loading = $state(false);
	let error = $state('');
	let preview = $state(null); // { moves, count }
	let query = $state('');

	let filtered = $derived.by(() => {
		if (!preview) return [];
		const q = query.trim().toLowerCase();
		if (!q) return preview.moves;
		return preview.moves.filter((m) =>
			m.current_path.toLowerCase().includes(q) || m.target_path.toLowerCase().includes(q));
	});

	async function runPreview() {
		loading = true;
		error = '';
		try {
			const res = await fetch('/api/library/cleanup/organize/preview', { method: 'POST' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			preview = await res.json();
		} catch (e) {
			error = `Preview failed: ${e.message}`;
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head><title>Library Tidy · Zonik</title></svelte:head>

<PageHeader title="Library Tidy" subtitle="Rename and move music files without losing favorites" icon={FolderTree} color={COLOR} />

<Card class="mb-4">
	<div class="flex items-start gap-3">
		<ShieldCheck class="w-5 h-5 flex-shrink-0 mt-0.5" style="color: {COLOR}" />
		<div class="text-sm text-[var(--text-secondary)] space-y-1.5">
			<p class="text-[var(--text-primary)] font-medium">Moving files is switched off until the safe tidy tool is ready.</p>
			<p>The old Rename &amp; Sort gave every moved track a new ID, which cut it off from its favorite, playlists and play history. Meanwhile the library is protected:</p>
			<ul class="list-disc pl-5 space-y-0.5 text-xs text-[var(--text-muted)]">
				<li>A track keeps its ID when its file moves.</li>
				<li>A scan recognises a file that was renamed or moved by hand (same size, duration and title) and keeps its favorite and history.</li>
				<li>A scan that finds a large number of tracks missing deletes none of them.</li>
				<li>A full backup of the folder structure, tracks and favorites was taken on 5 October, with a restore script.</li>
			</ul>
		</div>
	</div>
</Card>

<Card>
	<div class="flex flex-wrap items-center justify-between gap-3 mb-3">
		<div>
			<h2 class="text-sm font-semibold text-[var(--text-primary)]">Rename &amp; Sort preview</h2>
			<p class="text-xs text-[var(--text-muted)]">Where each file would go under the current naming scheme. Read-only.</p>
		</div>
		<Button variant="secondary" size="sm" disabled={loading} onclick={runPreview}>
			{#if loading}<Loader2 class="w-3 h-3 animate-spin mr-1" />{/if}
			{preview ? 'Refresh preview' : 'Preview'}
		</Button>
	</div>

	{#if error}
		<p class="text-sm text-[var(--color-error)]">{error}</p>
	{:else if loading && !preview}
		<p class="text-sm text-[var(--text-muted)] flex items-center gap-2"><Loader2 class="w-4 h-4 animate-spin" />Working out the moves…</p>
	{:else if preview}
		{#if preview.count === 0}
			<p class="text-sm text-[var(--color-success)]">Every file already matches the naming scheme.</p>
		{:else}
			<div class="flex flex-wrap items-center gap-3 mb-2">
				<span class="text-sm text-[var(--text-primary)]">{preview.count.toLocaleString()} files would move</span>
				<label class="relative flex-1 min-w-[200px] max-w-md">
					<Search class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
					<input class="{inputClass} pl-8" placeholder="Filter by path…" bind:value={query} />
				</label>
				{#if query}<span class="text-xs text-[var(--text-muted)]">{filtered.length.toLocaleString()} match</span>{/if}
			</div>
			<div class="max-h-[60vh] overflow-y-auto space-y-1">
				{#each filtered.slice(0, SHOW) as move (move.track_id)}
					<div class="text-xs py-1.5">
						<div class="text-red-400 font-mono truncate" title={move.current_path}>- {move.current_path}</div>
						<div class="text-emerald-400 font-mono truncate" title={move.target_path}>+ {move.target_path}</div>
					</div>
				{/each}
			</div>
			{#if filtered.length > SHOW}
				<p class="text-xs text-[var(--text-muted)] mt-2">Showing the first {SHOW} of {filtered.length.toLocaleString()}; filter to narrow it down.</p>
			{/if}
		{/if}
	{/if}
</Card>
