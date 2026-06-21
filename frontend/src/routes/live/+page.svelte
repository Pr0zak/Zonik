<script>
	import { onMount, onDestroy } from 'svelte';
	import { Radio, Heart, Music, Globe, Plug, Disc3, History } from 'lucide-svelte';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import { formatDuration, formatRelativeTime, coverUrl } from '$lib/utils.js';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	const SECTION_COLOR = 'var(--color-live, #f43f5e)';

	let nowPlaying = $state([]);
	let history = $state([]);
	let clients = $state({ ws_clients: [], api_clients: [] });

	let loadingNow = $state(true);
	let loadingHistory = $state(true);
	let loadingClients = $state(true);

	let timer = null;
	let tick = 0;

	async function fetchJSON(path) {
		const res = await fetch(path);
		if (!res.ok) throw new Error(`${res.status}`);
		return res.json();
	}

	async function loadNowPlaying() {
		try {
			nowPlaying = await fetchJSON('/api/live/now-playing');
		} catch (e) {
			console.error('Live now-playing:', e);
		} finally {
			loadingNow = false;
		}
	}

	async function loadHistory() {
		try {
			history = await fetchJSON('/api/live/history?limit=50');
		} catch (e) {
			console.error('Live history:', e);
		} finally {
			loadingHistory = false;
		}
	}

	async function loadClients() {
		try {
			clients = await fetchJSON('/api/live/clients');
		} catch (e) {
			console.error('Live clients:', e);
		} finally {
			loadingClients = false;
		}
	}

	onMount(() => {
		loadNowPlaying();
		loadClients();
		loadHistory();

		// Single shared timer (per dev_gotchas) — different cadences via tick counter.
		// 3s for now-playing, 9s for clients (every 3rd tick), 30s for history (every 10th tick).
		timer = setInterval(() => {
			tick++;
			loadNowPlaying();
			if (tick % 3 === 0) loadClients();
			if (tick % 10 === 0) loadHistory();
		}, 3000);
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	async function toggleStar(item, list) {
		try {
			if (item.starred) {
				await fetch('/api/favorites/unstar', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ track_id: item.track_id }),
				});
				addToast('Removed from favorites', 'success');
			} else {
				await fetch('/api/favorites/star', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ track_id: item.track_id }),
				});
				addToast('Added to favorites', 'success');
			}
			// Reflect change across both views.
			const flip = (i) => i.track_id === item.track_id ? { ...i, starred: !item.starred } : i;
			nowPlaying = nowPlaying.map(flip);
			history = history.map(flip);
		} catch (e) {
			addToast('Failed to toggle favorite', 'error');
		}
	}

	function play(item) {
		if (!item.track_id) return;
		storePlayTrack({ id: item.track_id, title: item.title, artist: item.artist });
	}

	function deviceLabel(userAgent) {
		if (!userAgent) return 'Unknown';
		const ua = userAgent.toLowerCase();
		if (ua.includes('zonikapp') || ua.includes('zonik-mobile')) return 'Zonik Mobile';
		if (ua.includes('symfonium')) return 'Symfonium';
		if (ua.includes('dsub') || ua.includes('ultrasonic')) return 'Subsonic Client';
		if (ua.includes('chrome')) return 'Chrome';
		if (ua.includes('firefox')) return 'Firefox';
		if (ua.includes('safari')) return 'Safari';
		return userAgent.split(' ')[0] || 'Client';
	}

	// Friendly label for a play's originating client (play_history.source / c= param).
	function clientLabel(src) {
		if (!src) return '';
		const s = src.toLowerCase();
		if (s.includes('wear')) return 'Watch';
		if (s.includes('zonikapp') || s.includes('zonik-mobile') || s.includes('android')) return 'Phone';
		if (s === 'web' || s.includes('web')) return 'Web';
		if (s.includes('symfonium')) return 'Symfonium';
		if (s.includes('dsub') || s.includes('ultrasonic')) return 'Subsonic';
		if (s === 'subsonic') return 'Subsonic';
		return src;
	}
</script>

