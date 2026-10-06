<script>
	import { onMount, onDestroy } from 'svelte';
	import { FolderTree, Loader2, ShieldCheck, Search, Heart, AlertTriangle } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import FilterPills from '../../components/ui/FilterPills.svelte';
	import { inputClass } from '$lib/utils.js';

	const COLOR = 'var(--color-tidy)';
	const PAGE = 200;

	let status = $state(null); // { state, done, total, error, summary }
	let rows = $state([]);
	let total = $state(0);
	let offset = $state(0);
	let filter = $state('move');
	let rule = $state('');
	let favoritesOnly = $state(false);
	let query = $state('');
	let poll = null;
	let searchTimer = null;

	const RULES = { album: 'Album', single: 'Singles', compilation: 'Compilation', untagged: 'Untagged', unreadable: 'Unreadable' };
	const NOTES = { conflict: 'Conflict', skip: 'Skipped', unchanged: 'Already right' };

	let summary = $derived(status?.summary);
	let building = $derived(status?.state === 'reading');

	async function loadStatus() {
		status = await fetch('/api/tidy/status').then((r) => r.json());
		if (building && !poll) poll = setInterval(tick, 1500);
	}

	async function tick() {
		await loadStatus();
		if (!building) {
			clearInterval(poll);
			poll = null;
			offset = 0;
			loadRows();
		}
	}

	async function loadRows() {
		const p = new URLSearchParams({ offset: String(offset), limit: String(PAGE) });
		if (filter) p.set('status', filter);
		if (rule) p.set('rule', rule);
		if (favoritesOnly) p.set('favorites', 'true');
		if (query.trim()) p.set('q', query.trim());
		const res = await fetch(`/api/tidy/plan?${p}`).then((r) => r.json());
		rows = res.moves;
		total = res.total;
	}

	async function buildPlan() {
		await fetch('/api/tidy/plan', { method: 'POST' });
		await loadStatus();
	}

	function refilter() {
		offset = 0;
		loadRows();
	}

	function onSearch() {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(refilter, 250);
	}

	onMount(async () => {
		await loadStatus();
		if (summary) loadRows();
	});
	onDestroy(() => clearInterval(poll));

	function fmtTime(iso) {
		return iso ? new Date(iso).toLocaleString() : '';
	}
</script>

<svelte:head><title>Library Tidy · Zonik</title></svelte:head>

<PageHeader title="Library Tidy" subtitle="Rename and move music files without losing favorites" icon={FolderTree} color={COLOR} />

<Card class="mb-4">
	<div class="flex items-start gap-3">
		<ShieldCheck class="w-5 h-5 flex-shrink-0 mt-0.5" style="color: {COLOR}" />
		<div class="text-sm text-[var(--text-secondary)] space-y-1">
			<p class="text-[var(--text-primary)] font-medium">This is a dry run: nothing moves yet.</p>
			<p class="text-xs text-[var(--text-muted)]">
				The plan reads every file's tags and works out where it belongs: <code>Artist/Album/NN - Title</code>,
				<code>Artist/Singles/</code> for singles, <code>Various Artists/Album/</code> for compilations and
				<code>_Untagged/</code> for files with no artist. Tracks keep their ID when moved, so favorites, playlists and
				history stay with them. A backup of the folder structure and favorites was taken on 5 October.
			</p>
		</div>
	</div>
</Card>

