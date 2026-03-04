<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';

	let stats = $state(null);
	let testResults = $state({});
	let services = $state({
		slskd_url: '',
		slskd_api_key: '',
		lidarr_url: '',
		lidarr_api_key: '',
		lastfm_api_key: '',
		lastfm_write_api_key: '',
		lastfm_write_api_secret: '',
	});
	let saving = $state(false);
	let dirty = $state(false);

	onMount(async () => {
		try {
			const [statsData, svcData] = await Promise.all([
				fetch('/api/library/stats').then(r => r.json()),
				fetch('/api/config/services').then(r => r.json()),
			]);
			stats = statsData;
			services = svcData;
		} catch (e) {
			console.error(e);
		}
	});

	function markDirty() {
		dirty = true;
	}

	async function saveServices() {
		saving = true;
		try {
			const resp = await fetch('/api/config/services', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(services),
			});
			if (resp.ok) {
				addToast('Settings saved', 'success');
				dirty = false;
				// Reload to get masked keys
				const svcData = await fetch('/api/config/services').then(r => r.json());
				services = svcData;
			} else {
				addToast('Failed to save settings', 'error');
			}
		} catch (e) {
			addToast('Failed to save: ' + e.message, 'error');
		} finally {
			saving = false;
		}
	}

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
		<!-- Library -->
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

		<!-- Service Connections (editable) -->
		<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-lg font-semibold">Service Connections</h2>
				<button on:click={saveServices} disabled={saving || !dirty}
					class="px-4 py-1.5 bg-accent-600 hover:bg-accent-700 disabled:opacity-50
						rounded text-xs font-medium transition">
					{saving ? 'Saving...' : 'Save'}
				</button>
			</div>

			<div class="space-y-5">
				<!-- slskd -->
				<div>
					<div class="flex items-center justify-between mb-2">
						<h3 class="text-sm font-medium">Soulseek (slskd)</h3>
						<button on:click={() => testConnection('soulseek')}
							class="px-2 py-0.5 bg-gray-800 hover:bg-gray-700 rounded text-xs transition">
							{testResults.soulseek || 'Test'}
						</button>
					</div>
					<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
						<div>
							<label class="block text-xs text-gray-500 mb-1">URL</label>
							<input type="text" bind:value={services.slskd_url} on:input={markDirty}
								placeholder="http://host:5030"
								class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm
									focus:outline-none focus:border-accent-500" />
						</div>
						<div>
							<label class="block text-xs text-gray-500 mb-1">API Key</label>
							<input type="password" bind:value={services.slskd_api_key} on:input={markDirty}
								placeholder="slskd API key"
								class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm
									focus:outline-none focus:border-accent-500" />
						</div>
					</div>
				</div>

				<!-- Lidarr -->
				<div>
					<h3 class="text-sm font-medium mb-2">Lidarr</h3>
					<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
						<div>
							<label class="block text-xs text-gray-500 mb-1">URL</label>
							<input type="text" bind:value={services.lidarr_url} on:input={markDirty}
								placeholder="http://host:8686"
								class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm
									focus:outline-none focus:border-accent-500" />
						</div>
						<div>
							<label class="block text-xs text-gray-500 mb-1">API Key</label>
							<input type="password" bind:value={services.lidarr_api_key} on:input={markDirty}
								placeholder="Lidarr API key"
								class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm
									focus:outline-none focus:border-accent-500" />
						</div>
					</div>
				</div>

				<!-- Last.fm -->
				<div>
					<div class="flex items-center justify-between mb-2">
						<h3 class="text-sm font-medium">Last.fm</h3>
						<button on:click={() => testConnection('lastfm')}
							class="px-2 py-0.5 bg-gray-800 hover:bg-gray-700 rounded text-xs transition">
							{testResults.lastfm || 'Test'}
						</button>
					</div>
					<div class="grid grid-cols-1 md:grid-cols-3 gap-3">
						<div>
							<label class="block text-xs text-gray-500 mb-1">Read API Key</label>
							<input type="password" bind:value={services.lastfm_api_key} on:input={markDirty}
								placeholder="Last.fm API key"
								class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm
									focus:outline-none focus:border-accent-500" />
						</div>
						<div>
							<label class="block text-xs text-gray-500 mb-1">Write API Key</label>
							<input type="password" bind:value={services.lastfm_write_api_key} on:input={markDirty}
								placeholder="Write API key"
								class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm
									focus:outline-none focus:border-accent-500" />
						</div>
						<div>
							<label class="block text-xs text-gray-500 mb-1">Write API Secret</label>
							<input type="password" bind:value={services.lastfm_write_api_secret} on:input={markDirty}
								placeholder="Write API secret"
								class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm
									focus:outline-none focus:border-accent-500" />
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Subsonic -->
		<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-lg font-semibold">Subsonic</h2>
				<button on:click={() => testConnection('subsonic')}
					class="px-2 py-0.5 bg-gray-800 hover:bg-gray-700 rounded text-xs transition">
					{testResults.subsonic || 'Test'}
				</button>
			</div>
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

		<!-- About -->
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
