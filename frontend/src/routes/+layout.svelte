<script>
	import '../app.css';
	import Sidebar from '../components/Sidebar.svelte';
	import TopBar from '../components/TopBar.svelte';
	import Player from '../components/Player.svelte';
	import Toast from '../components/Toast.svelte';
	import { onMount, onDestroy } from 'svelte';
	import { connectWebSocket, disconnectWebSocket } from '$lib/websocket.js';
	import { goto } from '$app/navigation';
	import { Menu } from 'lucide-svelte';
	import { sidebarOpen, isPlaying, showShortcuts, playNext, playPrev } from '$lib/stores.js';

	let { children } = $props();

	onMount(() => {
		connectWebSocket();
		if (window.innerWidth < 768) {
			$sidebarOpen = false;
		}
	});

	onDestroy(() => {
		disconnectWebSocket();
	});

	function handleKeydown(event) {
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

{#if $showShortcuts}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center"
		onclick={() => $showShortcuts = false}
		role="dialog">
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="bg-[var(--bg-secondary)] border border-[var(--border-subtle)] rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl animate-fade-slide-in"
			onclick={(e) => e.stopPropagation()}>
			<h2 class="text-lg font-bold text-[var(--text-primary)] mb-4">Keyboard Shortcuts</h2>
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
								<kbd class="px-2 py-0.5 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded text-xs font-mono text-[var(--text-muted)]">{key}</kbd>
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
								<kbd class="px-2 py-0.5 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded text-xs font-mono text-[var(--text-muted)]">{key}</kbd>
							</div>
						{/each}
					</div>
				</div>
			</div>
			<p class="mt-4 text-xs text-[var(--text-disabled)]">Press <kbd class="px-1 py-0.5 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded text-[10px] font-mono">?</kbd> to toggle this help</p>
		</div>
	</div>
{/if}

<div class="h-screen flex flex-col bg-[var(--bg-primary)]">
	<!-- Mobile header -->
	<div class="md:hidden flex items-center justify-between px-4 py-3 bg-[var(--bg-primary)] border-b border-[var(--border-subtle)]">
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
			<div class="flex items-center gap-3 px-4 md:px-6 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-primary)] shrink-0">
				<TopBar />
			</div>
			<main class="flex-1 overflow-y-auto p-4 md:p-6">
				<div class="animate-fade-in">
					{@render children()}
				</div>
			</main>
		</div>
	</div>
	<Player />
	<Toast />
</div>