<div class="max-w-6xl">
	<PageHeader
		title="Live"
		icon={Radio}
		color={SECTION_COLOR}
		subtitle="Real-time activity across all clients">
		{#snippet actions()}
			<Badge variant="info">
				<span class="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1.5"></span>
				Live
			</Badge>
		{/snippet}
	</PageHeader>

	<!-- Connected clients -->
	<section class="mb-6">
		<div class="flex items-center gap-2 mb-2">
			<Plug class="w-4 h-4" style="color: {SECTION_COLOR}" />
			<h2 class="text-sm font-semibold text-[var(--text-primary)] uppercase tracking-wider">Connected Clients</h2>
		</div>
		<Card padding="p-0">
			{#if loadingClients}
				<Skeleton variant="list-item" count={3} />
			{:else if !clients.ws_clients.length && !clients.api_clients.length}
				<EmptyState
					title="No clients connected"
					description="Active WebSocket and Subsonic API clients will appear here."
				>
					{#snippet icon()}<Plug class="w-10 h-10" />{/snippet}
				</EmptyState>
			{:else}
				<div class="divide-y divide-[var(--border-subtle)]">
					{#each clients.ws_clients as ws}
						<div class="flex items-center gap-3 px-4 py-3">
							<div class="w-9 h-9 rounded-md bg-[var(--surface-container-high)] flex items-center justify-center flex-shrink-0">
								<Globe class="w-4 h-4 text-[var(--text-secondary)]" />
							</div>
							<div class="flex-1 min-w-0">
								<p class="text-sm font-medium text-[var(--text-primary)] truncate">{deviceLabel(ws.user_agent)} (WebSocket)</p>
								<p class="text-xs text-[var(--text-muted)] truncate">
									{ws.ip || '—'} &middot; connected {formatRelativeTime(ws.connected_at)}
								</p>
							</div>
							<Badge variant="success">WS</Badge>
						</div>
					{/each}
					{#each clients.api_clients as api}
						<div class="flex items-center gap-3 px-4 py-3">
							<div class="w-9 h-9 rounded-md bg-[var(--surface-container-high)] flex items-center justify-center flex-shrink-0">
								<Radio class="w-4 h-4" style="color: {SECTION_COLOR}" />
							</div>
							<div class="flex-1 min-w-0">
								<p class="text-sm font-medium text-[var(--text-primary)] truncate">
									{api.client_name || 'Subsonic'}
									<span class="text-[var(--text-disabled)] font-normal">&middot; {api.username}</span>
								</p>
								<p class="text-xs text-[var(--text-muted)] truncate">
									{api.ip || '—'} &middot; last activity {formatRelativeTime(api.last_seen)}
								</p>
							</div>
							<span class="text-xs text-[var(--text-muted)] font-mono mr-2 hidden sm:inline">
								{api.endpoint_count} calls
							</span>
							<Badge variant="info">API</Badge>
						</div>
					{/each}
				</div>
			{/if}
		</Card>
	</section>

	<!-- Now playing -->
	<section class="mb-6">
		<div class="flex items-center gap-2 mb-2">
			<Disc3 class="w-4 h-4" style="color: {SECTION_COLOR}" />
			<h2 class="text-sm font-semibold text-[var(--text-primary)] uppercase tracking-wider">Now Playing</h2>
		</div>
		<Card padding="p-0">
			{#if loadingNow}
				<Skeleton variant="list-item" count={2} />
			{:else if !nowPlaying.length}
				<EmptyState
					title="Nothing playing"
					description="Tracks that clients are actively streaming will show up here."
				>
					{#snippet icon()}<Disc3 class="w-10 h-10" />{/snippet}
				</EmptyState>
			{:else}
				<div class="divide-y divide-[var(--border-subtle)]">
					{#each nowPlaying as np}
						<div class="flex items-center gap-3 px-4 py-3 group">
							<button class="relative w-14 h-14 rounded-md bg-[var(--surface-base)] overflow-hidden flex-shrink-0"
								onclick={() => play(np)}
								title="Play">
								{#if coverUrl(np.cover_art)}
									<img src={coverUrl(np.cover_art, 56)} alt="" class="w-full h-full object-cover" loading="lazy" />
								{:else}
									<div class="flex items-center justify-center w-full h-full">
										<Music class="w-5 h-5 text-[var(--text-disabled)]" />
									</div>
								{/if}
							</button>
							<div class="flex-1 min-w-0">
								<p class="text-sm font-medium text-[var(--text-primary)] truncate">{np.title}</p>
								<p class="text-xs text-[var(--text-muted)] truncate">
									{np.artist || 'Unknown artist'}{#if np.album} &middot; {np.album}{/if}
								</p>
								<p class="text-xs text-[var(--text-disabled)] mt-0.5 truncate">
									{np.username}{#if np.client} &middot; {np.client}{/if} &middot; started {formatRelativeTime(np.started_at)}
								</p>
							</div>
							<button onclick={() => toggleStar(np)}
								class="p-2 min-w-[44px] min-h-[44px] flex items-center justify-center transition-colors flex-shrink-0
									{np.starred ? 'text-red-400 hover:text-red-300' : 'text-[var(--text-muted)] hover:text-red-300'}"
								title={np.starred ? 'Unstar' : 'Star'}>
								<Heart class="w-4 h-4" fill={np.starred ? 'currentColor' : 'none'} />
							</button>
						</div>
					{/each}
				</div>
			{/if}
		</Card>
	</section>

	<!-- Recently played -->
	<section class="mb-6">
		<div class="flex items-center gap-2 mb-2">
			<History class="w-4 h-4" style="color: {SECTION_COLOR}" />
			<h2 class="text-sm font-semibold text-[var(--text-primary)] uppercase tracking-wider">Recently Played</h2>
		</div>
		<Card padding="p-0">
			{#if loadingHistory}
				<Skeleton variant="list-item" count={6} />
			{:else if !history.length}
				<EmptyState
					title="No plays yet"
					description="Scrobbled plays will appear here as soon as a client reports them."
				>
					{#snippet icon()}<History class="w-10 h-10" />{/snippet}
				</EmptyState>
			{:else}
				<div class="divide-y divide-[var(--border-subtle)]">
					{#each history as h (h.id)}
						<div class="flex items-center gap-3 px-4 py-2.5 group">
							<button class="relative w-10 h-10 rounded bg-[var(--surface-base)] overflow-hidden flex-shrink-0"
								onclick={() => play(h)}
								title="Play">
								{#if coverUrl(h.cover_art)}
									<img src={coverUrl(h.cover_art, 40)} alt="" class="w-full h-full object-cover" loading="lazy" />
								{:else}
									<div class="flex items-center justify-center w-full h-full">
										<Music class="w-4 h-4 text-[var(--text-disabled)]" />
									</div>
								{/if}
							</button>
							<div class="flex-1 min-w-0">
								<p class="text-sm text-[var(--text-primary)] truncate">{h.title}</p>
								<p class="text-xs text-[var(--text-muted)] truncate">
									{h.artist || 'Unknown'}{#if h.album} &middot; {h.album}{/if}
								</p>
								<p class="text-xs text-[var(--text-disabled)] truncate">
									{#if clientLabel(h.source)}{clientLabel(h.source)} &middot; {/if}{formatRelativeTime(h.played_at)}
								</p>
							</div>
							{#if h.duration}
								<span class="text-xs text-[var(--text-muted)] font-mono hidden sm:block">{formatDuration(h.duration)}</span>
							{/if}
							<button onclick={() => toggleStar(h)}
								class="p-2 min-w-[44px] min-h-[44px] flex items-center justify-center transition-colors flex-shrink-0
									{h.starred ? 'text-red-400 hover:text-red-300' : 'text-[var(--text-muted)] hover:text-red-300'}"
								title={h.starred ? 'Unstar' : 'Star'}>
								<Heart class="w-4 h-4" fill={h.starred ? 'currentColor' : 'none'} />
							</button>
						</div>
					{/each}
				</div>
			{/if}
		</Card>
	</section>
</div>
