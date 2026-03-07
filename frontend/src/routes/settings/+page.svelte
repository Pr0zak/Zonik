<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { inputClass, formatDateTime } from '$lib/utils.js';
	import { Settings, Eye, EyeOff, Wifi, RefreshCw, Users, Plus, Trash2, Key, Database, RotateCcw, Clock, Copy, Shield, ExternalLink, LogIn, Music, Download, Radio, HardDrive, Server, Info, Sparkles } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import ScheduleControl from '../../components/ui/ScheduleControl.svelte';

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
		lastfm_api_key: '',
		lastfm_write_api_key: '',
		lastfm_write_api_secret: '',
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

	onMount(() => {
		// Load each section independently so one failure doesn't block the page
		fetch('/api/library/stats').then(r => r.json()).then(d => stats = d).catch(() => {});
		fetch('/api/config/services').then(r => r.json()).then(d => {
			services = d;
			if (d.lastfm_session_key) {
				lastfmSession = { username: d.lastfm_username || 'Authenticated', authenticated: true };
			}
		}).catch(() => {});
		fetch('/api/config/version').then(r => r.json()).then(d => versionInfo = d).catch(() => {});
		fetch('/api/users').then(r => r.json()).then(d => users = d).catch(() => {});
		fetch('/api/config/backups').then(r => r.json()).then(d => backups = d).catch(() => {});
		fetch('/api/schedule').then(r => r.json()).then(tasks => {
			for (const t of tasks) schedTasks[t.task_name] = t;
		}).catch(() => {});

		// Handle Last.fm OAuth redirect
		const params = new URLSearchParams(window.location.search);
		if (params.get('lastfm_auth') === 'ok') {
			addToast('Last.fm authenticated successfully!', 'success');
			window.history.replaceState({}, '', '/settings');
			// Re-fetch to pick up new session
			fetch('/api/config/services').then(r => r.json()).then(d => {
				services = d;
				if (d.lastfm_session_key) {
					lastfmSession = { username: d.lastfm_username || 'Authenticated', authenticated: true };
				}
			}).catch(() => {});
		} else if (params.get('lastfm_auth') === 'failed') {
			addToast('Last.fm authentication failed', 'error');
			window.history.replaceState({}, '', '/settings');
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
			users = await fetch('/api/users').then(r => r.json());
		} catch (e) {
			console.error('Failed to load users', e);
		}
	}

	async function addUser() {
		try {
			const resp = await fetch('/api/users', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(newUser),
			});
			if (!resp.ok) {
				const data = await resp.json();
				addToast(data.detail || 'Failed to create user', 'error');
				return;
			}
			addToast(`User "${newUser.username}" created`, 'success');
			newUser = { username: '', password: '', is_admin: false };
			await loadUsers();
		} catch (e) {
			addToast('Failed to create user: ' + e.message, 'error');
		}
	}

	async function changePassword(userId) {
		try {
			const resp = await fetch(`/api/users/${userId}/password`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(pwForm),
			});
			if (!resp.ok) {
				const data = await resp.json();
				addToast(data.detail || 'Failed to change password', 'error');
				return;
			}
			addToast('Password changed', 'success');
			changingPw = null;
			pwForm = { current_password: '', new_password: '' };
		} catch (e) {
			addToast('Failed to change password: ' + e.message, 'error');
		}
	}

	async function deleteUser(userId) {
		if (!confirm('Are you sure you want to delete this user?')) return;
		try {
			const resp = await fetch(`/api/users/${userId}`, { method: 'DELETE' });
			if (!resp.ok) {
				const data = await resp.json();
				addToast(data.detail || 'Failed to delete user', 'error');
				return;
			}
			addToast('User deleted', 'success');
			await loadUsers();
		} catch (e) {
			addToast('Failed to delete user: ' + e.message, 'error');
		}
	}

	async function generateApiKey(userId) {
		try {
			const resp = await fetch(`/api/users/${userId}/api-key`, { method: 'POST' });
			if (!resp.ok) {
				addToast('Failed to generate API key', 'error');
				return;
			}
			const data = await resp.json();
			addToast('API key generated — copy it now', 'success');
			await loadUsers();
		} catch (e) {
			addToast('Failed to generate API key: ' + e.message, 'error');
		}
	}

	async function revokeApiKey(userId) {
		if (!confirm('Revoke this API key? Symfonium will need a new one.')) return;
		try {
			const resp = await fetch(`/api/users/${userId}/api-key`, { method: 'DELETE' });
			if (!resp.ok) {
				addToast('Failed to revoke API key', 'error');
				return;
			}
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
			const data = await fetch('/api/config/backup', { method: 'POST' }).then(r => r.json());
			if (data.error) { addToast(data.error, 'error'); return; }
			addToast('Backup created', 'success');
			backups = await fetch('/api/config/backups').then(r => r.json());
		} catch (e) { addToast('Backup failed', 'error'); }
		finally { creatingBackup = false; }
	}

	async function restoreBackup(filename) {
		if (!confirm('Restore this backup? Current data will be backed up first. Services must be restarted after restore.')) return;
		try {
			const data = await fetch(`/api/config/restore/${filename}`, { method: 'POST' }).then(r => r.json());
			if (data.error) { addToast(data.error, 'error'); return; }
			addToast(data.message, 'success');
		} catch (e) { addToast('Restore failed', 'error'); }
	}

	async function toggleSched(name) {
		const t = schedTasks[name];
		if (!t) return;
		const newEnabled = !t.enabled;
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: newEnabled }) });
		schedTasks[name] = { ...t, enabled: newEnabled };
	}
	async function updateSched(name, updates) {
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updates) });
		schedTasks[name] = { ...schedTasks[name], ...updates };
	}
	async function runSched(name) {
		schedRunning[name] = true;
		try {
			await fetch(`/api/schedule/${name}/run`, { method: 'POST' });
			addToast('Task started', 'success');
		} catch { addToast('Failed to run task', 'error'); }
		finally { schedRunning[name] = false; }
	}

	// inputClass imported from $lib/utils.js

	async function startLastfmAuth() {
		lastfmAuthLoading = true;
		try {
			const res = await fetch('/api/discovery/lastfm/auth-url');
			const data = await res.json();
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
			const res = await fetch(`/api/discovery/lastfm/callback?token=${encodeURIComponent(lastfmToken.trim())}`);
			const data = await res.json();
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
	<PageHeader title="Settings" color="var(--color-settings)" />

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
				<button type="button" onclick={() => { services.slsk_share_library = !services.slsk_share_library; markDirty(); }}
					class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200 {services.slsk_share_library ? 'bg-emerald-500' : 'bg-[var(--border-interactive)]'}"
					role="switch" aria-checked={services.slsk_share_library}>
					<span class="pointer-events-none inline-block h-4 w-4 translate-y-0.5 rounded-full bg-white shadow transition-transform duration-200 {services.slsk_share_library ? 'translate-x-4' : 'translate-x-0.5'}"></span>
				</button>
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
					class="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors">
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
				<p class="text-[11px] text-[var(--text-disabled)] mt-1">Click Authenticate, authorize on Last.fm, then copy the <code>token</code> parameter from the redirect URL and paste it above.</p>
			{/if}

			<!-- Last.fm Favorites Sync Schedule -->
			{#if schedTasks.lastfm_sync}
				<div class="mt-4 pt-4 border-t border-[var(--border-subtle)]">
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
					<button type="button" onclick={() => { services.lidarr_enabled = !services.lidarr_enabled; markDirty(); }}
						class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200 {services.lidarr_enabled ? 'bg-emerald-500' : 'bg-[var(--border-interactive)]'}"
						role="switch" aria-checked={services.lidarr_enabled}>
						<span class="pointer-events-none inline-block h-4 w-4 translate-y-0.5 rounded-full bg-white shadow transition-transform duration-200 {services.lidarr_enabled ? 'translate-x-4' : 'translate-x-0.5'}"></span>
					</button>
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

		<!-- 5. Subsonic -->
		<div class="bg-[var(--bg-primary)] border border-[var(--border-subtle)] rounded-xl p-4">
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
					<div class="bg-[var(--bg-tertiary)] rounded-md px-3 py-2">
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
									<Button variant="ghost" size="sm" onclick={() => generateApiKey(user.id)} title="Generate API key for Symfonium">
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
			<div class="mt-4 pt-4 border-t border-[var(--border-subtle)]">
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
				</div>
			</div>
			<div class="space-y-3">
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Claude API Key</label>
					<div class="relative">
						<input type={showField.claude_api_key ? 'text' : 'password'} bind:value={services.claude_api_key}
							oninput={() => dirty = true}
							placeholder="sk-ant-..."
							class={inputClass} />
						<button onclick={() => showField.claude_api_key = !showField.claude_api_key}
							class="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-secondary)]">
							{#if showField.claude_api_key}
								<EyeOff class="w-4 h-4" />
							{:else}
								<Eye class="w-4 h-4" />
							{/if}
						</button>
					</div>
					<p class="text-[10px] text-[var(--text-disabled)] mt-1">Optional. Enables AI re-ranking on the Discover &gt; For You tab. Uses ~$0.01-0.03 per call.</p>
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
		</Card>

		<!-- 8. Database -->
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
						<div class="flex items-center justify-between text-sm bg-[var(--bg-tertiary)] rounded-lg px-3 py-2">
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
			</div>
		</Card>
	</div>
</div>

<!-- Sticky save bar -->
{#if dirty}
	<div class="sticky bottom-0 left-0 right-0 bg-[var(--bg-secondary)]/95 backdrop-blur border-t border-[var(--border-subtle)] px-4 py-3 flex items-center justify-between z-10">
		<span class="text-xs text-[var(--text-muted)]">Unsaved changes</span>
		<Button variant="primary" size="sm" loading={saving} onclick={saveServices}>Save Changes</Button>
	</div>
{/if}
