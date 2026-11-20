<script>
	import { onMount } from 'svelte';
	import { Mic2, Search, RefreshCw, Pencil, X, Clock3, FileText } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import StatTile from '../../components/ui/StatTile.svelte';
	import FilterPills from '../../components/ui/FilterPills.svelte';
	import Pagination from '../../components/ui/Pagination.svelte';
	import Toggle from '../../components/ui/Toggle.svelte';
	import ScheduleControl from '../../components/ui/ScheduleControl.svelte';
	import { createScheduleHelpers } from '$lib/schedule.js';
	import { addToast } from '$lib/stores.js';
	import { inputClass } from '$lib/utils.js';

	const COLOR = 'var(--color-lyrics)';
	const SOURCES = { tags: 'File tags', lrc: '.lrc file', lrclib: 'LRCLIB', manual: 'Typed in' };

	let stats = $state(null);
	let items = $state([]);
	let total = $state(0);
	let offset = $state(0);
	let limit = $state(50);
	let filter = $state('all');
	let query = $state('');
	let searchTimer = null;
	let loading = $state(true);

	let schedTasks = $state({});
	let schedRunning = $state({});

	// The open track
	let open = $state(null);
	let openLoading = $state(false);
	let fetching = $state(false);
	let editing = $state(false);
	let editText = $state('');
	let savingEdit = $state(false);

	const { toggleSched, updateSched, runSched } = createScheduleHelpers(
		() => schedTasks,
		(name, val) => { schedTasks[name] = val; },
		addToast
	);

	async function loadStats() {
		stats = await fetch('/api/lyrics/stats').then((r) => r.json());
	}

	async function loadItems() {
		const p = new URLSearchParams({ status: filter, limit: String(limit), offset: String(offset) });
		if (query.trim()) p.set('q', query.trim());
		const res = await fetch(`/api/lyrics/tracks?${p}`).then((r) => r.json());
		items = res.items;
		total = res.total;
	}

	function onSearch() {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => { offset = 0; loadItems(); }, 300);
	}

	async function openTrack(id) {
		openLoading = true;
		editing = false;
		try {
			open = await fetch(`/api/lyrics/track/${id}`).then((r) => r.json());
		} finally {
			openLoading = false;
		}
	}

	async function lookUp() {
		if (!open) return;
		fetching = true;
		try {
			const r = await fetch(`/api/lyrics/track/${open.id}/fetch`, { method: 'POST' });
			if (!r.ok) throw new Error((await r.json()).detail || r.status);
			const p = await r.json();
			open = { ...open, ...p };
			addToast(p.status === 'found' ? 'Lyrics found' : 'No lyrics found', p.status === 'found' ? 'success' : 'info');
			loadStats();
			loadItems();
		} catch (e) {
			addToast(`Lookup failed: ${e.message}`, 'error');
		} finally {
			fetching = false;
		}
	}

	function fmt(ms) {
		const s = Math.floor(ms / 1000);
		return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
	}

	function startEdit() {
		editText = (open?.lines || [])
			.map((l) => (l.ms >= 0 ? `[${fmt(l.ms)}.${String(Math.floor((l.ms % 1000) / 10)).padStart(2, '0')}]${l.text}` : l.text))
			.join('\n');
		editing = true;
	}

	async function saveEdit() {
		savingEdit = true;
		try {
			const r = await fetch(`/api/lyrics/track/${open.id}`, {
				method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: editText }),
			});
			if (!r.ok) throw new Error(r.status);
			open = { ...open, ...(await r.json()) };
			editing = false;
			addToast('Lyrics saved', 'success');
			loadStats();
			loadItems();
		} catch (e) {
			addToast(`Could not save: ${e.message}`, 'error');
		} finally {
			savingEdit = false;
		}
	}

	async function setOnline(on) {
		await fetch('/api/tv/visualizer/config', {
			method: 'PUT', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ config: { lyrics_online: on }, updated_by: 'web' }),
		});
		stats = { ...stats, online: on };
	}

	function badge(it) {
		if (it.status === 'found') return it.synced ? ['Timed', 'text-emerald-300 bg-emerald-500/10'] : ['Plain', 'text-sky-300 bg-sky-500/10'];
		if (it.status === 'none') return ['None', 'text-[var(--text-muted)] bg-[var(--surface-container-high)]'];
		return ['Not checked', 'text-amber-300 bg-amber-500/10'];
	}

	onMount(async () => {
		try {
			await Promise.all([loadStats(), loadItems()]);
			const tasks = await fetch('/api/schedule').then((r) => r.json());
			for (const t of tasks) schedTasks[t.task_name] = t;
		} catch (e) {
			console.error('Lyrics load failed', e);
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head><title>Lyrics · Zonik</title></svelte:head>

<div class="p-4 md:p-6 max-w-7xl mx-auto">
	<PageHeader title="Lyrics" icon={Mic2} color={COLOR}
		subtitle={stats ? `${stats.found} of ${stats.tracks} tracks have lyrics · ${stats.timed} timed` : 'Lyrics for your library'} />

	{#if stats}
		<div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
			<StatTile label="With lyrics" value={stats.found} color={COLOR} onclick={() => { filter = 'all'; offset = 0; loadItems(); }}
				detail={stats.tracks ? `${Math.round((stats.found / stats.tracks) * 100)}% of the library` : ''} />
			<StatTile label="Timed" value={stats.timed} color="#10b981" active={filter === 'timed'}
				onclick={() => { filter = 'timed'; offset = 0; loadItems(); }} detail="Line by line, for the TV" />
			<StatTile label="Plain" value={stats.plain} color="#3b82f6" active={filter === 'plain'}
				onclick={() => { filter = 'plain'; offset = 0; loadItems(); }} />
			<StatTile label="None found" value={stats.none} color="var(--text-muted)" active={filter === 'none'}
				onclick={() => { filter = 'none'; offset = 0; loadItems(); }} />
			<StatTile label="Not checked yet" value={stats.unchecked} color="#f59e0b" active={filter === 'unchecked'}
				onclick={() => { filter = 'unchecked'; offset = 0; loadItems(); }} tone={stats.unchecked > 0 ? 'warn' : 'default'} />
		</div>
	{/if}

	<Card padding="p-4" class="mb-5">
		<div class="flex flex-col lg:flex-row gap-4 lg:items-center justify-between">
			<div class="min-w-0">
				<div class="text-sm font-semibold text-[var(--text-primary)]">Finding lyrics</div>
				<p class="text-xs text-[var(--text-muted)] mt-1 max-w-[70ch]">
					Each track is checked for lyrics in its own tags and in a .lrc file beside it, then on LRCLIB, a free
					lyrics database that mostly has them timed line by line. LRCLIB is sent the artist, title, album and
					length only. Tracks with no lyrics are tried again after 30 days.
				</p>
				{#if stats?.by_source && Object.keys(stats.by_source).length}
					<div class="flex flex-wrap gap-2 mt-2">
						{#each Object.entries(stats.by_source) as [src, n]}
							<span class="text-[11px] font-mono px-2 py-0.5 rounded-full bg-[var(--surface-container-high)] text-[var(--text-secondary)]">{SOURCES[src] || src}: {n}</span>
						{/each}
					</div>
				{/if}
			</div>
			<div class="flex-shrink-0">
				{#if stats}
					<Toggle checked={stats.online} label="Look up online (LRCLIB)" color={COLOR} onchange={(v) => setOnline(v)} />
				{/if}
			</div>
		</div>
		{#if schedTasks.lyrics_fetch}
			<div class="mt-4">
				<ScheduleControl taskName="lyrics_fetch" label="Lyrics Fetch" countLabel="Tracks per run"
					enabled={schedTasks.lyrics_fetch.enabled} intervalHours={schedTasks.lyrics_fetch.interval_hours}
					runAt={schedTasks.lyrics_fetch.run_at} dayOfWeek={schedTasks.lyrics_fetch.day_of_week}
					count={schedTasks.lyrics_fetch.count} lastRunAt={schedTasks.lyrics_fetch.last_run_at}
					running={schedRunning.lyrics_fetch}
					onToggle={() => toggleSched('lyrics_fetch')} onUpdate={(u) => updateSched('lyrics_fetch', u)}
					onRun={() => runSched('lyrics_fetch')} />
			</div>
		{/if}
	</Card>

	<div class="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] gap-5">
		<div class="min-w-0">
			<div class="flex flex-wrap items-center justify-between gap-3 mb-3">
				<FilterPills value={filter} onchange={(v) => { filter = v; offset = 0; loadItems(); }} options={[
					{ value: 'all', label: 'All', color: COLOR },
					{ value: 'timed', label: 'Timed', color: COLOR },
					{ value: 'plain', label: 'Plain', color: COLOR },
					{ value: 'none', label: 'None', color: COLOR },
					{ value: 'unchecked', label: 'Not checked', color: COLOR },
				]} />
				<div class="relative">
					<Search class="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
					<input id="lyrics-search" type="search" class="{inputClass} !w-64 !pl-8" placeholder="Search title or artist"
						aria-label="Search title or artist" bind:value={query} oninput={onSearch} />
				</div>
			</div>

			<Card padding="p-0">
				{#if loading}
					<p class="p-4 text-sm text-[var(--text-muted)]">Loading…</p>
				{:else if !items.length}
					<p class="p-4 text-sm text-[var(--text-muted)]">No tracks match.</p>
				{:else}
					<table class="w-full text-sm">
						<thead>
							<tr class="text-left text-xs text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
								<th class="px-3 py-2 font-medium">Title</th>
								<th class="px-3 py-2 font-medium hidden md:table-cell">Artist</th>
								<th class="px-3 py-2 font-medium">Lyrics</th>
								<th class="px-3 py-2 font-medium hidden lg:table-cell">Source</th>
							</tr>
						</thead>
						<tbody>
							{#each items as it (it.id)}
								{@const b = badge(it)}
								<tr class="border-b border-[var(--border-subtle)] last:border-0 cursor-pointer hover:bg-[var(--surface-container-high)] {open?.id === it.id ? 'bg-[var(--surface-container-high)]' : ''}"
									onclick={() => openTrack(it.id)}>
									<td class="px-3 py-2 text-[var(--text-primary)] truncate max-w-[16rem]">{it.title}</td>
									<td class="px-3 py-2 text-[var(--text-secondary)] truncate max-w-[12rem] hidden md:table-cell">{it.artist || '—'}</td>
									<td class="px-3 py-2"><span class="text-[11px] font-medium px-2 py-0.5 rounded-full {b[1]}">{b[0]}</span></td>
									<td class="px-3 py-2 text-xs text-[var(--text-muted)] hidden lg:table-cell">{SOURCES[it.source] || ''}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</Card>
			<Pagination {total} {offset} {limit} onchange={(o, l) => { offset = o; limit = l; loadItems(); }} />
		</div>

		<div class="min-w-0">
			<Card padding="p-4" class="xl:sticky xl:top-4">
				{#if openLoading}
					<p class="text-sm text-[var(--text-muted)]">Loading…</p>
				{:else if !open}
					<div class="text-sm text-[var(--text-muted)] flex items-center gap-2"><FileText class="w-4 h-4" /> Pick a track to see its lyrics.</div>
				{:else}
					<div class="flex items-start justify-between gap-2 mb-3">
						<div class="min-w-0">
							<div class="text-base font-semibold text-[var(--text-primary)] truncate">{open.title}</div>
							<div class="text-xs text-[var(--text-muted)] truncate">{open.artist || ''}{open.album ? ` · ${open.album}` : ''}</div>
							<div class="text-[11px] text-[var(--text-muted)] mt-1 flex items-center gap-1">
								{#if open.status === 'found'}
									{open.synced ? 'Timed' : 'Plain'} · {SOURCES[open.source] || open.source}
								{:else if open.status === 'none'}No lyrics found{:else}Not checked yet{/if}
								{#if open.checked_at}<Clock3 class="w-3 h-3 ml-1" /> {new Date(open.checked_at + 'Z').toLocaleDateString()}{/if}
							</div>
						</div>
						<button class="p-1 rounded hover:bg-[var(--surface-container-high)] text-[var(--text-muted)]" aria-label="Close" onclick={() => (open = null)}><X class="w-4 h-4" /></button>
					</div>
					<div class="flex gap-2 mb-3">
						<Button size="sm" variant="secondary" loading={fetching} onclick={lookUp}><RefreshCw class="w-3.5 h-3.5 mr-1" /> Look up again</Button>
						{#if !editing}<Button size="sm" variant="secondary" onclick={startEdit}><Pencil class="w-3.5 h-3.5 mr-1" /> Edit</Button>{/if}
					</div>
					{#if editing}
						<p class="text-[11px] text-[var(--text-muted)] mb-1">Plain lines, or LRC with [mm:ss.xx] times at the start of each line. Empty clears them.</p>
						<textarea id="lyrics-edit" class="{inputClass} !h-80 font-mono text-xs" bind:value={editText}></textarea>
						<div class="flex gap-2 mt-2">
							<Button size="sm" loading={savingEdit} onclick={saveEdit}>Save</Button>
							<Button size="sm" variant="ghost" onclick={() => (editing = false)}>Cancel</Button>
						</div>
					{:else if open.lines?.length}
						<div class="max-h-[60vh] overflow-y-auto pr-1 space-y-0.5">
							{#each open.lines as l}
								<div class="flex gap-3 text-sm leading-relaxed">
									{#if open.synced}<span class="font-mono text-[11px] text-[var(--text-muted)] w-10 flex-shrink-0 pt-0.5 tabular-nums">{fmt(l.ms)}</span>{/if}
									<span class="text-[var(--text-body)]">{l.text || '♪'}</span>
								</div>
							{/each}
						</div>
					{:else}
						<p class="text-sm text-[var(--text-muted)]">No lyrics yet. Look them up, or paste them in with Edit.</p>
					{/if}
				{/if}
			</Card>
		</div>
	</div>
</div>
