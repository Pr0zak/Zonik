<script>
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { sidebarOpen, updateAvailable } from '$lib/stores.js';

	const nav = [
		{ href: '/', label: 'Dashboard', icon: '⌂' },
		{ href: '/library', label: 'Library', icon: '♫' },
		{ href: '/discover', label: 'Discover', icon: '✦' },
		{ href: '/downloads', label: 'Downloads', icon: '↓' },
		{ href: '/playlists', label: 'Playlists', icon: '≡' },
		{ href: '/favorites', label: 'Favorites', icon: '★' },
		{ href: '/analysis', label: 'Analysis', icon: '~' },
		{ href: '/stats', label: 'Stats', icon: '◩' },
		{ href: '/schedule', label: 'Schedule', icon: '⏱' },
		{ href: '/logs', label: 'Logs', icon: '▤' },
		{ href: '/settings', label: 'Settings', icon: '⚙' },
	];

	onMount(async () => {
		try {
			const data = await fetch('/api/config/updates').then(r => r.json());
			$updateAvailable = data.update_available || false;
		} catch {
			// ignore
		}
	});
</script>

<aside class="w-56 bg-gray-900 border-r border-gray-800 flex flex-col h-full shrink-0"
	class:hidden={!$sidebarOpen}>
	<div class="p-4 border-b border-gray-800">
		<h1 class="text-xl font-bold text-accent-500">Zonik</h1>
	</div>
	<nav class="flex-1 p-2 space-y-0.5 overflow-y-auto">
		{#each nav as item}
			<a href={item.href}
				class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors
					{$page.url.pathname === item.href
						? 'bg-accent-700/20 text-accent-400'
						: 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'}">
				<span class="text-base w-5 text-center">{item.icon}</span>
				<span class="flex-1">{item.label}</span>
				{#if item.href === '/settings' && $updateAvailable}
					<span class="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" title="Update available"></span>
				{/if}
			</a>
		{/each}
	</nav>
</aside>
