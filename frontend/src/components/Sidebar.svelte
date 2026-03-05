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

<!-- Mobile backdrop -->
{#if $sidebarOpen}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div class="fixed inset-0 bg-black/50 z-40 md:hidden" onclick={() => $sidebarOpen = false}
		role="presentation"></div>
{/if}

<aside class="{$sidebarOpen ? '' : 'hidden'} w-64 bg-[var(--bg-primary)] flex flex-col h-full shrink-0 border-r border-[var(--border-subtle)]
	fixed inset-y-0 left-0 z-50 md:static md:z-auto">

	<!-- Logo -->
	<div class="px-5 pt-6 pb-4">
		<div>
			<h1 class="text-base font-bold tracking-tight"><span class="text-[var(--color-accent)]">Z</span><span class="text-[var(--text-primary)]">ONIK</span></h1>
			<p class="text-[10px] font-mono text-[var(--text-disabled)] uppercase tracking-wider">Music Backend</p>
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
			{@const Icon = item.icon}
			<a href={item.href}
				onclick={() => { if (window.innerWidth < 768) $sidebarOpen = false; }}
				class="group flex items-center gap-3 px-3 py-2 text-sm transition-all duration-200 border-l-2 rounded-r-md
					{active
						? 'text-white bg-[var(--bg-primary)]'
						: 'text-[var(--text-secondary)] hover:text-white hover:bg-white/5 border-transparent hover:border-white/20'}"
				style={active ? `border-color: ${item.color}` : ''}
			>
				<Icon
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
