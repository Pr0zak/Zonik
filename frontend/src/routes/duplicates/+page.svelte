<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import { formatSize, formatRelativeTime, formatDateTime } from '$lib/utils.js';
	import {
		Copy, Play, Search, Download, Trash2, Check, Loader2,
		ChevronDown, ChevronUp, Star, Heart, Music, AlertTriangle
	} from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import Modal from '../../components/ui/Modal.svelte';

	let loading = $state(true);
	let data = $state(null);
	let selected = $state(new Set());
	let executing = $state(false);
	let expandedGroups = $state(new Set());
	let confirmModal = $state(null); // null | 'db' | 'files'

	const FORMAT_COLORS = {
		flac: 'text-emerald-400 bg-emerald-500/15',
		wav: 'text-emerald-300 bg-emerald-500/10',
		alac: 'text-emerald-300 bg-emerald-500/10',
		aiff: 'text-emerald-300 bg-emerald-500/10',
		opus: 'text-blue-400 bg-blue-500/15',
		ogg: 'text-blue-300 bg-blue-500/10',
		m4a: 'text-amber-400 bg-amber-500/15',
		mp3: 'text-amber-300 bg-amber-500/10',
		aac: 'text-orange-400 bg-orange-500/15',
		wma: 'text-red-400 bg-red-500/15',
	};

	function formatBadgeClass(fmt) {
		return FORMAT_COLORS[fmt?.toLowerCase()] || 'text-[var(--text-muted)] bg-[var(--bg-tertiary)]';
	}

	function qualityPercent(score, maxScore) {
		if (!maxScore) return 0;
		return Math.min(100, Math.round((score / maxScore) * 100));
	}

	function qualityColor(pct) {
		if (pct >= 80) return 'bg-emerald-500';
		if (pct >= 60) return 'bg-amber-500';
		if (pct >= 40) return 'bg-orange-500';
		return 'bg-red-500';
	}

	async function loadDuplicates() {
		loading = true;
		try {
			data = await api.getDuplicates();
			// Auto-select all non-best tracks
			selected = new Set(
				(data.groups || []).flatMap(g => g.tracks.filter(t => !t.is_best).map(t => t.id))
			);
			// Expand all groups by default
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

	function toggleTrack(id) {
		const s = new Set(selected);
		s.has(id) ? s.delete(id) : s.add(id);
		selected = s;
	}

	function selectAllInferior() {
		selected = new Set(
			(data?.groups || []).flatMap(g => g.tracks.filter(t => !t.is_best).map(t => t.id))
		);
	}

	function deselectAll() {
		selected = new Set();
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

	// Compute max quality score across all tracks for relative bar widths
	let maxQuality = $derived(
		data?.groups
			? Math.max(...data.groups.flatMap(g => g.tracks.map(t => t.quality_score || 0)), 1)
			: 1
	);

	onMount(loadDuplicates);
</script>

<div class="px-6 py-5 max-w-7xl mx-auto">
	<PageHeader title="Duplicates" icon={Copy} color="var(--color-duplicates)"
		subtitle={data ? `${data.total_groups} group${data.total_groups !== 1 ? 's' : ''} \u00b7 ${data.total_duplicates} extra file${data.total_duplicates !== 1 ? 's' : ''} \u00b7 ${formatSize(data.reclaimable_bytes)} reclaimable` : ''} />

	{#if loading}
		<div class="space-y-4 mt-4">
			{#each Array(3) as _}
				<Skeleton class="h-32 rounded-lg" />
			{/each}
		</div>
	{:else if !data?.groups?.length}
		<div class="mt-8">
			<EmptyState icon={Check} title="No duplicates" message="Your library has no duplicate tracks." />
		</div>
	{:else}
		<!-- Action bar -->
		<div class="flex items-center justify-between mt-4 mb-3 sticky top-0 z-10 bg-[var(--bg-primary)] py-2 border-b border-[var(--border-subtle)]">
			<div class="flex items-center gap-3">
				<span class="text-sm text-[var(--text-secondary)]">{selected.size} selected</span>
				<button onclick={selectAllInferior} class="text-xs text-[var(--color-accent)] hover:underline">Select All Inferior</button>
				<button onclick={deselectAll} class="text-xs text-[var(--text-muted)] hover:underline">Deselect All</button>
			</div>
			<div class="flex items-center gap-2">
				{#if selected.size > 0}
					<Button variant="warning" size="sm" onclick={() => confirmModal = 'db'}>
						<Trash2 class="w-3.5 h-3.5 mr-1" /> Remove from DB
					</Button>
					<Button variant="danger" size="sm" onclick={() => confirmModal = 'files'}>
						<Trash2 class="w-3.5 h-3.5 mr-1" /> Remove + Delete Files
					</Button>
				{/if}
			</div>
		</div>

		<!-- Duplicate groups -->
		<div class="space-y-3">
			{#each data.groups as group, gi}
				<Card padding="p-0" class="border border-[var(--border-subtle)] overflow-hidden">
					<!-- Group header -->
					<button onclick={() => toggleGroup(gi)}
						class="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-hover)] transition-colors text-left">
						{#if group.tracks[0]?.album_id}
							<img src="/rest/getCoverArt?id={group.tracks[0].album_id}&size=48" alt=""
								class="w-10 h-10 rounded object-cover flex-shrink-0 bg-[var(--bg-tertiary)]"
								onerror={(e) => e.target.style.display='none'} />
						{:else}
							<div class="w-10 h-10 rounded bg-[var(--bg-tertiary)] flex items-center justify-center flex-shrink-0">
								<Music class="w-5 h-5 text-[var(--text-disabled)]" />
							</div>
						{/if}
						<div class="flex-1 min-w-0">
							<p class="text-sm font-medium text-[var(--text-primary)] truncate">{group.artist} — {group.title}</p>
							<p class="text-xs text-[var(--text-muted)]">{group.count} copies</p>
						</div>
						<Badge variant="warning">{group.count} versions</Badge>
						{#if expandedGroups.has(gi)}
							<ChevronUp class="w-4 h-4 text-[var(--text-muted)] flex-shrink-0" />
						{:else}
							<ChevronDown class="w-4 h-4 text-[var(--text-muted)] flex-shrink-0" />
						{/if}
					</button>

					<!-- Expanded track list -->
					{#if expandedGroups.has(gi)}
						<div class="border-t border-[var(--border-subtle)]">
							{#each group.tracks as track, ti}
								{@const qpct = qualityPercent(track.quality_score, maxQuality)}
								<div class="flex items-center gap-3 px-4 py-2.5 border-b border-[var(--border-primary)] last:border-b-0
									{track.is_best ? 'bg-emerald-500/5' : selected.has(track.id) ? 'bg-red-500/5' : 'hover:bg-[var(--bg-hover)]'} transition-colors">

									<!-- Checkbox (not for best) -->
									<div class="w-5 flex-shrink-0">
										{#if track.is_best}
											<span class="text-[10px] font-bold text-emerald-400">BEST</span>
										{:else}
											<input type="checkbox" checked={selected.has(track.id)}
												onchange={() => toggleTrack(track.id)}
												class="w-4 h-4 rounded accent-red-500 cursor-pointer" />
										{/if}
									</div>

									<!-- Cover art -->
									{#if track.album_id}
										<img src="/rest/getCoverArt?id={track.album_id}&size=36" alt=""
											class="w-9 h-9 rounded object-cover flex-shrink-0 bg-[var(--bg-tertiary)]"
											onerror={(e) => e.target.style.display='none'} />
									{:else}
										<div class="w-9 h-9 rounded bg-[var(--bg-tertiary)] flex-shrink-0"></div>
									{/if}

									<!-- Track info -->
									<div class="flex-1 min-w-0 grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-x-3 items-center">
										<!-- Title + album -->
										<div class="min-w-0">
											<p class="text-sm text-[var(--text-primary)] truncate">{track.title}</p>
											{#if track.album}
												<p class="text-[11px] text-[var(--text-muted)] truncate">{track.album}</p>
											{/if}
										</div>

										<!-- Format badge -->
										<span class="text-[10px] font-mono px-1.5 py-0.5 rounded {formatBadgeClass(track.format)} flex-shrink-0">
											{track.format?.toUpperCase() || '?'}
										</span>

										<!-- Bitrate + technical -->
										<div class="text-right flex-shrink-0 min-w-[70px]">
											{#if track.bitrate}
												<p class="text-xs text-[var(--text-secondary)] font-mono">{Math.round(track.bitrate / 1000)}kbps</p>
											{/if}
											{#if track.bit_depth && track.sample_rate}
												<p class="text-[10px] text-[var(--text-disabled)] font-mono">{track.bit_depth}bit/{Math.round(track.sample_rate / 1000)}kHz</p>
											{/if}
										</div>

										<!-- File size -->
										<span class="text-xs text-[var(--text-muted)] font-mono flex-shrink-0 min-w-[55px] text-right">
											{track.file_size ? formatSize(track.file_size) : '—'}
										</span>

										<!-- Quality bar -->
										<div class="flex items-center gap-1.5 flex-shrink-0 min-w-[80px]">
											<div class="w-12 h-1.5 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
												<div class="h-full rounded-full transition-all {qualityColor(qpct)}" style="width: {qpct}%"></div>
											</div>
											<span class="text-[10px] text-[var(--text-disabled)] font-mono w-6">{track.quality_score}</span>
										</div>

										<!-- Play count + rating -->
										<div class="flex items-center gap-2 flex-shrink-0">
											{#if track.play_count > 0}
												<span class="text-[10px] text-[var(--text-disabled)]" title="Play count">
													{track.play_count} plays
												</span>
											{/if}
											{#if track.is_favorite}
												<Heart class="w-3 h-3 text-red-400 fill-red-400" />
											{/if}
										</div>
									</div>

									<!-- Actions -->
									<div class="flex items-center gap-1 flex-shrink-0">
										<button onclick={() => playTrack(track)} class="p-1.5 hover:bg-white/10 rounded transition-colors" title="Play">
											<Play class="w-3.5 h-3.5 text-[var(--text-secondary)]" />
										</button>
										<button onclick={() => findUpgrade(track)} class="p-1.5 hover:bg-white/10 rounded transition-colors" title="Find upgrade on Soulseek">
											<Download class="w-3.5 h-3.5 text-[var(--text-secondary)]" />
										</button>
									</div>
								</div>

								<!-- File path row -->
								<div class="px-4 pb-1.5 -mt-1 ml-[3.75rem]">
									<p class="text-[10px] text-[var(--text-disabled)] font-mono truncate" title={track.file_path}>
										{track.file_path}
									</p>
									{#if track.created_at}
										<span class="text-[10px] text-[var(--text-disabled)]" title={formatDateTime(track.created_at)}>
											Added {formatRelativeTime(track.created_at)}
										</span>
									{/if}
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
	<Modal title="Confirm Removal" onclose={() => confirmModal = null}>
		<div class="space-y-3">
			<div class="flex items-start gap-2 p-3 rounded bg-amber-500/10 border border-amber-500/30">
				<AlertTriangle class="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
				<div>
					<p class="text-sm text-[var(--text-primary)]">
						{confirmModal === 'files'
							? `This will remove ${selected.size} track${selected.size !== 1 ? 's' : ''} from the database AND delete the files from disk.`
							: `This will remove ${selected.size} track${selected.size !== 1 ? 's' : ''} from the database. Files will remain on disk.`}
					</p>
					<p class="text-xs text-[var(--text-muted)] mt-1">This action cannot be undone.</p>
				</div>
			</div>
			<div class="flex justify-end gap-2">
				<Button variant="secondary" size="sm" onclick={() => confirmModal = null}>Cancel</Button>
				<Button variant={confirmModal === 'files' ? 'danger' : 'warning'} size="sm"
					disabled={executing}
					onclick={() => executeRemoval(confirmModal === 'files')}>
					{#if executing}<Loader2 class="w-3 h-3 animate-spin mr-1" />{/if}
					{confirmModal === 'files' ? 'Delete Files' : 'Remove from DB'}
				</Button>
			</div>
		</div>
	</Modal>
{/if}
