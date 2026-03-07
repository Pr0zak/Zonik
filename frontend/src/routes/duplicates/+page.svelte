<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import { formatSize, formatRelativeTime, formatDateTime } from '$lib/utils.js';
	import {
		Copy, Play, Search, Download, Trash2, Check, Loader2,
		ChevronDown, ChevronUp, Heart, Music, AlertTriangle, HardDrive, Clock
	} from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import Modal from '../../components/ui/Modal.svelte';
	import StarRating from '../../components/ui/StarRating.svelte';

	let loading = $state(true);
	let data = $state(null);
	let selected = $state(new Set());
	let executing = $state(false);
	let expandedGroups = $state(new Set());
	let confirmModal = $state(null); // null | 'db' | 'files'

	const FORMAT_COLORS = {
		flac: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
		wav: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
		alac: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
		aiff: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
		opus: 'text-blue-400 bg-blue-500/15 border-blue-500/30',
		ogg: 'text-blue-300 bg-blue-500/10 border-blue-500/20',
		m4a: 'text-amber-400 bg-amber-500/15 border-amber-500/30',
		mp3: 'text-amber-300 bg-amber-500/10 border-amber-500/20',
		aac: 'text-orange-400 bg-orange-500/15 border-orange-500/30',
		wma: 'text-red-400 bg-red-500/15 border-red-500/30',
	};

	function formatBadgeClass(fmt) {
		return FORMAT_COLORS[fmt?.toLowerCase()] || 'text-[var(--text-muted)] bg-[var(--bg-tertiary)] border-[var(--border-subtle)]';
	}

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
				<Skeleton class="h-40 rounded-lg" />
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
				<span class="text-sm text-[var(--text-secondary)] font-medium">{selected.size} selected</span>
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
							<img src="/rest/getCoverArt?id={group.tracks[0].album_id}&size=56" alt=""
								class="w-12 h-12 rounded object-cover flex-shrink-0 bg-[var(--bg-tertiary)]"
								onerror={(e) => e.target.style.display='none'} />
						{:else}
							<div class="w-12 h-12 rounded bg-[var(--bg-tertiary)] flex items-center justify-center flex-shrink-0">
								<Music class="w-6 h-6 text-[var(--text-disabled)]" />
							</div>
						{/if}
						<div class="flex-1 min-w-0">
							<p class="text-base font-semibold text-[var(--text-primary)] truncate">{group.artist} — {group.title}</p>
							<p class="text-sm text-[var(--text-muted)]">{group.count} copies</p>
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
						<div class="border-t border-[var(--border-subtle)] divide-y divide-[var(--border-primary)]">
							{#each group.tracks as track}
								{@const qpct = qualityPercent(track.quality_score, maxQuality)}
								<div class="px-4 py-3 transition-colors
									{track.is_best ? 'bg-emerald-500/5' : selected.has(track.id) ? 'bg-red-500/5' : 'hover:bg-[var(--bg-hover)]'}">

									<!-- Row 1: Main info -->
									<div class="flex items-center gap-3">
										<!-- Checkbox / BEST badge -->
										<div class="w-14 flex-shrink-0 flex justify-center">
											{#if track.is_best}
												<span class="text-[11px] font-bold text-emerald-400 bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.5 rounded-full uppercase tracking-wide">Best</span>
											{:else}
												<input type="checkbox" checked={selected.has(track.id)}
													onchange={() => toggleTrack(track.id)}
													class="w-4.5 h-4.5 rounded accent-red-500 cursor-pointer" />
											{/if}
										</div>

										<!-- Cover art -->
										{#if track.album_id}
											<img src="/rest/getCoverArt?id={track.album_id}&size=44" alt=""
												class="w-11 h-11 rounded object-cover flex-shrink-0 bg-[var(--bg-tertiary)]"
												onerror={(e) => e.target.style.display='none'} />
										{:else}
											<div class="w-11 h-11 rounded bg-[var(--bg-tertiary)] flex items-center justify-center flex-shrink-0">
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

										<!-- Format badge -->
										<span class="text-xs font-mono font-semibold px-2.5 py-1 rounded border {formatBadgeClass(track.format)} flex-shrink-0">
											{track.format?.toUpperCase() || '?'}
										</span>

										<!-- Bitrate -->
										<div class="text-right flex-shrink-0 min-w-[65px]">
											{#if track.bitrate}
												<p class="text-sm text-[var(--text-secondary)] font-mono">{Math.round(track.bitrate / 1000)}k</p>
											{:else}
												<p class="text-sm text-[var(--text-disabled)]">—</p>
											{/if}
										</div>

										<!-- File size -->
										<div class="flex-shrink-0 min-w-[65px] text-right">
											<p class="text-sm text-[var(--text-secondary)] font-mono">
												{track.file_size ? formatSize(track.file_size) : '—'}
											</p>
										</div>

										<!-- Quality bar -->
										<div class="flex items-center gap-2 flex-shrink-0 min-w-[100px]">
											<div class="w-16 h-2 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
												<div class="h-full rounded-full transition-all {qualityBarColor(qpct)}" style="width: {qpct}%"></div>
											</div>
											<span class="text-xs text-[var(--text-muted)] font-mono w-6 text-right">{track.quality_score}</span>
										</div>

										<!-- Actions -->
										<div class="flex items-center gap-0.5 flex-shrink-0">
											<button onclick={() => playTrack(track)} class="p-1.5 hover:bg-white/10 rounded transition-colors" title="Play">
												<Play class="w-4 h-4 text-[var(--text-secondary)]" />
											</button>
											<button onclick={() => findUpgrade(track)} class="p-1.5 hover:bg-white/10 rounded transition-colors" title="Find upgrade on Soulseek">
												<Download class="w-4 h-4 text-[var(--text-secondary)]" />
											</button>
											{#if track.is_favorite}
												<Heart class="w-4 h-4 text-red-400 fill-red-400 ml-1" />
											{/if}
										</div>
									</div>

									<!-- Row 2: Secondary details -->
									<div class="flex items-center gap-4 mt-2 ml-[6.75rem] text-xs text-[var(--text-muted)]">
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
