<script>
	import { onMount } from 'svelte';
	import Button from './ui/Button.svelte';
	import { api } from '$lib/api.js';
	import { addToast } from '$lib/stores.js';
	import { formatDateTime, formatRelativeTime } from '$lib/utils.js';

	let { userId } = $props();
	let devices = $state([]);
	let loading = $state(true);

	async function load() {
		try { devices = await api.getUserDevices(userId); }
		catch (e) { addToast(e.message || 'Failed to load devices', 'error'); }
		finally { loading = false; }
	}
	onMount(load);

	async function revoke(d) {
		if (!confirm(`Sign out "${d.label || 'this device'}"?`)) return;
		try {
			await api.revokeUserDevice(userId, d.id);
			addToast('Device revoked', 'success');
			await load();
		} catch (e) {
			addToast(e.message || 'Failed to revoke device', 'error');
		}
	}
</script>

<div class="ml-3 bg-[var(--surface-container)] rounded-md px-3 py-2 animate-fade-slide-in">
	{#if loading}
		<p class="text-xs text-[var(--text-muted)]">Loading...</p>
	{:else if !devices.length}
		<p class="text-xs text-[var(--text-muted)]">No active sessions or devices.</p>
	{:else}
		<div class="space-y-2">
			{#each devices as d (d.kind + d.id)}
				<div class="flex items-center justify-between gap-2 flex-wrap">
					<div class="min-w-0">
						<div class="text-sm text-[var(--text-primary)] truncate">{d.label || 'Unknown'}
							<span class="text-xs text-[var(--text-muted)]">· {d.kind === 'session' ? 'Browser' : (d.platform || 'device')}</span>
						</div>
						<div class="text-xs text-[var(--text-disabled)]">
							{d.ip || '-'} · signed in {d.created_at ? formatDateTime(d.created_at) : '-'} · last seen {d.last_seen_at ? formatRelativeTime(d.last_seen_at) : '-'}
						</div>
					</div>
					<Button variant="danger" size="sm" onclick={() => revoke(d)}>Revoke</Button>
				</div>
			{/each}
		</div>
	{/if}
</div>
