<script>
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { sidebarOpen, updateAvailable, activeJobs } from '$lib/stores.js';
	import { Loader2 } from 'lucide-svelte';
	import {
		LayoutDashboard, Library, Compass, Download, ListMusic,
		Heart, AudioWaveform, BarChart3, Clock, ScrollText, Settings
	} from 'lucide-svelte';

	const nav = [
		{ href: '/', label: 'Dashboard', icon: LayoutDashboard, color: 'var(--color-dashboard)' },
		{ href: '/library', label: 'Library', icon: Library, color: 'var(--color-library)' },
		{ href: '/discover', label: 'Discover', icon: Compass, color: 'var(--color-discover)' },
		{ href: '/downloads', label: 'Downloads', icon: Download, color: 'var(--color-downloads)' },
		{ href: '/playlists', label: 'Playlists', icon: ListMusic, color: 'var(--color-playlists)' },
		{ href: '/favorites', label: 'Favorites', icon: Heart, color: 'var(--color-favorites)' },
		{ href: '/analysis', label: 'Analysis', icon: AudioWaveform, color: 'var(--color-analysis)' },
		{ href: '/stats', label: 'Stats', icon: BarChart3, color: 'var(--color-stats)' },
		{ href: '/schedule', label: 'Schedule', icon: Clock, color: 'var(--color-schedule)' },
		{ href: '/logs', label: 'Logs', icon: ScrollText, color: 'var(--color-logs)' },
		{ href: '/settings', label: 'Settings', icon: Settings, color: 'var(--color-settings)' },
	];

	function isActive(pathname, href) {
		if (href === '/') return pathname === '/';
		return pathname.startsWith(href);
	}

	onMount(async () => {
		try {
			const data = await fetch('/api/config/updates').then(r => r.json());
			$updateAvailable = data.update_available || false;
		} catch {
			// ignore
		}
	});
</script>

<aside class="w-64 bg-[var(--bg-primary)] flex flex-col h-full shrink-0 border-r border-[var(--border-subtle)]"
	class:hidden={!$sidebarOpen}>

	<!-- Logo -->
	<div class="px-5 pt-6 pb-4">
		<div class="flex items-center gap-2.5">
			<img src="/favicon.svg" alt="Zonik" class="w-8 h-8 rounded-lg" />
			<div>
				<h1 class="text-base font-bold text-[var(--text-primary)] tracking-tight">Zonik</h1>
				<p class="text-[10px] font-mono text-[var(--text-disabled)] uppercase tracking-wider">Music Backend</p>
			</div>
		</div>
	</div>

	<!-- Navigation -->
	<div class="px-3 mb-2">
		<div class="flex items-center gap-2 px-2 mb-2">
			<div class="w-1.5 h-1.5 rounded-full bg-[var(--color-success)]"></div>
			<span class="text-[10px] font-mono font-bold uppercase tracking-wider text-[var(--text-disabled)]">Navigation</span>
		</div>
	</div>

	<nav class="flex-1 px-3 space-y-0.5 overflow-y-auto">
		{#each nav as item, i}
			{@const active = isActive($page.url.pathname, item.href)}
			<a href={item.href}
				class="group flex items-center gap-3 px-3 py-2 text-sm transition-all duration-200 border-l-2 rounded-r-md
					{active
						? 'text-white bg-[var(--bg-primary)]'
						: 'text-[var(--text-secondary)] hover:text-white hover:bg-white/5 border-transparent hover:border-white/20'}"
				style={active ? `border-color: ${item.color}` : ''}
			>
				<svelte:component this={item.icon}
					class="w-4 h-4 shrink-0 transition-colors"
					style={active ? `color: ${item.color}` : ''}
				/>
				<span class="flex-1 font-medium">{item.label}</span>
				{#if item.href === '/settings' && $updateAvailable}
					<span class="w-2 h-2 rounded-full bg-[var(--color-warning)] animate-pulse" title="Update available"></span>
				{/if}
			</a>
		{/each}
	</nav>

	<!-- Footer -->
	<div class="px-5 py-4 border-t border-[var(--border-subtle)]">
		{#if $activeJobs.length > 0}
			<div class="flex items-center gap-2 mb-2">
				<Loader2 class="w-3.5 h-3.5 text-[var(--color-info)] animate-spin" />
				<span class="text-xs text-[var(--color-info)]">{$activeJobs.length} active job{$activeJobs.length > 1 ? 's' : ''}</span>
			</div>
		{/if}
		<p class="text-[10px] font-mono text-[var(--text-disabled)]">OpenSubsonic</p>
	</div>
</aside>
