<script>
	import { onMount, onDestroy, tick } from 'svelte';
	import { formatSize, formatDuration, formatRelativeTime, parseUTC } from '$lib/utils.js';
	import { BarChart3, Wifi, Users, Share2, Download, ArrowUpDown, RotateCcw, Search, Clock, Radio, HardDrive, Zap, ShieldCheck, ShieldAlert, TrendingUp, Activity, Layers, Database, Server, Sparkles, AlertTriangle, SkipForward, ChevronDown, ChevronRight } from 'lucide-svelte';
	import { api } from '$lib/api.js';
	import { addToast } from '$lib/stores.js';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import DataTable from '../../components/ui/DataTable.svelte';
	import StatTile from '../../components/ui/StatTile.svelte';
	import { Chart, registerables } from 'chart.js';

	Chart.register(...registerables);

	let data = $state(null);
	let slsk = $state(null);
	let history = $state(null);
	let historyHours = $state(24);
	let loading = $state(true);

	let jobDashboard = $state(null);
	let jobStatusChartEl = $state(null);
	let jobTimelineChartEl = $state(null);
	let jobStatusChart = null;
	let jobTimelineChart = null;

	let playHistory = $state(null);
	let playPeriod = $state('7d');
	let playTimelineChartEl = $state(null);
	let playHourlyChartEl = $state(null);
	let playTimelineChart = null;
	let playHourlyChart = null;

	let skipSummary = $state(null);
	let skipRows = $state([]);
	let skipDetailsOpen = $state(false);
	let skipRowsLoading = $state(false);
	let skipSortKey = $state('skip_count');
	let skipSortDir = $state('desc');
	let expandedSkipId = $state(null);

	const skipColumns = [
		{ key: 'title', label: 'Track', sortable: true },
		{ key: 'album', label: 'Album', sortable: true, headerClass: 'hidden md:table-cell' },
		{ key: 'skip_count', label: 'Skips', sortable: true, align: 'right' },
		{ key: 'play_count', label: 'Plays', sortable: true, align: 'right', headerClass: 'hidden sm:table-cell' },
		{ key: 'last_skipped_at', label: 'Last skipped', sortable: true, align: 'right' },
		{ key: 'actions', label: '', width: '44px' },
	];

	// Sorting is client-side: the drill-down pulls every skipped track (capped at 500) once.
	let sortedSkipRows = $derived.by(() => {
		if (!skipSortKey || !skipSortDir) return skipRows;
		const dir = skipSortDir === 'asc' ? 1 : -1;
		const key = skipSortKey;
		return [...skipRows].sort((a, b) => {
			const av = a[key] ?? '';
			const bv = b[key] ?? '';
			if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
			return String(av).localeCompare(String(bv)) * dir;
		});
	});

	async function loadSkipSummary() {
		try {
			skipSummary = await fetch('/api/live/skips/summary').then(r => r.json());
		} catch (e) {
			console.error('Failed to load skip summary:', e);
		}
	}

	async function loadSkipRows() {
		skipRowsLoading = true;
		try {
			skipRows = await fetch('/api/live/skips?sort=recent&limit=500').then(r => r.json());
		} catch (e) {
			console.error('Failed to load skipped tracks:', e);
		} finally {
			skipRowsLoading = false;
		}
	}

	function toggleSkipDetails() {
		skipDetailsOpen = !skipDetailsOpen;
		if (skipDetailsOpen && !skipRows.length) loadSkipRows();
	}

	function setSkipSort(key, dir) {
		skipSortKey = key;
		skipSortDir = dir;
	}

	async function clearTrackSkips(row) {
		try {
			const res = await fetch(`/api/live/skips/${encodeURIComponent(row.track_id)}/reset`, { method: 'POST' });
			if (!res.ok) throw new Error(`${res.status}`);
			skipRows = skipRows.filter(r => r.track_id !== row.track_id);
			addToast('Skips cleared', 'success');
			loadSkipSummary();
		} catch (e) {
			addToast('Failed to clear skips', 'error');
		}
	}

	let aiUsage = $state(null);
	let aiDays = $state(30);
	let aiLoading = $state(false);
	let aiError = $state(null);
	let aiRequestSeq = 0; // monotonic — only the newest response may land
	let aiCostChartEl = $state(null);
	let aiTokensChartEl = $state(null);
	let aiRequestsChartEl = $state(null);
	let aiFeatureChartEl = $state(null);
	let aiCostChart = null;
	let aiTokensChart = null;
	let aiRequestsChart = null;
	let aiFeatureChart = null;

	let peersChartEl = $state(null);
	let transfersChartEl = $state(null);
	let speedChartEl = $state(null);
	let bandwidthChartEl = $state(null);
	let peersChart = null;
	let transfersChart = null;
	let speedChart = null;
	let bandwidthChart = null;

	const chartDefaults = {
		responsive: true,
		maintainAspectRatio: false,
		animation: { duration: 300 },
		interaction: { mode: 'index', intersect: false },
		plugins: {
			legend: {
				labels: { color: '#9ca3af', font: { size: 11, family: 'Inter' }, boxWidth: 12, padding: 8 },
			},
			tooltip: {
				backgroundColor: '#1a1a1a',
				borderColor: '#333',
				borderWidth: 1,
				titleColor: '#e5e5e5',
				bodyColor: '#9ca3af',
				titleFont: { size: 11, family: 'Inter' },
				bodyFont: { size: 11, family: 'Inter' },
				padding: 8,
			},
		},
		scales: {
			x: {
				ticks: { color: '#6b7280', font: { size: 10, family: 'Inter' }, maxRotation: 0, maxTicksLimit: 8 },
				grid: { color: 'rgba(255,255,255,0.04)' },
				border: { color: 'rgba(255,255,255,0.08)' },
			},
			y: {
				beginAtZero: true,
				ticks: { color: '#6b7280', font: { size: 10, family: 'Inter' } },
				grid: { color: 'rgba(255,255,255,0.04)' },
				border: { color: 'rgba(255,255,255,0.08)' },
			},
		},
	};

	function formatTimestamp(iso) {
		const d = parseUTC(iso);
		return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}

	function formatDateTimestamp(iso) {
		const d = parseUTC(iso);
		return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}

	function destroyJobCharts() {
		jobStatusChart?.destroy(); jobStatusChart = null;
		jobTimelineChart?.destroy(); jobTimelineChart = null;
	}

	function buildJobCharts() {
		if (!jobDashboard) return;
		destroyJobCharts();

		const STATUS_COLORS = {
			completed: '#10b981',
			failed: '#ef4444',
			running: '#3b82f6',
			pending: '#f59e0b',
			cancelled: '#6b7280',
		};

		// Status distribution donut
		if (jobStatusChartEl && Object.keys(jobDashboard.status_counts).length) {
			const entries = Object.entries(jobDashboard.status_counts).filter(([, v]) => v > 0);
			jobStatusChart = new Chart(jobStatusChartEl, {
				type: 'doughnut',
				data: {
					labels: entries.map(([k]) => k.charAt(0).toUpperCase() + k.slice(1)),
					datasets: [{
						data: entries.map(([, v]) => v),
						backgroundColor: entries.map(([k]) => STATUS_COLORS[k] || '#6b7280'),
						borderWidth: 0,
					}],
				},
				options: {
					responsive: true,
					maintainAspectRatio: false,
					cutout: '65%',
					animation: { duration: 300 },
					plugins: {
						legend: {
							position: 'right',
							labels: { color: '#9ca3af', font: { size: 11, family: 'Inter' }, boxWidth: 12, padding: 8 },
						},
						tooltip: chartDefaults.plugins.tooltip,
					},
				},
			});
		}

		// Hourly timeline
		if (jobTimelineChartEl && jobDashboard.hourly_timeline?.length) {
			const labels = jobDashboard.hourly_timeline.map(h => `${String(h.hour).padStart(2, '0')}:00`);
			jobTimelineChart = new Chart(jobTimelineChartEl, {
				type: 'bar',
				data: {
					labels,
					datasets: [{
						label: 'Jobs',
						data: jobDashboard.hourly_timeline.map(h => h.count),
						backgroundColor: 'rgba(139, 92, 246, 0.6)',
						borderColor: '#8b5cf6',
						borderWidth: 1,
						borderRadius: 3,
					}],
				},
				options: { ...chartDefaults, plugins: { ...chartDefaults.plugins, legend: { display: false } } },
			});
		}
	}

	function destroyPlayCharts() {
		playTimelineChart?.destroy(); playTimelineChart = null;
		playHourlyChart?.destroy(); playHourlyChart = null;
	}

	function buildPlayCharts() {
		if (!playHistory) return;
		destroyPlayCharts();

		if (playTimelineChartEl && playHistory.timeline.length > 1) {
			const labels = playHistory.timeline.map(d => {
				if (playPeriod === '24h') return d.period.split(' ')[1] || d.period;
				return d.period.slice(5); // MM-DD
			});
			playTimelineChart = new Chart(playTimelineChartEl, {
				type: 'bar',
				data: {
					labels,
					datasets: [{
						label: 'Plays',
						data: playHistory.timeline.map(d => d.count),
						backgroundColor: 'rgba(139, 92, 246, 0.6)',
						borderColor: '#8b5cf6',
						borderWidth: 1,
						borderRadius: 3,
					}],
				},
				options: { ...chartDefaults, plugins: { ...chartDefaults.plugins, legend: { display: false } } },
			});
		}

		if (playHourlyChartEl && playHistory.hourly_distribution.length) {
			// Fill all 24 hours
			const hourData = Array(24).fill(0);
			playHistory.hourly_distribution.forEach(h => { hourData[h.hour] = h.count; });
			playHourlyChart = new Chart(playHourlyChartEl, {
				type: 'bar',
				data: {
					labels: hourData.map((_, i) => `${String(i).padStart(2, '0')}:00`),
					datasets: [{
						label: 'Plays',
						data: hourData,
						backgroundColor: 'rgba(6, 182, 212, 0.5)',
						borderColor: '#06b6d4',
						borderWidth: 1,
						borderRadius: 3,
					}],
				},
				options: { ...chartDefaults, plugins: { ...chartDefaults.plugins, legend: { display: false } } },
			});
		}
	}

	async function loadPlayHistory() {
		try {
			playHistory = await api.getPlayHistory(playPeriod);
			await tick();
			buildPlayCharts();
		} catch (e) {
			console.error('Failed to load play history:', e);
		}
	}

	// ---- AI Usage ------------------------------------------------------------
	// Palette: #06b6d4 is the stats-section hue (single-hue / magnitude charts).
	// The three categorical slots below are fixed-order and CVD-validated for this
	// dark surface — do not cycle them or add a 4th.
	const AI_HUE = '#06b6d4';
	const AI_CAT = ['#3987e5', '#d95926', '#199e70']; // input / cache read / output
	const AI_SURFACE = '#201f1f'; // var(--surface-container) — the 2px stack gap

	const AI_FEATURE_LABELS = {
		recommendations: 'Recommendations',
		explainer: 'Explainer',
		playlist_curator: 'Playlist curator',
		download_advisor: 'Download advisor',
		nl_search: 'NL search',
		duplicate_resolver: 'Duplicate resolver',
		insights: 'Insights',
		auto_tagger: 'Auto tagger',
		playlist_gen: 'Playlist generation',
		mood_tagger: 'Mood tagger',
		unknown: 'Unknown',
	};

	function aiFeatureLabel(f) {
		if (!f) return 'Unknown';
		return AI_FEATURE_LABELS[f] || f.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
	}

	/**
	 * Money formatting that scales precision to magnitude — a single Haiku call
	 * costs a fraction of a cent and toFixed(2) would render it as "$0.00".
	 */
	function formatUSD(value) {
		const n = Number(value);
		if (!Number.isFinite(n) || n === 0) return '$0.00';
		const abs = Math.abs(n);
		if (abs >= 1) return `$${n.toFixed(2)}`;
		if (abs >= 0.01) return `$${n.toFixed(4)}`;
		if (abs < 0.000001) return '<$0.000001';
		return `$${n.toFixed(6).replace(/0+$/, '')}`;
	}

	/**
	 * formatUSD picks precision per value, which is right for a lone figure but
	 * wrong down a column or across an axis: "$5.11" next to "$0.4139" puts the
	 * decimal points in different places and can't be scanned. These two pick ONE
	 * precision for a whole set so the values line up.
	 */
	function usdDigits(max, min) {
		let digits = max >= 0.01 ? 2 : max >= 0.0001 ? 4 : 6;
		// ...but never so coarse that the smallest real value rounds to nothing.
		while (digits < 6 && min > 0 && min < 5 / 10 ** digits) digits++;
		return digits;
	}

	/** Shared precision for a column of values (tables, bar labels). */
	function usdColumn(values) {
		const nums = (values || []).map((v) => Math.abs(Number(v) || 0)).filter((v) => v > 0);
		if (!nums.length) return (v) => `$${(Number(v) || 0).toFixed(2)}`;
		const digits = usdDigits(Math.max(...nums), Math.min(...nums));
		return (v) => `$${(Number(v) || 0).toFixed(digits)}`;
	}

	/**
	 * Axis ticks take precision from the series maximum alone — the tick values
	 * are evenly spaced from zero, so the smallest datum is irrelevant to them
	 * and letting it in just pads every label with noise decimals.
	 */
	function usdAxis(values) {
		const max = Math.max(...(values || []).map((v) => Math.abs(Number(v) || 0)), 0);
		const digits = max >= 0.01 ? 2 : max >= 0.0001 ? 4 : 6;
		return (v) => `$${(Number(v) || 0).toFixed(digits)}`;
	}

	function formatTokens(value) {
		const n = Number(value) || 0;
		if (n >= 1000000) return `${(n / 1000000).toFixed(n >= 10000000 ? 0 : 1)}M`;
		if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
		return String(n);
	}

	function formatLatency(ms) {
		const n = Number(ms) || 0;
		if (n >= 10000) return `${(n / 1000).toFixed(0)}s`;
		if (n >= 1000) return `${(n / 1000).toFixed(1)}s`;
		return `${Math.round(n)}ms`;
	}

	function aiBucketLabel(period) {
		if (!period) return '';
		if (period.includes('T')) return period.slice(11, 16); // HH:00
		return period.slice(5); // MM-DD
	}

	// Direct value labels for the horizontal cost-by-feature bars.
	const aiBarValueLabels = {
		id: 'aiBarValueLabels',
		afterDatasetsDraw(chart) {
			const meta = chart.getDatasetMeta(0);
			if (!meta?.data?.length) return;
			const { ctx } = chart;
			const values = chart.data.datasets[0].data;
			const fmt = usdColumn(values); // one precision, so the labels line up
			ctx.save();
			ctx.font = '10px Inter, sans-serif';
			ctx.fillStyle = '#9ca3af';
			ctx.textAlign = 'left';
			ctx.textBaseline = 'middle';
			meta.data.forEach((bar, i) => {
				ctx.fillText(fmt(values[i]), bar.x + 6, bar.y);
			});
			ctx.restore();
		},
	};

	function destroyAICharts() {
		aiCostChart?.destroy(); aiCostChart = null;
		aiTokensChart?.destroy(); aiTokensChart = null;
		aiRequestsChart?.destroy(); aiRequestsChart = null;
		aiFeatureChart?.destroy(); aiFeatureChart = null;
	}

	function buildAICharts() {
		if (!aiUsage?.summary?.requests) return;
		destroyAICharts();

		const ts = aiUsage.timeseries || [];
		const labels = ts.map((p) => aiBucketLabel(p.period));

		// 1. Cost over time — single series, no legend (the title names it).
		if (aiCostChartEl && ts.length) {
			aiCostChart = new Chart(aiCostChartEl, {
				type: 'line',
				data: {
					labels,
					datasets: [{
						label: 'Cost',
						data: ts.map((p) => p.cost_usd),
						borderColor: AI_HUE,
						backgroundColor: 'rgba(6,182,212,0.10)',
						fill: true,
						tension: 0.3,
						pointRadius: 0,
						pointHoverRadius: 4,
						borderWidth: 2,
					}],
				},
				options: {
					...chartDefaults,
					plugins: {
						...chartDefaults.plugins,
						legend: { display: false },
						tooltip: {
							...chartDefaults.plugins.tooltip,
							callbacks: { label: (c) => ` ${formatUSD(c.parsed.y)}` },
						},
					},
					scales: {
						...chartDefaults.scales,
						y: {
							...chartDefaults.scales.y,
							ticks: { ...chartDefaults.scales.y.ticks, callback: usdAxis(ts.map((p) => p.cost_usd)) },
						},
					},
				},
			});
		}

		// 2. Tokens over time — stacked bar, fixed 3-slot categorical order.
		if (aiTokensChartEl && ts.length) {
			// Cache writes are folded into the input slot rather than given a 4th
			// categorical colour: they bill at 1.25x the input rate, and leaving
			// them out entirely would make the stack undercount the Tokens tile.
			const hasCacheWrite = ts.some((p) => (p.cache_write_tokens || 0) > 0);
			const series = [
				{
					label: hasCacheWrite ? 'Input (incl. cache write)' : 'Input',
					color: AI_CAT[0],
					value: (p) => (p.input_tokens || 0) + (p.cache_write_tokens || 0),
				},
				{ label: 'Cache read', color: AI_CAT[1], value: (p) => p.cache_read_tokens || 0 },
				{ label: 'Output', color: AI_CAT[2], value: (p) => p.output_tokens || 0 },
			];
			aiTokensChart = new Chart(aiTokensChartEl, {
				type: 'bar',
				data: {
					labels,
					datasets: series.map((s) => ({
						label: s.label,
						data: ts.map(s.value),
						backgroundColor: s.color,
						borderColor: AI_SURFACE, // 2px surface gap between stacked segments
						borderWidth: { top: 2 },
						borderSkipped: false,
						borderRadius: 2,
					})),
				},
				options: {
					...chartDefaults,
					plugins: {
						...chartDefaults.plugins,
						legend: { ...chartDefaults.plugins.legend, display: true, position: 'bottom' },
						tooltip: {
							...chartDefaults.plugins.tooltip,
							callbacks: { label: (c) => ` ${c.dataset.label}: ${(c.parsed.y || 0).toLocaleString()}` },
						},
					},
					scales: {
						x: { ...chartDefaults.scales.x, stacked: true },
						y: {
							...chartDefaults.scales.y,
							stacked: true,
							ticks: { ...chartDefaults.scales.y.ticks, callback: (v) => formatTokens(v) },
						},
					},
				},
			});
		}

		// 3. Requests over time — its own chart, never a second axis on cost.
		if (aiRequestsChartEl && ts.length) {
			aiRequestsChart = new Chart(aiRequestsChartEl, {
				type: 'bar',
				data: {
					labels,
					datasets: [{
						label: 'Requests',
						// AI_HUE, not AI_CAT[0] — that slot means "input tokens" in the
						// chart below, and one hue must not carry two meanings here.
						data: ts.map((p) => p.requests),
						backgroundColor: AI_HUE,
						borderRadius: 3,
						borderSkipped: false,
					}],
				},
				options: {
					...chartDefaults,
					plugins: {
						...chartDefaults.plugins,
						legend: { display: false },
						tooltip: {
							...chartDefaults.plugins.tooltip,
							callbacks: { label: (c) => ` ${c.parsed.y} request${c.parsed.y === 1 ? '' : 's'}` },
						},
					},
				},
			});
		}

		// 4. Cost by feature — horizontal bars, one hue, sorted desc, direct labels.
		const feats = [...(aiUsage.by_feature || [])].sort((a, b) => (b.cost_usd || 0) - (a.cost_usd || 0));
		if (aiFeatureChartEl && feats.length) {
			aiFeatureChart = new Chart(aiFeatureChartEl, {
				type: 'bar',
				data: {
					labels: feats.map((f) => aiFeatureLabel(f.feature)),
					datasets: [{
						label: 'Cost',
						data: feats.map((f) => f.cost_usd || 0),
						backgroundColor: AI_HUE,
						borderRadius: 4,
						borderSkipped: false,
						barThickness: 14,
					}],
				},
				options: {
					...chartDefaults,
					indexAxis: 'y',
					interaction: { mode: 'nearest', intersect: true },
					layout: { padding: { right: 64 } },
					plugins: {
						...chartDefaults.plugins,
						legend: { display: false },
						tooltip: {
							...chartDefaults.plugins.tooltip,
							callbacks: {
								label: (c) => {
									const f = feats[c.dataIndex];
									return ` ${formatUSD(f.cost_usd)} · ${f.requests} call${f.requests === 1 ? '' : 's'}`;
								},
							},
						},
					},
					scales: {
						// Every bar carries its own value label, so a value axis would
						// encode the same numbers twice (at four different decimal
						// widths, since formatUSD scales precision to magnitude).
						x: { ...chartDefaults.scales.x, display: false },
						y: {
							...chartDefaults.scales.y,
							grid: { display: false },
							// Spread, don't replace — bare ticks would drop the page's
							// recessive #6b7280/10px pair for a brighter, larger one.
							ticks: { ...chartDefaults.scales.y.ticks },
						},
					},
				},
				plugins: [aiBarValueLabels],
			});
		}
	}

	async function loadAIUsage() {
		// Period buttons fire faster than the 90d query returns, and the slower
		// request can resolve last — stamp each one and drop stale replies so
		// aiUsage can never disagree with the highlighted aiDays.
		const seq = ++aiRequestSeq;
		aiLoading = true;
		aiError = null;
		destroyAICharts();
		try {
			const payload = await api.getAIUsageDashboard(aiDays);
			if (seq !== aiRequestSeq) return; // superseded
			aiUsage = payload;
		} catch (e) {
			if (seq !== aiRequestSeq) return;
			console.error('Failed to load AI usage:', e);
			// Surfaced, not swallowed: the likeliest cause is a missing
			// ai_usage table (migration not run), and a blank card hides that.
			aiError = e?.message || 'Could not load AI usage.';
		} finally {
			if (seq === aiRequestSeq) {
				aiLoading = false;
				await tick();
				buildAICharts();
			}
		}
	}

	function destroyCharts() {
		peersChart?.destroy(); peersChart = null;
		transfersChart?.destroy(); transfersChart = null;
		speedChart?.destroy(); speedChart = null;
		bandwidthChart?.destroy(); bandwidthChart = null;
		destroyPlayCharts();
		destroyJobCharts();
	}

	function buildCharts() {
		if (!history?.length) return;
		destroyCharts();

		const labels = history.map(s => historyHours > 48 ? formatDateTimestamp(s.timestamp) : formatTimestamp(s.timestamp));

		// Peers chart
		if (peersChartEl) {
			peersChart = new Chart(peersChartEl, {
				type: 'line',
				data: {
					labels,
					datasets: [{
						label: 'Peers',
						data: history.map(s => s.peers),
						borderColor: '#3b82f6',
						backgroundColor: 'rgba(59,130,246,0.1)',
						fill: true,
						tension: 0.3,
						pointRadius: 0,
						borderWidth: 1.5,
					}, {
						label: 'Searches',
						data: history.map(s => s.active_searches),
						borderColor: '#a855f7',
						backgroundColor: 'rgba(168,85,247,0.05)',
						fill: true,
						tension: 0.3,
						pointRadius: 0,
						borderWidth: 1.5,
					}],
				},
				options: { ...chartDefaults },
			});
		}

		// Transfers chart
		if (transfersChartEl) {
			transfersChart = new Chart(transfersChartEl, {
				type: 'line',
				data: {
					labels,
					datasets: [{
						label: 'Active',
						data: history.map(s => s.active_transfers),
						borderColor: '#3b82f6',
						backgroundColor: 'rgba(59,130,246,0.1)',
						fill: true,
						tension: 0.3,
						pointRadius: 0,
						borderWidth: 1.5,
					}, {
						label: 'Queued',
						data: history.map(s => s.queued_transfers),
						borderColor: '#f59e0b',
						backgroundColor: 'rgba(245,158,11,0.05)',
						fill: true,
						tension: 0.3,
						pointRadius: 0,
						borderWidth: 1.5,
					}, {
						label: 'Completed',
						data: history.map(s => s.completed_transfers),
						borderColor: '#10b981',
						backgroundColor: 'rgba(16,185,129,0.05)',
						fill: true,
						tension: 0.3,
						pointRadius: 0,
						borderWidth: 1.5,
					}, {
						label: 'Failed',
						data: history.map(s => s.failed_transfers),
						borderColor: '#ef4444',
						backgroundColor: 'rgba(239,68,68,0.05)',
						fill: true,
						tension: 0.3,
						pointRadius: 0,
						borderWidth: 1.5,
					}],
				},
				options: { ...chartDefaults },
			});
		}

		// Speed chart
		if (speedChartEl) {
			speedChart = new Chart(speedChartEl, {
				type: 'line',
				data: {
					labels,
					datasets: [{
						label: 'Speed',
						data: history.map(s => s.speed),
						borderColor: '#f59e0b',
						backgroundColor: 'rgba(245,158,11,0.1)',
						fill: true,
						tension: 0.3,
						pointRadius: 0,
						borderWidth: 1.5,
					}],
				},
				options: {
					...chartDefaults,
					scales: {
						...chartDefaults.scales,
						y: {
							...chartDefaults.scales.y,
							ticks: {
								...chartDefaults.scales.y.ticks,
								callback: (v) => {
									if (v >= 1048576) return (v / 1048576).toFixed(1) + ' MB/s';
									if (v >= 1024) return (v / 1024).toFixed(0) + ' KB/s';
									return v + ' B/s';
								},
							},
						},
					},
				},
			});
		}

		// Bandwidth chart
		if (bandwidthChartEl) {
			bandwidthChart = new Chart(bandwidthChartEl, {
				type: 'line',
				data: {
					labels,
					datasets: [{
						label: 'Bytes Transferred',
						data: history.map(s => s.bytes_transferred),
						borderColor: '#06b6d4',
						backgroundColor: 'rgba(6,182,212,0.1)',
						fill: true,
						tension: 0.3,
						pointRadius: 0,
						borderWidth: 1.5,
					}],
				},
				options: {
					...chartDefaults,
					scales: {
						...chartDefaults.scales,
						y: {
							...chartDefaults.scales.y,
							ticks: {
								...chartDefaults.scales.y.ticks,
								callback: (v) => {
									if (v >= 1073741824) return (v / 1073741824).toFixed(1) + ' GB';
									if (v >= 1048576) return (v / 1048576).toFixed(0) + ' MB';
									if (v >= 1024) return (v / 1024).toFixed(0) + ' KB';
									return v + ' B';
								},
							},
						},
					},
				},
			});
		}
	}

	async function loadHistory() {
		try {
			history = await fetch(`/api/download/soulseek-stats/history?hours=${historyHours}`).then(r => r.json());
			await tick();
			buildCharts();
		} catch (e) {
			console.error('Failed to load stats history:', e);
		}
	}

	onMount(async () => {
		try {
			[data, slsk, jobDashboard] = await Promise.all([
				fetch('/api/library/stats/detailed').then(r => r.json()),
				fetch('/api/download/soulseek-stats').then(r => r.json()).catch(() => null),
				api.getJobDashboard().catch(() => null),
			]);
			// Set loading=false first so {#if} blocks render canvas elements
			loading = false;
			await Promise.all([loadHistory(), loadPlayHistory(), loadAIUsage(), loadSkipSummary()]);
			await tick();
			buildJobCharts();
		} catch (e) {
			console.error('Failed to load stats:', e);
			loading = false;
		}
	});

	// NOT the onMount return value: onMount above is async, so it resolves to a
	// Promise and Svelte discards any function it returns. Chart.js instances
	// would otherwise outlive the page, each holding a ResizeObserver.
	onDestroy(() => {
		destroyCharts();
		destroyAICharts();
		destroyJobCharts();
	});

	function barWidth(value, max) {
		if (!max) return '0%';
		return Math.max(2, (value / max) * 100) + '%';
	}

	// One shared precision per cost column, so the decimal points align down it.
	let aiModelCost = $derived(usdColumn((aiUsage?.by_model || []).map((m) => m.cost_usd)));
	let aiRecentCost = $derived(usdColumn((aiUsage?.recent || []).map((r) => r.cost_usd)));

	let maxFmt = $derived(data ? Math.max(...Object.values(data.formats), 1) : 1);
	let maxArt = $derived(data?.top_artists?.length ? data.top_artists[0].count : 1);
	let maxGenre = $derived(data?.genres?.length ? data.genres[0].count : 1);
	let maxBr = $derived(data ? Math.max(...Object.values(data.bitrates), 1) : 1);
	let maxYear = $derived(data?.years?.length ? Math.max(...data.years.map(y => y.count)) : 1);

	function formatUptime(seconds) {
		if (!seconds) return '—';
		const d = Math.floor(seconds / 86400);
		const h = Math.floor((seconds % 86400) / 3600);
		const m = Math.floor((seconds % 3600) / 60);
		if (d > 0) return `${d}d ${h}h`;
		if (h > 0) return `${h}h ${m}m`;
		return `${m}m`;
	}

	function formatSpeed(bps) {
		if (bps > 1048576) return `${(bps / 1048576).toFixed(1)} MB/s`;
		if (bps > 1024) return `${(bps / 1024).toFixed(0)} KB/s`;
		return `${bps} B/s`;
	}

	let showAllPeers = $state(false);

	const barColors = {
		formats: 'bg-[var(--color-accent)]',
		artists: 'bg-emerald-500',
		genres: 'bg-purple-500',
		bitrates: 'bg-blue-500',
	};
