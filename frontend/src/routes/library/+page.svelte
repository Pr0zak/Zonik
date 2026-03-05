<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { currentTrack, addToast, activeJobs } from '$lib/stores.js';
	import { formatDuration, formatSize, debounce } from '$lib/utils.js';
	import {
		Search, ScanLine, Download, Music, Users, Disc3,
		Play, ChevronLeft, ChevronRight, Grid3x3, List, Trash2, CheckSquare
	} from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import Modal from '../../components/ui/Modal.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	const tabs = [
		{ id: 'tracks', label: 'Tracks', icon: Music },
		{ id: 'artists', label: 'Artists', icon: Users },
		{ id: 'albums', label: 'Albums', icon: Disc3 },
	];

	let tab = $state('tracks');
	let search = $state('');
	let offset = $state(0);
	let limit = 48;
	let loading = $state(true);
	let viewMode = $state('grid');

	// Tracks state
	let tracks = $state([]);
	let trackTotal = $state(0);
	let sort = $state('title');
	let order = $state('asc');

	// Artists state
	let artists = $state([]);
	let artistTotal = $state(0);

	// Albums state
	let albums = $state([]);
	let albumTotal = $state(0);

	// Scan state
	let scanTriggered = $state(false);
	let scanning = $derived(scanTriggered || $activeJobs.some(j => j.type === 'library_scan'));
	let prevScanning = $state(false);

	$effect(() => {
		if (prevScanning && !scanning) {
			scanTriggered = false;
			loadData();
			addToast('Library scan finished', 'success');
		}
		prevScanning = scanning;
	});

	// Select mode (tracks only)
	let selectMode = $state(false);
	let selected = $state(new Set());

	// Similar tracks modal
	let showSimilar = $state(false);
	let similarSource = $state(null);
	let similarTracks = $state([]);
	let similarLoading = $state(false);
	let similarTab = $state('lastfm');

	// Artist detail overlay
	let selectedArtist = $state(null);
	let artistAlbums = $state([]);
	let artistTracks = $state([]);

	function coverUrl(id) {
		if (!id) return null;
		return `/rest/getCoverArt?id=${id}`;
	}

	async function loadData() {
		loading = true;
		try {
			if (tab === 'tracks') {
				const result = await api.getTracks({ offset, limit, sort, order, search: search || undefined });
				tracks = result.tracks;
				trackTotal = result.total;
			} else if (tab === 'artists') {
				const result = await api.getArtists({ offset, limit, search: search || undefined });
				artists = result.artists;
				artistTotal = result.total;
			} else if (tab === 'albums') {
				const result = await api.getAlbums({ offset, limit, search: search || undefined });
				albums = result.albums;
				albumTotal = result.total;
			}
		} catch (e) {
			console.error('Failed to load:', e);
		} finally {
			loading = false;
		}
	}

	onMount(async () => {
		await loadData();
		try {
			const active = await api.getActiveJobs();
			if (active.some(j => j.type === 'library_scan')) scanTriggered = true;
		} catch {}
	});

	function switchTab(newTab) {
		tab = newTab;
		offset = 0;
		search = '';
		selectMode = false;
		selected = new Set();
		loadData();
	}

	const debouncedSearch = debounce(() => {
		offset = 0;
		loadData();
	}, 300);

	async function scanLibrary() {
		scanTriggered = true;
		try {
			await api.scanLibrary();
			addToast('Library scan started', 'success');
		} catch (e) {
			addToast('Scan failed: ' + e.message, 'error');
			scanTriggered = false;
		}
	}

	function playTrack(track) {
		$currentTrack = track;
	}

	function toggleSort(col) {
		if (sort === col) order = order === 'asc' ? 'desc' : 'asc';
		else { sort = col; order = 'asc'; }
		loadData();
	}

	function prevPage() { offset = Math.max(0, offset - limit); loadData(); }
	function nextPage() { offset += limit; loadData(); }

	let currentTotal = $derived(tab === 'tracks' ? trackTotal : tab === 'artists' ? artistTotal : albumTotal);

	// Select mode helpers
	function toggleSelectMode() { selectMode = !selectMode; if (!selectMode) selected = new Set(); }
	function toggleSelect(id) {
		const next = new Set(selected);
		if (next.has(id)) next.delete(id); else next.add(id);
		selected = next;
	}
	function toggleSelectAll() {
		selected = selected.size === tracks.length ? new Set() : new Set(tracks.map(t => t.id));
	}
	async function bulkDelete() {
		if (!selected.size || !window.confirm(`Delete ${selected.size} track(s)? This cannot be undone.`)) return;
		try {
			const result = await api.bulkDeleteTracks([...selected]);
			addToast(`Deleted ${result.deleted} track(s)`, 'success');
			selected = new Set();
			await loadData();
		} catch (e) { addToast('Bulk delete failed: ' + e.message, 'error'); }
	}
	async function bulkAnalyze() {
		if (!selected.size) return;
		try {
			const result = await api.bulkAnalyzeTracks([...selected]);
			addToast(`Queued ${result.queued} track(s) for analysis`, 'success');
			selected = new Set();
		} catch (e) { addToast('Bulk analyze failed: ' + e.message, 'error'); }
	}

	// Similar tracks
	async function findSimilar(track, e) {
		e.stopPropagation();
		similarSource = track;
		showSimilar = true;
		similarTracks = [];
		similarLoading = true;
		similarTab = 'lastfm';
		await loadSimilarLastfm();
	}
	async function loadSimilarLastfm() {
		if (!similarSource?.artist) { similarTracks = []; similarLoading = false; return; }
		similarLoading = true;
		try {
			const data = await api.getSimilarTracks(similarSource.artist, similarSource.title);
			similarTracks = data.tracks || [];
		} catch { similarTracks = []; } finally { similarLoading = false; }
	}
	async function loadSimilarVibe() {
		if (!similarSource?.id) { similarTracks = []; similarLoading = false; return; }
		similarLoading = true;
		try {
			const data = await api.echoMatch(similarSource.id);
			similarTracks = (data.tracks || []).map(t => ({
				name: t.title, artist: t.artist, in_library: true, track_id: t.id, match: t.similarity,
			}));
		} catch { similarTracks = []; } finally { similarLoading = false; }
	}
	async function switchSimilarTab(t) {
		similarTab = t;
		if (t === 'lastfm') await loadSimilarLastfm(); else await loadSimilarVibe();
	}
	async function downloadSimilar(t) {
		try {
			await fetch('/api/download/trigger', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ artist: t.artist, track: t.name }) });
			addToast(`Downloading: ${t.artist} - ${t.name}`, 'success');
		} catch { addToast('Download failed', 'error'); }
	}
	async function downloadAllMissing() {
		const missing = similarTracks.filter(t => !t.in_library);
		if (!missing.length) return;
		try {
			await fetch('/api/download/bulk', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tracks: missing.map(t => ({ artist: t.artist, track: t.name })) }) });
			addToast(`Downloading ${missing.length} tracks`, 'success');
		} catch { addToast('Bulk download failed', 'error'); }
	}

	// Artist detail
	async function openArtist(artist) {
		selectedArtist = artist;
		try {
			const [albumsRes, tracksRes] = await Promise.all([
				api.getAlbums({ artist_id: artist.id, limit: 100 }),
				api.getTracks({ artist_id: artist.id, limit: 100, sort: 'title', order: 'asc' }),
			]);
			artistAlbums = albumsRes.albums;
			artistTracks = tracksRes.tracks;
		} catch { artistAlbums = []; artistTracks = []; }
	}

	// Album detail — filter tracks
	async function openAlbum(album) {
		tab = 'tracks';
		search = '';
		offset = 0;
		loading = true;
		try {
			const result = await api.getTracks({ album_id: album.id, limit: 100, sort: 'track_number', order: 'asc' });
			tracks = result.tracks;
			trackTotal = result.total;
		} catch (e) { console.error(e); } finally { loading = false; }
	}
