<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api.js';
	import FormatBadge from '../../components/ui/FormatBadge.svelte';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import { formatSize, formatRelativeTime, formatDateTime } from '$lib/utils.js';
	import {
		Copy, Play, Search, Download, Trash2, Check, Loader2, Filter,
		ChevronDown, ChevronUp, Heart, Music, AlertTriangle, HardDrive, Clock,
		ChevronsDown, ChevronsUp, Zap, ArrowDownUp, Layers, Star, Sparkles
	} from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import Modal from '../../components/ui/Modal.svelte';
	import StarRating from '../../components/ui/StarRating.svelte';
	import StatTile from '../../components/ui/StatTile.svelte';
	import FilterPills from '../../components/ui/FilterPills.svelte';
	import Toolbar from '../../components/ui/Toolbar.svelte';

	let loading = $state(true);
	let data = $state(null);
	let selected = $state(new Set());
	let executing = $state(false);
	let expandedGroups = $state(new Set());
	let confirmModal = $state(null); // null | 'db' | 'files' | 'auto-db' | 'auto-files'
	let sortBy = $state('space');
	let filterBy = $state('all');
	let searchQuery = $state('');

	function qualityPercent(score, maxScore) {
		if (!maxScore) return 0;
		return Math.min(100, Math.round((score / maxScore) * 100));
	}

	function qualityBarColor(pct) {
		if (pct >= 80) return 'bg-emerald-500';
		if (pct >= 60) return 'bg-amber-500';
		if (pct >= 40) return 'bg-orange-500';
		return 'bg-red-500';
	}

	async function loadDuplicates() {
		loading = true;
		try {
			data = await api.getDuplicates();
			selected = new Set(
				(data.groups || []).flatMap(g => g.tracks.filter(t => !t.is_best).map(t => t.id))
			);
			expandedGroups = new Set((data.groups || []).map((_, i) => i));
		} catch (e) {
			addToast('Failed to load duplicates', 'error');
		} finally {
			loading = false;
		}
	}

	function toggleGroup(idx) {
		const s = new Set(expandedGroups);
		s.has(idx) ? s.delete(idx) : s.add(idx);
		expandedGroups = s;
	}

	function expandAll() {
		expandedGroups = new Set(displayGroups.map((_, i) => i));
	}

	function collapseAll() {
		expandedGroups = new Set();
	}

	function toggleTrack(id) {
		const s = new Set(selected);
		s.has(id) ? s.delete(id) : s.add(id);
		selected = s;
	}

	function selectAllInferior() {
		selected = new Set(
			(data?.groups || []).flatMap(g => g.tracks.filter(t => !t.is_best && !t.is_favorite).map(t => t.id))
		);
	}

	function deselectAll() {
		selected = new Set();
	}

	function autoResolve() {
		const ids = (data?.groups || []).flatMap(g =>
			g.tracks.filter(t => !t.is_best && !t.is_favorite).map(t => t.id)
		);
		selected = new Set(ids);
		confirmModal = 'auto';
	}

	let aiResolveLoading = $state(false);
	let aiRecommendations = $state(null);

	async function aiResolve() {
		aiResolveLoading = true;
		try {
			const data = await api.aiResolveDuplicates();
			if (data.error) { addToast(data.error, 'error'); return; }
			aiRecommendations = data.recommendations || [];
			if (!aiRecommendations.length) { addToast('No AI recommendations', 'info'); return; }
			// Auto-select AI-recommended removals
			const removeIds = new Set(aiRecommendations.flatMap(r => r.remove_ids || []));
			selected = removeIds;
			addToast(`AI suggests removing ${removeIds.size} tracks`, 'success');
		} catch (e) { addToast('AI resolve failed: ' + e.message, 'error'); }
		finally { aiResolveLoading = false; }
	}

	function findUpgrade(track) {
		goto(`/downloads?artist=${encodeURIComponent(track.artist)}&track=${encodeURIComponent(track.title)}`);
	}

	function playTrack(track) {
		storePlayTrack({
			id: track.id,
			title: track.title,
			artist: track.artist,
			album: track.album,
			album_id: track.album_id,
		});
	}

	async function executeRemoval(deleteFiles = false) {
		const removeIds = [...selected];
		if (!removeIds.length) return;
		executing = true;
		try {
			const result = await api.removeDuplicates(removeIds, deleteFiles);
			addToast(
				`Removed ${result.removed} duplicate${result.removed !== 1 ? 's' : ''}${deleteFiles ? `, deleted ${result.files_deleted} file${result.files_deleted !== 1 ? 's' : ''}` : ''}`,
				'success'
			);
			confirmModal = null;
			await loadDuplicates();
		} catch {
			addToast('Removal failed', 'error');
		} finally {
			executing = false;
		}
	}

	// --- Computed stats ---
	let stats = $derived.by(() => {
		const groups = data?.groups || [];
		if (!groups.length) return null;
		const formatMismatches = groups.filter(g => g.best_format !== g.worst_format).length;
		const largestGroup = Math.max(...groups.map(g => g.count));
		return {
			totalGroups: groups.length,
			totalExtra: data.total_duplicates,
			reclaimable: data.reclaimable_bytes,
			formatMismatches,
			largestGroup,
		};
	});

	// --- Sort + Filter ---
	function sortGroups(groups, sort) {
		const sorted = [...groups];
		switch (sort) {
			case 'space':
				sorted.sort((a, b) => {
					const aSpace = a.tracks.filter(t => !t.is_best).reduce((s, t) => s + (t.file_size || 0), 0);
					const bSpace = b.tracks.filter(t => !t.is_best).reduce((s, t) => s + (t.file_size || 0), 0);
					return bSpace - aSpace;
				});
				break;
			case 'copies':
				sorted.sort((a, b) => b.count - a.count);
				break;
			case 'gap':
				sorted.sort((a, b) => {
					const aGap = (a.tracks[0]?.quality_score || 0) - (a.tracks[a.tracks.length - 1]?.quality_score || 0);
					const bGap = (b.tracks[0]?.quality_score || 0) - (b.tracks[b.tracks.length - 1]?.quality_score || 0);
					return bGap - aGap;
				});
				break;
			case 'artist':
				sorted.sort((a, b) => a.artist.localeCompare(b.artist));
				break;
			case 'recent':
				sorted.sort((a, b) => {
					const aMax = Math.max(...a.tracks.map(t => t.created_at ? new Date(t.created_at).getTime() : 0));
					const bMax = Math.max(...b.tracks.map(t => t.created_at ? new Date(t.created_at).getTime() : 0));
					return bMax - aMax;
				});
				break;
		}
		return sorted;
	}

	function filterGroups(groups, filter) {
		switch (filter) {
			case 'format_mismatch':
				return groups.filter(g => g.best_format !== g.worst_format);
			case 'same_format':
				return groups.filter(g => g.best_format === g.worst_format);
			case 'has_favorites':
				return groups.filter(g => g.tracks.some(t => t.is_favorite));
			default:
				return groups;
		}
	}

	let displayGroups = $derived.by(() => {
		let groups = data?.groups || [];
		if (searchQuery.trim()) {
			const q = searchQuery.trim().toLowerCase();
			groups = groups.filter(g =>
				g.artist.toLowerCase().includes(q) || g.title.toLowerCase().includes(q)
			);
		}
		groups = filterGroups(groups, filterBy);
		groups = sortGroups(groups, sortBy);
		return groups;
	});

	let maxQuality = $derived(
		data?.groups
			? Math.max(...data.groups.flatMap(g => g.tracks.map(t => t.quality_score || 0)), 1)
			: 1
	);

	// Count selected favorites for warning
	let selectedFavCount = $derived.by(() => {
		if (!data?.groups) return 0;
		const allTracks = data.groups.flatMap(g => g.tracks);
		return allTracks.filter(t => selected.has(t.id) && t.is_favorite).length;
	});

	let selectedTotalSize = $derived.by(() => {
		if (!data?.groups) return 0;
		const allTracks = data.groups.flatMap(g => g.tracks);
		return allTracks.filter(t => selected.has(t.id)).reduce((s, t) => s + (t.file_size || 0), 0);
	});

	onMount(loadDuplicates);
