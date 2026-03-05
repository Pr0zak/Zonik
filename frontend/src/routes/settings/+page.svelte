<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { Settings, Eye, EyeOff, Wifi, RefreshCw } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';

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
	let showField = $state({});

	let versionInfo = $state(null);
	let updateInfo = $state(null);
	let checkingUpdates = $state(false);
	let upgradeJobId = $state(null);
	let upgradeJob = $state(null);
	let upgrading = $state(false);

	onMount(async () => {
		try {
			const [statsData, svcData, verData] = await Promise.all([
				fetch('/api/library/stats').then(r => r.json()),
				fetch('/api/config/services').then(r => r.json()),
				fetch('/api/config/version').then(r => r.json()),
			]);
			stats = statsData;
			services = svcData;
			versionInfo = verData;
		} catch (e) {
			console.error(e);
		}
	});

	async function checkForUpdates() {
		checkingUpdates = true;
		updateInfo = null;
		try {
			const data = await fetch('/api/config/updates').then(r => r.json());
			updateInfo = data;
		} catch (e) {
			addToast('Failed to check for updates: ' + e.message, 'error');
		} finally {
			checkingUpdates = false;
		}
	}

	async function triggerUpgrade() {
		upgrading = true;
		try {
			const data = await fetch('/api/config/upgrade', { method: 'POST' }).then(r => r.json());
			if (data.error) {
				addToast(data.error, 'error');
				upgrading = false;
				return;
			}
			upgradeJobId = data.job_id;
			pollUpgradeJob();
		} catch (e) {
			addToast('Failed to start upgrade: ' + e.message, 'error');
			upgrading = false;
		}
	}

	function pollUpgradeJob() {
		if (!upgradeJobId) return;
		let failCount = 0;
		const interval = setInterval(async () => {
			try {
				const data = await fetch(`/api/jobs/${upgradeJobId}`).then(r => r.json());
				upgradeJob = data;
				failCount = 0;
				if (data.status === 'completed' || data.status === 'failed') {
					clearInterval(interval);
					upgrading = false;
					if (data.status === 'completed') {
						addToast('Upgrade completed! Reloading...', 'success');
						setTimeout(() => window.location.reload(), 5000);
					} else {
						addToast('Upgrade failed. Check log for details.', 'error');
					}
				}
			} catch {
				failCount++;
				if (failCount > 3) {
					clearInterval(interval);
					upgrading = false;
					addToast('Server is restarting after upgrade...', 'success');
					const reloadCheck = setInterval(async () => {
						try {
							await fetch('/api/config/version');
							clearInterval(reloadCheck);
							window.location.reload();
						} catch {
							// still restarting
						}
					}, 3000);
				}
			}
		}, 2000);
	}

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

	function testBadgeVariant(service) {
		const r = testResults[service];
		if (!r) return 'default';
		if (r.status === 'testing') return 'warning';
		if (r.status === 'ok') return 'success';
		return 'error';
	}

	function testBtnLabel(service, fallback) {
		const r = testResults[service];
		if (!r) return fallback;
		return r.message;
	}

	function toggleField(field) {
		showField[field] = !showField[field];
		showField = { ...showField };
	}

	const inputClass = 'w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)] placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20';
</script>

