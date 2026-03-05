<script>
	import { Clock, Play } from 'lucide-svelte';
	import Button from './Button.svelte';

	let {
		taskName,
		label = '',
		enabled = false,
		intervalHours = 24,
		runAt = '',
		dayOfWeek = null,
		count = null,
		lastRunAt = null,
		countLabel = 'Limit',
		running = false,
		onToggle = () => {},
		onUpdate = () => {},
		onRun = () => {},
	} = $props();

	const intervalOptions = [
		{ value: 6, label: '6h' },
		{ value: 12, label: '12h' },
		{ value: 24, label: '24h' },
		{ value: 48, label: '2d' },
		{ value: 168, label: '7d' },
	];

	const dayOptions = [
		{ value: 0, label: 'Mon' },
		{ value: 1, label: 'Tue' },
		{ value: 2, label: 'Wed' },
		{ value: 3, label: 'Thu' },
		{ value: 4, label: 'Fri' },
		{ value: 5, label: 'Sat' },
		{ value: 6, label: 'Sun' },
	];
</script>

<div class="flex items-center gap-3 py-2">
	<!-- Toggle -->
	<button onclick={onToggle}
		class="w-8 h-5 rounded-full transition-colors relative flex-shrink-0
			{enabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--border-interactive)]'}">
		<span class="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow-sm
			{enabled ? 'left-[14px]' : 'left-0.5'}"></span>
	</button>

	<!-- Label -->
	{#if label}
		<span class="text-xs text-[var(--text-secondary)] font-medium min-w-0 truncate">{label}</span>
	{/if}

	<div class="flex items-center gap-2 ml-auto flex-shrink-0">
		<!-- Interval -->
		<select value={intervalHours}
			onchange={(e) => onUpdate({ interval_hours: parseInt(e.target.value) })}
			class="bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded px-1.5 py-1 text-[10px] text-[var(--text-body)] focus:outline-none">
			{#each intervalOptions as opt}
				<option value={opt.value} selected={opt.value === intervalHours}>{opt.label}</option>
			{/each}
		</select>

		<!-- Time -->
		<input type="time" value={runAt || ''}
			onchange={(e) => onUpdate({ run_at: e.target.value })}
			class="bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded px-1.5 py-1 text-[10px] text-[var(--text-body)] w-[70px] focus:outline-none" />

		<!-- Day of week (for weekly tasks) -->
		{#if dayOfWeek !== null && dayOfWeek !== undefined}
			<select value={dayOfWeek}
				onchange={(e) => onUpdate({ day_of_week: parseInt(e.target.value) })}
				class="bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded px-1.5 py-1 text-[10px] text-[var(--text-body)] focus:outline-none">
				{#each dayOptions as opt}
					<option value={opt.value} selected={opt.value === dayOfWeek}>{opt.label}</option>
				{/each}
			</select>
		{/if}

		<!-- Count -->
		{#if count !== null && count !== undefined}
			<input type="number" value={count} min="1" max="1000"
				onchange={(e) => onUpdate({ count: parseInt(e.target.value) })}
				class="bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded px-1.5 py-1 text-[10px] text-[var(--text-body)] w-14 focus:outline-none"
				title={countLabel} />
		{/if}

		<!-- Run -->
		<Button variant="default" size="sm" loading={running} onclick={onRun}>
			<Play class="w-3 h-3" />
		</Button>
	</div>

	<!-- Last run -->
	{#if lastRunAt}
		<span class="text-[9px] text-[var(--text-muted)] font-mono flex-shrink-0 hidden lg:block" title="Last ran: {new Date(lastRunAt).toLocaleString()}">
			ran {(() => {
				const d = new Date(lastRunAt);
				const now = new Date();
				const diff = now - d;
				const mins = Math.floor(diff / 60000);
				if (mins < 60) return `${mins}m ago`;
				const hrs = Math.floor(mins / 60);
				if (hrs < 24) return `${hrs}h ago`;
				const days = Math.floor(hrs / 24);
				return `${days}d ago`;
			})()}
		</span>
	{/if}
</div>