</script>

<div class="px-3 sm:px-6 py-5 max-w-7xl mx-auto">
	<PageHeader title="Duplicates" icon={Copy} color="var(--color-duplicates)"
		subtitle={data ? `${data.total_groups} group${data.total_groups !== 1 ? 's' : ''} \u00b7 ${data.total_duplicates} extra file${data.total_duplicates !== 1 ? 's' : ''} \u00b7 ${formatSize(data.reclaimable_bytes)} reclaimable` : ''} />

	{#if loading}
		<div class="space-y-4 mt-4">
			<Skeleton class="h-40 rounded-lg" />
			<Skeleton class="h-40 rounded-lg" />
			<Skeleton class="h-40 rounded-lg" />
		</div>
	{:else if !data?.groups?.length}
		<div class="mt-8">
			<EmptyState title="No duplicates" description="Your library has no duplicate tracks.">
				{#snippet icon()}<Check class="w-12 h-12" />{/snippet}
			</EmptyState>
		</div>
	{:else}
		<!-- Stats Bar -->
		{#if stats}
			<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mt-4">
				<StatTile label="Groups" value={stats.totalGroups} color="#fbbf24" />
				<StatTile label="Extra Files" value={stats.totalExtra} color="#f87171" />
				<StatTile label="Reclaimable" value={formatSize(stats.reclaimable)} color="#34d399" />
				<StatTile label="Format Mismatches" value={stats.formatMismatches} color="#c084fc" />
				<StatTile label="Largest Group" value="{stats.largestGroup} copies" color="#60a5fa" />
			</div>
		{/if}

		<Toolbar>
			{#snippet row1Left()}
				<FilterPills
					options={[
						{ value: 'all', label: 'All', color: 'duplicates' },
						{ value: 'format_mismatch', label: 'Format Mismatch', color: 'duplicates' },
						{ value: 'same_format', label: 'Same Format', color: 'duplicates' },
						{ value: 'has_favorites', label: 'Has Favorites', color: 'duplicates' },
					]}
					value={filterBy}
					onchange={(v) => filterBy = v}
					variant="outline"
				/>
			{/snippet}
			{#snippet row1Right()}
				<div class="relative flex-1 sm:flex-none">
					<Search class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
					<input type="text" bind:value={searchQuery} placeholder="Search..."
						class="pl-8 pr-3 py-1.5 text-xs rounded-md bg-[var(--surface-lowest)] text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] w-full sm:w-36 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20" />
				</div>
				<select bind:value={sortBy}
					class="text-xs rounded-md bg-[var(--surface-lowest)] text-[var(--text-secondary)] px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20">
					<option value="space">Reclaimable Space</option>
					<option value="copies">Most Copies</option>
					<option value="gap">Quality Gap</option>
					<option value="artist">Artist A-Z</option>
					<option value="recent">Recently Added</option>
				</select>
			{/snippet}
			{#snippet row2Left()}
				<span class="text-[var(--text-secondary)] font-medium">{selected.size} selected</span>
				<button onclick={selectAllInferior} class="text-[var(--color-accent)] hover:underline whitespace-nowrap">Select Inferior</button>
				<button onclick={deselectAll} class="text-[var(--text-muted)] hover:underline whitespace-nowrap">Deselect</button>
				<span class="text-[var(--text-disabled)] hidden sm:inline">&middot;</span>
				<button onclick={expandAll} class="text-[var(--text-secondary)] hover:underline flex items-center gap-0.5 whitespace-nowrap">
					<ChevronsDown class="w-3 h-3" /> Expand
				</button>
				<button onclick={collapseAll} class="text-[var(--text-secondary)] hover:underline flex items-center gap-0.5 whitespace-nowrap">
					<ChevronsUp class="w-3 h-3" /> Collapse
				</button>
			{/snippet}
			{#snippet row2Right()}
				<Button variant="secondary" size="sm" loading={aiResolveLoading} onclick={aiResolve}>
					<Sparkles class="w-3.5 h-3.5 mr-1 text-amber-400" /> AI Resolve
				</Button>
				<Button variant="primary" size="sm" onclick={autoResolve}>
					<Zap class="w-3.5 h-3.5 mr-1" /> Auto-Resolve
				</Button>
				{#if selected.size > 0}
					<Button variant="warning" size="sm" onclick={() => confirmModal = 'db'}>
						<Trash2 class="w-3.5 h-3.5 mr-1" /> Remove
					</Button>
					<Button variant="danger" size="sm" onclick={() => confirmModal = 'files'}>
						<Trash2 class="w-3.5 h-3.5 mr-1" /> Delete Files
					</Button>
				{/if}
			{/snippet}
		</Toolbar>

		<!-- Results count -->
		{#if displayGroups.length !== (data?.groups?.length || 0)}
			<p class="text-xs text-[var(--text-muted)] mb-2">Showing {displayGroups.length} of {data.groups.length} groups</p>
		{/if}

		<!-- Duplicate groups -->
		<div class="space-y-3">
			{#each displayGroups as group, gi}
				<Card padding="p-0" class="overflow-hidden">
					<!-- Group header -->
					<button onclick={() => toggleGroup(gi)}
						class="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--surface-container-high)] transition-colors text-left">
						{#if group.tracks[0]?.album_id}
							<img src="/rest/getCoverArt?id={group.tracks[0].album_id}&size=56" alt=""
								class="w-12 h-12 rounded object-cover flex-shrink-0 bg-[var(--surface-container)]"
								onerror={(e) => e.target.style.display='none'} />
						{:else}
							<div class="w-12 h-12 rounded bg-[var(--surface-container)] flex items-center justify-center flex-shrink-0">
								<Music class="w-6 h-6 text-[var(--text-disabled)]" />
							</div>
						{/if}
						<div class="flex-1 min-w-0">
							<p class="text-base font-semibold text-[var(--text-primary)] truncate">{group.artist} — {group.title}</p>
							<p class="text-sm text-[var(--text-muted)]">
								{group.count} copies
								{#if group.best_format && group.worst_format && group.best_format !== group.worst_format}
									<span class="mx-1.5 text-[var(--text-disabled)]">&middot;</span>
									<span class="font-mono text-xs">
										<span class="text-emerald-400">{group.best_format.toUpperCase()}{#if group.best_bitrate} {Math.round(group.best_bitrate / 1000)}k{/if}</span>
										<span class="text-[var(--text-disabled)]"> vs </span>
										<span class="text-red-400">{group.worst_format.toUpperCase()}{#if group.worst_bitrate} {Math.round(group.worst_bitrate / 1000)}k{/if}</span>
									</span>
								{:else if group.best_bitrate && group.worst_bitrate && group.best_bitrate > group.worst_bitrate * 2}
									<span class="mx-1.5 text-[var(--text-disabled)]">&middot;</span>
									<span class="font-mono text-xs">
										<span class="text-emerald-400">{Math.round(group.best_bitrate / 1000)}k</span>
										<span class="text-[var(--text-disabled)]"> vs </span>
										<span class="text-red-400">{Math.round(group.worst_bitrate / 1000)}k</span>
									</span>
								{/if}
							</p>
						</div>
						<Badge variant="warning">{group.count} versions</Badge>
						{#if expandedGroups.has(gi)}
							<ChevronUp class="w-5 h-5 text-[var(--text-muted)] flex-shrink-0" />
						{:else}
							<ChevronDown class="w-5 h-5 text-[var(--text-muted)] flex-shrink-0" />
						{/if}
					</button>

					<!-- Expanded track list -->
					{#if expandedGroups.has(gi)}
						<div>
							{#each group.tracks as track}
								{@const qpct = qualityPercent(track.quality_score, maxQuality)}
								<div class="px-4 py-3 transition-colors
									{track.is_best ? 'bg-emerald-500/5' : selected.has(track.id) ? (track.is_favorite ? 'bg-amber-500/5 border-l-2 border-l-amber-500' : 'bg-red-500/5') : 'hover:bg-[var(--surface-container-high)]'}">

									<!-- Row 1: Main info -->
									<div class="flex items-center gap-2 sm:gap-3 flex-wrap sm:flex-nowrap">
										<!-- Checkbox / BEST badge -->
										<div class="w-10 sm:w-14 flex-shrink-0 flex justify-center">
											{#if track.is_best}
												<span class="text-xs font-bold text-emerald-400 bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.5 rounded-full uppercase tracking-wide">Best</span>
											{:else}
												<input type="checkbox" checked={selected.has(track.id)}
													onchange={() => toggleTrack(track.id)}
													class="w-4.5 h-4.5 rounded accent-red-500 cursor-pointer" />
											{/if}
										</div>

										<!-- Cover art -->
										{#if track.album_id}
											<img src="/rest/getCoverArt?id={track.album_id}&size=44" alt=""
												class="w-10 h-10 sm:w-11 sm:h-11 rounded object-cover flex-shrink-0 bg-[var(--surface-container)]"
												onerror={(e) => e.target.style.display='none'} />
										{:else}
											<div class="w-10 h-10 sm:w-11 sm:h-11 rounded bg-[var(--surface-container)] flex items-center justify-center flex-shrink-0">
												<Music class="w-5 h-5 text-[var(--text-disabled)]" />
											</div>
										{/if}

										<!-- Title + Album -->
										<div class="flex-1 min-w-0">
											<p class="text-sm font-medium text-[var(--text-primary)] truncate">{track.title}</p>
											{#if track.album}
												<p class="text-xs text-[var(--text-muted)] truncate">{track.album}</p>
											{/if}
										</div>

										<FormatBadge format={track.format} class="flex-shrink-0 px-2.5 py-1" />

										<!-- Bitrate -->
										<div class="text-right flex-shrink-0 min-w-[50px] hidden sm:block">
											{#if track.bitrate}
												<p class="text-sm text-[var(--text-secondary)] font-mono">{Math.round(track.bitrate / 1000)}k</p>
											{:else}
												<p class="text-sm text-[var(--text-disabled)]">—</p>
											{/if}
										</div>

										<!-- File size -->
										<div class="flex-shrink-0 min-w-[50px] text-right hidden sm:block">
											<p class="text-sm text-[var(--text-secondary)] font-mono">
												{track.file_size ? formatSize(track.file_size) : '—'}
											</p>
										</div>

										<!-- Quality bar -->
										<div class="flex items-center gap-2 flex-shrink-0 hidden md:flex min-w-[100px]">
											<div class="w-16 h-2 bg-[var(--surface-container)] rounded-full overflow-hidden">
												<div class="h-full rounded-full transition-all {qualityBarColor(qpct)}" style="width: {qpct}%"></div>
											</div>
											<span class="text-xs text-[var(--text-muted)] font-mono w-6 text-right">{track.quality_score}</span>
										</div>

										<!-- Actions -->
										<div class="flex items-center gap-0.5 flex-shrink-0">
											<button onclick={() => playTrack(track)} class="p-2 min-w-[44px] min-h-[44px] sm:p-1.5 sm:min-w-0 sm:min-h-0 flex items-center justify-center hover:bg-white/10 rounded transition-colors" title="Play">
												<Play class="w-4 h-4 text-[var(--text-secondary)]" />
											</button>
											<button onclick={() => findUpgrade(track)} class="p-2 min-w-[44px] min-h-[44px] sm:p-1.5 sm:min-w-0 sm:min-h-0 flex items-center justify-center hover:bg-white/10 rounded transition-colors" title="Find upgrade on Soulseek">
												<Download class="w-4 h-4 text-[var(--text-secondary)]" />
											</button>
											{#if track.is_favorite}
												<Heart class="w-4 h-4 text-red-400 fill-red-400 ml-1" />
											{/if}
										</div>
									</div>

									<!-- Favorite warning when selected -->
									{#if !track.is_best && track.is_favorite && selected.has(track.id)}
										<div class="flex items-center gap-1.5 mt-1.5 ml-0 sm:ml-[6.75rem] text-xs text-amber-400">
											<AlertTriangle class="w-3 h-3" />
											This track is favorited
										</div>
									{/if}

									<!-- Row 2: Secondary details -->
									<div class="flex items-center gap-4 mt-2 ml-0 sm:ml-[6.75rem] text-xs text-[var(--text-muted)] overflow-x-auto">
										<!-- File path -->
										<span class="font-mono truncate flex-1 min-w-0" title={track.file_path}>
											{track.file_path}
										</span>

										<!-- Technical specs -->
										{#if track.bit_depth && track.sample_rate}
											<span class="flex-shrink-0 font-mono text-[var(--text-disabled)]">
												{track.bit_depth}bit / {Math.round(track.sample_rate / 1000)}kHz
											</span>
										{/if}

										<!-- Play count -->
										{#if track.play_count > 0}
											<span class="flex items-center gap-1 flex-shrink-0">
												<Play class="w-3 h-3" />
												{track.play_count} play{track.play_count !== 1 ? 's' : ''}
											</span>
										{/if}

										<!-- Rating -->
										{#if track.rating}
											<span class="flex-shrink-0" onclick={(e) => e.stopPropagation()}>
												<StarRating rating={track.rating} size="xs" />
											</span>
										{/if}

										<!-- Added date -->
										{#if track.created_at}
											<span class="flex items-center gap-1 flex-shrink-0" title={formatDateTime(track.created_at)}>
												<Clock class="w-3 h-3" />
												{formatRelativeTime(track.created_at)}
											</span>
										{/if}
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</Card>
			{/each}
		</div>
	{/if}
</div>

<!-- Confirmation Modal -->
{#if confirmModal}
	<Modal title={confirmModal === 'auto' ? 'Auto-Resolve Duplicates' : 'Confirm Removal'} onclose={() => confirmModal = null}>
		<div class="space-y-3">
			<div class="flex items-start gap-2 p-3 rounded bg-amber-500/10 border border-amber-500/30">
				<AlertTriangle class="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
				<div>
					{#if confirmModal === 'auto'}
						<p class="text-sm text-[var(--text-primary)]">
							This will remove <span class="font-bold">{selected.size}</span> non-best track{selected.size !== 1 ? 's' : ''} across all groups, keeping the best quality version{selectedFavCount > 0 ? '' : ' and all favorited tracks'}.
						</p>
					{:else}
						<p class="text-sm text-[var(--text-primary)]">
							{confirmModal === 'files'
								? `This will remove ${selected.size} track${selected.size !== 1 ? 's' : ''} from the database AND delete the files from disk.`
								: `This will remove ${selected.size} track${selected.size !== 1 ? 's' : ''} from the database. Files will remain on disk.`}
						</p>
					{/if}
					{#if selectedFavCount > 0}
						<p class="text-xs text-amber-400 mt-1 flex items-center gap-1">
							<Heart class="w-3 h-3 fill-amber-400" />
							Includes {selectedFavCount} favorited track{selectedFavCount !== 1 ? 's' : ''}
						</p>
					{/if}
					<p class="text-xs text-[var(--text-muted)] mt-1">
						Space to reclaim: <span class="font-mono text-[var(--text-secondary)]">{formatSize(selectedTotalSize)}</span>
					</p>
					<p class="text-xs text-[var(--text-muted)] mt-0.5">This action cannot be undone.</p>
				</div>
			</div>
			<div class="flex justify-end gap-2">
				<Button variant="secondary" size="sm" onclick={() => confirmModal = null}>Cancel</Button>
				{#if confirmModal === 'auto'}
					<Button variant="warning" size="sm" disabled={executing} onclick={() => executeRemoval(false)}>
						{#if executing}<Loader2 class="w-3 h-3 animate-spin mr-1" />{/if}
						Remove from DB
					</Button>
					<Button variant="danger" size="sm" disabled={executing} onclick={() => executeRemoval(true)}>
						{#if executing}<Loader2 class="w-3 h-3 animate-spin mr-1" />{/if}
						Remove + Delete Files
					</Button>
				{:else}
					<Button variant={confirmModal === 'files' ? 'danger' : 'warning'} size="sm"
						disabled={executing}
						onclick={() => executeRemoval(confirmModal === 'files')}>
						{#if executing}<Loader2 class="w-3 h-3 animate-spin mr-1" />{/if}
						{confirmModal === 'files' ? 'Delete Files' : 'Remove from DB'}
					</Button>
				{/if}
			</div>
		</div>
	</Modal>
{/if}