</script>

<div class="max-w-7xl">
	<PageHeader title="Library" color="var(--color-library)">
		<Button variant="primary" size="sm" loading={scanning} onclick={scanLibrary}>
			<ScanLine class="w-3.5 h-3.5" />
			{scanning ? 'Scanning...' : 'Scan'}
		</Button>
	</PageHeader>

	<!-- Tabs -->
	<div class="flex items-center gap-1 mb-4 border-b border-[var(--border-subtle)]">
		{#each tabs as t}
			{@const Icon = t.icon}
			<button onclick={() => switchTab(t.id)}
				class="flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px
					{tab === t.id
						? 'border-[var(--color-library)] text-[var(--text-primary)]'
						: 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}">
				<Icon class="w-4 h-4" />
				{t.label}
			</button>
		{/each}

		<div class="flex-1"></div>

		<!-- Search -->
		<div class="relative hidden sm:block">
			<Search class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--text-disabled)]" />
			<input type="text" placeholder="Search..."
				bind:value={search} oninput={debouncedSearch}
				class="bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md pl-8 pr-3 py-1.5 text-sm w-48
					placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
		</div>

		<!-- View toggle -->
		<div class="flex border border-[var(--border-subtle)] rounded-md overflow-hidden ml-2">
			<button onclick={() => viewMode = 'grid'}
				class="p-1.5 transition-colors {viewMode === 'grid' ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}">
				<Grid3x3 class="w-4 h-4" />
			</button>
			<button onclick={() => viewMode = 'list'}
				class="p-1.5 transition-colors {viewMode === 'list' ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}">
				<List class="w-4 h-4" />
			</button>
		</div>
	</div>

	<!-- Mobile search -->
	<div class="sm:hidden mb-4">
		<div class="relative">
			<Search class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--text-disabled)]" />
			<input type="text" placeholder="Search..." bind:value={search} oninput={debouncedSearch}
				class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md pl-8 pr-3 py-2 text-sm
					placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
		</div>
	</div>

	<!-- Select mode bar (tracks only) -->
	{#if tab === 'tracks' && selectMode}
		<div class="flex items-center gap-3 mb-3 px-1">
			<span class="text-sm text-[var(--text-secondary)] font-medium">{selected.size} selected</span>
			<Button variant="secondary" size="sm" onclick={toggleSelectAll}>
				{selected.size === tracks.length ? 'Deselect All' : 'Select All'}
			</Button>
			{#if selected.size > 0}
				<Button variant="danger" size="sm" onclick={bulkDelete}>
					<Trash2 class="w-3.5 h-3.5" /> Delete
				</Button>
				<Button variant="primary" size="sm" onclick={bulkAnalyze}>
					<ScanLine class="w-3.5 h-3.5" /> Analyze
				</Button>
			{/if}
			<div class="flex-1"></div>
			<Button variant="secondary" size="sm" onclick={toggleSelectMode}>Cancel</Button>
		</div>
	{/if}

	<!-- TRACKS TAB -->
	{#if tab === 'tracks'}
		{#if loading}
			<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
				{#each Array(12) as _}
					<div class="animate-pulse">
						<div class="aspect-square bg-[var(--bg-secondary)] rounded-lg mb-2"></div>
						<Skeleton class="h-3 w-3/4 mb-1" />
						<Skeleton class="h-2.5 w-1/2" />
					</div>
				{/each}
			</div>
		{:else if tracks.length}
			{#if viewMode === 'grid'}
				<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
					{#each tracks as track}
						<button class="group text-left transition-all"
							onclick={() => selectMode ? toggleSelect(track.id) : playTrack(track)}>
							<div class="relative aspect-square bg-[var(--bg-secondary)] rounded-lg overflow-hidden mb-2 border border-[var(--border-subtle)]
								{selectMode && selected.has(track.id) ? 'ring-2 ring-[var(--color-accent)]' : ''}">
								{#if coverUrl(track.cover_art)}
									<img src={coverUrl(track.cover_art)} alt="" class="w-full h-full object-cover" loading="lazy"
										onerror={(e) => { e.target.style.display = 'none'; e.target.nextElementSibling.style.display = 'flex'; }} />
									<div class="hidden items-center justify-center w-full h-full absolute inset-0 bg-[var(--bg-secondary)]">
										<Music class="w-8 h-8 text-[var(--text-disabled)]" />
									</div>
								{:else}
									<div class="flex items-center justify-center w-full h-full">
										<Music class="w-8 h-8 text-[var(--text-disabled)]" />
									</div>
								{/if}
								<div class="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center">
									<Play class="w-10 h-10 text-white opacity-0 group-hover:opacity-100 transition-opacity drop-shadow-lg" />
								</div>
								{#if track.format}
									<div class="absolute top-1.5 right-1.5">
										<span class="text-[9px] font-mono font-bold uppercase px-1.5 py-0.5 rounded bg-black/60 text-white/80">{track.format}</span>
									</div>
								{/if}
								{#if selectMode}
									<div class="absolute top-1.5 left-1.5">
										<div class="w-5 h-5 rounded border-2 flex items-center justify-center
											{selected.has(track.id) ? 'bg-[var(--color-accent)] border-[var(--color-accent)]' : 'border-white/60 bg-black/30'}">
											{#if selected.has(track.id)}
												<svg class="w-3 h-3 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>
											{/if}
										</div>
									</div>
								{/if}
							</div>
							<p class="text-sm font-medium text-[var(--text-primary)] truncate">{track.title}</p>
							<p class="text-xs text-[var(--text-muted)] truncate">{track.artist || 'Unknown'}</p>
						</button>
					{/each}
				</div>
			{:else}
				<!-- List view -->
				<Card padding="p-0">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-left">
								{#if selectMode}
									<th class="px-3 py-2.5 w-10">
										<input type="checkbox" checked={selected.size === tracks.length && tracks.length > 0}
											onchange={toggleSelectAll} class="rounded cursor-pointer" />
									</th>
								{/if}
								<th class="px-3 py-2.5 w-10"></th>
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider cursor-pointer hover:text-[var(--text-body)]" onclick={() => toggleSort('title')}>Title</th>
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider hidden md:table-cell">Artist</th>
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider hidden lg:table-cell">Album</th>
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider hidden lg:table-cell w-16">Time</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-[var(--border-subtle)]">
							{#each tracks as track}
								<tr class="hover:bg-[var(--bg-hover)] cursor-pointer transition-colors group"
									onclick={() => selectMode ? toggleSelect(track.id) : playTrack(track)}>
									{#if selectMode}
										<td class="px-3 py-2 w-10">
											<input type="checkbox" checked={selected.has(track.id)}
												onclick={(e) => { e.stopPropagation(); toggleSelect(track.id); }} class="rounded cursor-pointer" />
										</td>
									{/if}
									<td class="px-3 py-2 w-10">
										<div class="w-8 h-8 rounded bg-[var(--bg-secondary)] overflow-hidden flex-shrink-0">
											{#if coverUrl(track.cover_art)}
												<img src={coverUrl(track.cover_art)} alt="" class="w-full h-full object-cover" loading="lazy" />
											{:else}
												<div class="flex items-center justify-center w-full h-full"><Music class="w-4 h-4 text-[var(--text-disabled)]" /></div>
											{/if}
										</div>
									</td>
									<td class="px-3 py-2">
										<p class="font-medium text-[var(--text-primary)] truncate max-w-xs">{track.title}</p>
										<p class="text-xs text-[var(--text-muted)] md:hidden truncate">{track.artist || '-'}</p>
									</td>
									<td class="px-3 py-2 text-[var(--text-secondary)] hidden md:table-cell truncate max-w-[200px]">{track.artist || '-'}</td>
									<td class="px-3 py-2 text-[var(--text-muted)] hidden lg:table-cell truncate max-w-[200px]">{track.album || '-'}</td>
									<td class="px-3 py-2 text-[var(--text-muted)] font-mono text-xs hidden lg:table-cell">{formatDuration(track.duration)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</Card>
			{/if}

			{#if !selectMode}
				<div class="flex justify-end mt-2">
					<Button variant="secondary" size="sm" onclick={toggleSelectMode}>
						<CheckSquare class="w-3.5 h-3.5" /> Select
					</Button>
				</div>
			{/if}
		{:else}
			<EmptyState title="No tracks found" description={search ? 'Try a different search term.' : 'Scan your library to import tracks.'}>
				{#snippet icon()}<Music class="w-10 h-10" />{/snippet}
			</EmptyState>
		{/if}

	<!-- ARTISTS TAB -->
	{:else if tab === 'artists'}
		{#if selectedArtist}
			<button onclick={() => { selectedArtist = null; }} class="flex items-center gap-1 text-sm text-[var(--text-muted)] hover:text-[var(--text-primary)] mb-4 transition-colors">
				<ChevronLeft class="w-4 h-4" /> Back to Artists
			</button>
			<div class="flex items-center gap-4 mb-6">
				<div class="w-20 h-20 rounded-full bg-[var(--bg-secondary)] overflow-hidden border border-[var(--border-subtle)] flex-shrink-0">
					{#if coverUrl(selectedArtist.cover_art)}
						<img src={coverUrl(selectedArtist.cover_art)} alt="" class="w-full h-full object-cover" />
					{:else}
						<div class="flex items-center justify-center w-full h-full"><Users class="w-8 h-8 text-[var(--text-disabled)]" /></div>
					{/if}
				</div>
				<div>
					<h2 class="text-xl font-bold text-[var(--text-primary)]">{selectedArtist.name}</h2>
					<p class="text-sm text-[var(--text-muted)]">{selectedArtist.track_count} track{selectedArtist.track_count !== 1 ? 's' : ''} &middot; {artistAlbums.length} album{artistAlbums.length !== 1 ? 's' : ''}</p>
				</div>
			</div>

			{#if artistAlbums.length}
				<h3 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">Albums</h3>
				<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
					{#each artistAlbums as album}
						<button class="group text-left" onclick={() => openAlbum(album)}>
							<div class="relative aspect-square bg-[var(--bg-secondary)] rounded-lg overflow-hidden mb-2 border border-[var(--border-subtle)]">
								{#if coverUrl(album.cover_art)}
									<img src={coverUrl(album.cover_art)} alt="" class="w-full h-full object-cover" loading="lazy" />
								{:else}
									<div class="flex items-center justify-center w-full h-full"><Disc3 class="w-8 h-8 text-[var(--text-disabled)]" /></div>
								{/if}
								<div class="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors"></div>
							</div>
							<p class="text-sm font-medium text-[var(--text-primary)] truncate">{album.title}</p>
							<p class="text-xs text-[var(--text-muted)]">{album.year || ''} &middot; {album.track_count} tracks</p>
						</button>
					{/each}
				</div>
			{/if}

			{#if artistTracks.length}
				<h3 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">Tracks</h3>
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each artistTracks as track, i}
							<button class="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--bg-hover)] transition-colors text-left" onclick={() => playTrack(track)}>
								<span class="text-xs text-[var(--text-disabled)] font-mono w-6 text-right">{i + 1}</span>
								<div class="w-8 h-8 rounded bg-[var(--bg-secondary)] overflow-hidden flex-shrink-0">
									{#if coverUrl(track.cover_art)}
										<img src={coverUrl(track.cover_art)} alt="" class="w-full h-full object-cover" loading="lazy" />
									{:else}
										<div class="flex items-center justify-center w-full h-full"><Music class="w-3 h-3 text-[var(--text-disabled)]" /></div>
									{/if}
								</div>
								<div class="flex-1 min-w-0">
									<p class="text-sm font-medium text-[var(--text-primary)] truncate">{track.title}</p>
									<p class="text-xs text-[var(--text-muted)] truncate">{track.album || ''}</p>
								</div>
								<span class="text-xs text-[var(--text-muted)] font-mono">{formatDuration(track.duration)}</span>
							</button>
						{/each}
					</div>
				</Card>
			{/if}
		{:else if loading}
			<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
				{#each Array(12) as _}
					<div class="animate-pulse">
						<div class="aspect-square bg-[var(--bg-secondary)] rounded-full mb-2"></div>
						<Skeleton class="h-3 w-3/4 mx-auto mb-1" />
						<Skeleton class="h-2.5 w-1/2 mx-auto" />
					</div>
				{/each}
			</div>
		{:else if artists.length}
			{#if viewMode === 'grid'}
				<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
					{#each artists as artist}
						<button class="group text-center" onclick={() => openArtist(artist)}>
							<div class="relative aspect-square bg-[var(--bg-secondary)] rounded-full overflow-hidden mb-2 border border-[var(--border-subtle)] mx-auto
								group-hover:border-[var(--color-accent)]/50 transition-colors">
								{#if coverUrl(artist.cover_art)}
									<img src={coverUrl(artist.cover_art)} alt="" class="w-full h-full object-cover" loading="lazy"
										onerror={(e) => { e.target.style.display = 'none'; e.target.nextElementSibling.style.display = 'flex'; }} />
									<div class="hidden items-center justify-center w-full h-full absolute inset-0 bg-[var(--bg-secondary)]">
										<Users class="w-8 h-8 text-[var(--text-disabled)]" />
									</div>
								{:else}
									<div class="flex items-center justify-center w-full h-full">
										<Users class="w-8 h-8 text-[var(--text-disabled)]" />
									</div>
								{/if}
							</div>
							<p class="text-sm font-medium text-[var(--text-primary)] truncate">{artist.name}</p>
							<p class="text-xs text-[var(--text-muted)]">{artist.track_count} track{artist.track_count !== 1 ? 's' : ''}</p>
						</button>
					{/each}
				</div>
			{:else}
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each artists as artist}
							<button class="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-hover)] transition-colors text-left" onclick={() => openArtist(artist)}>
								<div class="w-10 h-10 rounded-full bg-[var(--bg-secondary)] overflow-hidden flex-shrink-0">
									{#if coverUrl(artist.cover_art)}
										<img src={coverUrl(artist.cover_art)} alt="" class="w-full h-full object-cover" loading="lazy" />
									{:else}
										<div class="flex items-center justify-center w-full h-full"><Users class="w-4 h-4 text-[var(--text-disabled)]" /></div>
									{/if}
								</div>
								<div class="flex-1 min-w-0">
									<p class="text-sm font-medium text-[var(--text-primary)]">{artist.name}</p>
								</div>
								<span class="text-xs text-[var(--text-muted)] font-mono">{artist.track_count} tracks</span>
							</button>
						{/each}
					</div>
				</Card>
			{/if}
		{:else}
			<EmptyState title="No artists found" description={search ? 'Try a different search term.' : 'Scan your library to populate artists.'}>
				{#snippet icon()}<Users class="w-10 h-10" />{/snippet}
			</EmptyState>
		{/if}

	<!-- ALBUMS TAB -->
	{:else if tab === 'albums'}
		{#if loading}
			<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
				{#each Array(12) as _}
					<div class="animate-pulse">
						<div class="aspect-square bg-[var(--bg-secondary)] rounded-lg mb-2"></div>
						<Skeleton class="h-3 w-3/4 mb-1" />
						<Skeleton class="h-2.5 w-1/2" />
					</div>
				{/each}
			</div>
		{:else if albums.length}
			{#if viewMode === 'grid'}
				<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
					{#each albums as album}
						<button class="group text-left" onclick={() => openAlbum(album)}>
							<div class="relative aspect-square bg-[var(--bg-secondary)] rounded-lg overflow-hidden mb-2 border border-[var(--border-subtle)]">
								{#if coverUrl(album.cover_art)}
									<img src={coverUrl(album.cover_art)} alt="" class="w-full h-full object-cover" loading="lazy"
										onerror={(e) => { e.target.style.display = 'none'; e.target.nextElementSibling.style.display = 'flex'; }} />
									<div class="hidden items-center justify-center w-full h-full absolute inset-0 bg-[var(--bg-secondary)]">
										<Disc3 class="w-8 h-8 text-[var(--text-disabled)]" />
									</div>
								{:else}
									<div class="flex items-center justify-center w-full h-full">
										<Disc3 class="w-8 h-8 text-[var(--text-disabled)]" />
									</div>
								{/if}
								<div class="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors"></div>
								{#if album.year}
									<div class="absolute top-1.5 right-1.5">
										<span class="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-black/60 text-white/80">{album.year}</span>
									</div>
								{/if}
							</div>
							<p class="text-sm font-medium text-[var(--text-primary)] truncate">{album.title}</p>
							<p class="text-xs text-[var(--text-muted)] truncate">{album.artist || 'Various'} &middot; {album.track_count} tracks</p>
						</button>
					{/each}
				</div>
			{:else}
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each albums as album}
							<button class="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-hover)] transition-colors text-left" onclick={() => openAlbum(album)}>
								<div class="w-10 h-10 rounded bg-[var(--bg-secondary)] overflow-hidden flex-shrink-0">
									{#if coverUrl(album.cover_art)}
										<img src={coverUrl(album.cover_art)} alt="" class="w-full h-full object-cover" loading="lazy" />
									{:else}
										<div class="flex items-center justify-center w-full h-full"><Disc3 class="w-4 h-4 text-[var(--text-disabled)]" /></div>
									{/if}
								</div>
								<div class="flex-1 min-w-0">
									<p class="text-sm font-medium text-[var(--text-primary)] truncate">{album.title}</p>
									<p class="text-xs text-[var(--text-muted)] truncate">{album.artist || 'Various'}</p>
								</div>
								<div class="text-right flex-shrink-0">
									{#if album.year}<span class="text-xs text-[var(--text-muted)] font-mono">{album.year}</span>{/if}
									<p class="text-xs text-[var(--text-disabled)]">{album.track_count} tracks</p>
								</div>
							</button>
						{/each}
					</div>
				</Card>
			{/if}
		{:else}
			<EmptyState title="No albums found" description={search ? 'Try a different search term.' : 'Scan your library to populate albums.'}>
				{#snippet icon()}<Disc3 class="w-10 h-10" />{/snippet}
			</EmptyState>
		{/if}
	{/if}

	<!-- Pagination -->
	{#if currentTotal > limit}
		<div class="flex justify-center items-center gap-3 mt-4">
			<Button variant="secondary" size="sm" disabled={offset === 0} onclick={prevPage}>
				<ChevronLeft class="w-4 h-4" /> Prev
			</Button>
			<span class="text-sm text-[var(--text-muted)] font-mono">
				{offset + 1}-{Math.min(offset + limit, currentTotal)} of {currentTotal}
			</span>
			<Button variant="secondary" size="sm" disabled={offset + limit >= currentTotal} onclick={nextPage}>
				Next <ChevronRight class="w-4 h-4" />
			</Button>
		</div>
	{/if}
</div>

<!-- Similar Tracks Modal -->
<Modal bind:open={showSimilar} title="Find Similar">
	{#snippet children()}
		{#if similarSource}
			<p class="text-sm text-[var(--text-secondary)] mb-3">{similarSource.title} - {similarSource.artist}</p>
		{/if}
		<div class="flex gap-1 mb-4">
			<button onclick={() => switchSimilarTab('lastfm')}
				class="px-3 py-1 rounded-md text-xs font-medium transition-colors
					{similarTab === 'lastfm' ? 'bg-[var(--color-accent)] text-white' : 'bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-white'}">
				Last.fm
			</button>
			<button onclick={() => switchSimilarTab('vibe')}
				class="px-3 py-1 rounded-md text-xs font-medium transition-colors
					{similarTab === 'vibe' ? 'bg-purple-600 text-white' : 'bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-white'}">
				Vibe Match
			</button>
		</div>
		{#if similarLoading}
			<div class="space-y-2 py-4">{#each Array(5) as _}<Skeleton class="h-10 rounded" />{/each}</div>
		{:else if similarTracks.length}
			<div class="space-y-1">
				{#each similarTracks as t}
					<div class="flex items-center justify-between px-3 py-2 rounded-md hover:bg-[var(--bg-hover)] text-sm transition-colors">
						<div class="flex-1 min-w-0">
							<span class="font-medium text-[var(--text-primary)]">{t.name}</span>
							<span class="text-[var(--text-secondary)]"> - {t.artist}</span>
						</div>
						<div class="flex items-center gap-2 ml-3 shrink-0">
							{#if t.match != null}
								<span class="text-xs text-[var(--text-muted)] font-mono">{Math.round((t.match || 0) * 100)}%</span>
							{/if}
							{#if t.in_library}
								<Badge variant="success">In Library</Badge>
							{:else}
								<Button variant="success" size="sm" onclick={() => downloadSimilar(t)}>
									<Download class="w-3 h-3" /> Get
								</Button>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{:else}
			<p class="text-[var(--text-muted)] text-center py-8 text-sm">
				{similarTab === 'vibe' ? 'No vibe embeddings. Run audio analysis first.' : 'No similar tracks found.'}
			</p>
		{/if}
	{/snippet}
	{#snippet footer()}
		{#if similarTracks.some(t => !t.in_library)}
			<div class="flex items-center justify-between">
				<span class="text-xs text-[var(--text-muted)]">{similarTracks.filter(t => !t.in_library).length} not in library</span>
				<Button variant="success" size="sm" onclick={downloadAllMissing}>
					<Download class="w-3 h-3" /> Download All Missing
				</Button>
			</div>
		{/if}
	{/snippet}
</Modal>
