<script>
	import { api } from '$lib/api.js';
	import { addToast } from '$lib/stores.js';
	import { formatSize } from '$lib/utils.js';

	let artist = $state('');
	let track = $state('');
	let results = $state([]);
	let searching = $state(false);
	let downloading = $state({});

	async function searchSoulseek() {
		if (!artist.trim() || !track.trim()) return;
		searching = true;
		results = [];
		try {
			const data = await fetch('/api/download/search', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ artist: artist.trim(), track: track.trim() })
			}).then(r => r.json());
			results = data.results || [];
			if (!results.length) addToast('No results found', 'warning');
		} catch (e) {
			addToast('Search failed: ' + e.message, 'error');
		} finally {
			searching = false;
		}
	}

	async function downloadFile(result) {
		const key = result.username + result.filename;
		downloading[key] = true;
		try {
			const data = await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					artist: artist.trim(),
					track: track.trim(),
					username: result.username,
					filename: result.filename,
				})
			}).then(r => r.json());
			addToast('Download started', 'success');
		} catch (e) {
			addToast('Download failed: ' + e.message, 'error');
		} finally {
			downloading[key] = false;
		}
	}

	async function autoDownload() {
		try {
			const data = await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ artist: artist.trim(), track: track.trim() })
			}).then(r => r.json());
			addToast('Auto-download started (best result)', 'success');
		} catch (e) {
			addToast('Download failed: ' + e.message, 'error');
		}
	}

	function handleKeydown(e) {
		if (e.key === 'Enter') searchSoulseek();
	}
</script>

<div class="max-w-6xl">
	<h1 class="text-2xl font-bold mb-6">Downloads</h1>

	<div class="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-6">
		<h2 class="text-lg font-semibold mb-4">Soulseek Search</h2>
		<div class="flex gap-3 mb-4">
			<input type="text" placeholder="Artist" bind:value={artist} on:keydown={handleKeydown}
				class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
					focus:outline-none focus:border-accent-500" />
			<input type="text" placeholder="Track" bind:value={track} on:keydown={handleKeydown}
				class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
					focus:outline-none focus:border-accent-500" />
			<button on:click={searchSoulseek} disabled={searching || !artist || !track}
				class="px-4 py-2 bg-accent-600 hover:bg-accent-700 rounded-lg text-sm font-medium
					disabled:opacity-50 transition whitespace-nowrap">
				{searching ? 'Searching...' : 'Search'}
			</button>
			<button on:click={autoDownload} disabled={!artist || !track}
				class="px-4 py-2 bg-green-700 hover:bg-green-800 rounded-lg text-sm font-medium
					disabled:opacity-50 transition whitespace-nowrap">
				Auto
			</button>
		</div>

		{#if results.length}
			<div class="border border-gray-800 rounded-lg overflow-hidden">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-gray-800 text-gray-400 text-left">
							<th class="px-4 py-2">File</th>
							<th class="px-4 py-2">User</th>
							<th class="px-4 py-2">Format</th>
							<th class="px-4 py-2">Size</th>
							<th class="px-4 py-2">Bitrate</th>
							<th class="px-4 py-2"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-800/50">
						{#each results as r}
							{@const key = r.username + r.filename}
							<tr class="hover:bg-gray-800/50">
								<td class="px-4 py-2 max-w-xs truncate" title={r.filename}>
									{r.filename.split(/[/\\]/).pop()}
								</td>
								<td class="px-4 py-2 text-gray-400">{r.username}</td>
								<td class="px-4 py-2">
									<span class="px-2 py-0.5 bg-gray-800 rounded text-xs uppercase">{r.extension}</span>
								</td>
								<td class="px-4 py-2 text-gray-400">{formatSize(r.size)}</td>
								<td class="px-4 py-2 text-gray-400">{r.bitRate ? r.bitRate + ' kbps' : '-'}</td>
								<td class="px-4 py-2">
									<button on:click={() => downloadFile(r)}
										disabled={downloading[key]}
										class="px-3 py-1 bg-green-700 hover:bg-green-800 rounded text-xs
											disabled:opacity-50 transition">
										{downloading[key] ? '...' : 'Download'}
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</div>
