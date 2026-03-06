<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { api } from '$lib/api.js';
	import { currentTrack, addToast, activeJobs, playTrack as storePlayTrack } from '$lib/stores.js';
	import { formatDuration, formatSize, formatRelativeTime, formatDateTime, debounce } from '$lib/utils.js';
	import {
		Search, ScanLine, Download, Music, Users, Disc3,
		Play, ChevronLeft, ChevronRight, Grid3x3, List, Trash2, CheckSquare, Heart,
		MoreVertical, Pencil, AudioWaveform, ShieldBan, Clock,
		FileSearch, Copy, FolderTree, Eye, Loader2, AlertTriangle, X, Check, RotateCcw
	} from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import Modal from '../../components/ui/Modal.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import ScheduleControl from '../../components/ui/ScheduleControl.svelte';
	import StarRating from '../../components/ui/StarRating.svelte';

	const tabs = [
		{ id: 'tracks', label: 'Tracks', icon: Music },
		{ id: 'artists', label: 'Artists', icon: Users },
		{ id: 'albums', label: 'Albums', icon: Disc3 },
	];

	let tab = $state('tracks');
	let search = $state('');
	let offset = $state(0);
	let limit = $state(24);
	const limitOptions = [24, 48, 96, 192];
	let loading = $state(true);
	let viewMode = $state('grid');

	// Tracks state
	let tracks = $state([]);
	let trackTotal = $state(0);
	let sort = $state('title');
	let order = $state('asc');
	let analyzedFilter = $state(''); // '', 'yes', 'no'
	let filterArtistId = $state('');
	let filterArtistName = $state('');
	let filterAlbumId = $state('');
	let filterAlbumName = $state('');

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

	// Schedule state
	let schedTasks = $state({});
	let schedRunning = $state({});

	async function toggleSched(name) {
		const t = schedTasks[name];
		if (!t) return;
		const newEnabled = !t.enabled;
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: newEnabled }) });
		schedTasks[name] = { ...t, enabled: newEnabled };
	}
	async function updateSched(name, updates) {
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updates) });
		schedTasks[name] = { ...schedTasks[name], ...updates };
	}
	async function runSched(name) {
		schedRunning[name] = true;
		try {
			await fetch(`/api/schedule/${name}/run`, { method: 'POST' });
			addToast('Task started', 'success');
		} catch { addToast('Failed to run task', 'error'); }
		finally { schedRunning[name] = false; }
	}

	// Cleanup state
	let cleanupTab = $state(null); // 'orphans' | 'duplicates' | 'organize'
	let cleanupLoading = $state(false);
	let cleanupPreview = $state(null);
	let cleanupExecuting = $state(false);
	let dedupSelected = $state(new Set()); // track IDs selected for removal
	let organizeSelected = $state(new Set()); // track IDs selected for organize

	async function previewCleanup(type) {
		cleanupTab = type;
		cleanupLoading = true;
		cleanupPreview = null;
		dedupSelected = new Set();
		organizeSelected = new Set();
		try {
			const res = await fetch(`/api/library/cleanup/${type}/preview`, { method: 'POST' });
			cleanupPreview = await res.json();
			if (type === 'duplicates' && cleanupPreview?.groups) {
				dedupSelected = new Set(cleanupPreview.groups.flatMap(g => g.remove.map(r => r.id)));
			}
			if (type === 'organize' && cleanupPreview?.moves) {
				organizeSelected = new Set(cleanupPreview.moves.map(m => m.track_id));
			}
		} catch (e) {
			addToast('Preview failed', 'error');
		} finally {
			cleanupLoading = false;
		}
	}

	function toggleDedupTrack(id) {
		const s = new Set(dedupSelected);
		if (s.has(id)) s.delete(id); else s.add(id);
		dedupSelected = s;
	}

	function toggleDedupAll() {
		if (!cleanupPreview?.groups) return;
		const allIds = cleanupPreview.groups.flatMap(g => g.remove.map(r => r.id));
		dedupSelected = dedupSelected.size === allIds.length ? new Set() : new Set(allIds);
	}

	function toggleOrganizeTrack(id) {
		const s = new Set(organizeSelected);
		if (s.has(id)) s.delete(id); else s.add(id);
		organizeSelected = s;
	}

	function toggleOrganizeAll() {
		if (!cleanupPreview?.moves) return;
		const allIds = cleanupPreview.moves.map(m => m.track_id);
		organizeSelected = organizeSelected.size === allIds.length ? new Set() : new Set(allIds);
	}

	async function executeOrphans() {
		cleanupExecuting = true;
		try {
			const res = await fetch('/api/library/cleanup/orphans', { method: 'POST' });
			const result = await res.json();
			addToast(`Removed ${result.removed} orphaned tracks`, 'success');
			cleanupPreview = null;
			cleanupTab = null;
			loadData();
		} catch { addToast('Cleanup failed', 'error'); }
		finally { cleanupExecuting = false; }
	}

	async function executeDuplicates(deleteFiles = false) {
		const removeIds = [...dedupSelected];
		if (!removeIds.length) return;
		cleanupExecuting = true;
		try {
			const res = await fetch('/api/library/cleanup/duplicates', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ remove_ids: removeIds, delete_files: deleteFiles }),
			});
			const result = await res.json();
			addToast(`Removed ${result.removed} duplicates${deleteFiles ? `, deleted ${result.files_deleted} files` : ''}`, 'success');
			cleanupPreview = null;
			cleanupTab = null;
			loadData();
		} catch { addToast('Dedup failed', 'error'); }
		finally { cleanupExecuting = false; }
	}

	async function executeOrganize() {
		const moveIds = [...organizeSelected];
		if (!moveIds.length) return;
		cleanupExecuting = true;
		try {
			const res = await fetch('/api/library/cleanup/organize', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ move_ids: moveIds }),
			});
			const result = await res.json();
			addToast(`Organized ${result.moved} files${result.errors ? `, ${result.errors} errors` : ''}`, 'success');
			cleanupPreview = null;
			cleanupTab = null;
			loadData();
		} catch { addToast('Organize failed', 'error'); }
		finally { cleanupExecuting = false; }
	}

	// Upgrade scanner state
	let showUpgrades = $state(false);
	let upgradeMode = $state('low_bitrate');
	let upgradeMaxBitrate = $state(256);
	let upgradeLimit = $state(100);
	let upgradeLoading = $state(false);
	let upgradeTracks = $state([]);
	let upgradeSelected = $state(new Set());
	let upgradeDownloading = $state(false);

	const upgradeModes = [
		{ value: 'low_bitrate', label: 'Low Bitrate', desc: 'Tracks below a bitrate threshold' },
		{ value: 'lossy_to_lossless', label: 'Lossy → Lossless', desc: 'All MP3/AAC/OGG tracks (upgrade to FLAC)' },
		{ value: 'all_lossy', label: 'All Lossy Formats', desc: 'Every non-lossless track in library' },
	];

	async function scanUpgrades() {
		upgradeLoading = true;
		upgradeTracks = [];
		upgradeSelected = new Set();
		try {
			const res = await fetch('/api/library/upgrades/scan', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ mode: upgradeMode, max_bitrate: upgradeMaxBitrate, limit: upgradeLimit }),
			});
			const data = await res.json();
			upgradeTracks = data.tracks || [];
		} catch { addToast('Scan failed', 'error'); }
		finally { upgradeLoading = false; }
	}

	function toggleUpgradeSelect(id) {
		const s = new Set(upgradeSelected);
		s.has(id) ? s.delete(id) : s.add(id);
		upgradeSelected = s;
	}

	function selectAllUpgrades() {
		if (upgradeSelected.size === upgradeTracks.length) {
			upgradeSelected = new Set();
		} else {
			upgradeSelected = new Set(upgradeTracks.map(t => t.id));
		}
	}

	async function downloadUpgrades() {
		const tracks = upgradeTracks.filter(t => upgradeSelected.has(t.id));
		if (!tracks.length) return;
		upgradeDownloading = true;
		try {
			const res = await fetch('/api/download/bulk', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ tracks: tracks.map(t => ({ artist: t.artist, track: t.title })) }),
			});
			const data = await res.json();
			addToast(`Upgrade download started (${tracks.length} tracks)`, 'success');
			showUpgrades = false;
		} catch { addToast('Download failed', 'error'); }
		finally { upgradeDownloading = false; }
	}

	// Select mode (tracks only)
	let selectMode = $state(false);
	let selected = $state(new Set());

	// Favorites
	let favTrackIds = $state(new Set());
	let favAlbumIds = $state(new Set());
	let favArtistIds = $state(new Set());

	async function loadFavoriteIds() {
		try {
			const ids = await api.getFavoriteIds();
			favTrackIds = new Set(ids.track_ids);
			favAlbumIds = new Set(ids.album_ids);
			favArtistIds = new Set(ids.artist_ids);
		} catch {}
	}

	async function toggleFav(type, id, e) {
		e?.stopPropagation();
		const setMap = { track: favTrackIds, album: favAlbumIds, artist: favArtistIds };
		const keyMap = { track: 'track_id', album: 'album_id', artist: 'artist_id' };
		const s = setMap[type];
		const isFav = s.has(id);
		try {
			if (isFav) {
				await api.unstar({ [keyMap[type]]: id });
				s.delete(id);
			} else {
				await api.star({ [keyMap[type]]: id });
				s.add(id);
			}
			// Trigger reactivity
			if (type === 'track') favTrackIds = new Set(favTrackIds);
			else if (type === 'album') favAlbumIds = new Set(favAlbumIds);
			else favArtistIds = new Set(favArtistIds);
		} catch { addToast('Failed to update favorite', 'error'); }
	}

	// Similar tracks modal
	let showSimilar = $state(false);
	let similarSource = $state(null);
	let similarTracks = $state([]);
	let similarLoading = $state(false);
	let similarTab = $state('lastfm');
	let similarDownloading = $state(new Set());

	// Remix discovery modal
	let showRemixes = $state(false);
	let remixSource = $state(null);
	let remixes = $state([]);
	let remixLoading = $state(false);
	let remixDownloadStatus = $state({}); // { "artist|name": "downloading"|"done"|"failed" }

	// Track action menu
	let menuTrack = $state(null);
	let menuPos = $state({ x: 0, y: 0 });

	function openMenu(track, e) {
		e.stopPropagation();
		const rect = e.currentTarget.getBoundingClientRect();
		menuPos = { x: rect.left, y: rect.bottom + 4 };
		menuTrack = track;
	}

	function closeMenu() { menuTrack = null; }

	async function deleteTrack(track) {
		closeMenu();
		if (!window.confirm(`Delete "${track.title}"? This cannot be undone.`)) return;
		try {
			await api.deleteTrack(track.id);
			addToast(`Deleted: ${track.title}`, 'success');
			await loadData();
		} catch (e) { addToast('Delete failed: ' + e.message, 'error'); }
	}

	async function blacklistArtist(track) {
		closeMenu();
		const artist = track.artist_name || 'Unknown';
		if (!window.confirm(`Blacklist artist "${artist}"? Future downloads for this artist will be blocked.`)) return;
		try {
			await api.addToBlacklist(artist);
			addToast(`Blacklisted: ${artist}`, 'success');
		} catch (e) { addToast('Blacklist failed: ' + e.message, 'error'); }
	}

	// Edit track modal
	let editTrack = $state(null);
	let showEdit = $state(false);
	let editForm = $state({ title: '', genre: '', year: '', track_number: '' });
	let editSaving = $state(false);

	$effect(() => {
		if (!showEdit) editTrack = null;
	});

	function openEdit(track) {
		closeMenu();
		editForm = {
			title: track.title || '',
			genre: track.genre || '',
			year: track.year || '',
			track_number: track.track_number || '',
		};
		editTrack = track;
		showEdit = true;
	}

	async function saveEdit() {
		if (!editTrack) return;
		editSaving = true;
		try {
			const data = {};
			if (editForm.title) data.title = editForm.title;
			if (editForm.genre) data.genre = editForm.genre;
			if (editForm.year) data.year = parseInt(editForm.year) || null;
			if (editForm.track_number) data.track_number = parseInt(editForm.track_number) || null;
			await api.updateTrack(editTrack.id, data);
			addToast('Track updated', 'success');
			showEdit = false;
			await loadData();
		} catch (e) { addToast('Update failed: ' + e.message, 'error'); }
		finally { editSaving = false; }
	}

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
				const result = await api.getTracks({ offset, limit, sort, order, search: search || undefined, analyzed: analyzedFilter || undefined, artist_id: filterArtistId || undefined, album_id: filterAlbumId || undefined });
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

	// React to URL search param changes (TopBar navigation, even if already on /library)
	$effect(() => {
		const searchParam = $page.url.searchParams.get('search');
		if (searchParam && searchParam !== search) {
			search = searchParam;
			viewMode = 'list';
			tab = 'tracks';
			offset = 0;
			loadData();
		}
	});

	onMount(async () => {
		// Handle search param on initial mount
		const searchParam = $page.url.searchParams.get('search');
		if (searchParam) {
			search = searchParam;
			viewMode = 'list';
		}
		await Promise.all([loadData(), loadFavoriteIds()]);
		try {
			const active = await api.getActiveJobs();
			if (active.some(j => j.type === 'library_scan')) scanTriggered = true;
		} catch (e) { console.error('Active jobs check failed:', e); }
		try {
			const tasks = await fetch('/api/schedule').then(r => r.json());
			for (const t of tasks) schedTasks[t.task_name] = t;
		} catch (e) { console.error('Schedule load failed:', e); }
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
		storePlayTrack(track, tracks);
	}

	function toggleSort(col) {
		if (sort === col) order = order === 'asc' ? 'desc' : 'asc';
		else { sort = col; order = (col === 'created_at' || col === 'play_count') ? 'desc' : 'asc'; }
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

	async function bulkFindUpgrades() {
		if (!selected.size) return;
		const selectedTracks = tracks.filter(t => selected.has(t.id));
		const items = selectedTracks.map(t => ({ artist: t.artist || '', track: t.title || '' }));
		try {
			const resp = await fetch('/api/download/bulk', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ tracks: items }),
			});
			const data = await resp.json();
			addToast(`Searching upgrades for ${items.length} track(s)`, 'success');
			selected = new Set();
			selectMode = false;
		} catch (e) { addToast('Find upgrades failed: ' + e.message, 'error'); }
	}

	// Similar tracks
	async function findSimilar(track, e) {
		e.stopPropagation();
		similarSource = track;
		showSimilar = true;
		similarTracks = [];
		similarLoading = true;
		similarTab = 'lastfm';
		similarDownloading = new Set();
		await loadSimilarLastfm();
	}
	async function loadSimilarLastfm() {
		if (!similarSource?.artist) { similarTracks = []; similarLoading = false; return; }
		similarLoading = true;
		try {
			const data = await api.getSimilarTracks(similarSource.artist, similarSource.title);
			similarTracks = data.tracks || [];
		} catch (e) { console.error('Similar tracks failed:', e); similarTracks = []; } finally { similarLoading = false; }
	}
	async function loadSimilarVibe() {
		if (!similarSource?.id) { similarTracks = []; similarLoading = false; return; }
		similarLoading = true;
		try {
			const data = await api.echoMatch(similarSource.id);
			similarTracks = (data.tracks || []).map(t => ({
				name: t.title, artist: t.artist, in_library: true, track_id: t.id, match: t.similarity,
			}));
		} catch (e) { console.error('Vibe match failed:', e); similarTracks = []; } finally { similarLoading = false; }
	}
	async function findRemixes(track) {
		remixSource = track;
		showRemixes = true;
		remixes = [];
		remixLoading = true;
		remixDownloadStatus = {};
		try {
			const data = await api.getRemixes(track.artist, track.title);
			remixes = data.remixes || [];
		} catch (e) { console.error('Remix search failed:', e); remixes = []; }
		remixLoading = false;
	}

	async function switchSimilarTab(t) {
		similarTab = t;
		if (t === 'lastfm') await loadSimilarLastfm(); else await loadSimilarVibe();
	}
	async function downloadSimilar(t) {
		const key = `${t.artist}::${t.name}`.toLowerCase();
		similarDownloading = new Set([...similarDownloading, key]);
		try {
			await fetch('/api/download/trigger', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ artist: t.artist, track: t.name }) });
			addToast(`Downloading ${t.name}`, 'success');
		} catch { addToast('Download failed', 'error'); similarDownloading.delete(key); similarDownloading = new Set(similarDownloading); }
	}
	async function downloadAllMissing() {
		const missing = similarTracks.filter(t => !t.in_library && !similarDownloading.has(`${t.artist}::${t.name}`.toLowerCase()));
		if (!missing.length) return;
		for (const t of missing) similarDownloading = new Set([...similarDownloading, `${t.artist}::${t.name}`.toLowerCase()]);
		let started = 0;
		for (const t of missing) {
			try {
				await fetch('/api/download/trigger', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ artist: t.artist, track: t.name }) });
				started++;
			} catch { /* individual failures tracked via WS */ }
		}
		addToast(`Queued ${started} downloads`, 'success');
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
		} catch (e) { console.error('Artist detail failed:', e); artistAlbums = []; artistTracks = []; addToast('Failed to load artist details', 'error'); }
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
		<Button variant="secondary" size="sm" onclick={() => { showUpgrades = !showUpgrades; if (showUpgrades && !upgradeTracks.length) scanUpgrades(); }}>
			<Download class="w-3.5 h-3.5" />
			Upgrade
		</Button>
		<Button variant="primary" size="sm" loading={scanning} onclick={scanLibrary}>
			<ScanLine class="w-3.5 h-3.5" />
			{scanning ? 'Scanning...' : 'Scan'}
		</Button>
	</PageHeader>

	<!-- Upgrade Scanner -->
	{#if showUpgrades}
		<Card padding="p-4" class="mb-4">
			<div class="flex items-center justify-between mb-3">
				<h3 class="text-sm font-semibold text-[var(--text-primary)]">Find Upgradeable Tracks</h3>
				<button onclick={() => showUpgrades = false} class="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
					<X class="w-4 h-4" />
				</button>
			</div>

			<!-- Options -->
			<div class="flex flex-wrap items-center gap-3 mb-3">
				<div class="flex items-center gap-2">
					<span class="text-xs text-[var(--text-muted)]">Mode:</span>
					<select class="bg-[var(--bg-tertiary)] text-[var(--text-body)] text-xs border border-[var(--border-primary)] rounded px-2 py-1" bind:value={upgradeMode} onchange={scanUpgrades}>
						{#each upgradeModes as m}
							<option value={m.value}>{m.label}</option>
						{/each}
					</select>
				</div>
				{#if upgradeMode === 'low_bitrate'}
					<div class="flex items-center gap-2">
						<span class="text-xs text-[var(--text-muted)]">Below:</span>
						<select class="bg-[var(--bg-tertiary)] text-[var(--text-body)] text-xs border border-[var(--border-primary)] rounded px-2 py-1" bind:value={upgradeMaxBitrate} onchange={scanUpgrades}>
							<option value={128}>128 kbps</option>
							<option value={192}>192 kbps</option>
							<option value={256}>256 kbps</option>
							<option value={320}>320 kbps</option>
						</select>
					</div>
				{/if}
				<div class="flex items-center gap-2">
					<span class="text-xs text-[var(--text-muted)]">Limit:</span>
					<select class="bg-[var(--bg-tertiary)] text-[var(--text-body)] text-xs border border-[var(--border-primary)] rounded px-2 py-1" bind:value={upgradeLimit} onchange={scanUpgrades}>
						<option value={25}>25</option>
						<option value={50}>50</option>
						<option value={100}>100</option>
						<option value={200}>200</option>
					</select>
				</div>
				<Button variant="secondary" size="sm" loading={upgradeLoading} onclick={scanUpgrades}>
					<Search class="w-3 h-3" /> Rescan
				</Button>
			</div>

			<p class="text-xs text-[var(--text-muted)] mb-3">
				{upgradeModes.find(m => m.value === upgradeMode)?.desc}
			</p>

			{#if upgradeLoading}
				<div class="flex items-center gap-2 py-4 text-[var(--text-muted)]">
					<Loader2 class="w-4 h-4 animate-spin" />
					<span class="text-sm">Scanning library...</span>
				</div>
			{:else if upgradeTracks.length}
				<div class="flex items-center justify-between mb-2">
					<div class="flex items-center gap-2">
						<button onclick={selectAllUpgrades} class="text-xs text-[var(--color-accent)] hover:underline">
							{upgradeSelected.size === upgradeTracks.length ? 'Deselect All' : 'Select All'}
						</button>
						<span class="text-xs text-[var(--text-muted)]">{upgradeSelected.size} selected</span>
					</div>
					{#if upgradeSelected.size > 0}
						<Button variant="primary" size="sm" loading={upgradeDownloading} onclick={downloadUpgrades}>
							<Download class="w-3 h-3" /> Download {upgradeSelected.size} Upgrade{upgradeSelected.size !== 1 ? 's' : ''}
						</Button>
					{/if}
				</div>
				<div class="max-h-80 overflow-y-auto border border-[var(--border-primary)] rounded-lg">
					<table class="w-full text-xs">
						<thead class="bg-[var(--bg-tertiary)] sticky top-0">
							<tr class="text-left text-[var(--text-muted)]">
								<th class="p-2 w-8"></th>
								<th class="p-2">Track</th>
								<th class="p-2">Artist</th>
								<th class="p-2 w-16">Format</th>
								<th class="p-2 w-20">Bitrate</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-[var(--border-subtle)]">
							{#each upgradeTracks as track}
								<tr class="hover:bg-[var(--bg-hover)] cursor-pointer" onclick={() => toggleUpgradeSelect(track.id)}>
									<td class="p-2">
										<input type="checkbox" checked={upgradeSelected.has(track.id)}
											class="rounded border-[var(--border-interactive)]" />
									</td>
									<td class="p-2 text-[var(--text-body)] truncate max-w-[200px]">{track.title}</td>
									<td class="p-2 text-[var(--text-muted)] truncate max-w-[150px]">{track.artist}</td>
									<td class="p-2">
										<Badge variant={track.format === 'flac' || track.format === 'wav' ? 'success' : 'default'}>
											{(track.format || '?').toUpperCase()}
										</Badge>
									</td>
									<td class="p-2 text-[var(--text-muted)] font-mono">
										{track.bitrate ? `${Math.round(track.bitrate / 1000)}k` : '—'}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<p class="text-sm text-emerald-400 py-2">No tracks found matching the upgrade criteria. Your library is already high quality!</p>
			{/if}
		</Card>
	{/if}

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

		<!-- Analyzed filter (tracks tab only) -->
		{#if tab === 'tracks'}
			<select class="bg-[var(--bg-tertiary)] text-[var(--text-body)] text-xs border border-[var(--border-primary)] rounded px-2 py-1 ml-2"
				value={analyzedFilter} onchange={(e) => { analyzedFilter = e.target.value; offset = 0; loadData(); }}>
				<option value="">All Tracks</option>
				<option value="no">Not Analyzed</option>
				<option value="yes">Analyzed</option>
			</select>
		{/if}

		<!-- Active filter pills -->
		{#if filterArtistId}
			<span class="inline-flex items-center gap-1 bg-[var(--bg-tertiary)] text-xs text-[var(--text-body)] border border-[var(--border-primary)] rounded px-2 py-1 ml-2">
				Artist: {filterArtistName}
				<button onclick={() => { filterArtistId = ''; filterArtistName = ''; offset = 0; loadData(); }} class="text-[var(--text-muted)] hover:text-white ml-0.5">
					<X class="w-3 h-3" />
				</button>
			</span>
		{/if}
		{#if filterAlbumId}
			<span class="inline-flex items-center gap-1 bg-[var(--bg-tertiary)] text-xs text-[var(--text-body)] border border-[var(--border-primary)] rounded px-2 py-1 ml-2">
				Album: {filterAlbumName}
				<button onclick={() => { filterAlbumId = ''; filterAlbumName = ''; offset = 0; loadData(); }} class="text-[var(--text-muted)] hover:text-white ml-0.5">
					<X class="w-3 h-3" />
				</button>
			</span>
		{/if}

		<!-- Per-page select -->
		<select class="bg-[var(--bg-tertiary)] text-[var(--text-body)] text-xs border border-[var(--border-primary)] rounded px-2 py-1 ml-2" value={limit} onchange={(e) => { limit = +e.target.value; offset = 0; loadData(); }}>
			{#each limitOptions as opt}
				<option value={opt}>{opt}/page</option>
			{/each}
		</select>

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

		<!-- Select mode toggle (tracks tab only) -->
		{#if tab === 'tracks' && !selectMode}
			<Button variant="secondary" size="sm" onclick={toggleSelectMode}>
				<CheckSquare class="w-3.5 h-3.5" /> Select
			</Button>
		{/if}
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
				<Button variant="success" size="sm" onclick={bulkFindUpgrades}>
					<Download class="w-3.5 h-3.5" /> Find Upgrades
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
						<div class="group text-left transition-all">
							<button class="w-full text-left" onclick={() => selectMode ? toggleSelect(track.id) : playTrack(track)}>
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
									{#if !track.analyzed}
										<div class="absolute bottom-1.5 left-1.5" title="Not analyzed">
											<AudioWaveform class="w-3.5 h-3.5 text-white/40" />
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
							</button>
							<div class="flex items-center justify-between gap-1">
								<p class="text-sm font-medium text-[var(--text-primary)] truncate flex-1">{track.title}</p>
								<button onclick={(e) => toggleFav('track', track.id, e)}
									class="p-0.5 flex-shrink-0 transition-colors {favTrackIds.has(track.id) ? 'text-red-400' : 'text-[var(--text-disabled)] hover:text-red-400'}">
									<Heart class="w-3.5 h-3.5" fill={favTrackIds.has(track.id) ? 'currentColor' : 'none'} />
								</button>
								<button onclick={(e) => openMenu(track, e)}
									class="p-0.5 flex-shrink-0 text-[var(--text-disabled)] hover:text-[var(--text-primary)] transition-colors">
									<MoreVertical class="w-3.5 h-3.5" />
								</button>
							</div>
							<p class="text-xs text-[var(--text-muted)] truncate">{track.artist || 'Unknown'}</p>
						</div>
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
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider cursor-pointer hover:text-[var(--text-body)]" onclick={() => toggleSort('title')}>Title {sort === 'title' ? (order === 'asc' ? '↑' : '↓') : ''}</th>
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider hidden md:table-cell cursor-pointer hover:text-[var(--text-body)]" onclick={() => toggleSort('artist_id')}>Artist {sort === 'artist_id' ? (order === 'asc' ? '↑' : '↓') : ''}</th>
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider hidden lg:table-cell">Album</th>
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider hidden xl:table-cell w-16 cursor-pointer hover:text-[var(--text-body)]" onclick={() => toggleSort('play_count')}>Plays {sort === 'play_count' ? (order === 'asc' ? '↑' : '↓') : ''}</th>
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider hidden xl:table-cell w-24 cursor-pointer hover:text-[var(--text-body)]" onclick={() => toggleSort('rating')}>Rating {sort === 'rating' ? (order === 'asc' ? '↑' : '↓') : ''}</th>
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider hidden xl:table-cell w-20 cursor-pointer hover:text-[var(--text-body)]" onclick={() => toggleSort('created_at')}>Added {sort === 'created_at' ? (order === 'asc' ? '↑' : '↓') : ''}</th>
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider hidden lg:table-cell w-12 cursor-pointer hover:text-[var(--text-body)]" onclick={() => toggleSort('analyzed')} title="Audio analysis status">
									<AudioWaveform class="w-3.5 h-3.5 inline" /> {sort === 'analyzed' ? (order === 'asc' ? '↑' : '↓') : ''}
								</th>
								<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider hidden lg:table-cell w-16">Time</th>
								<th class="px-3 py-2.5 w-10"></th>
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
										{#if track.artist_id}
											<button class="text-xs text-[var(--text-muted)] md:hidden truncate hover:text-[var(--color-accent)] hover:underline"
												onclick={(e) => { e.stopPropagation(); filterArtistId = track.artist_id; filterArtistName = track.artist; filterAlbumId = ''; filterAlbumName = ''; offset = 0; loadData(); }}>
												{track.artist || '-'}
											</button>
										{:else}
											<p class="text-xs text-[var(--text-muted)] md:hidden truncate">{track.artist || '-'}</p>
										{/if}
									</td>
									<td class="px-3 py-2 hidden md:table-cell truncate max-w-[200px]">
										{#if track.artist_id}
											<button class="text-[var(--text-secondary)] hover:text-[var(--color-accent)] hover:underline transition-colors text-left truncate max-w-full"
												onclick={(e) => { e.stopPropagation(); filterArtistId = track.artist_id; filterArtistName = track.artist; filterAlbumId = ''; filterAlbumName = ''; offset = 0; loadData(); }}>
												{track.artist || '-'}
											</button>
										{:else}
											<span class="text-[var(--text-secondary)]">{track.artist || '-'}</span>
										{/if}
									</td>
									<td class="px-3 py-2 hidden lg:table-cell truncate max-w-[200px]">
										{#if track.album_id}
											<button class="text-[var(--text-muted)] hover:text-[var(--color-accent)] hover:underline transition-colors text-left truncate max-w-full"
												onclick={(e) => { e.stopPropagation(); filterAlbumId = track.album_id; filterAlbumName = track.album; filterArtistId = ''; filterArtistName = ''; offset = 0; loadData(); }}>
												{track.album || '-'}
											</button>
										{:else}
											<span class="text-[var(--text-muted)]">{track.album || '-'}</span>
										{/if}
									</td>
									<td class="px-3 py-2 text-[var(--text-muted)] font-mono text-xs hidden xl:table-cell">{track.play_count || 0}</td>
									<td class="px-3 py-2 hidden xl:table-cell" onclick={(e) => e.stopPropagation()}>
										<StarRating rating={track.rating || 0} size="xs" onrate={async (r) => { await api.setRating(track.id, r); track.rating = r || null; }} />
									</td>
									<td class="px-3 py-2 text-[var(--text-muted)] text-xs hidden xl:table-cell" title={track.created_at ? formatDateTime(track.created_at) : ''}>{track.created_at ? formatRelativeTime(track.created_at) : '-'}</td>
									<td class="px-3 py-2 hidden lg:table-cell text-center" title={track.analyzed ? 'Analyzed' : 'Not analyzed'}>
										<AudioWaveform class="w-3.5 h-3.5 inline {track.analyzed ? 'text-pink-400' : 'text-[var(--text-disabled)] opacity-30'}" />
									</td>
									<td class="px-3 py-2 text-[var(--text-muted)] font-mono text-xs hidden lg:table-cell">{formatDuration(track.duration)}</td>
									<td class="px-3 py-2 w-20">
										<div class="flex items-center gap-0.5">
											<button onclick={(e) => toggleFav('track', track.id, e)}
												class="p-1 transition-colors {favTrackIds.has(track.id) ? 'text-red-400' : 'text-[var(--text-disabled)] hover:text-red-400'}">
												<Heart class="w-3.5 h-3.5" fill={favTrackIds.has(track.id) ? 'currentColor' : 'none'} />
											</button>
											<button onclick={(e) => openMenu(track, e)}
												class="p-1 text-[var(--text-disabled)] hover:text-[var(--text-primary)] transition-colors">
												<MoreVertical class="w-3.5 h-3.5" />
											</button>
										</div>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</Card>
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
				<div class="flex-1">
					<h2 class="text-xl font-bold text-[var(--text-primary)]">{selectedArtist.name}</h2>
					<p class="text-sm text-[var(--text-muted)]">{selectedArtist.track_count} track{selectedArtist.track_count !== 1 ? 's' : ''} &middot; {artistAlbums.length} album{artistAlbums.length !== 1 ? 's' : ''}</p>
				</div>
				<button onclick={async () => {
					if (!window.confirm(`Blacklist artist "${selectedArtist.name}"? Future downloads will be blocked.`)) return;
					try {
						await api.addToBlacklist(selectedArtist.name);
						addToast(`Blacklisted: ${selectedArtist.name}`, 'success');
					} catch (e) { addToast('Blacklist failed: ' + e.message, 'error'); }
				}} class="flex items-center gap-1.5 px-3 py-1.5 text-sm text-orange-400 hover:text-orange-300 bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)] rounded-md transition-colors"
					title="Blacklist this artist from downloads">
					<ShieldBan class="w-3.5 h-3.5" /> Blacklist
				</button>
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
							<div class="flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--bg-hover)] transition-colors group">
								<button class="flex items-center gap-3 flex-1 min-w-0 text-left" onclick={() => playTrack(track)}>
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
								<div class="flex items-center gap-0.5">
									<button onclick={(e) => toggleFav('track', track.id, e)}
										class="p-1 transition-colors {favTrackIds.has(track.id) ? 'text-red-400' : 'text-[var(--text-disabled)] hover:text-red-400'}">
										<Heart class="w-3.5 h-3.5" fill={favTrackIds.has(track.id) ? 'currentColor' : 'none'} />
									</button>
									<button onclick={(e) => openMenu(track, e)}
										class="p-1 text-[var(--text-disabled)] hover:text-[var(--text-primary)] transition-colors">
										<MoreVertical class="w-3.5 h-3.5" />
									</button>
								</div>
							</div>
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
						<div class="group text-center">
							<button class="w-full" onclick={() => openArtist(artist)}>
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
							</button>
							<div class="flex items-center justify-center gap-1">
								<p class="text-sm font-medium text-[var(--text-primary)] truncate">{artist.name}</p>
								<button onclick={(e) => toggleFav('artist', artist.id, e)}
									class="p-0.5 flex-shrink-0 transition-colors {favArtistIds.has(artist.id) ? 'text-red-400' : 'text-[var(--text-disabled)] hover:text-red-400'}">
									<Heart class="w-3 h-3" fill={favArtistIds.has(artist.id) ? 'currentColor' : 'none'} />
								</button>
							</div>
							<p class="text-xs text-[var(--text-muted)]">{artist.track_count} track{artist.track_count !== 1 ? 's' : ''}</p>
						</div>
					{/each}
				</div>
			{:else}
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each artists as artist}
							<div class="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-hover)] transition-colors">
								<button class="flex items-center gap-3 flex-1 min-w-0 text-left" onclick={() => openArtist(artist)}>
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
								<button onclick={(e) => toggleFav('artist', artist.id, e)}
									class="p-1 flex-shrink-0 transition-colors {favArtistIds.has(artist.id) ? 'text-red-400' : 'text-[var(--text-disabled)] hover:text-red-400'}">
									<Heart class="w-3.5 h-3.5" fill={favArtistIds.has(artist.id) ? 'currentColor' : 'none'} />
								</button>
							</div>
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
						<div class="group text-left">
							<button class="w-full text-left" onclick={() => openAlbum(album)}>
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
							</button>
							<div class="flex items-center justify-between">
								<p class="text-sm font-medium text-[var(--text-primary)] truncate flex-1">{album.title}</p>
								<button onclick={(e) => toggleFav('album', album.id, e)}
									class="p-0.5 flex-shrink-0 transition-colors {favAlbumIds.has(album.id) ? 'text-red-400' : 'text-[var(--text-disabled)] hover:text-red-400'}">
									<Heart class="w-3.5 h-3.5" fill={favAlbumIds.has(album.id) ? 'currentColor' : 'none'} />
								</button>
							</div>
							<p class="text-xs text-[var(--text-muted)] truncate">{album.artist || 'Various'} &middot; {album.track_count} tracks</p>
						</div>
					{/each}
				</div>
			{:else}
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each albums as album}
							<div class="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-hover)] transition-colors">
								<button class="flex items-center gap-3 flex-1 min-w-0 text-left" onclick={() => openAlbum(album)}>
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
								<button onclick={(e) => toggleFav('album', album.id, e)}
									class="p-1 flex-shrink-0 transition-colors {favAlbumIds.has(album.id) ? 'text-red-400' : 'text-[var(--text-disabled)] hover:text-red-400'}">
									<Heart class="w-3.5 h-3.5" fill={favAlbumIds.has(album.id) ? 'currentColor' : 'none'} />
								</button>
							</div>
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

	<!-- Schedule -->
	{#if schedTasks.library_scan || schedTasks.library_cleanup}
		<Card padding="p-4" class="mt-6">
			<div class="flex items-center gap-2 mb-2">
				<Clock class="w-4 h-4 text-[var(--text-muted)]" />
				<span class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">Schedule</span>
			</div>
			{#if schedTasks.library_scan}
				<ScheduleControl taskName="library_scan" label="Library Scan" enabled={schedTasks.library_scan.enabled} intervalHours={schedTasks.library_scan.interval_hours} runAt={schedTasks.library_scan.run_at} lastRunAt={schedTasks.library_scan.last_run_at} running={schedRunning.library_scan} onToggle={() => toggleSched('library_scan')} onUpdate={(u) => updateSched('library_scan', u)} onRun={() => runSched('library_scan')} />
			{/if}
			{#if schedTasks.library_cleanup}
				<ScheduleControl taskName="library_cleanup" label="Orphan Cleanup (scheduled)" enabled={schedTasks.library_cleanup.enabled} intervalHours={schedTasks.library_cleanup.interval_hours} runAt={schedTasks.library_cleanup.run_at} lastRunAt={schedTasks.library_cleanup.last_run_at} running={schedRunning.library_cleanup} onToggle={() => toggleSched('library_cleanup')} onUpdate={(u) => updateSched('library_cleanup', u)} onRun={() => runSched('library_cleanup')} />
				<div class="flex items-center gap-2 mt-1.5 ml-1">
					<AlertTriangle class="w-3 h-3 text-amber-400/70" />
					<span class="text-[11px] text-amber-400/70">Destructive — removes orphaned database entries for files no longer on disk</span>
				</div>
			{/if}
		</Card>
	{/if}

	<!-- Library Cleanup Tools — Danger Zone -->
	<Card padding="p-4" class="mt-4 border border-amber-500/20">
		<div class="flex items-center gap-2 mb-1">
			<AlertTriangle class="w-4 h-4 text-amber-400" />
			<span class="text-xs text-amber-400/80 font-mono uppercase tracking-wider">Danger Zone</span>
		</div>
		<p class="text-[11px] text-[var(--text-disabled)] mb-3">These tools modify or delete files and database entries. Always preview before executing.</p>
		<div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
			<button class="text-left p-3 rounded-lg border transition-colors {cleanupTab === 'orphans' ? 'border-red-500/50 bg-red-500/10' : 'border-red-500/20 bg-[var(--bg-secondary)] hover:bg-red-500/5'}" onclick={() => previewCleanup('orphans')}>
				<div class="flex items-center gap-2 mb-1">
					<FileSearch class="w-4 h-4 text-red-400" />
					<span class="text-sm font-medium text-[var(--text-primary)]">Orphan Cleanup</span>
					<span class="text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 font-mono">DESTRUCTIVE</span>
				</div>
				<p class="text-xs text-[var(--text-muted)]">Remove database entries for files that no longer exist on disk.</p>
			</button>
			<button class="text-left p-3 rounded-lg border transition-colors {cleanupTab === 'duplicates' ? 'border-amber-500/50 bg-amber-500/10' : 'border-amber-500/20 bg-[var(--bg-secondary)] hover:bg-amber-500/5'}" onclick={() => previewCleanup('duplicates')}>
				<div class="flex items-center gap-2 mb-1">
					<Copy class="w-4 h-4 text-amber-400" />
					<span class="text-sm font-medium text-[var(--text-primary)]">Deduplication</span>
					<span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-mono">CAUTION</span>
				</div>
				<p class="text-xs text-[var(--text-muted)]">Find duplicate tracks and keep the best quality version. Can delete files.</p>
			</button>
			<button class="text-left p-3 rounded-lg border transition-colors {cleanupTab === 'organize' ? 'border-amber-500/50 bg-amber-500/10' : 'border-amber-500/20 bg-[var(--bg-secondary)] hover:bg-amber-500/5'}" onclick={() => previewCleanup('organize')}>
				<div class="flex items-center gap-2 mb-1">
					<FolderTree class="w-4 h-4 text-amber-400" />
					<span class="text-sm font-medium text-[var(--text-primary)]">Rename & Sort</span>
					<span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-mono">CAUTION</span>
				</div>
				<p class="text-xs text-[var(--text-muted)]">Move and rename files into Artist/Album/Track folder structure.</p>
			</button>
		</div>

		{#if cleanupLoading}
			<div class="flex items-center gap-2 p-4 text-[var(--text-muted)]">
				<Loader2 class="w-4 h-4 animate-spin" />
				<span class="text-sm">Scanning library...</span>
			</div>
		{:else if cleanupTab === 'orphans' && cleanupPreview}
			<div class="border border-[var(--border-primary)] rounded-lg p-3">
				<div class="flex items-center justify-between mb-2">
					<span class="text-sm font-medium text-[var(--text-primary)]">
						{cleanupPreview.count} orphaned track{cleanupPreview.count !== 1 ? 's' : ''} found
					</span>
					{#if cleanupPreview.count > 0}
						<Button variant="danger" size="sm" disabled={cleanupExecuting} onclick={executeOrphans}>
							{#if cleanupExecuting}<Loader2 class="w-3 h-3 animate-spin mr-1" />{/if}
							Remove All
						</Button>
					{/if}
				</div>
				{#if cleanupPreview.orphans?.length}
					<div class="max-h-64 overflow-y-auto space-y-1">
						{#each cleanupPreview.orphans as orphan}
							<div class="text-xs text-[var(--text-muted)] font-mono truncate py-1 border-b border-[var(--border-primary)] last:border-0">
								{orphan.file_path}
							</div>
						{/each}
					</div>
				{:else}
					<p class="text-sm text-emerald-400">No orphaned tracks found. Library is clean.</p>
				{/if}
			</div>
		{:else if cleanupTab === 'duplicates' && cleanupPreview}
			<div class="border border-[var(--border-primary)] rounded-lg p-3">
				<div class="flex items-center justify-between mb-2">
					<div class="flex items-center gap-3">
						<span class="text-sm font-medium text-[var(--text-primary)]">
							{cleanupPreview.total_groups} duplicate group{cleanupPreview.total_groups !== 1 ? 's' : ''} ({cleanupPreview.total_duplicates} extra file{cleanupPreview.total_duplicates !== 1 ? 's' : ''})
						</span>
						{#if cleanupPreview.total_duplicates > 0}
							<button onclick={toggleDedupAll} class="text-xs text-[var(--color-accent)] hover:underline">
								{dedupSelected.size === cleanupPreview.groups.flatMap(g => g.remove.map(r => r.id)).length ? 'Deselect All' : 'Select All'}
							</button>
						{/if}
					</div>
					{#if dedupSelected.size > 0}
						<div class="flex items-center gap-2">
							<span class="text-xs text-[var(--text-muted)]">{dedupSelected.size} selected</span>
							<Button variant="warning" size="sm" disabled={cleanupExecuting} onclick={() => executeDuplicates(false)}>
								{#if cleanupExecuting}<Loader2 class="w-3 h-3 animate-spin mr-1" />{/if}
								Remove from DB
							</Button>
							<Button variant="danger" size="sm" disabled={cleanupExecuting} onclick={() => executeDuplicates(true)}>
								Remove + Delete Files
							</Button>
						</div>
					{/if}
				</div>
				{#if cleanupPreview.groups?.length}
					<div class="max-h-80 overflow-y-auto space-y-3">
						{#each cleanupPreview.groups as group}
							<div class="border border-[var(--border-primary)] rounded p-2">
								<p class="text-sm font-medium text-[var(--text-primary)] mb-1">{group.artist} — {group.title}</p>
								<div class="text-xs space-y-1">
									<div class="flex items-center gap-2 text-emerald-400">
										<span class="font-mono">KEEP</span>
										<span class="text-[var(--text-muted)] flex-1 truncate">{group.keep.file_path}</span>
										<Badge>{group.keep.format?.toUpperCase()}</Badge>
										{#if group.keep.bitrate}<Badge variant="info">{Math.round(group.keep.bitrate / 1000)}k</Badge>{/if}
										{#if group.keep.file_size}<span class="text-[var(--text-muted)] font-mono">{formatSize(group.keep.file_size)}</span>{/if}
									</div>
									{#each group.remove as rem}
										<div class="flex items-center gap-2 {dedupSelected.has(rem.id) ? 'text-red-400' : 'text-[var(--text-disabled)]'}">
											<input type="checkbox" checked={dedupSelected.has(rem.id)} onchange={() => toggleDedupTrack(rem.id)}
												class="w-3.5 h-3.5 rounded accent-red-500 cursor-pointer" />
											<span class="font-mono">{dedupSelected.has(rem.id) ? 'DROP' : 'SKIP'}</span>
											<span class="text-[var(--text-muted)] flex-1 truncate">{rem.file_path}</span>
											<Badge>{rem.format?.toUpperCase()}</Badge>
											{#if rem.bitrate}<Badge variant="info">{Math.round(rem.bitrate / 1000)}k</Badge>{/if}
											{#if rem.file_size}<span class="text-[var(--text-muted)] font-mono">{formatSize(rem.file_size)}</span>{/if}
										</div>
									{/each}
								</div>
							</div>
						{/each}
					</div>
				{:else}
					<p class="text-sm text-emerald-400">No duplicates found.</p>
				{/if}
			</div>
		{:else if cleanupTab === 'organize' && cleanupPreview}
			<div class="border border-[var(--border-primary)] rounded-lg p-3">
				<div class="flex items-center justify-between mb-2">
					<div class="flex items-center gap-3">
						<span class="text-sm font-medium text-[var(--text-primary)]">
							{cleanupPreview.count} file{cleanupPreview.count !== 1 ? 's' : ''} to reorganize
						</span>
						{#if cleanupPreview.count > 0}
							<button onclick={toggleOrganizeAll} class="text-xs text-[var(--color-accent)] hover:underline">
								{organizeSelected.size === cleanupPreview.moves.length ? 'Deselect All' : 'Select All'}
							</button>
						{/if}
					</div>
					{#if organizeSelected.size > 0}
						<div class="flex items-center gap-2">
							<span class="text-xs text-[var(--text-muted)]">{organizeSelected.size} selected</span>
							<Button variant="primary" size="sm" disabled={cleanupExecuting} onclick={executeOrganize}>
								{#if cleanupExecuting}<Loader2 class="w-3 h-3 animate-spin mr-1" />{/if}
								Organize Selected
							</Button>
						</div>
					{/if}
				</div>
				{#if cleanupPreview.count > 0}
					<div class="flex items-center gap-2 mb-2 p-2 rounded bg-amber-500/10 border border-amber-500/30">
						<AlertTriangle class="w-4 h-4 text-amber-400 flex-shrink-0" />
						<span class="text-xs text-amber-300">This will move files on disk. A library scan is required afterwards.</span>
					</div>
				{/if}
				{#if cleanupPreview.moves?.length}
					<div class="max-h-80 overflow-y-auto space-y-1">
						{#each cleanupPreview.moves as move}
							<div class="flex items-start gap-2 text-xs py-1 border-b border-[var(--border-primary)] last:border-0 {organizeSelected.has(move.track_id) ? '' : 'opacity-40'}">
								<input type="checkbox" checked={organizeSelected.has(move.track_id)} onchange={() => toggleOrganizeTrack(move.track_id)}
									class="w-3.5 h-3.5 mt-0.5 rounded accent-blue-500 cursor-pointer flex-shrink-0" />
								<div class="min-w-0 flex-1">
									<div class="text-red-400 font-mono truncate">- {move.current_path}</div>
									<div class="text-emerald-400 font-mono truncate">+ {move.target_path}</div>
								</div>
							</div>
						{/each}
					</div>
				{:else}
					<p class="text-sm text-emerald-400">All files are already properly organized.</p>
				{/if}
			</div>
		{/if}
	</Card>

	<!-- Pagination -->
	{#if currentTotal > 0}
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

<!-- Track Action Menu -->
{#if menuTrack}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 z-40" onclick={closeMenu}></div>
	<div class="fixed z-50 bg-[var(--bg-secondary)] border border-[var(--border-subtle)] rounded-lg shadow-xl py-1 min-w-[160px]"
		style="left: {Math.min(menuPos.x, window.innerWidth - 180)}px; top: {Math.min(menuPos.y, window.innerHeight - 200)}px">
		<button class="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--text-body)] hover:bg-[var(--bg-hover)] transition-colors text-left"
			onclick={() => { const t = menuTrack; closeMenu(); findSimilar(t, new Event('click')); }}>
			<AudioWaveform class="w-3.5 h-3.5 text-purple-400" /> Find Similar
		</button>
		<button class="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--text-body)] hover:bg-[var(--bg-hover)] transition-colors text-left"
			onclick={() => openEdit(menuTrack)}>
			<Pencil class="w-3.5 h-3.5 text-blue-400" /> Edit Info
		</button>
		<button class="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--text-body)] hover:bg-[var(--bg-hover)] transition-colors text-left"
			onclick={() => { toggleFav('track', menuTrack.id); closeMenu(); }}>
			<Heart class="w-3.5 h-3.5 {favTrackIds.has(menuTrack.id) ? 'text-red-400' : ''}"
				fill={favTrackIds.has(menuTrack.id) ? 'currentColor' : 'none'} />
			{favTrackIds.has(menuTrack.id) ? 'Unfavorite' : 'Favorite'}
		</button>
		<button class="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--text-body)] hover:bg-[var(--bg-hover)] transition-colors text-left"
			onclick={() => { const t = menuTrack; closeMenu(); findRemixes(t); }}>
			<Disc3 class="w-3.5 h-3.5 text-teal-400" /> Find Remixes
		</button>
		<button class="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--text-body)] hover:bg-[var(--bg-hover)] transition-colors text-left"
			onclick={() => { const t = menuTrack; closeMenu(); goto(`/downloads?artist=${encodeURIComponent(t.artist || '')}&track=${encodeURIComponent(t.title || '')}`); }}>
			<Download class="w-3.5 h-3.5 text-green-400" /> Find Upgrade
		</button>
		<button class="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--text-body)] hover:bg-[var(--bg-hover)] transition-colors text-left"
			onclick={() => blacklistArtist(menuTrack)}>
			<ShieldBan class="w-3.5 h-3.5 text-orange-400" /> Blacklist Artist
		</button>
		<div class="border-t border-[var(--border-subtle)] my-1"></div>
		<button class="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-400 hover:bg-[var(--bg-hover)] transition-colors text-left"
			onclick={() => deleteTrack(menuTrack)}>
			<Trash2 class="w-3.5 h-3.5" /> Delete Track
		</button>
	</div>
{/if}

<!-- Edit Track Modal -->
<Modal bind:open={showEdit} title="Edit Track Info">
	{#snippet children()}
		<div class="space-y-3">
			<div>
				<label class="block text-xs text-[var(--text-muted)] mb-1">Title</label>
				<input type="text" bind:value={editForm.title}
					class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm
						focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
			</div>
			<div class="grid grid-cols-3 gap-3">
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Genre</label>
					<input type="text" bind:value={editForm.genre}
						class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm
							focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				</div>
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Year</label>
					<input type="number" bind:value={editForm.year}
						class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm
							focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				</div>
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Track #</label>
					<input type="number" bind:value={editForm.track_number}
						class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm
							focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				</div>
			</div>
			<p class="text-xs text-[var(--text-disabled)]">Changes are saved to both the database and the audio file tags.</p>
		</div>
	{/snippet}
	{#snippet footer()}
		<div class="flex justify-end gap-2">
			<Button variant="secondary" size="sm" onclick={() => showEdit = false}>Cancel</Button>
			<Button variant="primary" size="sm" loading={editSaving} onclick={saveEdit}>Save</Button>
		</div>
	{/snippet}
</Modal>

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
							{:else if similarDownloading.has(`${t.artist}::${t.name}`.toLowerCase())}
								<Badge variant="info">
									<span class="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1"></span>
									Downloading
								</Badge>
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
		{@const missingCount = similarTracks.filter(t => !t.in_library && !similarDownloading.has(`${t.artist}::${t.name}`.toLowerCase())).length}
		{@const dlCount = similarTracks.filter(t => similarDownloading.has(`${t.artist}::${t.name}`.toLowerCase())).length}
		<div class="flex items-center justify-between">
			<span class="text-xs text-[var(--text-muted)]">
				{similarTracks.length} similar &middot; {similarTracks.filter(t => t.in_library).length} in library
				{#if dlCount > 0}&middot; {dlCount} downloading{/if}
				{#if missingCount > 0}&middot; {missingCount} missing{/if}
			</span>
			{#if missingCount > 0}
				<Button variant="success" size="sm" onclick={downloadAllMissing}>
					<Download class="w-3 h-3" /> Get All Missing ({missingCount})
				</Button>
			{/if}
		</div>
	{/snippet}
</Modal>

<!-- Remix Discovery Modal -->
<Modal bind:open={showRemixes} title="Find Remixes">
	{#snippet children()}
		{#if remixSource}
			<p class="text-xs text-[var(--text-muted)] mb-3">
				Remixes of <span class="text-[var(--text-primary)]">{remixSource.title}</span> by <span class="text-[var(--text-secondary)]">{remixSource.artist}</span>
			</p>
		{/if}
		{#if remixLoading}
			<div class="space-y-2">
				{#each Array(5) as _}
					<Skeleton class="h-10 rounded" />
				{/each}
			</div>
		{:else if remixes.length}
			<div class="space-y-1 max-h-96 overflow-y-auto">
				{#each remixes as remix}
					{@const rkey = `${remix.artist}|${remix.name}`}
					<div class="flex items-center gap-3 px-3 py-2 rounded hover:bg-[var(--bg-hover)] transition-colors group">
						<div class="flex-1 min-w-0">
							<p class="text-sm text-[var(--text-primary)] truncate">{remix.name}</p>
							<p class="text-xs text-[var(--text-muted)]">{remix.artist}</p>
						</div>
						<Badge variant={remix.version_type === 'remix' ? 'info' : remix.version_type === 'extended' ? 'success' : 'default'}>
							{remix.version_type}
						</Badge>
						{#if remix.in_library}
							<Badge variant="success">In Library</Badge>
						{:else if remixDownloadStatus[rkey] === 'downloading'}
							<Badge variant="info"><Loader2 class="w-3 h-3 animate-spin inline" /> Downloading</Badge>
						{:else if remixDownloadStatus[rkey] === 'done'}
							<Badge variant="success"><Check class="w-3 h-3 inline" /> Queued</Badge>
						{:else if remixDownloadStatus[rkey] === 'failed'}
							<Button variant="danger" size="sm"
								onclick={async () => {
									remixDownloadStatus[rkey] = 'downloading';
									try {
										await fetch('/api/download/trigger', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ artist: remix.artist, track: remix.name }) });
										remixDownloadStatus[rkey] = 'done';
									} catch { remixDownloadStatus[rkey] = 'failed'; addToast('Download failed', 'error'); }
								}}>
								<RotateCcw class="w-3 h-3" /> Retry
							</Button>
						{:else}
							<Button variant="success" size="sm"
								onclick={async () => {
									remixDownloadStatus[rkey] = 'downloading';
									try {
										await fetch('/api/download/trigger', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ artist: remix.artist, track: remix.name }) });
										remixDownloadStatus[rkey] = 'done';
										addToast(`Downloading ${remix.name}`, 'success');
									} catch { remixDownloadStatus[rkey] = 'failed'; addToast('Download failed', 'error'); }
								}}>
								<Download class="w-3 h-3" /> Get
							</Button>
						{/if}
					</div>
				{/each}
			</div>
		{:else}
			<p class="text-[var(--text-muted)] text-center py-8 text-sm">No remixes found.</p>
		{/if}
	{/snippet}
	{#snippet footer()}
		<span class="text-xs text-[var(--text-muted)]">
			{remixes.length} remixes found &middot; {remixes.filter(r => r.in_library).length} in library
		</span>
	{/snippet}
</Modal>
