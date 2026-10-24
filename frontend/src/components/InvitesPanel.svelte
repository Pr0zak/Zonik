<script>
	import { onMount } from 'svelte';
	import { Link2, Copy, QrCode, Ban, Plus } from 'lucide-svelte';
	import Button from './ui/Button.svelte';
	import Badge from './ui/Badge.svelte';
	import { api } from '$lib/api.js';
	import { addToast } from '$lib/stores.js';
	import { inputClass, formatDateTime, formatRelativeTime } from '$lib/utils.js';
	import { EXPIRY_OPTIONS, inviteLink, inviteStatusLabel, inviteStatusTone, copyText } from '$lib/invites.js';

	let invites = $state([]);
	let showAll = $state(false);
	let form = $state({ role: 'user', note: '', expires_days: 7 });
	let creating = $state(false);
	let fresh = $state(null); // the invite just created
	let qrOpen = $state({});
	let freshInput = $state(null);
	let rowInputs = $state({});

	async function load() {
		try {
			invites = await api.getInvites(showAll);
		} catch (e) {
			addToast(e.message || 'Failed to load invites', 'error');
		}
	}

	onMount(load);

	async function create() {
		creating = true;
		try {
			const body = { role: form.role, expires_days: Number(form.expires_days) };
			if (form.note.trim()) body.note = form.note.trim();
			fresh = await api.createInvite(body);
			form.note = '';
			await load();
		} catch (e) {
			addToast(e.message || 'Failed to create invite', 'error');
		} finally {
			creating = false;
		}
	}

	async function copy(inv, el) {
		const ok = await copyText(inviteLink(inv, window.location.origin), el);
		addToast(ok ? 'Invite link copied' : 'Press Ctrl/Cmd+C to copy the selected link', ok ? 'success' : 'info');
	}

	async function revoke(inv) {
		if (!confirm('Revoke this invite link? It will stop working immediately.')) return;
		try {
			await api.revokeInvite(inv.id);
			if (fresh?.id === inv.id) fresh = null;
			addToast('Invite revoked', 'success');
			await load();
		} catch (e) {
			addToast(e.message || 'Failed to revoke invite', 'error');
		}
	}

	function toggleQr(id) { qrOpen[id] = !qrOpen[id]; }
	function selectAll(e) { e.currentTarget.select(); }
</script>

<div class="mb-6 pb-6 border-b border-white/[0.04]">
	<div class="flex items-center gap-2 mb-3">
		<Link2 class="w-4 h-4 text-[var(--text-muted)]" />
		<h3 class="text-sm font-semibold text-[var(--text-primary)]">Invites</h3>
	</div>
	<p class="text-xs text-[var(--text-muted)] mb-3">Send someone a single-use link so they can create their own account.</p>

	<div class="flex gap-2 flex-wrap items-center">
		<select aria-label="Invite role" bind:value={form.role} class="{inputClass} !w-auto">
			<option value="user">User</option>
			<option value="admin">Admin</option>
		</select>
		<input type="text" placeholder="Note (who is it for?)" bind:value={form.note} class={inputClass + ' flex-1 min-w-[8rem]'} />
		<select aria-label="Expires after" bind:value={form.expires_days} class="{inputClass} !w-auto">
			{#each EXPIRY_OPTIONS as d}
				<option value={d}>{d} day{d === 1 ? '' : 's'}</option>
			{/each}
		</select>
		<Button variant="primary" size="sm" loading={creating} onclick={create}>
			<Plus class="w-3.5 h-3.5" /> Create invite
		</Button>
	</div>

	{#if fresh}
		<div class="mt-3 bg-[var(--surface-container)] rounded-md p-3 space-y-3 animate-fade-slide-in">
			<p class="text-xs text-[var(--text-muted)]">New invite link{fresh.role === 'admin' ? ' (admin)' : ''}. Expires {formatDateTime(fresh.expires_at)}.</p>
			<div class="flex gap-2">
				<input type="text" readonly bind:this={freshInput} value={inviteLink(fresh, window.location.origin)} onfocus={selectAll}
					aria-label="Invite link" class="{inputClass} flex-1 min-w-0 font-mono text-xs" />
				<Button variant="secondary" size="sm" onclick={() => copy(fresh, freshInput)}><Copy class="w-3.5 h-3.5" /> Copy</Button>
			</div>
			<img src={api.inviteQrUrl(fresh.id)} alt="QR code for the invite link" class="w-40 h-40 bg-white rounded-md p-2" />
		</div>
	{/if}

	<div class="mt-4 flex items-center justify-between">
		<span class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)]">{showAll ? 'All invites' : 'Active invites'}</span>
		<label class="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
			<input type="checkbox" bind:checked={showAll} onchange={load} /> Show used/expired
		</label>
	</div>

	<div class="mt-2 space-y-2">
		{#each invites as inv (inv.id)}
			<div class="bg-[var(--surface-container)] rounded-md px-3 py-2 {inv.status !== 'active' ? 'opacity-70' : ''}">
				<div class="flex items-center justify-between gap-2 flex-wrap">
					<div class="flex items-center gap-2 min-w-0 flex-wrap">
						<Badge variant={inviteStatusTone(inv.status)} size="sm">{inviteStatusLabel(inv.status)}</Badge>
						<span class="text-sm text-[var(--text-primary)] truncate">{inv.note || 'No note'}</span>
						{#if inv.role === 'admin'}<Badge variant="warning" size="sm">Admin</Badge>{/if}
					</div>
					{#if inv.status === 'active'}
						<div class="flex items-center gap-1">
							<input type="text" readonly bind:this={rowInputs[inv.id]} value={inviteLink(inv, window.location.origin)} class="sr-only" tabindex="-1" aria-hidden="true" />
							<Button variant="ghost" size="sm" onclick={() => copy(inv, rowInputs[inv.id])} title="Copy link"><Copy class="w-3.5 h-3.5" /></Button>
							<Button variant="ghost" size="sm" onclick={() => toggleQr(inv.id)} title="Show QR code"><QrCode class="w-3.5 h-3.5" /></Button>
							<Button variant="ghost" size="sm" onclick={() => revoke(inv)} title="Revoke invite"><Ban class="w-3.5 h-3.5 text-red-400" /></Button>
						</div>
					{/if}
				</div>
				<div class="text-xs text-[var(--text-disabled)] mt-1">
					{#if inv.status === 'used'}
						Used by {inv.used_by?.username ?? 'unknown'}{inv.used_at ? ` ${formatRelativeTime(inv.used_at)}` : ''}
					{:else}
						{inv.status === 'active' ? 'Expires' : 'Expired'} {formatDateTime(inv.expires_at)}
					{/if}
					 · created by {inv.created_by?.username ?? '?'}
				</div>
				{#if qrOpen[inv.id] && inv.status === 'active'}
					<img src={api.inviteQrUrl(inv.id)} alt="QR code for the invite link" class="w-40 h-40 bg-white rounded-md p-2 mt-2" />
				{/if}
			</div>
		{:else}
			<p class="text-sm text-[var(--text-muted)]">{showAll ? 'No invites yet.' : 'No active invites.'}</p>
		{/each}
	</div>
</div>
