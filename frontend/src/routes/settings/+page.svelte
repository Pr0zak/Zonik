<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';

	let stats = $state(null);
	let testResults = $state({});

	onMount(async () => {
		try {
			stats = await fetch('/api/library/stats').then(r => r.json());
		} catch (e) {
			console.error(e);
		}
	});

	async function testConnection(service) {
		testResults[service] = 'testing...';
		testResults = { ...testResults };
		try {
			if (service === 'subsonic') {
				const data = await fetch('/rest/ping?f=json').then(r => r.json());
				testResults[service] = data['subsonic-response']?.status === 'ok' ? 'Connected' : 'Failed';
			} else if (service === 'soulseek') {
				const data = await fetch('/api/download/status').then(r => r.json());
				testResults[service] = 'Connected';
			} else if (service === 'lastfm') {
				const data = await fetch('/api/discovery/top-tracks?limit=1').then(r => r.json());
				testResults[service] = data.tracks?.length ? 'Connected' : 'No data';
			}
		} catch (e) {
			testResults[service] = 'Failed: ' + e.message;
		}
		testResults = { ...testResults };
	}
</script>

<div class="max-w-4xl">
	<h1 class="text-2xl font-bold mb-6">Settings</h1>

	<div class="space-y-6">
		<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
			<h2 class="text-lg font-semibold mb-4">Library</h2>
			<div class="space-y-3 text-sm">
				<div class="flex items-center justify-between">
					<span class="text-gray-400">Music Directory</span>
					<span class="font-mono text-xs">Configured in zonik.toml</span>
				</div>
				{#if stats}
					<div class="flex items-center justify-between">
						<span class="text-gray-400">Tracks</span>
						<span>{stats.tracks?.toLocaleString()}</span>
					</div>
					<div class="flex items-center justify-between">
						<span class="text-gray-400">Artists</span>
						<span>{stats.artists?.toLocaleString()}</span>
					</div>
					<div class="flex items-center justify-between">
						<span class="text-gray-400">Albums</span>
						<span>{stats.albums?.toLocaleString()}</span>
					</div>
				{/if}
			</div>
		</div>

		<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
			<h2 class="text-lg font-semibold mb-4">Connections</h2>
			<div class="space-y-4">
				{#each [
					{ key: 'subsonic', label: 'Subsonic API', desc: '/rest/* endpoints' },
					{ key: 'soulseek', label: 'Soulseek (slskd)', desc: 'P2P music search & download' },
					{ key: 'lastfm', label: 'Last.fm', desc: 'Discovery, scrobbling, metadata' },
				] as svc}
					<div class="flex items-center justify-between">
						<div>
							<p class="font-medium text-sm">{svc.label}</p>
							<p class="text-xs text-gray-500">{svc.desc}</p>
						</div>
						<div class="flex items-center gap-3">
							{#if testResults[svc.key]}
								<span class="text-xs {testResults[svc.key].startsWith('Connected') ? 'text-green-400' : 'text-red-400'}">
									{testResults[svc.key]}
								</span>
							{/if}
							<button on:click={() => testConnection(svc.key)}
								class="px-3 py-1 bg-gray-800 hover:bg-gray-700 rounded text-xs transition">
								Test
							</button>
						</div>
					</div>
				{/each}
			</div>
		</div>

		<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
			<h2 class="text-lg font-semibold mb-4">Subsonic</h2>
			<div class="space-y-3 text-sm">
				<div class="flex items-center justify-between">
					<span class="text-gray-400">Server Name</span>
					<span>Zonik</span>
				</div>
				<div class="flex items-center justify-between">
					<span class="text-gray-400">API Version</span>
					<span>1.16.1 (OpenSubsonic)</span>
				</div>
				<div class="flex items-center justify-between">
					<span class="text-gray-400">Default User</span>
					<code class="text-accent-400 text-xs">admin / admin</code>
				</div>
				<div class="flex items-center justify-between">
					<span class="text-gray-400">Endpoint</span>
					<code class="text-accent-400 text-xs">/rest/*</code>
				</div>
			</div>
		</div>

		<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
			<h2 class="text-lg font-semibold mb-4">About</h2>
			<div class="space-y-2 text-sm text-gray-400">
				<p>Zonik v0.1.0</p>
				<p>Self-hosted music backend with OpenSubsonic API</p>
				<p>FastAPI + SQLite + SvelteKit</p>
			</div>
		</div>
	</div>
</div>
