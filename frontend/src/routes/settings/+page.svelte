<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { Settings, Eye, EyeOff, Wifi, RefreshCw, Users, Plus, Trash2, Key, Database, RotateCcw } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';

	let stats = $state(null);
	let testResults = $state({});
	let services = $state({
		download_dir: '',
		cover_cache_dir: '',
		slsk_username: '',
		slsk_password: '',
		slsk_listen_port: 2234,
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

	let backups = $state([]);
	let creatingBackup = $state(false);

	let users = $state([]);
	let newUser = $state({ username: '', password: '', is_admin: false });
	let changingPw = $state(null);
	let pwForm = $state({ current_password: '', new_password: '' });

	onMount(async () => {
		try {
			const [statsData, svcData, verData, usersData, backupsData] = await Promise.all([
				fetch('/api/library/stats').then(r => r.json()),
				fetch('/api/config/services').then(r => r.json()),
				fetch('/api/config/version').then(r => r.json()),
				fetch('/api/users').then(r => r.json()),
				fetch('/api/config/backups').then(r => r.json()).catch(() => []),
			]);
			stats = statsData;
			services = svcData;
			versionInfo = verData;
			users = usersData;
			backups = backupsData;
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
					<input type="text" bind:value={services.download_dir} oninput={markDirty}
						placeholder="/music/Downloads" class={inputClass} />
				</div>
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Cover Art Cache</label>
					<input type="text" bind:value={services.cover_cache_dir} oninput={markDirty}
						placeholder="/opt/zonik/cache/covers" class={inputClass} />
				</div>
			</div>
		</Card>

		<!-- Users -->
		<Card padding="p-6">
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-base font-semibold text-[var(--text-primary)]">User Management</h2>
			</div>

			<div class="space-y-3">
				{#each users as user}
					<div class="flex items-center justify-between px-3 py-2 bg-[var(--bg-tertiary)] rounded-md">
						<div class="flex items-center gap-3">
							<span class="font-medium text-[var(--text-primary)]">{user.username}</span>
							{#if user.is_admin}
								<Badge variant="info">Admin</Badge>
							{/if}
						</div>
						<div class="flex items-center gap-2">
							<Button variant="ghost" size="sm" onclick={() => { changingPw = changingPw === user.id ? null : user.id; }}>
								<Key class="w-3.5 h-3.5" />
							</Button>
							{#if !user.is_admin}
								<Button variant="ghost" size="sm" onclick={() => deleteUser(user.id)}>
									<Trash2 class="w-3.5 h-3.5 text-red-400" />
								</Button>
							{/if}
						</div>
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

		<!-- Database Backups -->
		<Card padding="p-6">
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Database</h2>
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
									{new Date(backup.created_at).toLocaleString()} &middot; {(backup.size / 1024 / 1024).toFixed(1)} MB
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

		<!-- Service Connections -->
		<Card padding="p-6">
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Service Connections</h2>
				<Button variant="primary" size="sm" loading={saving} disabled={!dirty} onclick={saveServices}>
					Save
				</Button>
			</div>

			<div class="space-y-5">
				<!-- Soulseek -->
				<div>
					<div class="flex items-center justify-between mb-2">
						<h3 class="text-sm font-medium text-[var(--text-primary)]">Soulseek</h3>
						<button onclick={() => testConnection('soulseek')}
							class="transition-colors">
							<Badge variant={testBadgeVariant('soulseek')}>{testBtnLabel('soulseek', 'Test')}</Badge>
						</button>
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
					<p class="mt-2 text-xs text-[var(--text-disabled)]">Connects directly to the Soulseek P2P network.</p>
				</div>

				<!-- Lidarr -->
				<div>
					<div class="flex items-center justify-between mb-2">
						<div class="flex items-center gap-3">
							<h3 class="text-sm font-medium text-[var(--text-primary)]">Lidarr</h3>
							<button type="button" onclick={() => { services.lidarr_enabled = !services.lidarr_enabled; markDirty(); }}
								class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200 {services.lidarr_enabled ? 'bg-emerald-500' : 'bg-[var(--border-interactive)]'}"
								role="switch" aria-checked={services.lidarr_enabled}>
								<span class="pointer-events-none inline-block h-4 w-4 translate-y-0.5 rounded-full bg-white shadow transition-transform duration-200 {services.lidarr_enabled ? 'translate-x-4' : 'translate-x-0.5'}"></span>
							</button>
						</div>
						{#if services.lidarr_enabled}
							<button onclick={() => testConnection('lidarr')}
								class="transition-colors">
								<Badge variant={testBadgeVariant('lidarr')}>{testBtnLabel('lidarr', 'Test')}</Badge>
							</button>
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
						<p class="text-xs text-[var(--text-disabled)]">Secondary download source. Enable to configure.</p>
					{/if}
				</div>

				<!-- Last.fm -->
				<div>
					<div class="flex items-center justify-between mb-2">
						<h3 class="text-sm font-medium text-[var(--text-primary)]">Last.fm</h3>
						<button onclick={() => testConnection('lastfm')}
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
				</div>
			</div>
		</Card>

		<!-- Subsonic -->
		<Card padding="p-6">
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Subsonic</h2>
				<button onclick={() => testConnection('subsonic')} class="transition-colors">
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
