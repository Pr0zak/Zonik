<script>
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { sidebarOpen, updateAvailable, activeJobs, activeTransfers } from '$lib/stores.js';
	import { Loader2 } from 'lucide-svelte';
	import {
		LayoutDashboard, Library, Compass, Download, ListMusic,
		Heart, AudioWaveform, BarChart3, Clock, ScrollText, Settings, Github, Network
	} from 'lucide-svelte';

	let currentTransfer = $derived($activeTransfers.find(t => t.state === 'transferring') || null);

	const nav = [
		{ href: '/', label: 'Dashboard', icon: LayoutDashboard, color: 'var(--color-dashboard)' },
		{ href: '/library', label: 'Library', icon: Library, color: 'var(--color-library)' },
		{ href: '/discover', label: 'Discover', icon: Compass, color: 'var(--color-discover)' },
		{ href: '/downloads', label: 'Downloads', icon: Download, color: 'var(--color-downloads)' },
		{ href: '/playlists', label: 'Playlists', icon: ListMusic, color: 'var(--color-playlists)' },
		{ href: '/favorites', label: 'Favorites', icon: Heart, color: 'var(--color-favorites)' },
		{ href: '/analysis', label: 'Analysis', icon: AudioWaveform, color: 'var(--color-analysis)' },
		{ href: '/map', label: 'Music Map', icon: Network, color: 'var(--color-map)' },
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
	<div class="px-5 pt-6 pb-5">
		<h1 class="text-3xl font-bold tracking-[0.15em]"><span class="text-[var(--color-accent)]">Z</span><span class="text-[var(--text-primary)]">ONIK</span></h1>
		<p class="text-[10px] font-mono text-[var(--text-disabled)] uppercase tracking-wider mt-0.5">Music Backend</p>
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
		{#if currentTransfer}
			<a href="/downloads" class="block mb-2 -mx-2 px-2 py-1.5 hover:bg-white/5 rounded transition-colors"
				onclick={() => { if (window.innerWidth < 768) $sidebarOpen = false; }}>
				<div class="flex items-center gap-2 mb-1">
					<Download class="w-3 h-3 text-[var(--color-downloads)] flex-shrink-0" />
					<span class="text-[10px] text-[var(--text-primary)] truncate flex-1">
						{currentTransfer.filename?.split(/[/\\]/).pop() || 'Downloading...'}
					</span>
					<span class="text-[10px] text-[var(--color-downloads)] font-mono flex-shrink-0">{currentTransfer.progress || 0}%</span>
				</div>
				<div class="h-0.5 bg-[var(--border-interactive)] rounded-full overflow-hidden">
					<div class="h-full bg-[var(--color-downloads)] rounded-full transition-all duration-300"
						style="width: {currentTransfer.progress || 0}%"></div>
				</div>
			</a>
		{/if}
		{#if $activeJobs.length > 0}
			<a href="/logs" class="flex items-center gap-2 mb-2 hover:bg-white/5 -mx-2 px-2 py-1 rounded transition-colors"
				onclick={() => { if (window.innerWidth < 768) $sidebarOpen = false; }}>
				<Loader2 class="w-3.5 h-3.5 text-[var(--color-info)] animate-spin" />
				<div class="flex-1 min-w-0">
					<span class="text-xs text-[var(--color-info)]">{$activeJobs.length} active job{$activeJobs.length > 1 ? 's' : ''}</span>
					{#if $activeJobs[0]}
						<p class="text-[10px] text-[var(--text-muted)] truncate">{$activeJobs[0].type.replace('_', ' ')}{$activeJobs[0].total ? ` ${$activeJobs[0].progress || 0}/${$activeJobs[0].total}` : ''}</p>
					{/if}
				</div>
			</a>
		{/if}
		<div class="flex items-center justify-between">
			<p class="text-[10px] font-mono text-[var(--text-disabled)]">OpenSubsonic</p>
			<a href="https://github.com/Pr0zak/Zonik" target="_blank" rel="noopener noreferrer"
				class="flex items-center gap-1.5 text-[var(--text-disabled)] hover:text-[var(--text-secondary)] transition-colors group" title="View on GitHub">
				<Github class="w-3.5 h-3.5 group-hover:text-white transition-colors" />
			</a>
		</div>
	</div>
</aside>
