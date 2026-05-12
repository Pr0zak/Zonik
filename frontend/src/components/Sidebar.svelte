<script>
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { sidebarOpen, updateAvailable, activeJobs, activeTransfers } from '$lib/stores.js';
	import { Loader2 } from 'lucide-svelte';
	import {
		LayoutDashboard, Library, Compass, Download, ListMusic,
		Heart, AudioWaveform, BarChart3, Clock, ScrollText, Settings, Github, Network, Copy, ArrowUpCircle, Radio
	} from 'lucide-svelte';

	let currentTransfer = $derived($activeTransfers.find(t => t.state === 'transferring') || null);
	let appVersion = $state('');

	onMount(async () => {
		try {
			const data = await fetch('/api/config/version').then(r => r.json());
			appVersion = data.version || '';
		} catch {}
	});

	const navGroups = [
		{
			label: 'Library',
			items: [
				{ href: '/', label: 'Dashboard', icon: LayoutDashboard, color: 'var(--color-dashboard)' },
				{ href: '/library', label: 'Tracks', icon: Library, color: 'var(--color-library)' },
				{ href: '/favorites', label: 'Favorites', icon: Heart, color: 'var(--color-favorites)' },
				{ href: '/stats', label: 'Stats', icon: BarChart3, color: 'var(--color-stats)' },
			]
		},
		{
			label: 'Discover',
			items: [
				{ href: '/discover', label: 'Discover', icon: Compass, color: 'var(--color-discover)' },
				{ href: '/map', label: 'Music Map', icon: Network, color: 'var(--color-map)' },
				{ href: '/analysis', label: 'Analysis', icon: AudioWaveform, color: 'var(--color-analysis)' },
			]
		},
		{
			label: 'Activity',
			items: [
				{ href: '/live', label: 'Live', icon: Radio, color: 'var(--color-live)' },
			]
		},
		{
			label: 'Manage',
			items: [
				{ href: '/downloads', label: 'Downloads', icon: Download, color: 'var(--color-downloads)' },
				{ href: '/playlists', label: 'Playlists', icon: ListMusic, color: 'var(--color-playlists)' },
				{ href: '/duplicates', label: 'Duplicates', icon: Copy, color: 'var(--color-duplicates)' },
				{ href: '/upgrades', label: 'Upgrades', icon: ArrowUpCircle, color: 'var(--color-upgrades)' },
			]
		},
		{
			label: 'System',
			items: [
				{ href: '/schedule', label: 'Schedule', icon: Clock, color: 'var(--color-schedule)' },
				{ href: '/logs', label: 'Logs', icon: ScrollText, color: 'var(--color-logs)' },
				{ href: '/settings', label: 'Settings', icon: Settings, color: 'var(--color-settings)' },
			]
		},
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
	<div class="fixed inset-0 glass-subtle z-40 md:hidden" onclick={() => $sidebarOpen = false}
		role="presentation"></div>
{/if}

<aside class="{$sidebarOpen ? '' : 'hidden'} w-[80vw] max-w-64 bg-[var(--surface-container-low)] flex flex-col h-full shrink-0
	fixed inset-y-0 left-0 z-50 md:static md:z-auto md:w-64 md:max-w-none">

	<!-- Logo -->
	<div class="px-5 pt-6 pb-5">
		<h1 class="text-3xl font-bold tracking-editorial"><span class="bg-gradient-primary bg-clip-text text-transparent">Z</span><span class="text-[var(--text-primary)]">ONIK</span></h1>
		<p class="text-xs font-mono text-[var(--text-disabled)] uppercase tracking-wider mt-0.5">Music Backend</p>
	</div>

	<nav class="flex-1 px-3 overflow-y-auto space-y-5">
		{#each navGroups as group}
			<div>
				<p class="px-3 mb-1.5 text-[10px] font-medium uppercase tracking-widest text-[var(--text-muted)]">{group.label}</p>
				<div class="space-y-0.5">
					{#each group.items as item}
						{@const active = isActive($page.url.pathname, item.href)}
						{@const Icon = item.icon}
						<a href={item.href}
							onclick={() => { if (window.innerWidth < 768) $sidebarOpen = false; }}
							class="group flex items-center gap-3 px-3 py-2 text-sm transition-all duration-200 rounded-md relative
								{active
									? 'text-[var(--text-primary)] bg-[var(--surface-container-high)]'
									: 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container)]'}"
						>
							{#if active}
								<div class="absolute left-0 top-1/2 -translate-y-1/2 w-[2px] h-4 rounded-r" style="background: {item.color}; box-shadow: 0 0 8px {item.color};"></div>
							{/if}
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
				</div>
			</div>
		{/each}
	</nav>

	<!-- Footer -->
	<div class="px-5 py-4">
		{#if currentTransfer}
			<a href="/downloads" class="block mb-2 -mx-2 px-2 py-1.5 hover:bg-white/5 rounded transition-colors"
				onclick={() => { if (window.innerWidth < 768) $sidebarOpen = false; }}>
				<div class="flex items-center gap-2 mb-1">
					<Download class="w-3 h-3 text-[var(--color-downloads)] flex-shrink-0" />
					<span class="text-xs text-[var(--text-primary)] truncate flex-1">
						{currentTransfer.filename?.split(/[/\\]/).pop() || 'Downloading...'}
					</span>
					<span class="text-xs text-[var(--color-downloads)] font-mono flex-shrink-0">{currentTransfer.progress || 0}%</span>
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
						<p class="text-xs text-[var(--text-muted)] truncate">{$activeJobs[0].type.replace('_', ' ')}{$activeJobs[0].total ? ` ${$activeJobs[0].progress || 0}/${$activeJobs[0].total}` : ''}</p>
					{/if}
				</div>
			</a>
		{/if}
		<div class="flex items-center justify-between">
			<p class="text-xs font-mono text-[var(--text-disabled)]">{appVersion ? `v${appVersion}` : 'OpenSubsonic'}</p>
			<a href="https://github.com/Pr0zak/Zonik" target="_blank" rel="noopener noreferrer"
				class="flex items-center gap-1.5 text-[var(--text-disabled)] hover:text-[var(--text-secondary)] transition-colors group" title="View on GitHub">
				<Github class="w-3.5 h-3.5 group-hover:text-white transition-colors" />
			</a>
		</div>
	</div>
</aside>
