<script>
	import '../app.css';
	import Sidebar from '../components/Sidebar.svelte';
	import TopBar from '../components/TopBar.svelte';
	import Player from '../components/Player.svelte';
	import Toast from '../components/Toast.svelte';
	import Modal from '../components/ui/Modal.svelte';
	import { onMount, onDestroy } from 'svelte';
	import { connectWebSocket, disconnectWebSocket } from '$lib/websocket.js';
	import { initCast } from '$lib/cast.js';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { Menu, Loader2 } from 'lucide-svelte';
	import AdminsOnly from '../components/AdminsOnly.svelte';
	import ChangePasswordModal from '../components/ChangePasswordModal.svelte';
	import {
		currentUser, authReady, loadStatus, loadMe, isAdmin, isAdminPath, isPublicPath,
		loginUrl, setUnauthorizedHandler, notifyUnauthorized, isAuthExempt,
	} from '$lib/auth.js';
	import { sidebarOpen, isPlaying, showShortcuts, playNext, playPrev, isMobile } from '$lib/stores.js';

	let { children } = $props();

	let mql;
	let mqlHandler;
	let socketsUp = false;
	let castStarted = false;

	let pathname = $derived($page.url.pathname);
	let publicPage = $derived(isPublicPath(pathname));
	let showShell = $derived($authReady && !!$currentUser && !publicPage);
	let blocked = $derived(showShell && !isAdmin($currentUser) && isAdminPath(pathname));

	function toLogin() {
		const here = window.location.pathname + window.location.search;
		if (isPublicPath(window.location.pathname)) return;
		goto(loginUrl(here), { replaceState: true });
	}

	// Redirect once auth has resolved and there is no session on a non-public page.
	$effect(() => {
		if ($authReady && !$currentUser && !publicPage) toLogin();
	});

	// Websocket and cast only run while someone is signed in.
	$effect(() => {
		if ($currentUser && !socketsUp) {
			socketsUp = true;
			connectWebSocket();
			if (!castStarted) { castStarted = true; initCast(); }
		} else if (!$currentUser && socketsUp) {
			socketsUp = false;
			disconnectWebSocket();
		}
	});

	onMount(async () => {
		// One-time wrapper so raw fetch('/api/...') calls also bounce to the login page on 401.
		if (!window.__zonikFetchWrapped) {
			window.__zonikFetchWrapped = true;
			const orig = window.fetch.bind(window);
			window.fetch = async (input, init) => {
				const res = await orig(input, init);
				if (res.status === 401) {
					const url = typeof input === 'string' ? input : input?.url;
					if (url && !isAuthExempt(url) && new URL(url, window.location.origin).pathname.startsWith('/api/')) notifyUnauthorized();
				}
				return res;
			};
		}
		let bouncing = false;
		setUnauthorizedHandler(() => {
			if (bouncing) return;
			bouncing = true;
			$currentUser = null;
			toLogin();
			setTimeout(() => { bouncing = false; }, 1500);
		});

		mql = window.matchMedia('(max-width: 767px)');
		$isMobile = mql.matches;
		mqlHandler = (e) => { $isMobile = e.matches; };
		mql.addEventListener('change', mqlHandler);
		if ($isMobile) {
			$sidebarOpen = false;
		}

		await loadStatus();
		await loadMe();
		$authReady = true;
	});

	onDestroy(() => {
		disconnectWebSocket();
		if (mql && mqlHandler) mql.removeEventListener('change', mqlHandler);
	});

	function handleKeydown(event) {
		if (!$currentUser || publicPage) return;
		// Don't trigger shortcuts when typing in inputs
		const tag = event.target?.tagName?.toLowerCase();
		if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

		const key = event.key.toLowerCase();
		const ctrl = event.ctrlKey || event.metaKey;

		// ? = show shortcuts help
		if (key === '?' || (key === '/' && event.shiftKey)) {
			event.preventDefault();
			$showShortcuts = !$showShortcuts;
			return;
		}

		// Space = play/pause
		if (key === ' ' && !ctrl) {
			event.preventDefault();
			$isPlaying = !$isPlaying;
			return;
		}

		// Escape = close shortcuts / clear focus
		if (key === 'escape') {
			$showShortcuts = false;
			return;
		}

		// / = focus search bar
		if (key === '/' && !event.shiftKey && !ctrl) {
			event.preventDefault();
			document.querySelector('[data-search-input]')?.focus();
			return;
		}

		// b = toggle sidebar
		if (key === 'b' && !ctrl) {
			$sidebarOpen = !$sidebarOpen;
			return;
		}

		// Navigation shortcuts
		if (key === '1') { goto('/'); return; }
		if (key === '2') { goto('/library'); return; }
		if (key === '3') { goto('/discover'); return; }
		if (key === '4') { goto('/downloads'); return; }
		if (key === '5') { goto('/playlists'); return; }
		if (key === '6') { goto('/favorites'); return; }
		if (key === '7') { goto('/analysis'); return; }
		if (key === '8') { goto('/stats'); return; }
		if (key === '9') { goto('/schedule'); return; }
		if (key === '0') { goto('/logs'); return; }
		if (key === 'm') { goto('/map'); return; }
		if (key === 's' && !ctrl) { goto('/settings'); return; }

		// n = next track, p = prev track
		if (key === 'n' && !ctrl) { playNext(); return; }
		if (key === 'p' && !ctrl) { playPrev(); return; }
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<Modal bind:open={$showShortcuts} title="Keyboard Shortcuts" maxWidth="max-w-md">
	{#snippet children()}
		<div class="space-y-4">
			<div>
				<h3 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-2">General</h3>
				<div class="space-y-1.5">
					{#each [
						['?', 'Show shortcuts'],
						['Space', 'Play / Pause'],
						['N', 'Next track'],
						['P', 'Previous track'],
						['B', 'Toggle sidebar'],
						['Esc', 'Close dialog'],
					] as [key, desc]}
						<div class="flex items-center justify-between text-sm">
							<span class="text-[var(--text-secondary)]">{desc}</span>
							<kbd class="px-2 py-0.5 bg-[var(--surface-lowest)] rounded text-xs font-mono text-[var(--text-muted)]">{key}</kbd>
						</div>
					{/each}
				</div>
			</div>
			<div>
				<h3 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-2">Navigation</h3>
				<div class="space-y-1.5">
					{#each [
						['1', 'Dashboard'],
						['2', 'Library'],
						['3', 'Discover'],
						['4', 'Downloads'],
						['5', 'Playlists'],
						['6', 'Favorites'],
						['7', 'Analysis'],
						['8', 'Stats'],
						['9', 'Schedule'],
						['0', 'Logs'],
						['S', 'Settings'],
					] as [key, desc]}
						<div class="flex items-center justify-between text-sm">
							<span class="text-[var(--text-secondary)]">{desc}</span>
							<kbd class="px-2 py-0.5 bg-[var(--surface-lowest)] rounded text-xs font-mono text-[var(--text-muted)]">{key}</kbd>
						</div>
					{/each}
				</div>
			</div>
			<p class="text-xs text-[var(--text-disabled)]">Press <kbd class="px-1 py-0.5 bg-[var(--surface-lowest)] rounded text-xs font-mono">?</kbd> to toggle this help</p>
		</div>
	{/snippet}