<div class="max-w-4xl">
	<PageHeader title="Settings" color="var(--color-settings)" />

	<div class="space-y-6">
		<!-- Library -->
		<Card padding="p-6">
			<h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">Library</h2>
			<div class="space-y-3 text-sm">
				<div class="flex items-center justify-between">
					<span class="text-[var(--text-secondary)]">Music Directory</span>
					<span class="font-mono text-xs text-[var(--text-muted)]">Configured in zonik.toml</span>
				</div>
				{#if stats}
					{#each [['Tracks', stats.tracks], ['Artists', stats.artists], ['Albums', stats.albums]] as [label, val]}
						<div class="flex items-center justify-between">
							<span class="text-[var(--text-secondary)]">{label}</span>
							<span class="text-[var(--text-primary)] font-mono text-xs">{val?.toLocaleString()}</span>
						</div>
					{/each}
				{/if}
			</div>
			<div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Download Directory</label>
					<input type="text" bind:value={services.download_dir} on:input={markDirty}
						placeholder="/music/Downloads" class={inputClass} />
				</div>
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Cover Art Cache</label>
					<input type="text" bind:value={services.cover_cache_dir} on:input={markDirty}
						placeholder="/opt/zonik/cache/covers" class={inputClass} />
				</div>
			</div>
		</Card>

		<!-- Service Connections -->
		<Card padding="p-6">
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Service Connections</h2>
				<Button variant="primary" size="sm" loading={saving} disabled={!dirty} onclick={saveServices}>
					Save
				</Button>
			</div>

			<div class="space-y-5">
				<!-- slskd -->
				<div>
					<div class="flex items-center justify-between mb-2">
						<h3 class="text-sm font-medium text-[var(--text-primary)]">Soulseek (slskd)</h3>
						<button on:click={() => testConnection('soulseek')}
							class="transition-colors">
							<Badge variant={testBadgeVariant('soulseek')}>{testBtnLabel('soulseek', 'Test')}</Badge>
						</button>
					</div>
					<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
						<div>
							<label class="block text-xs text-[var(--text-muted)] mb-1">URL</label>
							<input type="text" bind:value={services.slskd_url} on:input={markDirty}
								placeholder="http://host:5030" class={inputClass} />
						</div>
						<div>
							<label class="block text-xs text-[var(--text-muted)] mb-1">API Key</label>
							<div class="relative">
								<input type={showField.slskd ? 'text' : 'password'} bind:value={services.slskd_api_key} on:input={markDirty}
									placeholder="slskd API key" class="{inputClass} pr-8" />
								<button type="button" on:click={() => toggleField('slskd')}
									class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-disabled)] hover:text-[var(--text-secondary)] transition-colors">
									{#if showField.slskd}
										<EyeOff class="w-4 h-4" />
									{:else}
										<Eye class="w-4 h-4" />
									{/if}
								</button>
							</div>
						</div>
					</div>
				</div>

				<!-- Lidarr -->
				<div>
					<div class="flex items-center justify-between mb-2">
						<h3 class="text-sm font-medium text-[var(--text-primary)]">Lidarr</h3>
						<button on:click={() => testConnection('lidarr')}
							class="transition-colors">
							<Badge variant={testBadgeVariant('lidarr')}>{testBtnLabel('lidarr', 'Test')}</Badge>
						</button>
					</div>
					<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
						<div>
							<label class="block text-xs text-[var(--text-muted)] mb-1">URL</label>
							<input type="text" bind:value={services.lidarr_url} on:input={markDirty}
								placeholder="http://host:8686" class={inputClass} />
						</div>
						<div>
							<label class="block text-xs text-[var(--text-muted)] mb-1">API Key</label>
							<div class="relative">
								<input type={showField.lidarr ? 'text' : 'password'} bind:value={services.lidarr_api_key} on:input={markDirty}
									placeholder="Lidarr API key" class="{inputClass} pr-8" />
								<button type="button" on:click={() => toggleField('lidarr')}
									class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-disabled)] hover:text-[var(--text-secondary)] transition-colors">
									{#if showField.lidarr}
										<EyeOff class="w-4 h-4" />
									{:else}
										<Eye class="w-4 h-4" />
									{/if}
								</button>
							</div>
						</div>
					</div>
				</div>

				<!-- Last.fm -->
				<div>
					<div class="flex items-center justify-between mb-2">
						<h3 class="text-sm font-medium text-[var(--text-primary)]">Last.fm</h3>
						<button on:click={() => testConnection('lastfm')}
							class="transition-colors">
							<Badge variant={testBadgeVariant('lastfm')}>{testBtnLabel('lastfm', 'Test')}</Badge>
						</button>
					</div>
					<div class="grid grid-cols-1 md:grid-cols-3 gap-3">
						{#each [
							{ key: 'lastfm_read', bind: 'lastfm_api_key', label: 'Read API Key', placeholder: 'Last.fm API key' },
							{ key: 'lastfm_write', bind: 'lastfm_write_api_key', label: 'Write API Key', placeholder: 'Write API key' },
							{ key: 'lastfm_secret', bind: 'lastfm_write_api_secret', label: 'Write API Secret', placeholder: 'Write API secret' },
						] as field}
							<div>
								<label class="block text-xs text-[var(--text-muted)] mb-1">{field.label}</label>
								<div class="relative">
									<input type={showField[field.key] ? 'text' : 'password'} bind:value={services[field.bind]} on:input={markDirty}
										placeholder={field.placeholder} class="{inputClass} pr-8" />
									<button type="button" on:click={() => toggleField(field.key)}
										class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-disabled)] hover:text-[var(--text-secondary)] transition-colors">
										{#if showField[field.key]}
											<EyeOff class="w-4 h-4" />
										{:else}
											<Eye class="w-4 h-4" />
										{/if}
									</button>
								</div>
							</div>
						{/each}
					</div>
				</div>
			</div>
		</Card>

		<!-- Subsonic -->
		<Card padding="p-6">
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Subsonic</h2>
				<button on:click={() => testConnection('subsonic')} class="transition-colors">
					<Badge variant={testBadgeVariant('subsonic')}>{testBtnLabel('subsonic', 'Test')}</Badge>
				</button>
			</div>
			<div class="space-y-3 text-sm">
				{#each [
					['Server Name', 'Zonik'],
					['API Version', '1.16.1 (OpenSubsonic)'],
					['Default User', 'admin / admin'],
					['Endpoint', '/rest/*'],
				] as [label, val]}
					<div class="flex items-center justify-between">
						<span class="text-[var(--text-secondary)]">{label}</span>
						<code class="text-[var(--color-accent-light)] text-xs font-mono">{val}</code>
					</div>
				{/each}
			</div>
		</Card>

		<!-- About -->
		<Card padding="p-6">
			<h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">About</h2>
			<div class="space-y-2 text-sm text-[var(--text-secondary)]">
				{#if versionInfo}
					<p class="text-[var(--text-primary)]">Zonik v{versionInfo.version} <span class="font-mono text-xs text-[var(--text-muted)]">({versionInfo.commit})</span></p>
				{:else}
					<p class="text-[var(--text-primary)]">Zonik</p>
				{/if}
				<p>Self-hosted music backend with OpenSubsonic API</p>
				<p class="text-[var(--text-muted)]">FastAPI + SQLite + SvelteKit</p>
			</div>
		</Card>

		<!-- Updates -->
		<Card padding="p-6">
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Updates</h2>
				{#if updateInfo?.update_available}
					<Badge variant="warning">Update Available</Badge>
				{:else if updateInfo && !updateInfo.error}
					<Badge variant="success">Up to Date</Badge>
				{/if}
			</div>

			<div class="space-y-4">
				{#if versionInfo}
					<div class="flex items-center justify-between text-sm">
						<span class="text-[var(--text-secondary)]">Current Version</span>
						<span class="font-mono text-xs text-[var(--text-body)]">v{versionInfo.version} ({versionInfo.commit})</span>
					</div>
				{/if}

				{#if !upgrading}
					<div class="flex gap-2">
						<Button variant="secondary" size="sm" loading={checkingUpdates} onclick={checkForUpdates}>
							<RefreshCw class="w-3.5 h-3.5" />
							Check for Updates
						</Button>
						{#if updateInfo?.update_available}
							<Button variant="primary" size="sm" onclick={triggerUpgrade}>
								Upgrade Now
							</Button>
						{/if}
					</div>
				{/if}

				{#if updateInfo?.error}
					<p class="text-sm text-red-400">{updateInfo.error}</p>
				{/if}

				{#if updateInfo?.update_available}
					<div class="bg-[var(--bg-tertiary)] rounded-lg p-3 space-y-2">
						<div class="flex items-center justify-between text-sm">
							<span class="text-[var(--text-muted)]">Latest</span>
							<span class="font-mono text-xs text-[var(--text-body)]">{updateInfo.latest_commit}</span>
						</div>
						<p class="text-sm text-[var(--text-body)]">{updateInfo.latest_message}</p>
						{#if updateInfo.ahead_by}
							<p class="text-xs text-[var(--text-muted)]">{updateInfo.ahead_by} commit{updateInfo.ahead_by > 1 ? 's' : ''} behind</p>
						{/if}
						{#if updateInfo.commits?.length}
							<div class="mt-2 space-y-1 max-h-32 overflow-y-auto">
								{#each updateInfo.commits as c}
									<div class="flex gap-2 text-xs">
										<span class="font-mono text-[var(--color-accent-light)] shrink-0">{c.sha}</span>
										<span class="text-[var(--text-body)] truncate">{c.message}</span>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/if}

				{#if upgrading || upgradeJob}
					<div class="space-y-3">
						<div>
							<div class="flex justify-between text-xs mb-1">
								<span class="text-blue-400">Upgrading...</span>
								<span class="text-[var(--text-muted)] font-mono">{upgradeJob?.progress || 0}/5</span>
							</div>
							<div class="w-full bg-[var(--border-interactive)] rounded-full h-2">
								<div class="h-2 rounded-full transition-all duration-500
									{upgradeJob?.status === 'completed' ? 'bg-emerald-500' : upgradeJob?.status === 'failed' ? 'bg-red-500' : 'bg-blue-500'}"
									style="width: {((upgradeJob?.progress || 0) / 5) * 100}%"></div>
							</div>
						</div>

						{#if upgradeJob?.log}
							{@const logLines = (() => { try { return JSON.parse(upgradeJob.log); } catch { return []; } })()}
							<div class="bg-[var(--bg-primary)] rounded-lg p-3 max-h-48 overflow-y-auto font-mono text-xs text-[var(--text-muted)] space-y-0.5 border border-[var(--border-subtle)]">
								{#each logLines as line}
									<div class:text-emerald-400={line.includes('✓') || line.includes('upgraded')}
										 class:text-red-400={line.includes('Error') || line.includes('error')}
										 class:text-amber-400={line.startsWith('[')}>
										{line}
									</div>
								{/each}
							</div>
						{/if}

						{#if upgradeJob?.status === 'completed'}
							<p class="text-sm text-emerald-400">Upgrade completed! Page will reload shortly...</p>
						{:else if upgradeJob?.status === 'failed'}
							<p class="text-sm text-red-400">Upgrade failed. Review the log above for details.</p>
						{/if}
					</div>
				{/if}
			</div>
		</Card>
	</div>
</div>