</script>

<div class="max-w-6xl">
	<PageHeader title="Library Stats" color="var(--color-stats)" />

	{#if loading}
		<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
			<Skeleton class="h-20 rounded-lg" />
			<Skeleton class="h-20 rounded-lg" />
			<Skeleton class="h-20 rounded-lg" />
			<Skeleton class="h-20 rounded-lg" />
			<Skeleton class="h-20 rounded-lg" />
			<Skeleton class="h-20 rounded-lg" />
		</div>
		<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
			<Skeleton class="h-64 rounded-lg" />
			<Skeleton class="h-64 rounded-lg" />
			<Skeleton class="h-64 rounded-lg" />
			<Skeleton class="h-64 rounded-lg" />
		</div>
	{:else if data}
		<!-- Overview Cards -->
		<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
			{#each [
				{ v: data.tracks.toLocaleString(), l: 'Tracks' },
				{ v: data.artists.toLocaleString(), l: 'Artists' },
				{ v: data.albums.toLocaleString(), l: 'Albums' },
				{ v: formatSize(data.total_size_bytes), l: 'Total Size' },
				{ v: formatDuration(data.total_duration_seconds), l: 'Duration' },
				{ v: data.favorites.toLocaleString(), l: 'Favorites' },
			] as card}
				<Card padding="p-4">
					<p class="text-2xl font-bold text-[var(--text-primary)]">{card.v}</p>
					<p class="text-xs text-[var(--text-muted)]">{card.l}</p>
				</Card>
			{/each}
		</div>

		<!-- Processing Status -->
		<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
			<Card padding="p-4">
				<h3 class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider mb-2">Audio Analyzed</h3>
				<p class="text-lg font-bold text-[var(--text-primary)]">{data.analyzed} <span class="text-sm text-[var(--text-muted)] font-normal">/ {data.tracks}</span></p>
				{#if data.tracks > 0}
					<div class="mt-2 h-1.5 bg-[var(--border-interactive)] rounded-full overflow-hidden">
						<div class="h-full bg-[var(--color-accent)] rounded-full transition-all" style="width: {(data.analyzed / data.tracks * 100).toFixed(1)}%"></div>
					</div>
				{/if}
			</Card>
			<Card padding="p-4">
				<h3 class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider mb-2">Vibe Embeddings</h3>
				<p class="text-lg font-bold text-[var(--text-primary)]">{data.embedded} <span class="text-sm text-[var(--text-muted)] font-normal">/ {data.tracks}</span></p>
				{#if data.tracks > 0}
					<div class="mt-2 h-1.5 bg-[var(--border-interactive)] rounded-full overflow-hidden">
						<div class="h-full bg-purple-500 rounded-full transition-all" style="width: {(data.embedded / data.tracks * 100).toFixed(1)}%"></div>
					</div>
				{/if}
			</Card>
			<Card padding="p-4">
				<h3 class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider mb-2">Playlists</h3>
				<p class="text-lg font-bold text-[var(--text-primary)]">{data.playlists}</p>
			</Card>
		</div>

		<div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
			<!-- Formats -->
			<Card padding="p-4">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Formats</h2>
				<div class="space-y-2">
					{#each Object.entries(data.formats).sort((a, b) => b[1] - a[1]) as [fmt, count]}
						<div class="flex items-center gap-3 text-sm group">
							<span class="w-16 text-right text-[var(--text-muted)] uppercase font-mono text-xs">{fmt}</span>
							<div class="flex-1 h-5 bg-[var(--surface-container-high)] rounded overflow-hidden">
								<div class="h-full {barColors.formats} rounded transition-colors" style="width: {barWidth(count, maxFmt)}"></div>
							</div>
							<span class="w-12 text-right text-[var(--text-muted)] text-xs font-mono">{count}</span>
						</div>
					{/each}
				</div>
			</Card>

			<!-- Top Artists -->
			<Card padding="p-4">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Top Artists</h2>
				<div class="space-y-2">
					{#each data.top_artists as artist}
						<div class="flex items-center gap-3 text-sm group">
							<span class="w-32 truncate text-right text-[var(--text-body)]" title={artist.name}>{artist.name}</span>
							<div class="flex-1 h-5 bg-[var(--surface-container-high)] rounded overflow-hidden">
								<div class="h-full {barColors.artists} rounded transition-colors" style="width: {barWidth(artist.count, maxArt)}"></div>
							</div>
							<span class="w-10 text-right text-[var(--text-muted)] text-xs font-mono">{artist.count}</span>
						</div>
					{/each}
				</div>
			</Card>

			<!-- Genres -->
			<Card padding="p-4">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Top Genres</h2>
				<div class="space-y-2">
					{#each data.genres as genre}
						<div class="flex items-center gap-3 text-sm group">
							<span class="w-32 truncate text-right text-[var(--text-body)]" title={genre.name}>{genre.name}</span>
							<div class="flex-1 h-5 bg-[var(--surface-container-high)] rounded overflow-hidden">
								<div class="h-full {barColors.genres} rounded transition-colors" style="width: {barWidth(genre.count, maxGenre)}"></div>
							</div>
							<span class="w-10 text-right text-[var(--text-muted)] text-xs font-mono">{genre.count}</span>
						</div>
					{/each}
				</div>
			</Card>

			<!-- Bitrate -->
			<Card padding="p-4">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Bitrate Distribution</h2>
				<div class="space-y-2">
					{#each Object.entries(data.bitrates).sort() as [range, count]}
						<div class="flex items-center gap-3 text-sm group">
							<span class="w-20 text-right text-[var(--text-muted)] text-xs font-mono">{range} kbps</span>
							<div class="flex-1 h-5 bg-[var(--surface-container-high)] rounded overflow-hidden">
								<div class="h-full {barColors.bitrates} rounded transition-colors" style="width: {barWidth(count, maxBr)}"></div>
							</div>
							<span class="w-10 text-right text-[var(--text-muted)] text-xs font-mono">{count}</span>
						</div>
					{/each}
				</div>
			</Card>
		</div>

		<!-- Year Distribution -->
		{#if data.years.length}
			<Card padding="p-4" class="mb-8">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Year Distribution</h2>
				<div class="flex items-end gap-px h-32">
					{#each data.years as yr}
						<div class="flex-1 flex flex-col items-center justify-end h-full group relative">
							<div class="w-full bg-[var(--color-accent)] rounded-t min-h-[2px] transition-colors"
								style="height: {barWidth(yr.count, maxYear)}"></div>
							<div class="hidden group-hover:block absolute bottom-full mb-1 bg-[var(--surface-container-high)] text-xs px-2 py-1 rounded whitespace-nowrap z-10 text-[var(--text-body)] ghost-border">
								{yr.year}: {yr.count} tracks
							</div>
						</div>
					{/each}
				</div>
				<div class="flex justify-between text-xs text-[var(--text-muted)] mt-1 font-mono">
					<span>{data.years[0]?.year}</span>
					<span>{data.years[data.years.length - 1]?.year}</span>
				</div>
			</Card>
		{/if}

		<!-- Most Played -->
		{#if data.most_played.length}
			<Card padding="p-4" class="mb-8">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Most Played</h2>
				<div class="space-y-2">
					{#each data.most_played as track, i}
						<div class="flex items-center gap-3 text-sm">
							<span class="w-6 text-right text-[var(--text-muted)] font-mono text-xs">{i + 1}.</span>
							<span class="flex-1 truncate text-[var(--text-body)]">{track.title}</span>
							<span class="text-[var(--text-secondary)] truncate max-w-48">{track.artist || 'Unknown'}</span>
							<span class="text-[var(--color-accent-light)] text-xs font-mono w-12 text-right">{track.plays}x</span>
						</div>
					{/each}
				</div>
			</Card>
		{/if}

		<!-- Play History -->
		{#if playHistory}
			<Card padding="p-4" class="mb-8">
				<div class="flex items-center justify-between mb-4">
					<div class="flex items-center gap-2">
						<Activity class="w-4 h-4 text-purple-400" />
						<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Listening History</h2>
						<span class="text-xs text-[var(--text-muted)]">({playHistory.total_plays} plays)</span>
					</div>
					<div class="flex gap-1">
						{#each [
							{ v: '24h', l: '24h' },
							{ v: '7d', l: '7d' },
							{ v: '30d', l: '30d' },
							{ v: '90d', l: '90d' },
						] as opt}
							<button
								class="px-2.5 py-1 text-xs rounded transition-colors {playPeriod === opt.v ? 'bg-purple-500 text-white' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] bg-[var(--surface-container)]'}"
								onclick={() => { playPeriod = opt.v; loadPlayHistory(); }}
							>
								{opt.l}
							</button>
						{/each}
					</div>
				</div>

				<div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
					<div>
						<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Plays Over Time</h3>
						<div class="h-48">
							<canvas bind:this={playTimelineChartEl}></canvas>
						</div>
					</div>
					<div>
						<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">By Hour of Day</h3>
						<div class="h-48">
							<canvas bind:this={playHourlyChartEl}></canvas>
						</div>
					</div>
				</div>

				{#if playHistory.top_tracks.length}
					<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
						<div>
							<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Top Tracks (Period)</h3>
							<div class="space-y-1.5">
								{#each playHistory.top_tracks.slice(0, 10) as track, i}
									<div class="flex items-center gap-2 text-sm">
										<span class="w-5 text-right text-[var(--text-muted)] font-mono text-xs">{i + 1}</span>
										<span class="flex-1 truncate text-[var(--text-body)]">{track.title}</span>
										<span class="text-[var(--text-secondary)] truncate max-w-32 text-xs">{track.artist || 'Unknown'}</span>
										<span class="text-purple-400 text-xs font-mono w-8 text-right">{track.plays}x</span>
									</div>
								{/each}
							</div>
						</div>
						<div>
							<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Top Artists (Period)</h3>
							<div class="space-y-1.5">
								{#each playHistory.top_artists.slice(0, 10) as artist, i}
									<div class="flex items-center gap-2 text-sm">
										<span class="w-5 text-right text-[var(--text-muted)] font-mono text-xs">{i + 1}</span>
										<span class="flex-1 truncate text-[var(--text-body)]">{artist.name}</span>
										<span class="text-purple-400 text-xs font-mono w-8 text-right">{artist.plays}x</span>
									</div>
								{/each}
							</div>
						</div>
					</div>
				{/if}
			</Card>
		{/if}

		<!-- Skips -->
		{#if skipSummary}
			<Card padding="p-4" class="mb-8">
				<div class="flex items-center gap-2 mb-4">
					<SkipForward class="w-4 h-4 text-cyan-400" />
					<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Skips</h2>
					<span class="text-xs text-[var(--text-disabled)] hidden sm:inline">Skipped before the halfway mark on the phone or watch · each full listen pays one back</span>
				</div>

				<div class="grid grid-cols-3 gap-3 mb-6">
					<StatTile label="Tracks skipped" value={skipSummary.tracks_with_skips} color="#06b6d4" />
					<StatTile label="Active skips" value={skipSummary.active_skips} color="#06b6d4" />
					<StatTile label="Skipped (7d)" value={skipSummary.skipped_7d} color="#06b6d4" />
				</div>

				{#if skipSummary.top_artists.length}
					<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Most-Skipped Artists</h3>
					<div class="space-y-1.5 mb-4">
						{#each skipSummary.top_artists as artist, i}
							<div class="flex items-center gap-2 text-sm">
								<span class="w-5 text-right text-[var(--text-muted)] font-mono text-xs">{i + 1}</span>
								<span class="flex-1 truncate text-[var(--text-body)]">{artist.name}</span>
								<span class="text-[var(--text-disabled)] text-xs">{artist.tracks} {artist.tracks === 1 ? 'track' : 'tracks'}</span>
								<span class="text-cyan-400 text-xs font-mono w-10 text-right">{artist.skips}</span>
							</div>
						{/each}
					</div>
				{/if}

				<button onclick={toggleSkipDetails}
					class="flex items-center gap-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
					{#if skipDetailsOpen}<ChevronDown class="w-3.5 h-3.5" />{:else}<ChevronRight class="w-3.5 h-3.5" />{/if}
					{skipDetailsOpen ? 'Hide' : 'Show'} skipped tracks
				</button>

				{#if skipDetailsOpen}
					<div class="mt-3">
						{#if skipRowsLoading}
							<Skeleton variant="table-row" count={5} />
						{:else}
							<DataTable
								columns={skipColumns}
								rows={sortedSkipRows}
								rowKey={(r) => r.track_id}
								sortKey={skipSortKey}
								sortDir={skipSortDir}
								onsort={setSkipSort}
								onrowclick={(r) => expandedSkipId = expandedSkipId === r.track_id ? null : r.track_id}
								viewport="32rem"
							>
								{#snippet row(r)}
									<td class="px-3 py-2 max-w-0 w-1/2">
										<p class="truncate text-[var(--text-body)]">{r.title}</p>
										<p class="truncate text-xs text-[var(--text-muted)]">{r.artist || 'Unknown'}</p>
									</td>
									<td class="px-3 py-2 hidden md:table-cell max-w-0 truncate text-[var(--text-secondary)]">{r.album || '—'}</td>
									<td class="px-3 py-2 text-right font-mono text-cyan-400">{r.skip_count}</td>
									<td class="px-3 py-2 text-right font-mono text-[var(--text-secondary)] hidden sm:table-cell">{r.play_count}</td>
									<td class="px-3 py-2 text-right text-xs text-[var(--text-muted)] whitespace-nowrap">{formatRelativeTime(r.last_skipped_at)}</td>
									<td class="px-1 py-1 text-right">
										<button onclick={(e) => { e.stopPropagation(); clearTrackSkips(r); }}
											class="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
											title="Clear skips">
											<RotateCcw class="w-3.5 h-3.5" />
										</button>
									</td>
								{/snippet}
								{#snippet expandRow(r)}
									{#if expandedSkipId === r.track_id}
										<tr>
											<td colspan={skipColumns.length} class="px-3 pb-3 pt-1">
												<div class="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 text-xs bg-[var(--surface-base)] rounded-lg p-3">
													<div><p class="text-[var(--text-disabled)]">Album</p><p class="text-[var(--text-secondary)] truncate">{r.album || '—'}</p></div>
													<div><p class="text-[var(--text-disabled)]">Genre</p><p class="text-[var(--text-secondary)] truncate">{r.genre || '—'}</p></div>
													<div><p class="text-[var(--text-disabled)]">Year</p><p class="text-[var(--text-secondary)]">{r.year || '—'}</p></div>
													<div><p class="text-[var(--text-disabled)]">Length</p><p class="text-[var(--text-secondary)]">{r.duration ? formatDuration(r.duration) : '—'}</p></div>
													<div><p class="text-[var(--text-disabled)]">Format</p><p class="text-[var(--text-secondary)]">{r.format ? r.format.toUpperCase() : '—'}{#if r.bitrate} · {r.bitrate} kbps{/if}</p></div>
													<div><p class="text-[var(--text-disabled)]">Rating</p><p class="text-[var(--text-secondary)]">{r.rating ? '★'.repeat(r.rating) : '—'}{#if r.starred} · ♥{/if}</p></div>
													<div><p class="text-[var(--text-disabled)]">Last played</p><p class="text-[var(--text-secondary)]">{r.last_played_at ? formatRelativeTime(r.last_played_at) : 'Never'}</p></div>
													<div><p class="text-[var(--text-disabled)]">Skip rate</p><p class="text-[var(--text-secondary)]">{r.skip_count + r.play_count ? Math.round(100 * r.skip_count / (r.skip_count + r.play_count)) + '%' : '—'}</p></div>
												</div>
											</td>
										</tr>
									{/if}
								{/snippet}
								{#snippet empty()}
									<p class="text-sm text-[var(--text-muted)]">No skipped tracks yet.</p>
								{/snippet}
							</DataTable>
						{/if}
					</div>
				{/if}
			</Card>
		{/if}

		<!-- AI Usage -->
		{#if aiUsage || aiError}
			<Card padding="p-4" class="mb-8">
				<div class="flex items-center justify-between mb-4">
					<div class="flex items-center gap-2">
						<Sparkles class="w-4 h-4 text-[var(--color-stats)]" />
						<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">AI Usage</h2>
						{#if aiUsage?.summary?.requests}
							<span class="text-xs text-[var(--text-muted)]">({aiUsage.summary.requests.toLocaleString()} calls)</span>
						{/if}
					</div>
					<div class="flex gap-1">
						{#each [
							{ v: 7, l: '7d' },
							{ v: 30, l: '30d' },
							{ v: 90, l: '90d' },
						] as opt}
							<button
								class="px-2.5 py-1 text-xs rounded transition-colors {aiDays === opt.v ? 'bg-[var(--color-stats)] text-white' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] bg-[var(--surface-container)]'}"
								onclick={() => { aiDays = opt.v; loadAIUsage(); }}
							>
								{opt.l}
							</button>
						{/each}
					</div>
				</div>

				{#if aiError}
					<div class="text-center py-12 text-sm">
						<AlertTriangle class="w-8 h-8 mx-auto mb-2 text-red-400 opacity-70" />
						<p class="text-[var(--text-secondary)]">Could not load AI usage.</p>
						<p class="text-xs text-[var(--text-muted)] mt-1">{aiError}</p>
						<p class="text-xs text-[var(--text-disabled)] mt-1">
							If the server was just upgraded, the <span class="font-mono">ai_usage</span> migration may not have run yet.
						</p>
					</div>
				{:else if !aiUsage.summary?.requests}
					<div class="text-center py-12 text-[var(--text-muted)] text-sm">
						<Sparkles class="w-8 h-8 mx-auto mb-2 opacity-30" />
						<p>No AI calls recorded yet.</p>
						{#if aiUsage.all_time?.requests}
							<p class="text-xs mt-1">
								{aiUsage.all_time.requests.toLocaleString()} all-time calls · {formatUSD(aiUsage.all_time.cost_usd)} — none in the last {aiDays} days.
							</p>
						{/if}
					</div>
				{:else}
					<div class="transition-opacity {aiLoading ? 'opacity-50' : ''}">
						<!-- Summary tiles -->
						<div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
							<div class="bg-[var(--surface-container-high)] rounded-lg p-3">
								<p class="text-xs text-[var(--text-muted)]">Requests</p>
								<p class="text-lg font-bold text-[var(--text-primary)]">{aiUsage.summary.requests.toLocaleString()}</p>
								<p class="text-xs text-[var(--text-muted)] mt-0.5">{formatLatency(aiUsage.summary.avg_latency_ms)} avg</p>
							</div>
							<div class="bg-[var(--surface-container-high)] rounded-lg p-3">
								<p class="text-xs text-[var(--text-muted)]">Cost ({aiDays}d)</p>
								<p class="text-lg font-bold text-[var(--text-primary)]">{formatUSD(aiUsage.summary.cost_usd)}</p>
								<p class="text-xs text-[var(--text-muted)] mt-0.5">estimated</p>
							</div>
							<div class="bg-[var(--surface-container-high)] rounded-lg p-3">
								<p class="text-xs text-[var(--text-muted)]">All-time cost</p>
								<p class="text-lg font-bold text-[var(--text-primary)]">{formatUSD(aiUsage.all_time?.cost_usd)}</p>
								<p class="text-xs text-[var(--text-muted)] mt-0.5">{(aiUsage.all_time?.requests || 0).toLocaleString()} calls</p>
							</div>
							<div class="bg-[var(--surface-container-high)] rounded-lg p-3">
								<p class="text-xs text-[var(--text-muted)]">Tokens</p>
								<p class="text-lg font-bold text-[var(--text-primary)]">{formatTokens(aiUsage.summary.total_tokens)}</p>
								<p class="text-xs text-[var(--text-muted)] mt-0.5">
									{formatTokens(aiUsage.summary.input_tokens)} in · {formatTokens(aiUsage.summary.output_tokens)} out{#if (aiUsage.summary.cache_read_tokens || 0) + (aiUsage.summary.cache_write_tokens || 0) > 0} · {formatTokens((aiUsage.summary.cache_read_tokens || 0) + (aiUsage.summary.cache_write_tokens || 0))} cache{/if}
								</p>
							</div>
							<div class="bg-[var(--surface-container-high)] rounded-lg p-3">
								<p class="text-xs text-[var(--text-muted)]">Error rate</p>
								<p class="text-lg font-bold {aiUsage.summary.errors ? 'text-red-400' : 'text-[var(--text-primary)]'}">{((aiUsage.summary.error_rate || 0) * 100).toFixed(1)}%</p>
								<p class="text-xs text-[var(--text-muted)] mt-0.5">{aiUsage.summary.errors || 0} failed</p>
							</div>
						</div>

						<!-- Cost + requests over time (separate charts — never one dual axis) -->
						<div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
							<div>
								<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Estimated Cost Over Time</h3>
								<div class="h-48">
									<canvas bind:this={aiCostChartEl}></canvas>
								</div>
							</div>
							<div>
								<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Requests Over Time</h3>
								<div class="h-48">
									<canvas bind:this={aiRequestsChartEl}></canvas>
								</div>
							</div>
						</div>

						<div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
							<div>
								<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Tokens Over Time</h3>
								<div class="h-48">
									<canvas bind:this={aiTokensChartEl}></canvas>
								</div>
							</div>
							<div>
								<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Cost by Feature</h3>
								<div style="height: {Math.max(192, (aiUsage.by_feature?.length || 1) * 30 + 40)}px">
									<canvas bind:this={aiFeatureChartEl}></canvas>
								</div>
							</div>
						</div>

						<!-- By model -->
						{#if aiUsage.by_model?.length}
							<div class="mb-6">
								<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">By Model</h3>
								<table class="w-full text-sm">
									<thead>
										<tr class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">
											<th class="text-left font-normal pb-1.5">Model</th>
											<th class="text-right font-normal pb-1.5">Calls</th>
											<th class="text-right font-normal pb-1.5">In</th>
											<th class="text-right font-normal pb-1.5">Out</th>
											<th class="text-right font-normal pb-1.5">Cost</th>
										</tr>
									</thead>
									<tbody>
										{#each aiUsage.by_model as m}
											<tr class="border-t border-[var(--border-subtle)]">
												<td class="py-1.5 pr-3 text-[var(--text-body)] font-mono text-xs truncate max-w-64" title={m.model}>
													{m.model}
													{#if !m.known_pricing}
														<span class="text-[var(--text-disabled)] ml-1" title="Model not in the pricing table — costed with a fallback rate">est.</span>
													{/if}
												</td>
												<td class="py-1.5 text-right text-[var(--text-secondary)] font-mono text-xs">{m.requests.toLocaleString()}</td>
												<td class="py-1.5 text-right text-[var(--text-secondary)] font-mono text-xs">{formatTokens(m.input_tokens)}</td>
												<td class="py-1.5 text-right text-[var(--text-secondary)] font-mono text-xs">{formatTokens(m.output_tokens)}</td>
												<td class="py-1.5 text-right text-[var(--text-primary)] font-mono text-xs">{aiModelCost(m.cost_usd)}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}

						<!-- Recent calls -->
						{#if aiUsage.recent?.length}
							<div>
								<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Recent Calls</h3>
								<table class="w-full text-sm">
									<thead>
										<tr class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">
											<th class="text-left font-normal pb-1.5">Time</th>
											<th class="text-left font-normal pb-1.5">Feature</th>
											<th class="text-left font-normal pb-1.5">Model</th>
											<th class="text-right font-normal pb-1.5">Tokens</th>
											<th class="text-right font-normal pb-1.5">Cost</th>
											<th class="text-right font-normal pb-1.5">Latency</th>
										</tr>
									</thead>
									<tbody>
										{#each aiUsage.recent as r}
											<tr class="border-t border-[var(--border-subtle)]">
												<td class="py-1.5 pr-3 text-[var(--text-muted)] font-mono text-xs whitespace-nowrap">{formatDateTimestamp(r.created_at)}</td>
												<td class="py-1.5 pr-3 text-[var(--text-body)] text-xs">
													<span class="inline-flex items-center gap-1.5">
														{#if !r.success}
															<AlertTriangle class="w-3 h-3 text-red-400 flex-shrink-0" />
														{/if}
														{aiFeatureLabel(r.feature)}
													</span>
													{#if !r.success && r.error}
														<span class="text-red-400 text-xs ml-1" title={r.error}>· {r.error}</span>
													{/if}
												</td>
												<td class="py-1.5 pr-3 text-[var(--text-secondary)] font-mono text-xs truncate max-w-48" title={r.model}>{r.model}</td>
												<td class="py-1.5 text-right text-[var(--text-secondary)] font-mono text-xs whitespace-nowrap">{formatTokens(r.input_tokens)} → {formatTokens(r.output_tokens)}</td>
												<td class="py-1.5 text-right text-[var(--text-primary)] font-mono text-xs">{aiRecentCost(r.cost_usd)}</td>
												<td class="py-1.5 text-right text-[var(--text-muted)] font-mono text-xs">{formatLatency(r.latency_ms)}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}

						<!-- Estimate disclaimer — inside {:else} so it only ever
						     disclaims figures that are actually on screen. -->
						<p class="text-xs text-[var(--text-muted)] mt-4 leading-relaxed">
							Cost is <span class="text-[var(--text-secondary)]">estimated</span> from recorded token counts at published rates
							as of {aiUsage.pricing?.as_of || 'unknown'} — these are not billed amounts.
							{#if aiUsage.pricing?.unknown_models?.length}
								Priced with a fallback rate (model not in the pricing table): {aiUsage.pricing.unknown_models.join(', ')}.
							{/if}
						</p>
					</div>
				{/if}
			</Card>
		{/if}

		<!-- System Stats Section -->
		<div class="flex items-center gap-3 mb-6 mt-4">
			<div class="h-px flex-1 bg-[var(--border-subtle)]"></div>
			<span class="text-xs font-mono uppercase tracking-wider text-[var(--text-disabled)]">System</span>
			<div class="h-px flex-1 bg-[var(--border-subtle)]"></div>
		</div>

		<!-- Database & Backend -->
		{#if data.database || data.backend}
			<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
				{#if data.database}
					<Card padding="p-4">
						<div class="flex items-center gap-2 mb-3">
							<Database class="w-4 h-4 text-[var(--color-stats)]" />
							<h3 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Database</h3>
						</div>
						<div class="space-y-2">
							<div class="flex justify-between text-sm">
								<span class="text-[var(--text-muted)]">Backend</span>
								<span class="text-[var(--text-primary)] font-mono">{data.database.backend === 'postgresql' ? 'PostgreSQL' : 'SQLite'}</span>
							</div>
							{#if data.database.file_size_bytes}
								<div class="flex justify-between text-sm">
									<span class="text-[var(--text-muted)]">DB Size</span>
									<span class="text-[var(--text-primary)] font-mono">{formatSize(data.database.file_size_bytes)}</span>
								</div>
							{/if}
							{#if data.database.wal_size_bytes}
								<div class="flex justify-between text-sm">
									<span class="text-[var(--text-muted)]">WAL Size</span>
									<span class="text-[var(--text-primary)] font-mono">{formatSize(data.database.wal_size_bytes)}</span>
								</div>
							{/if}
							{#if data.database.total_rows}
								<div class="flex justify-between text-sm">
									<span class="text-[var(--text-muted)]">Total Rows</span>
									<span class="text-[var(--text-primary)] font-mono">{data.database.total_rows.toLocaleString()}</span>
								</div>
							{/if}
						</div>
					</Card>
				{/if}
				{#if data.backend}
					<Card padding="p-4">
						<div class="flex items-center gap-2 mb-3">
							<Server class="w-4 h-4 text-[var(--color-stats)]" />
							<h3 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Backend</h3>
						</div>
						<div class="space-y-2">
							<div class="flex justify-between text-sm">
								<span class="text-[var(--text-muted)]">Python</span>
								<span class="text-[var(--text-primary)] font-mono">{data.backend.python_version}</span>
							</div>
							<div class="flex justify-between text-sm">
								<span class="text-[var(--text-muted)]">Process ID</span>
								<span class="text-[var(--text-primary)] font-mono">{data.backend.pid}</span>
							</div>
						</div>
					</Card>
				{/if}
			</div>
		{/if}

		<!-- Job Stats -->
		{#if data.job_stats.length}
			<Card padding="p-4" class="mb-8">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Job History Summary</h2>
				<div class="grid grid-cols-2 md:grid-cols-4 gap-3">
					{#each data.job_stats as js}
						<div class="bg-[var(--surface-container)] rounded-lg p-3">
							<p class="text-xs text-[var(--text-muted)]">{js.type}</p>
							<p class="text-sm font-medium text-[var(--text-primary)]">{js.completed} <span class="text-[var(--text-muted)]">/ {js.total}</span></p>
						</div>
					{/each}
				</div>
			</Card>
		{/if}

		<!-- Job Pipeline Dashboard -->
		{#if jobDashboard}
			<Card padding="p-4" class="mb-8">
				<div class="flex items-center gap-2 mb-4">
					<Layers class="w-4 h-4 text-violet-400" />
					<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Job Pipeline (24h)</h2>
					{#if jobDashboard.failure_rate_7d > 0}
						<span class="text-xs text-red-400 ml-auto">{(jobDashboard.failure_rate_7d * 100).toFixed(1)}% failure rate (7d)</span>
					{/if}
				</div>

				<!-- Summary tiles -->
				<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
					<div class="bg-[var(--surface-container)] rounded-lg p-3">
						<p class="text-xs text-[var(--text-muted)]">Active</p>
						<p class="text-lg font-bold text-blue-400">{jobDashboard.active_count}</p>
					</div>
					{#each Object.entries(jobDashboard.status_counts).filter(([, v]) => v > 0) as [status, count]}
						<div class="bg-[var(--surface-container)] rounded-lg p-3">
							<p class="text-xs text-[var(--text-muted)] capitalize">{status}</p>
							<p class="text-lg font-bold {status === 'completed' ? 'text-emerald-400' : status === 'failed' ? 'text-red-400' : status === 'running' ? 'text-blue-400' : 'text-amber-400'}">{count}</p>
						</div>
					{/each}
				</div>

				<div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-4">
					<!-- Status Distribution -->
					<div>
						<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Status Distribution</h3>
						<div class="h-48">
							<canvas bind:this={jobStatusChartEl}></canvas>
						</div>
					</div>
					<!-- Hourly Timeline -->
					<div>
						<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Jobs by Hour</h3>
						<div class="h-48">
							<canvas bind:this={jobTimelineChartEl}></canvas>
						</div>
					</div>
				</div>

				<!-- Type breakdown + avg duration -->
				{#if jobDashboard.type_distribution?.length || jobDashboard.avg_duration_by_type?.length}
					<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
						{#if jobDashboard.type_distribution?.length}
							<div>
								<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">By Type (24h)</h3>
								<div class="space-y-1.5">
									{#each jobDashboard.type_distribution as td}
										<div class="flex items-center gap-2 text-sm">
											<span class="flex-1 text-[var(--text-body)] text-xs">{td.type}</span>
											<span class="text-[var(--text-muted)] text-xs font-mono w-8 text-right">{td.count}</span>
										</div>
									{/each}
								</div>
							</div>
						{/if}
						{#if jobDashboard.avg_duration_by_type?.length}
							<div>
								<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Avg Duration (7d)</h3>
								<div class="space-y-1.5">
									{#each jobDashboard.avg_duration_by_type as ad}
										<div class="flex items-center gap-2 text-sm">
											<span class="flex-1 text-[var(--text-body)] text-xs">{ad.type}</span>
											<span class="text-[var(--text-muted)] text-xs font-mono w-16 text-right">{formatDuration(ad.avg_seconds)}</span>
										</div>
									{/each}
								</div>
							</div>
						{/if}
					</div>
				{/if}
			</Card>
		{/if}

		<!-- Soulseek P2P -->
		{#if slsk}
			<Card padding="p-4" class="mb-8">
				<div class="flex items-center justify-between mb-4">
					<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Soulseek P2P</h2>
					<button
						class="flex items-center gap-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
						onclick={async () => {
							const res = await fetch('/api/download/reset-reputation', { method: 'POST' });
							const d = await res.json();
							slsk = await fetch('/api/download/soulseek-stats').then(r => r.json()).catch(() => slsk);
							addToast(`Reputation reset (${d.cleared} entries cleared)`, 'success');
						}}
					>
						<RotateCcw class="w-3.5 h-3.5" />
						Reset Reputation
					</button>
				</div>

				<!-- Connection & Network -->
				<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
					<div class="bg-[var(--surface-container)] rounded-lg p-4">
						<div class="flex items-center gap-2 mb-2">
							<Wifi class="w-4 h-4 {slsk.connected ? 'text-emerald-400' : 'text-red-400'}" />
							<span class="text-xs text-[var(--text-muted)]">Connection</span>
						</div>
						<p class="text-lg font-bold text-[var(--text-primary)]">{slsk.connected ? 'Online' : 'Offline'}</p>
						{#if slsk.username}
							<p class="text-xs text-[var(--text-muted)] truncate mt-0.5">{slsk.username}</p>
						{/if}
					</div>
					<div class="bg-[var(--surface-container)] rounded-lg p-4">
						<div class="flex items-center gap-2 mb-2">
							<Clock class="w-4 h-4 text-[var(--color-stats)]" />
							<span class="text-xs text-[var(--text-muted)]">Uptime</span>
						</div>
						<p class="text-lg font-bold text-[var(--text-primary)]">{formatUptime(slsk.uptime_seconds)}</p>
						<p class="text-xs text-[var(--text-muted)] mt-0.5">{slsk.reconnects} reconnect{slsk.reconnects !== 1 ? 's' : ''}</p>
					</div>
					<div class="bg-[var(--surface-container)] rounded-lg p-4">
						<div class="flex items-center gap-2 mb-2">
							<Users class="w-4 h-4 text-[var(--color-downloads)]" />
							<span class="text-xs text-[var(--text-muted)]">Peers</span>
						</div>
						<p class="text-lg font-bold text-[var(--text-primary)]">{slsk.peers}</p>
						<p class="text-xs text-[var(--text-muted)] mt-0.5">active connections</p>
					</div>
					<div class="bg-[var(--surface-container)] rounded-lg p-4">
						<div class="flex items-center gap-2 mb-2">
							<Radio class="w-4 h-4 text-[var(--color-discover)]" />
							<span class="text-xs text-[var(--text-muted)]">Listen Port</span>
						</div>
						<p class="text-lg font-bold text-[var(--text-primary)]">{slsk.listen_port || '—'}</p>
						<p class="text-xs text-[var(--text-muted)] mt-0.5">{slsk.active_searches} active search{slsk.active_searches !== 1 ? 'es' : ''}</p>
					</div>
				</div>

				<!-- Sharing & Transfers -->
				<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
					<div class="bg-[var(--surface-container)] rounded-lg p-4">
						<div class="flex items-center gap-2 mb-2">
							<Share2 class="w-4 h-4 text-[var(--color-discover)]" />
							<span class="text-xs text-[var(--text-muted)]">Sharing</span>
						</div>
						<p class="text-lg font-bold text-[var(--text-primary)]">{slsk.shared_files.toLocaleString()}</p>
						<p class="text-xs text-[var(--text-muted)] mt-0.5">{slsk.shared_folders} folders</p>
					</div>
					<div class="bg-[var(--surface-container)] rounded-lg p-4">
						<div class="flex items-center gap-2 mb-2">
							<ArrowUpDown class="w-4 h-4 text-[var(--color-downloads)]" />
							<span class="text-xs text-[var(--text-muted)]">Transfers</span>
						</div>
						<p class="text-lg font-bold text-[var(--text-primary)]">{slsk.active_transfers} active</p>
						<p class="text-xs text-[var(--text-muted)] mt-0.5">{slsk.queued_transfers} queued</p>
					</div>
					<div class="bg-[var(--surface-container)] rounded-lg p-4">
						<div class="flex items-center gap-2 mb-2">
							<HardDrive class="w-4 h-4 text-[var(--color-stats)]" />
							<span class="text-xs text-[var(--text-muted)]">Transferred</span>
						</div>
						<p class="text-lg font-bold text-[var(--text-primary)]">{formatSize(slsk.total_bytes_transferred)}</p>
						<p class="text-xs text-[var(--text-muted)] mt-0.5">{slsk.completed_transfers} done · {slsk.failed_transfers} failed</p>
					</div>
					<div class="bg-[var(--surface-container)] rounded-lg p-4">
						<div class="flex items-center gap-2 mb-2">
							<Zap class="w-4 h-4 text-amber-400" />
							<span class="text-xs text-[var(--text-muted)]">Speed</span>
						</div>
						<p class="text-lg font-bold text-[var(--text-primary)]">{slsk.aggregate_speed > 0 ? formatSpeed(slsk.aggregate_speed) : '—'}</p>
						<p class="text-xs text-[var(--text-muted)] mt-0.5">aggregate</p>
					</div>
				</div>

				<!-- Peer Reputation -->
				{#if slsk.reputation?.tracked_peers > 0}
					<div class="mt-2">
						<div class="flex items-center justify-between mb-2">
							<h3 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Peer Reputation ({slsk.reputation.tracked_peers})</h3>
							{#if slsk.reputation.tracked_peers > 10}
								<button
									class="text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
									onclick={() => showAllPeers = !showAllPeers}
								>
									{showAllPeers ? 'Show less' : `Show all ${slsk.reputation.tracked_peers}`}
								</button>
							{/if}
						</div>
						<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
							{#each (showAllPeers ? slsk.reputation.peers : slsk.reputation.peers.slice(0, 12)) as peer}
								<div class="bg-[var(--surface-container-high)] rounded px-3 py-2 flex items-center gap-2">
									{#if peer.failures > peer.successes}
										<ShieldAlert class="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
									{:else}
										<ShieldCheck class="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
									{/if}
									<div class="min-w-0">
										<p class="text-xs text-[var(--text-body)] truncate" title={peer.username}>{peer.username}</p>
										<p class="text-xs text-[var(--text-muted)]">
											<span class="text-emerald-400">{peer.successes}</span> /
											<span class="text-red-400">{peer.failures}</span>
										</p>
									</div>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			</Card>

			<!-- Soulseek History Charts -->
			<Card padding="p-4" class="mb-8">
				<div class="flex items-center justify-between mb-4">
					<div class="flex items-center gap-2">
						<TrendingUp class="w-4 h-4 text-[var(--color-stats)]" />
						<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">P2P History</h2>
					</div>
					<div class="flex gap-1">
						{#each [
							{ v: 6, l: '6h' },
							{ v: 24, l: '24h' },
							{ v: 72, l: '3d' },
							{ v: 168, l: '7d' },
						] as opt}
							<button
								class="px-2.5 py-1 text-xs rounded transition-colors {historyHours === opt.v ? 'bg-[var(--color-stats)] text-white' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] bg-[var(--surface-container)]'}"
								onclick={() => { historyHours = opt.v; loadHistory(); }}
							>
								{opt.l}
							</button>
						{/each}
					</div>
				</div>

				{#if history?.length > 1}
					<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
						<div>
							<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Peers & Searches</h3>
							<div class="h-48">
								<canvas bind:this={peersChartEl}></canvas>
							</div>
						</div>
						<div>
							<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Transfers</h3>
							<div class="h-48">
								<canvas bind:this={transfersChartEl}></canvas>
							</div>
						</div>
						<div>
							<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Transfer Speed</h3>
							<div class="h-48">
								<canvas bind:this={speedChartEl}></canvas>
							</div>
						</div>
						<div>
							<h3 class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-2">Bandwidth</h3>
							<div class="h-48">
								<canvas bind:this={bandwidthChartEl}></canvas>
							</div>
						</div>
					</div>
				{:else}
					<div class="text-center py-12 text-[var(--text-muted)] text-sm">
						<TrendingUp class="w-8 h-8 mx-auto mb-2 opacity-30" />
						<p>No history data yet. Stats are collected every 5 minutes.</p>
					</div>
				{/if}
			</Card>
		{/if}
	{/if}
</div>
