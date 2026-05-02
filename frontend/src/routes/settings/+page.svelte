<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { createScheduleHelpers } from '$lib/schedule.js';
	import { addToast } from '$lib/stores.js';
	import { inputClass, formatDateTime } from '$lib/utils.js';
	import { Settings, Eye, EyeOff, Wifi, RefreshCw, Users, Plus, Trash2, Key, Database, RotateCcw, Clock, Copy, Shield, ExternalLink, LogIn, Music, Download, Radio, HardDrive, Server, Info, Sparkles, AudioWaveform, Tv, Smartphone } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import ScheduleControl from '../../components/ui/ScheduleControl.svelte';
	import Toggle from '../../components/ui/Toggle.svelte';

	let stats = $state(null);
	let testResults = $state({});
	let services = $state({
		download_dir: '',
		cover_cache_dir: '',
		naming_scheme: '{artist}/{album}/{track_number} - {title}',
		slsk_username: '',
		slsk_password: '',
		slsk_listen_port: 2234,
		slsk_max_concurrent_downloads: 4,
		slsk_parallel_sources: 1,
		slsk_source_strategy: 'first',
		slsk_share_library: true,
		lidarr_enabled: false,
		lidarr_url: '',
		lidarr_api_key: '',
		spotify_client_id: '',
		spotify_client_secret: '',
		apple_music_developer_token: '',
		lastfm_api_key: '',
		lastfm_write_api_key: '',
		lastfm_write_api_secret: '',
		ai_reranking: true,
		ai_search: true,
		ai_playlist_gen: true,
		ai_explanations: true,
		ai_auto_tagging: true,
		ai_mood_tags: true,
		ai_insights: true,
		ai_duplicate_resolver: true,
		ai_download_advisor: true,
		ai_playlist_curator: true,
	});
	let aiUsage = $state(null);
	let saving = $state(false);
	let dirty = $state(false);
	let showField = $state({});

	let versionInfo = $state(null);
	let updateInfo = $state(null);
	let checkingUpdates = $state(false);
	let upgradeJobId = $state(null);
	let upgradeJob = $state(null);
	let upgrading = $state(false);
	let restarting = $state(false);

	let schedTasks = $state({});
	let lastfmSession = $state({ username: '', authenticated: false });
	let lastfmAuthLoading = $state(false);
	let lastfmToken = $state('');
	let schedRunning = $state({});
	let backups = $state([]);
	let creatingBackup = $state(false);

	let users = $state([]);
	let newUser = $state({ username: '', password: '', is_admin: false });
	let changingPw = $state(null);
	let pwForm = $state({ current_password: '', new_password: '' });

	function applyServices(d) {
		services = d;
		if (d.lastfm_session_key) {
			lastfmSession = { username: d.lastfm_username || 'Authenticated', authenticated: true };
		}
	}

	onMount(() => {
		// Load each section independently so one failure doesn't block the page
		api.getStats().then(d => stats = d).catch(() => {});
		api.getServices().then(applyServices).catch(() => {});
		api.getVersion().then(d => versionInfo = d).catch(() => {});
		api.getUsers().then(d => users = d).catch(() => {});
		api.getBackups().then(d => backups = d).catch(() => {});
		api.getAIUsage().then(d => aiUsage = d).catch(() => {});
		loadAnalysisStats();
		api.getSchedule().then(tasks => {
			for (const t of tasks) schedTasks[t.task_name] = t;
		}).catch(() => {});

		// Handle Last.fm OAuth redirect
		const params = new URLSearchParams(window.location.search);
		if (params.get('lastfm_auth') === 'ok') {
			addToast('Last.fm authenticated successfully!', 'success');
			window.history.replaceState({}, '', '/settings');
			api.getServices().then(applyServices).catch(() => {});
		} else if (params.get('lastfm_auth') === 'failed') {
			addToast('Last.fm authentication failed', 'error');
			window.history.replaceState({}, '', '/settings');
		}
	});

	async function checkForUpdates() {
		checkingUpdates = true;
		updateInfo = null;
		try {
			updateInfo = await api.checkUpdates();
		} catch (e) {
			addToast('Failed to check for updates: ' + e.message, 'error');
		} finally {
			checkingUpdates = false;
		}
	}

	async function restartApp() {
		if (!confirm('Restart Zonik? The app will be briefly unavailable.')) return;
		restarting = true;
		try {
			await api.restart();
			addToast('Restarting...', 'success');
			const reloadCheck = setInterval(async () => {
				try {
					await api.getVersion();
					clearInterval(reloadCheck);
					restarting = false;
					window.location.reload();
				} catch {
					// still restarting
				}
			}, 3000);
		} catch {
			addToast('Restart failed', 'error');
			restarting = false;
		}
	}

	async function triggerUpgrade() {
		upgrading = true;
		try {
			const data = await api.upgrade();
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
				const data = await api.getJob(upgradeJobId);
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
							await api.getVersion();
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
			await api.saveServices(services);
			addToast('Settings saved', 'success');
			dirty = false;
			services = await api.getServices();
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
				const data = await api.testService(service);
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

	function testDotColor(service) {
		const r = testResults[service];
		if (!r) return '';
		if (r.status === 'ok') return 'bg-emerald-400';
		if (r.status === 'error') return 'bg-red-400';
		if (r.status === 'testing') return 'bg-amber-400 animate-pulse';
		return '';
	}

	function toggleField(field) {
		showField[field] = !showField[field];
		showField = { ...showField };
	}

	async function loadUsers() {
		try {
			users = await api.getUsers();
		} catch (e) {
			console.error('Failed to load users', e);
		}
	}

	async function addUser() {
		try {
			await api.createUser(newUser);
			addToast(`User "${newUser.username}" created`, 'success');
			newUser = { username: '', password: '', is_admin: false };
			await loadUsers();
		} catch (e) {
			addToast(e.message || 'Failed to create user', 'error');
		}
	}

	async function changePassword(userId) {
		try {
			await api.changePassword(userId, pwForm);
			addToast('Password changed', 'success');
			changingPw = null;
			pwForm = { current_password: '', new_password: '' };
		} catch (e) {
			addToast(e.message || 'Failed to change password', 'error');
		}
	}

	async function deleteUser(userId) {
		if (!confirm('Are you sure you want to delete this user?')) return;
		try {
			await api.deleteUser(userId);
			addToast('User deleted', 'success');
			await loadUsers();
		} catch (e) {
			addToast(e.message || 'Failed to delete user', 'error');
		}
	}

	async function generateApiKey(userId) {
		try {
			await api.generateApiKey(userId);
			addToast('API key generated — copy it now', 'success');
			await loadUsers();
		} catch (e) {
			addToast('Failed to generate API key: ' + e.message, 'error');
		}
	}

	async function revokeApiKey(userId) {
		if (!confirm('Revoke this API key? Zonik-mobile will need a new one.')) return;
		try {
			await api.revokeApiKey(userId);
			addToast('API key revoked', 'success');
			await loadUsers();
		} catch (e) {
			addToast('Failed to revoke API key: ' + e.message, 'error');
		}
	}

	function copyApiKey(key) {
		navigator.clipboard.writeText(key);
		addToast('API key copied to clipboard', 'success');
	}

	async function createBackup() {
		creatingBackup = true;
		try {
			const data = await api.createBackup();
			if (data.error) { addToast(data.error, 'error'); return; }
			addToast('Backup created', 'success');
			backups = await api.getBackups();
		} catch (e) { addToast('Backup failed', 'error'); }
		finally { creatingBackup = false; }
	}

	async function restoreBackup(filename) {
		if (!confirm('Restore this backup? Current data will be backed up first. Services must be restarted after restore.')) return;
		try {
			const data = await api.restoreBackup(filename);
			if (data.error) { addToast(data.error, 'error'); return; }
			addToast(data.message, 'success');
		} catch (e) { addToast('Restore failed', 'error'); }
	}

	let analysisStats = $state(null);

	// Load analysis stats
	function loadAnalysisStats() {
		fetch('/api/analysis/stats').then(r => r.json()).then(d => analysisStats = d).catch(() => {});
	}

	const { toggleSched, updateSched, runSched, updateSchedConfig } = createScheduleHelpers(
		() => schedTasks,
		(name, val) => { schedTasks[name] = val; },
		addToast
	);

	// inputClass imported from $lib/utils.js

	async function startLastfmAuth() {
		lastfmAuthLoading = true;
		try {
			const data = await api.getLastfmAuthUrl();
			if (data.error) {
				addToast(data.error, 'error');
			} else {
				window.open(data.url, '_blank');
				addToast('Authorize on Last.fm, then paste the token below', 'info');
			}
		} catch (e) {
			addToast('Failed to get auth URL', 'error');
		} finally {
			lastfmAuthLoading = false;
		}
	}

	async function submitLastfmToken() {
		if (!lastfmToken.trim()) return;
		try {
			const data = await api.lastfmCallback(lastfmToken.trim());
			if (data.error) {
				addToast(`Last.fm auth failed: ${data.error}`, 'error');
			} else {
				lastfmSession = { username: data.username || 'Authenticated', authenticated: true };
				lastfmToken = '';
				addToast(`Authenticated as ${data.username}`, 'success');
			}
		} catch (e) {
			addToast('Failed to exchange token', 'error');
		}
	}
</script>

<div class="max-w-4xl">
	<PageHeader title="Settings" icon={Settings} color="var(--color-settings)" />

	<div class="space-y-6">
		<!-- 1. Library & Storage -->
		<Card padding="p-4">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-3">
					<div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, var(--color-library) 15%, transparent)">
						<Music class="w-4 h-4" style="color: var(--color-library)" />
					</div>
					<h2 class="text-base font-semibold text-[var(--text-primary)]">Library & Storage</h2>
				</div>
			</div>

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
					<input type="text" bind:value={services.download_dir} oninput={markDirty}
						placeholder="/music/Downloads" class={inputClass} />
				</div>
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Cover Art Cache</label>
					<input type="text" bind:value={services.cover_cache_dir} oninput={markDirty}
						placeholder="/opt/zonik/cache/covers" class={inputClass} />
				</div>
			</div>

			<div class="mt-3">
				<label class="block text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">File Naming Scheme</label>
				<input type="text" bind:value={services.naming_scheme} oninput={markDirty}
					placeholder={'{artist}/{album}/{track_number} - {title}'} class={inputClass} />
				<p class="mt-1 text-xs text-[var(--text-disabled)]">
					Variables: <code class="text-[var(--color-accent-light)]">{'{artist}'}</code>, <code class="text-[var(--color-accent-light)]">{'{album}'}</code>, <code class="text-[var(--color-accent-light)]">{'{track_number}'}</code>, <code class="text-[var(--color-accent-light)]">{'{title}'}</code> — used by Rename &amp; Sort
				</p>
			</div>

			<div class="mt-4 flex items-center justify-between">
				<div>
					<span class="text-sm text-[var(--text-secondary)]">Share Library</span>
					<p class="text-xs text-[var(--text-disabled)]">Share your music library with Soulseek peers so others can browse and download from you</p>
				</div>
				<Toggle
					checked={services.slsk_share_library}
					onchange={(v) => { services.slsk_share_library = v; markDirty(); }}
					color="#10b981"
				/>
			</div>
		</Card>

		<!-- 2. Soulseek -->
		<Card padding="p-4">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-3">
					<div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, var(--color-downloads) 15%, transparent)">
						<Download class="w-4 h-4" style="color: var(--color-downloads)" />
					</div>
					<h2 class="text-base font-semibold text-[var(--text-primary)]">Soulseek</h2>
					{#if testDotColor('soulseek')}
						<span class="w-2 h-2 rounded-full {testDotColor('soulseek')}"></span>
					{/if}
				</div>
				<Button variant="secondary" size="sm" onclick={() => testConnection('soulseek')}>
					{testBtnLabel('soulseek', 'Test Connection')}
				</Button>
			</div>

			<div class="grid grid-cols-1 md:grid-cols-3 gap-3">
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Username</label>
					<input type="text" bind:value={services.slsk_username} oninput={markDirty}
						placeholder="Soulseek username" class={inputClass} />
				</div>
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Password</label>
					<div class="relative">
						<input type={showField.slsk_pass ? 'text' : 'password'} bind:value={services.slsk_password} oninput={markDirty}
							placeholder="Soulseek password" class="{inputClass} pr-8" />
						<button type="button" onclick={() => toggleField('slsk_pass')}
							class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-disabled)] hover:text-[var(--text-secondary)] transition-colors">
							{#if showField.slsk_pass}
								<EyeOff class="w-4 h-4" />
							{:else}
								<Eye class="w-4 h-4" />
							{/if}
						</button>
					</div>
				</div>
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Listen Port</label>
					<input type="number" bind:value={services.slsk_listen_port} oninput={markDirty}
						placeholder="2234" class={inputClass} />
				</div>
			</div>

			<div class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider mt-4 mb-2">Download Settings</div>

			<div class="grid grid-cols-1 md:grid-cols-3 gap-3">
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Download Queue</label>
					<select bind:value={services.slsk_max_concurrent_downloads} onchange={markDirty} class={inputClass}>
						<option value={1}>1 at a time</option>
						<option value={2}>2 concurrent</option>
						<option value={3}>3 concurrent</option>
						<option value={4}>4 concurrent</option>
						<option value={6}>6 concurrent</option>
						<option value={8}>8 concurrent</option>
						<option value={10}>10 concurrent</option>
					</select>
				</div>
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Sources per Track</label>
					<select bind:value={services.slsk_parallel_sources} onchange={markDirty} class={inputClass}>
						<option value={1}>1 (sequential)</option>
						<option value={2}>2 sources</option>
						<option value={3}>3 sources</option>
						<option value={4}>4 sources</option>
						<option value={5}>5 sources</option>
					</select>
				</div>
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Source Strategy</label>
					<select bind:value={services.slsk_source_strategy} onchange={markDirty} class={inputClass}>
						<option value="first">First completed</option>
						<option value="best">Best quality</option>
					</select>
				</div>
			</div>
		</Card>

		<!-- 3. Last.fm -->
		<Card padding="p-4">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-3">
					<div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, #d51007 15%, transparent)">
						<Radio class="w-4 h-4" style="color: #d51007" />
					</div>
					<h2 class="text-base font-semibold text-[var(--text-primary)]">Last.fm</h2>
					{#if testDotColor('lastfm')}
						<span class="w-2 h-2 rounded-full {testDotColor('lastfm')}"></span>
					{/if}
				</div>
				<Button variant="secondary" size="sm" onclick={() => testConnection('lastfm')}>
					{testBtnLabel('lastfm', 'Test Connection')}
				</Button>
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
							<input type={showField[field.key] ? 'text' : 'password'} bind:value={services[field.bind]} oninput={markDirty}
								placeholder={field.placeholder} class="{inputClass} pr-8" />
							<button type="button" onclick={() => toggleField(field.key)}
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

			<!-- Authentication -->
			<div class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider mt-4 mb-2">Authentication</div>
			<div class="flex items-center gap-3 flex-wrap">
				{#if lastfmSession.authenticated}
					<Badge variant="success">Authenticated as {lastfmSession.username}</Badge>
				{:else}
					<Badge variant="default">Not authenticated — scrobbling & favorites sync disabled</Badge>
				{/if}
				<button onclick={startLastfmAuth} disabled={lastfmAuthLoading}
					class="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-[var(--surface-container)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-high)] transition-colors">
					<ExternalLink class="w-3 h-3" />
					{lastfmSession.authenticated ? 'Re-authenticate' : 'Authenticate with Last.fm'}
				</button>
			</div>
			{#if !lastfmSession.authenticated}
				<div class="flex items-center gap-2 mt-2">
					<input type="text" bind:value={lastfmToken} placeholder="Paste token from Last.fm callback URL"
						class="{inputClass} flex-1 text-xs" />
					<button onclick={submitLastfmToken} disabled={!lastfmToken.trim()}
						class="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-green-600/20 text-green-400 hover:bg-green-600/30 transition-colors disabled:opacity-50">
						<LogIn class="w-3 h-3" />
						Submit Token
					</button>
				</div>
				<p class="text-xs text-[var(--text-disabled)] mt-1">Click Authenticate, authorize on Last.fm, then copy the <code>token</code> parameter from the redirect URL and paste it above.</p>
			{/if}

			<!-- Last.fm Favorites Sync Schedule -->
			{#if schedTasks.lastfm_sync}
				<div class="mt-4 pt-4 ">
					<ScheduleControl taskName="lastfm_sync" label="Last.fm Favorites Sync" enabled={schedTasks.lastfm_sync.enabled} intervalHours={schedTasks.lastfm_sync.interval_hours} runAt={schedTasks.lastfm_sync.run_at} lastRunAt={schedTasks.lastfm_sync.last_run_at} running={schedRunning.lastfm_sync} onToggle={() => toggleSched('lastfm_sync')} onUpdate={(u) => updateSched('lastfm_sync', u)} onRun={() => runSched('lastfm_sync')} />
				</div>
			{/if}
		</Card>

		<!-- 4. Lidarr -->
		<Card padding="p-4">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-3">
					<div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, var(--color-discover) 15%, transparent)">
						<HardDrive class="w-4 h-4" style="color: var(--color-discover)" />
					</div>
					<h2 class="text-base font-semibold text-[var(--text-primary)]">Lidarr</h2>
					<Toggle
						checked={services.lidarr_enabled}
						onchange={(v) => { services.lidarr_enabled = v; markDirty(); }}
						color="#10b981"
					/>
					{#if testDotColor('lidarr')}
						<span class="w-2 h-2 rounded-full {testDotColor('lidarr')}"></span>
					{/if}
				</div>
				{#if services.lidarr_enabled}
					<Button variant="secondary" size="sm" onclick={() => testConnection('lidarr')}>
						{testBtnLabel('lidarr', 'Test Connection')}
					</Button>
				{/if}
			</div>

			{#if services.lidarr_enabled}
				<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1">URL</label>
						<input type="text" bind:value={services.lidarr_url} oninput={markDirty}
							placeholder="http://host:8686" class={inputClass} />
					</div>
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1">API Key</label>
						<div class="relative">
							<input type={showField.lidarr ? 'text' : 'password'} bind:value={services.lidarr_api_key} oninput={markDirty}
								placeholder="Lidarr API key" class="{inputClass} pr-8" />
							<button type="button" onclick={() => toggleField('lidarr')}
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
			{:else}
				<p class="text-sm text-[var(--text-disabled)]">Secondary download source. Enable to configure.</p>
			{/if}
		</Card>

		<!-- 5. Spotify -->
		<Card padding="p-4">
			<div class="flex items-center gap-3 mb-4">
				<div class="w-8 h-8 rounded-lg flex items-center justify-center bg-green-500/15">
					<Music class="w-4 h-4 text-green-400" />
				</div>
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Spotify</h2>
			</div>
			<p class="text-xs text-[var(--text-muted)] mb-3">For importing Spotify playlists. Get credentials from <a href="https://developer.spotify.com/dashboard" target="_blank" class="text-green-400 hover:underline">Spotify Developer Dashboard</a>.</p>
			<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1.5">Client ID</label>
					<input type="text" bind:value={services.spotify_client_id} oninput={markDirty} placeholder="Spotify Client ID" class={inputClass} />
				</div>
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1.5">Client Secret</label>
					<div class="relative">
						<input type={showField.spotify ? 'text' : 'password'} bind:value={services.spotify_client_secret} oninput={markDirty} placeholder="Spotify Client Secret" class="{inputClass} pr-8" />
						<button type="button" onclick={() => toggleField('spotify')}
							class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-disabled)] hover:text-[var(--text-secondary)] transition-colors">
							{#if showField.spotify}<EyeOff class="w-4 h-4" />{:else}<Eye class="w-4 h-4" />{/if}
						</button>
					</div>
				</div>
			</div>
		</Card>

		<!-- 6. Apple Music -->
		<Card padding="p-4">
			<div class="flex items-center gap-3 mb-4">
				<div class="w-8 h-8 rounded-lg flex items-center justify-center bg-pink-500/15">
					<Music class="w-4 h-4 text-pink-400" />
				</div>
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Apple Music</h2>
			</div>
			<p class="text-xs text-[var(--text-muted)] mb-3">For importing Apple Music playlists. Requires a developer token from Apple.</p>
			<div>
				<label class="block text-xs text-[var(--text-muted)] mb-1.5">Developer Token</label>
				<div class="relative">
					<input type={showField.apple ? 'text' : 'password'} bind:value={services.apple_music_developer_token} oninput={markDirty} placeholder="Apple Music developer JWT" class="{inputClass} pr-8" />
					<button type="button" onclick={() => toggleField('apple')}
						class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-disabled)] hover:text-[var(--text-secondary)] transition-colors">
						{#if showField.apple}<EyeOff class="w-4 h-4" />{:else}<Eye class="w-4 h-4" />{/if}
					</button>
				</div>
			</div>
		</Card>

		<!-- 7. Subsonic -->
		<div class="bg-[var(--bg-primary)] ghost-border rounded-xl p-4">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-3">
					<div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, var(--color-settings) 15%, transparent)">
						<Server class="w-4 h-4" style="color: var(--color-settings)" />
					</div>
					<h2 class="text-base font-semibold text-[var(--text-primary)]">Subsonic</h2>
					{#if testDotColor('subsonic')}
						<span class="w-2 h-2 rounded-full {testDotColor('subsonic')}"></span>
					{/if}
				</div>
				<Button variant="secondary" size="sm" onclick={() => testConnection('subsonic')}>
					{testBtnLabel('subsonic', 'Test Connection')}
				</Button>
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
		</div>

		<!-- 6. Users & Access -->
		<Card padding="p-4">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-3">
					<div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, var(--color-playlists) 15%, transparent)">
						<Users class="w-4 h-4" style="color: var(--color-playlists)" />
					</div>
					<h2 class="text-base font-semibold text-[var(--text-primary)]">Users & Access</h2>
				</div>
			</div>

			<div class="space-y-3">
				{#each users as user}
					<div class="bg-[var(--surface-container)] rounded-md px-3 py-2">
						<div class="flex items-center justify-between">
							<div class="flex items-center gap-3">
								<span class="font-medium text-[var(--text-primary)]">{user.username}</span>
								{#if user.is_admin}
									<Badge variant="info">Admin</Badge>
								{/if}
								{#if user.has_api_key}
									<Badge variant="success">API Key</Badge>
								{/if}
							</div>
							<div class="flex items-center gap-2">
								<Button variant="ghost" size="sm" onclick={() => { changingPw = changingPw === user.id ? null : user.id; }} title="Change password">
									<Key class="w-3.5 h-3.5" />
								</Button>
								{#if user.has_api_key}
									<Button variant="ghost" size="sm" onclick={() => copyApiKey(user.subsonic_api_key)} title="Copy API key">
										<Copy class="w-3.5 h-3.5" />
									</Button>
									<Button variant="ghost" size="sm" onclick={() => revokeApiKey(user.id)} title="Revoke API key">
										<Shield class="w-3.5 h-3.5 text-red-400" />
									</Button>
								{:else}
									<Button variant="ghost" size="sm" onclick={() => generateApiKey(user.id)} title="Generate API key for Zonik-mobile">
										<Shield class="w-3.5 h-3.5" />
									</Button>
								{/if}
								{#if !user.is_admin}
									<Button variant="ghost" size="sm" onclick={() => deleteUser(user.id)}>
										<Trash2 class="w-3.5 h-3.5 text-red-400" />
									</Button>
								{/if}
							</div>
						</div>
						{#if user.has_api_key}
							<div class="mt-1.5 flex items-center gap-2">
								<code class="text-xs font-mono text-[var(--text-muted)] bg-[var(--bg-primary)] px-2 py-0.5 rounded">
									{showField['apikey_' + user.id] ? user.subsonic_api_key : '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022'}
								</code>
								<button class="text-[var(--text-disabled)] hover:text-[var(--text-muted)]" onclick={() => toggleField('apikey_' + user.id)}>
									{#if showField['apikey_' + user.id]}
										<EyeOff class="w-3 h-3" />
									{:else}
										<Eye class="w-3 h-3" />
									{/if}
								</button>
							</div>
						{/if}
					</div>
					{#if changingPw === user.id}
						<div class="ml-3 flex gap-2 animate-fade-slide-in">
							<input type="password" placeholder="Current password" bind:value={pwForm.current_password} class={inputClass + ' flex-1'} />
							<input type="password" placeholder="New password" bind:value={pwForm.new_password} class={inputClass + ' flex-1'} />
							<Button variant="primary" size="sm" onclick={() => changePassword(user.id)}>Save</Button>
						</div>
					{/if}
				{/each}
			</div>

			<!-- Add User -->
			<div class="mt-4 pt-4 ">
				<div class="flex gap-2">
					<input type="text" placeholder="Username" bind:value={newUser.username} class={inputClass + ' flex-1'} />
					<input type="password" placeholder="Password" bind:value={newUser.password} class={inputClass + ' flex-1'} />
					<label class="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
						<input type="checkbox" bind:checked={newUser.is_admin} /> Admin
					</label>
					<Button variant="primary" size="sm" disabled={!newUser.username || !newUser.password} onclick={addUser}>
						<Plus class="w-3.5 h-3.5" />
						Add
					</Button>
				</div>
			</div>
		</Card>

		<!-- 7. AI Assistant -->
		<Card padding="p-4">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-3">
					<div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, var(--color-discover) 15%, transparent)">
						<Sparkles class="w-4 h-4" style="color: var(--color-discover)" />
					</div>
					<h2 class="text-base font-semibold text-[var(--text-primary)]">AI Assistant</h2>
					{#if testDotColor('claude')}
						<span class="w-2 h-2 rounded-full {testDotColor('claude')}"></span>
					{/if}
				</div>
				<Button variant="secondary" size="sm" onclick={() => testConnection('claude')}>
					{testBtnLabel('claude', 'Test Connection')}
				</Button>
			</div>
			<div class="space-y-3">
				<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1">Claude API Key</label>
						<div class="relative">
							<input type={showField.claude_api_key ? 'text' : 'password'} bind:value={services.claude_api_key}
								oninput={() => dirty = true}
								placeholder="sk-ant-..."
								class="{inputClass} pr-8" />
							<button onclick={() => showField.claude_api_key = !showField.claude_api_key}
								class="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-disabled)] hover:text-[var(--text-secondary)] transition-colors">
								{#if showField.claude_api_key}
									<EyeOff class="w-4 h-4" />
								{:else}
									<Eye class="w-4 h-4" />
								{/if}
							</button>
						</div>
					</div>
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1">Model</label>
						<select bind:value={services.claude_model} oninput={() => dirty = true}
							class={inputClass}>
							<option value="claude-sonnet-4-20250514">Claude Sonnet 4</option>
							<option value="claude-haiku-4-5-20251001">Claude Haiku 4.5</option>
						</select>
					</div>
				</div>

				<!-- Usage stats -->
				{#if aiUsage && aiUsage.requests > 0}
					<div class="flex items-center gap-4 text-xs text-[var(--text-muted)] bg-[var(--surface-container)] rounded-lg px-3 py-2">
						<span>Session: <span class="text-[var(--text-secondary)] font-mono">{aiUsage.requests}</span> requests</span>
						<span><span class="text-[var(--text-secondary)] font-mono">{(aiUsage.input_tokens + aiUsage.output_tokens).toLocaleString()}</span> tokens</span>
						<span>~<span class="text-[var(--text-secondary)] font-mono">${aiUsage.estimated_cost_usd}</span></span>
						{#if aiUsage.errors > 0}
							<span class="text-red-400">{aiUsage.errors} errors</span>
						{/if}
					</div>
				{/if}

				<!-- Feature toggles -->
				<div class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider mt-4 mb-2">AI Features</div>
				<div class="grid grid-cols-1 md:grid-cols-2 gap-2">
					{#each [
						{ key: 'ai_reranking', label: 'AI Re-ranking', desc: 'Claude re-ranks recommendations' },
						{ key: 'ai_search', label: 'Natural Language Search', desc: 'Search with plain English' },
						{ key: 'ai_playlist_gen', label: 'AI Playlist Generation', desc: 'Generate playlists from prompts' },
						{ key: 'ai_explanations', label: 'Why? Explanations', desc: 'Deep recommendation explanations' },
						{ key: 'ai_auto_tagging', label: 'Auto-Tagging', desc: 'AI genre tag suggestions' },
						{ key: 'ai_mood_tags', label: 'Mood Tags', desc: 'CLAP-based mood labeling' },
						{ key: 'ai_insights', label: 'Listening Insights', desc: 'Weekly AI listening summary' },
						{ key: 'ai_duplicate_resolver', label: 'Duplicate Resolver', desc: 'AI picks best duplicate' },
						{ key: 'ai_download_advisor', label: 'Download Advisor', desc: 'AI ranks search results' },
						{ key: 'ai_playlist_curator', label: 'Playlist Curator', desc: 'AI ranks discovered playlists' },
					] as toggle}
						<div class="flex items-center justify-between py-1.5 px-2.5 rounded-md bg-[var(--surface-container)]">
							<div class="min-w-0">
								<span class="text-sm text-[var(--text-secondary)]">{toggle.label}</span>
								<p class="text-xs text-[var(--text-disabled)] truncate">{toggle.desc}</p>
							</div>
							<div class="ml-3">
								<Toggle
									checked={services[toggle.key]}
									onchange={(v) => { services[toggle.key] = v; markDirty(); }}
									color="#10b981"
								/>
							</div>
						</div>
					{/each}
				</div>
				<p class="text-xs text-[var(--text-disabled)]">Features require a Claude API key. Mood Tags uses CLAP locally (zero API cost) with optional Claude enhancement.</p>
			</div>
		</Card>

		<!-- 8. Audio Analysis -->
		<Card padding="p-4">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-3">
					<div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, var(--color-analysis) 15%, transparent)">
						<AudioWaveform class="w-4 h-4" style="color: var(--color-analysis)" />
					</div>
					<h2 class="text-base font-semibold text-[var(--text-primary)]">Audio Analysis</h2>
				</div>
			</div>

			<!-- Stats -->
			{#if analysisStats}
				<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
					<div class="px-3 py-2 rounded-lg bg-[var(--surface-container)]">
						<p class="text-lg font-bold text-[var(--text-primary)]">{analysisStats.analyzed?.toLocaleString() || 0}</p>
						<p class="text-xs text-[var(--text-muted)]">Analyzed</p>
					</div>
					<div class="px-3 py-2 rounded-lg bg-[var(--surface-container)]">
						<p class="text-lg font-bold text-[var(--text-primary)]">{analysisStats.total_tracks?.toLocaleString() || 0}</p>
						<p class="text-xs text-[var(--text-muted)]">Total Tracks</p>
					</div>
					<div class="px-3 py-2 rounded-lg bg-[var(--surface-container)]">
						<p class="text-lg font-bold text-[var(--text-primary)]">{analysisStats.total_tracks ? Math.round((analysisStats.analyzed / analysisStats.total_tracks) * 100) : 0}%</p>
						<p class="text-xs text-[var(--text-muted)]">Coverage</p>
					</div>
					<div class="px-3 py-2 rounded-lg bg-[var(--surface-container)]">
						<p class="text-lg font-bold text-[var(--text-primary)]">{(analysisStats.total_tracks || 0) - (analysisStats.analyzed || 0)}</p>
						<p class="text-xs text-[var(--text-muted)]">Remaining</p>
					</div>
				</div>
				{#if analysisStats.analyzed < analysisStats.total_tracks}
					<div class="h-1.5 rounded-full bg-[var(--surface-container-highest)] mb-4 overflow-hidden">
						<div class="h-full bg-[var(--color-analysis)] rounded-full transition-all" style="width: {(analysisStats.analyzed / analysisStats.total_tracks) * 100}%"></div>
					</div>
				{/if}
			{/if}

			<p class="text-xs text-[var(--text-muted)] mb-4">Essentia audio analysis extracts BPM, key, energy, danceability, and loudness from each track. Used by Music Map, vibe search, and AI recommendations.</p>

			<!-- Schedule -->
			{#if schedTasks.audio_analysis}
				<div class="space-y-3">
					<ScheduleControl
						taskName="audio_analysis"
						label="Audio Analysis"
						enabled={schedTasks.audio_analysis.enabled}
						intervalHours={schedTasks.audio_analysis.interval_hours}
						runAt={schedTasks.audio_analysis.run_at}
						lastRunAt={schedTasks.audio_analysis.last_run_at}
						count={schedTasks.audio_analysis.count}
						countLabel="Batch Size"
						running={schedRunning.audio_analysis}
						onToggle={() => toggleSched('audio_analysis')}
						onUpdate={(u) => updateSched('audio_analysis', u)}
						onRun={() => { runSched('audio_analysis'); }}
					/>
					<div class="flex items-center gap-4 ml-1 text-xs">
						<label class="flex items-center gap-1.5 text-[var(--text-muted)]">
							Batch Size
							<input
								type="number"
								value={schedTasks.audio_analysis.count || 200}
								onchange={(e) => updateSched('audio_analysis', { count: parseInt(e.target.value) || 200 })}
								min="10" max="1000" step="10"
								class="w-20 bg-[var(--surface-container)] ghost-border rounded px-2 py-1 text-xs text-[var(--text-body)]"
							/>
							<span class="text-[var(--text-disabled)]">tracks/run</span>
						</label>
					</div>
					<p class="text-xs text-[var(--text-disabled)]">Higher batch sizes use more CPU. 50–100 recommended for low-power servers, 200 for dedicated hardware.</p>
				</div>
			{/if}
		</Card>

		<!-- 9. Database -->
		<Card padding="p-4">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-3">
					<div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, var(--color-stats) 15%, transparent)">
						<Database class="w-4 h-4" style="color: var(--color-stats)" />
					</div>
					<h2 class="text-base font-semibold text-[var(--text-primary)]">Database</h2>
				</div>
				<Button variant="secondary" size="sm" loading={creatingBackup} onclick={createBackup}>
					<Database class="w-3.5 h-3.5" />
					Create Backup
				</Button>
			</div>
			{#if backups.length}
				<div class="space-y-2">
					{#each backups as backup}
						<div class="flex items-center justify-between text-sm bg-[var(--surface-container)] rounded-lg px-3 py-2">
							<div class="flex flex-col">
								<span class="font-mono text-xs text-[var(--text-body)]">{backup.filename}</span>
								<span class="text-xs text-[var(--text-muted)]">
									{formatDateTime(backup.created_at)} &middot; {(backup.size / 1024 / 1024).toFixed(1)} MB
								</span>
							</div>
							<button onclick={() => restoreBackup(backup.filename)}
								class="text-[var(--text-muted)] hover:text-amber-400 transition-colors" title="Restore this backup">
								<RotateCcw class="w-4 h-4" />
							</button>
						</div>
					{/each}
				</div>
			{:else}
				<p class="text-sm text-[var(--text-muted)]">No backups yet. Create one to protect your data.</p>
			{/if}
		</Card>

		<!-- 8. About & Updates -->
		<Card padding="p-4">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-3">
					<div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, var(--color-settings) 15%, transparent)">
						<Info class="w-4 h-4" style="color: var(--color-settings)" />
					</div>
					<div>
						<h2 class="text-base font-semibold text-[var(--text-primary)]">About & Updates</h2>
						{#if versionInfo}
							<p class="text-xs text-[var(--text-muted)] mt-0.5">Zonik v{versionInfo.version} <span class="font-mono">({versionInfo.commit})</span></p>
						{/if}
					</div>
				</div>
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
						<Button variant="ghost" size="sm" loading={restarting} onclick={restartApp}>
							<RotateCcw class="w-3.5 h-3.5" />
							Restart
						</Button>
					</div>
				{/if}

				{#if updateInfo?.error}
					<p class="text-sm text-red-400">{updateInfo.error}</p>
				{/if}

				{#if updateInfo?.update_available}
					<div class="bg-[var(--surface-container)] rounded-lg p-3 space-y-2">
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
							<div class="bg-[var(--bg-primary)] rounded-lg p-3 max-h-48 overflow-y-auto font-mono text-xs text-[var(--text-muted)] space-y-0.5 ghost-border">
								{#each logLines as line}
									<div class:text-emerald-400={line.includes('\u2713') || line.includes('upgraded')}
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

				<!-- Quick links -->
				<div class="flex gap-3 pt-2">
					<a href="/pair"
						class="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--surface-container)] hover:bg-[var(--surface-container-high)] transition-colors text-sm text-[var(--text-secondary)]">
						<Tv class="w-4 h-4 text-[var(--color-primary)]" />
						Pair a Device
					</a>
					<a href="/app" target="_blank"
						class="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--surface-container)] hover:bg-[var(--surface-container-high)] transition-colors text-sm text-[var(--text-secondary)]">
						<Smartphone class="w-4 h-4 text-[var(--color-discover)]" />
						Download Mobile App
					</a>
				</div>
			</div>
		</Card>
	</div>
</div>

<!-- Sticky save bar -->
{#if dirty}
	<div class="sticky bottom-0 left-0 right-0 bg-[var(--surface-base)]/95 backdrop-blur px-4 py-3 flex items-center justify-between z-10">
		<span class="text-xs text-[var(--text-muted)]">Unsaved changes</span>
		<Button variant="primary" size="sm" loading={saving} onclick={saveServices}>Save Changes</Button>
	</div>
{/if}