</Modal>

{#if !$authReady || (!$currentUser && !publicPage)}
	<!-- Auth not resolved yet (or redirecting to /login): nothing of the app shell renders. -->
	<div class="h-screen flex items-center justify-center bg-[var(--bg-primary)]">
		<Loader2 class="w-6 h-6 text-[var(--text-disabled)] animate-spin" />
	</div>
{:else if publicPage}
	<div class="h-screen overflow-y-auto bg-[var(--bg-primary)]">
		{@render children()}
	</div>
	<Toast />
{:else}
<div class="h-screen flex flex-col bg-[var(--bg-primary)]">
	<!-- Mobile header -->
	<div class="md:hidden flex items-center justify-between px-4 py-3 bg-[var(--surface-base)]">
		<button onclick={() => $sidebarOpen = !$sidebarOpen} class="text-[var(--text-secondary)] hover:text-white transition-colors">
			<Menu class="w-5 h-5" />
		</button>
		<div class="flex items-center gap-2">
			<img src="/favicon.svg" alt="Zonik" class="w-6 h-6 rounded" />
			<span class="font-bold text-sm text-[var(--text-primary)]">Zonik</span>
		</div>
		<div class="w-5"></div>
	</div>

	<div class="flex flex-1 overflow-hidden">
		<Sidebar />
		<div class="flex-1 flex flex-col overflow-hidden">
			<!-- Top bar with search -->
			<div class="flex items-center gap-3 px-4 md:px-6 py-3 bg-[var(--surface-base)] shrink-0">
				<TopBar />
			</div>
			<main class="flex-1 overflow-y-auto p-4 md:p-6">
				<div class="animate-fade-in">
					{#if blocked}
						<AdminsOnly />
					{:else}
						{@render children()}
					{/if}
				</div>
			</main>
			<!-- In the content column, not under the whole window, so the sidebar keeps the full
			     height and its last links (Logs, Settings) aren't pushed out of view. -->
			<Player />
		</div>
	</div>
	<Toast />
</div>

{#if $currentUser?.must_change_password}
	<ChangePasswordModal />
{/if}
{/if}