<Card class="mb-4">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div class="text-sm">
			{#if building}
				<span class="flex items-center gap-2 text-[var(--text-primary)]"><Loader2 class="w-4 h-4 animate-spin" />Reading tags… {status.done.toLocaleString()} of {status.total.toLocaleString()}</span>
				<div class="mt-2 h-1.5 w-72 max-w-full rounded bg-[var(--surface-container-high)] overflow-hidden">
					<div class="h-full transition-all" style="width: {status.total ? (100 * status.done) / status.total : 0}%; background: {COLOR}"></div>
				</div>
			{:else if status?.state === 'error'}
				<span class="text-[var(--color-error)]">Plan failed: {status.error}</span>
			{:else if summary}
				<span class="text-[var(--text-muted)]">Plan built {fmtTime(summary.built_at)} for {summary.tracks.toLocaleString()} tracks.</span>
			{:else}
				<span class="text-[var(--text-muted)]">No plan yet. Building one reads every file's tags, which takes several minutes the first time.</span>
			{/if}
		</div>
		<Button variant="secondary" size="sm" disabled={building} onclick={buildPlan}>
			{summary ? 'Rebuild plan' : 'Build plan'}
		</Button>
	</div>

	{#if summary && !building}
		<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mt-4">
			{#each [
				['To move', summary.status.move ?? 0, ''],
				['Already right', summary.status.unchanged ?? 0, ''],
				['Conflicts', summary.status.conflict ?? 0, 'warn'],
				['Skipped', summary.status.skip ?? 0, ''],
				['Favorites moving', summary.favorites_moving, ''],
				['Compilations', summary.rule.compilation ?? 0, ''],
			] as [label, n, tone]}
				<div class="rounded-lg bg-[var(--surface-container-high)] px-3 py-2">
					<div class="text-[11px] text-[var(--text-muted)]">{label}</div>
					<div class="text-lg font-semibold {tone === 'warn' && n ? 'text-amber-400' : 'text-[var(--text-primary)]'}">{n.toLocaleString()}</div>
				</div>
			{/each}
		</div>
	{/if}
</Card>

{#if summary && !building}
	<Card>
		<div class="flex flex-wrap items-center gap-3 mb-3">
			<FilterPills value={filter} onchange={(v) => { filter = v; refilter(); }} options={[
				{ value: 'move', label: 'To move', count: summary.status.move ?? 0 },
				{ value: 'conflict', label: 'Conflicts', count: summary.status.conflict ?? 0 },
				{ value: 'skip', label: 'Skipped', count: summary.status.skip ?? 0 },
				{ value: 'unchanged', label: 'Already right', count: summary.status.unchanged ?? 0 },
			]} />
			<select class="{inputClass} !w-auto" bind:value={rule} onchange={refilter}>
				<option value="">Every rule</option>
				{#each Object.entries(RULES) as [k, label]}<option value={k}>{label}</option>{/each}
			</select>
			<label class="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] cursor-pointer">
				<input type="checkbox" bind:checked={favoritesOnly} onchange={refilter} class="accent-[var(--color-accent)]" /> Favorites only
			</label>
			<label class="relative flex-1 min-w-[200px] max-w-md">
				<Search class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
				<input class="{inputClass} pl-8" placeholder="Filter by path…" bind:value={query} oninput={onSearch} />
			</label>
		</div>

		{#if filter === 'conflict' && total}
			<p class="text-xs text-amber-300 flex items-center gap-1.5 mb-2"><AlertTriangle class="w-3.5 h-3.5" />Conflicts are left where they are. Most are duplicate copies; clearing them on the Duplicates page resolves them.</p>
		{/if}

		<div class="space-y-1">
			{#each rows as m (m.track_id)}
				<div class="text-xs py-1.5 border-b border-[var(--border-subtle)] last:border-0">
					<div class="flex items-center gap-2 mb-0.5">
						<span class="px-1.5 py-0.5 rounded bg-[var(--surface-container-high)] text-[10px] text-[var(--text-muted)]">{RULES[m.rule] ?? m.rule}</span>
						{#if m.status !== 'move'}<span class="text-[10px] {m.status === 'conflict' ? 'text-amber-400' : 'text-[var(--text-muted)]'}">{NOTES[m.status] ?? m.status}{m.note ? ` · ${m.note}` : ''}</span>{/if}
						{#if m.favorite}<Heart class="w-3 h-3 text-red-400 fill-current" />{/if}
						{#if m.playlists}<span class="text-[10px] text-[var(--text-muted)]">in {m.playlists} playlist{m.playlists > 1 ? 's' : ''}</span>{/if}
					</div>
					<div class="text-red-400 font-mono truncate" title={m.from}>- {m.from}</div>
					{#if m.to !== m.from}<div class="text-emerald-400 font-mono truncate" title={m.to}>+ {m.to}</div>{/if}
				</div>
			{:else}
				<p class="text-sm text-[var(--text-muted)] py-4">Nothing matches.</p>
			{/each}
		</div>

		{#if total > PAGE}
			<div class="flex items-center justify-between mt-3 text-xs text-[var(--text-muted)]">
				<span>{(offset + 1).toLocaleString()}–{Math.min(offset + PAGE, total).toLocaleString()} of {total.toLocaleString()}</span>
				<div class="flex gap-2">
					<Button variant="ghost" size="sm" disabled={offset === 0} onclick={() => { offset = Math.max(0, offset - PAGE); loadRows(); }}>Previous</Button>
					<Button variant="ghost" size="sm" disabled={offset + PAGE >= total} onclick={() => { offset += PAGE; loadRows(); }}>Next</Button>
				</div>
			</div>
		{/if}
	</Card>
{/if}
