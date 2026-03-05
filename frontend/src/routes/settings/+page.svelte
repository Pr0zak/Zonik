<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';

	let stats = $state(null);
	let testResults = $state({});
	let services = $state({
		slskd_url: '',
		slskd_api_key: '',
		download_dir: '',
		lidarr_url: '',
		lidarr_api_key: '',
		lastfm_api_key: '',
		lastfm_write_api_key: '',
		lastfm_write_api_secret: '',
		cover_cache_dir: '',
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
		testResults[service] = { status: 'testing', message: 'Testing...' };
		testResults = { ...testResults };
		try {
			if (service === 'subsonic') {
				const data = await fetch('/rest/ping?f=json').then(r => r.json());
				const ok = data['subsonic-response']?.status === 'ok';
				testResults[service] = { status: ok ? 'ok' : 'error', message: ok ? 'Connected' : 'Failed' };
			} else {
				if (dirty) await saveServices();
				const data = await fetch(`/api/config/test/${service}`, { method: 'POST' }).then(r => r.json());
				testResults[service] = { status: data.status, message: data.status === 'ok' ? 'Connected' : data.message || 'Failed' };
			}
		} catch (e) {
			testResults[service] = { status: 'error', message: e.message };
		}
		testResults = { ...testResults };
	}

	function testBtnClass(service) {
		const r = testResults[service];
		if (!r) return 'bg-gray-800 hover:bg-gray-700 text-gray-300';
		if (r.status === 'testing') return 'bg-yellow-800 text-yellow-200';
		if (r.status === 'ok') return 'bg-green-800 text-green-200';
		return 'bg-red-800 text-red-200';
	}

	function testBtnLabel(service, fallback) {
		const r = testResults[service];
		if (!r) return fallback;
		return r.message;
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
			<div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
				<div>
					<label class="block text-xs text-gray-500 mb-1">Download Directory</label>
					<input type="text" bind:value={services.download_dir} on:input={markDirty}
						placeholder="/music/Downloads"
						class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm
							focus:outline-none focus:border-accent-500" />
				</div>
				<div>
					<label class="block text-xs text-gray-500 mb-1">Cover Art Cache</label>
					<input type="text" bind:value={services.cover_cache_dir} on:input={markDirty}
						placeholder="/opt/zonik/cache/covers"
						class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm
							focus:outline-none focus:border-accent-500" />
				</div>
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
							class="px-2 py-0.5 rounded text-xs transition {testBtnClass('soulseek')}">
							{testBtnLabel('soulseek', 'Test')}
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
					<div class="flex items-center justify-between mb-2">
						<h3 class="text-sm font-medium">Lidarr</h3>
						<button on:click={() => testConnection('lidarr')}
							class="px-2 py-0.5 rounded text-xs transition {testBtnClass('lidarr')}">
							{testBtnLabel('lidarr', 'Test')}
						</button>
					</div>
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
							class="px-2 py-0.5 rounded text-xs transition {testBtnClass('lastfm')}">
							{testBtnLabel('lastfm', 'Test')}
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
					class="px-2 py-0.5 rounded text-xs transition {testBtnClass('subsonic')}">
					{testBtnLabel('subsonic', 'Test')}
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
