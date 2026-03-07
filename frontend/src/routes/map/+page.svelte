<script>
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import { Network, ZoomIn, ZoomOut, Search, X, Eye, Copy, Music, BarChart3, Gem } from 'lucide-svelte';
	import * as d3 from 'd3';

	let container = $state(null);
	let graphData = $state(null);
	let loading = $state(true);
	let error = $state(null);
	let selectedNode = $state(null);
	let zoomLevel = $state('artist');
	let searchQuery = $state('');
	let simulation = null;
	let zoomBehavior = null;
	let currentTransform = $state(d3.zoomIdentity);

	// View modes
	let viewMode = $state('genre'); // 'genre' | 'play_heatmap' | 'quality' | 'duplicates'
	let duplicateArtistIds = $state(new Set());

	const VIEW_MODES = [
		{ id: 'genre', label: 'Genre', icon: Network },
		{ id: 'play_heatmap', label: 'Play Heatmap', icon: BarChart3 },
		{ id: 'quality', label: 'Quality', icon: Gem },
		{ id: 'duplicates', label: 'Duplicates', icon: Copy },
	];

	const ZOOM_THRESHOLDS = { genre: 0.5, artist: 2.0 };

	// Store D3 selections for recoloring
	let nodeSelection = null;
	let linkSelection = null;
	let processedNodes = null;

	function getZoomLevel(k) {
		if (k < ZOOM_THRESHOLDS.genre) return 'genre';
		if (k < ZOOM_THRESHOLDS.artist) return 'artist';
		return 'track';
	}

	// Color scales for view modes
	function playHeatmapColor(playCount, maxPlays) {
		if (!playCount || maxPlays === 0) return '#334155'; // slate-700 (cold)
		const t = Math.min(1, playCount / maxPlays);
		// cold(blue) → warm(orange) → hot(red)
		if (t < 0.33) return d3.interpolateRgb('#334155', '#3b82f6')(t / 0.33);
		if (t < 0.66) return d3.interpolateRgb('#3b82f6', '#f59e0b')((t - 0.33) / 0.33);
		return d3.interpolateRgb('#f59e0b', '#ef4444')((t - 0.66) / 0.34);
	}

	function qualityColor(avgQuality) {
		if (avgQuality >= 120) return '#22c55e'; // green — lossless
		if (avgQuality >= 80) return '#84cc16'; // lime — high
		if (avgQuality >= 50) return '#f59e0b'; // amber — mid
		if (avgQuality >= 30) return '#f97316'; // orange — low
		return '#ef4444'; // red — very low
	}

	function getNodeColor(node) {
		if (node.type === 'genre') {
			if (viewMode === 'genre' || viewMode === 'duplicates') return node.color;
			return 'rgba(255,255,255,0.1)';
		}
		switch (viewMode) {
			case 'play_heatmap': {
				const maxPlays = Math.max(...(processedNodes || []).filter(n => n.type === 'artist').map(n => n.play_count || 0), 1);
				return playHeatmapColor(node.play_count || 0, maxPlays);
			}
			case 'quality':
				return qualityColor(node.avg_quality || 0);
			case 'duplicates':
				return duplicateArtistIds.has(node.id.replace('artist:', '')) ? '#f59e0b' : node.color;
			default:
				return node.color || '#888';
		}
	}

	function applyViewMode() {
		if (!nodeSelection || !processedNodes) return;

		nodeSelection.select('circle')
			.transition().duration(400)
			.attr('fill', d => getNodeColor(d))
			.attr('stroke', d => {
				if (viewMode === 'duplicates' && d.type === 'artist' && duplicateArtistIds.has(d.id.replace('artist:', ''))) {
					return '#f59e0b';
				}
				return getNodeColor(d);
			})
			.attr('stroke-width', d => {
				if (viewMode === 'duplicates' && d.type === 'artist' && duplicateArtistIds.has(d.id.replace('artist:', ''))) {
					return 3;
				}
				return d.type === 'genre' ? 2 : 1;
			});

		// Add/remove pulsing animation for duplicates
		nodeSelection.select('.dupe-ring').remove();
		if (viewMode === 'duplicates') {
			nodeSelection.filter(d => d.type === 'artist' && duplicateArtistIds.has(d.id.replace('artist:', '')))
				.append('circle')
				.attr('class', 'dupe-ring')
				.attr('r', d => d.radius + 4)
				.attr('fill', 'none')
				.attr('stroke', '#f59e0b')
				.attr('stroke-width', 2)
				.attr('stroke-opacity', 0.6)
				.style('animation', 'pulse-ring 2s ease-in-out infinite');
		}
	}

	async function loadGraph() {
		loading = true;
		error = null;
		try {
			graphData = await api.getMapGraph({ max_artists: 200, min_genre_tracks: 3 });
			// Also load duplicate artist IDs
			try {
				const dupeData = await api.getDuplicateArtists();
				duplicateArtistIds = new Set(dupeData.artist_ids || []);
			} catch { /* ignore */ }
		} catch (e) {
			error = e.message;
		}
		loading = false;
	}

	function initGraph() {
		if (!container || !graphData) return;

		const width = container.clientWidth;
		const height = container.clientHeight;

		// Clear previous
		d3.select(container).select('svg').remove();
		if (simulation) simulation.stop();

		const svgEl = d3.select(container)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.style('background', 'var(--bg-primary)');

		// Add CSS animation for pulsing ring
		svgEl.append('defs').append('style').text(`
			@keyframes pulse-ring {
				0%, 100% { stroke-opacity: 0.6; }
				50% { stroke-opacity: 0.15; }
			}
		`);

		const g = svgEl.append('g');

		// Zoom
		zoomBehavior = d3.zoom()
			.scaleExtent([0.1, 8])
			.on('zoom', (event) => {
				g.attr('transform', event.transform);
				currentTransform = event.transform;
				zoomLevel = getZoomLevel(event.transform.k);
				updateVisibility(event.transform.k);
			});
		svgEl.call(zoomBehavior);

		// Process data
		const nodes = graphData.nodes.map(d => ({ ...d }));
		const edges = graphData.edges.map(d => ({ ...d }));
		processedNodes = nodes;

		// Radius scale
		const genreExtent = d3.extent(nodes.filter(n => n.type === 'genre'), d => d.size);
		const artistExtent = d3.extent(nodes.filter(n => n.type === 'artist'), d => d.size);
		const genreRadius = d3.scaleSqrt().domain(genreExtent[0] ? genreExtent : [1, 100]).range([20, 60]);
		const artistRadius = d3.scaleSqrt().domain(artistExtent[0] ? artistExtent : [1, 50]).range([6, 20]);

		nodes.forEach(n => {
			n.radius = n.type === 'genre' ? genreRadius(n.size) : artistRadius(n.size);
		});

		// Links
		linkSelection = g.append('g')
			.attr('class', 'links')
			.selectAll('line')
			.data(edges)
			.join('line')
			.attr('stroke', d => d.type === 'genre_cooccurrence' ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.04)')
			.attr('stroke-width', d => d.type === 'genre_cooccurrence' ? Math.min(3, d.weight * 0.5) : 0.5);

		// Nodes
		nodeSelection = g.append('g')
			.attr('class', 'nodes')
			.selectAll('g')
			.data(nodes)
			.join('g')
			.attr('cursor', 'pointer')
			.call(d3.drag()
				.on('start', dragstarted)
				.on('drag', dragged)
				.on('end', dragended));

		// Circle
		nodeSelection.append('circle')
			.attr('r', d => d.radius)
			.attr('fill', d => getNodeColor(d))
			.attr('fill-opacity', d => d.type === 'genre' ? 0.25 : 0.6)
			.attr('stroke', d => getNodeColor(d))
			.attr('stroke-width', d => d.type === 'genre' ? 2 : 1)
			.attr('stroke-opacity', 0.8);

		// Favorite badge
		nodeSelection.filter(d => d.is_favorite)
			.append('circle')
			.attr('r', d => d.radius * 0.3)
			.attr('cx', d => d.radius * 0.6)
			.attr('cy', d => -d.radius * 0.6)
			.attr('fill', '#ef4444');

		// Labels
		nodeSelection.append('text')
			.text(d => d.label.length > 20 ? d.label.slice(0, 18) + '...' : d.label)
			.attr('text-anchor', 'middle')
			.attr('dy', d => d.radius + 14)
			.attr('fill', 'var(--text-secondary)')
			.attr('font-size', d => d.type === 'genre' ? '12px' : '9px')
			.attr('font-weight', d => d.type === 'genre' ? '600' : '400')
			.attr('class', 'node-label');

		// Interactions
		nodeSelection.on('click', (event, d) => {
			event.stopPropagation();
			selectedNode = d;
		});

		nodeSelection.on('dblclick', (event, d) => {
			if (d.type === 'genre') {
				const genreArtists = nodes.filter(n => n.type === 'artist' && n.genre === d.label);
				if (genreArtists.length) {
					const cx = d3.mean(genreArtists, n => n.x);
					const cy = d3.mean(genreArtists, n => n.y);
					svgEl.transition().duration(750).call(
						zoomBehavior.transform,
						d3.zoomIdentity.translate(width / 2, height / 2).scale(1.5).translate(-cx, -cy)
					);
				}
			}
		});

		nodeSelection.on('mouseenter', (event, d) => {
			const connectedIds = new Set();
			connectedIds.add(d.id);
			edges.forEach(e => {
				const src = typeof e.source === 'object' ? e.source.id : e.source;
				const tgt = typeof e.target === 'object' ? e.target.id : e.target;
				if (src === d.id) connectedIds.add(tgt);
				if (tgt === d.id) connectedIds.add(src);
			});
			nodeSelection.select('circle').attr('fill-opacity', n => connectedIds.has(n.id) ? 0.9 : 0.1);
			linkSelection.attr('stroke-opacity', e => {
				const src = typeof e.source === 'object' ? e.source.id : e.source;
				const tgt = typeof e.target === 'object' ? e.target.id : e.target;
				return connectedIds.has(src) && connectedIds.has(tgt) ? 0.6 : 0.02;
			});
		});

		nodeSelection.on('mouseleave', () => {
			nodeSelection.select('circle').attr('fill-opacity', d => d.type === 'genre' ? 0.25 : 0.6);
			linkSelection.attr('stroke-opacity', 1);
			linkSelection.attr('stroke', d => d.type === 'genre_cooccurrence' ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.04)');
		});

		// Click empty to deselect
		svgEl.on('click', () => { selectedNode = null; });

		// Simulation
		simulation = d3.forceSimulation(nodes)
			.force('charge', d3.forceManyBody()
				.strength(d => d.type === 'genre' ? -300 : -60))
			.force('link', d3.forceLink(edges)
				.id(d => d.id)
				.distance(d => {
					if (d.type === 'artist_genre') return 120;
					if (d.type === 'genre_cooccurrence') return 250;
					return 80;
				})
				.strength(d => d.type === 'artist_genre' ? 0.3 : 0.1))
			.force('center', d3.forceCenter(width / 2, height / 2))
			.force('collision', d3.forceCollide().radius(d => d.radius + 4))
			.on('tick', () => {
				linkSelection
					.attr('x1', d => d.source.x)
					.attr('y1', d => d.source.y)
					.attr('x2', d => d.target.x)
					.attr('y2', d => d.target.y);
				nodeSelection.attr('transform', d => `translate(${d.x},${d.y})`);
			});

		// Apply initial view mode if not genre
		if (viewMode !== 'genre') applyViewMode();

		function updateVisibility(k) {
			const level = getZoomLevel(k);
			nodeSelection.select('circle').attr('opacity', d => {
				if (level === 'genre') return d.type === 'genre' ? 1 : 0.15;
				if (level === 'artist') return d.type === 'genre' ? 0.2 : 1;
				return d.type === 'track' ? 1 : 0.3;
			});
			nodeSelection.select('.node-label').attr('opacity', d => {
				if (level === 'genre') return d.type === 'genre' ? 1 : 0;
				if (level === 'artist') return d.type === 'artist' ? 1 : (d.type === 'genre' ? 0.5 : 0);
				return d.type === 'track' ? 1 : 0.3;
			});
		}

		function dragstarted(event, d) {
			if (!event.active) simulation.alphaTarget(0.3).restart();
			d.fx = d.x;
			d.fy = d.y;
		}

		function dragged(event, d) {
			d.fx = event.x;
			d.fy = event.y;
		}

		function dragended(event, d) {
			if (!event.active) simulation.alphaTarget(0);
			d.fx = null;
			d.fy = null;
		}
	}

	function handleZoom(direction) {
		if (!container || !zoomBehavior) return;
		const svgEl = d3.select(container).select('svg');
		const factor = direction === 'in' ? 1.5 : 0.67;
		svgEl.transition().duration(300).call(zoomBehavior.scaleBy, factor);
	}

	let searchResults = $state([]);
	let searchFocused = $state(false);

	function fuzzyScore(label, query) {
		const l = label.toLowerCase();
		const q = query.toLowerCase();
		if (l === q) return 100;
		if (l.startsWith(q)) return 90;
		if (l.includes(q)) return 80;
		let li = 0;
		let matched = 0;
		let consecutive = 0;
		let maxConsecutive = 0;
		for (let qi = 0; qi < q.length; qi++) {
			const found = l.indexOf(q[qi], li);
			if (found === -1) return 0;
			matched++;
			consecutive = (found === li) ? consecutive + 1 : 1;
			maxConsecutive = Math.max(maxConsecutive, consecutive);
			li = found + 1;
		}
		return 30 + (matched / q.length) * 20 + maxConsecutive * 5 - (li - matched) * 0.5;
	}

	function updateSearchResults() {
		const q = searchQuery.trim();
		if (!q || !graphData?.nodes) { searchResults = []; return; }
		searchResults = graphData.nodes
			.map(n => ({ node: n, score: fuzzyScore(n.label, q) }))
			.filter(r => r.score > 0)
			.sort((a, b) => b.score - a.score)
			.slice(0, 8)
			.map(r => r.node);
	}

	function navigateToNode(node) {
		if (!container || !zoomBehavior) return;
		// Find the simulation node (has x,y) by matching ID
		const simNode = processedNodes?.find(n => n.id === node.id);
		const target = simNode || node;
		if (target.x === undefined) return;
		const svgEl = d3.select(container).select('svg');
		const width = container.clientWidth;
		const height = container.clientHeight;
		svgEl.transition().duration(750).call(
			zoomBehavior.transform,
			d3.zoomIdentity.translate(width / 2, height / 2).scale(1.5).translate(-target.x, -target.y)
		);
		selectedNode = target;
		searchResults = [];
		searchFocused = false;
	}

	function handleSearch() {
		if (searchResults.length) navigateToNode(searchResults[0]);
	}

	function switchViewMode(mode) {
		viewMode = mode;
		applyViewMode();
	}

	onMount(() => {
		loadGraph().then(() => {
			if (graphData) setTimeout(initGraph, 50);
		});
	});

	onDestroy(() => {
		if (simulation) simulation.stop();
	});

	$effect(() => {
		if (graphData && container) {
			initGraph();
		}
	});
</script>

<div class="flex flex-col h-[calc(100vh-8rem)] -m-4 md:-m-6">
	<div class="px-6 pt-5 pb-3 flex items-center justify-between flex-wrap gap-2">
		<PageHeader title="Music Map" icon={Network} color="var(--color-map)"
			subtitle={graphData ? `${graphData.meta.total_artists} artists \u00b7 ${graphData.meta.total_genres} genres \u00b7 ${graphData.meta.total_tracks} tracks` : ''} />

		<div class="flex items-center gap-2">
			<!-- View mode selector -->
			<div class="flex items-center bg-[var(--bg-tertiary)] rounded border border-[var(--border-subtle)] overflow-hidden">
				{#each VIEW_MODES as mode}
					{@const Icon = mode.icon}
					<button onclick={() => switchViewMode(mode.id)}
						class="flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] transition-colors
							{viewMode === mode.id
								? 'bg-[var(--color-map)]/20 text-[var(--color-map)]'
								: 'text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-white/5'}"
						title={mode.label}>
						<Icon class="w-3.5 h-3.5" />
						<span class="hidden sm:inline">{mode.label}</span>
					</button>
				{/each}
			</div>

			<!-- Search -->
			<div class="relative">
				<input type="text" bind:value={searchQuery}
					oninput={updateSearchResults}
					onfocus={() => { searchFocused = true; updateSearchResults(); }}
					onblur={() => setTimeout(() => searchFocused = false, 200)}
					onkeydown={(e) => e.key === 'Enter' && handleSearch()}
					placeholder="Search nodes..."
					class="bg-[var(--bg-tertiary)] text-[var(--text-primary)] text-xs px-3 py-1.5 pl-8 rounded border border-[var(--border-subtle)] w-48 focus:outline-none focus:border-[var(--color-map)]" />
				<Search class="w-3.5 h-3.5 text-[var(--text-muted)] absolute left-2.5 top-1/2 -translate-y-1/2" />
				{#if searchFocused && searchResults.length}
					<div class="absolute top-full left-0 right-0 mt-1 bg-[var(--bg-secondary)] border border-[var(--border-subtle)] rounded shadow-lg z-50 max-h-64 overflow-y-auto">
						{#each searchResults as node}
							<button onclick={() => navigateToNode(node)}
								class="w-full text-left px-3 py-1.5 hover:bg-[var(--bg-hover)] flex items-center gap-2 transition-colors">
								<div class="w-2 h-2 rounded-full flex-shrink-0" style="background-color: {node.color}"></div>
								<span class="text-xs text-[var(--text-primary)] truncate">{node.label}</span>
								<span class="text-[10px] text-[var(--text-disabled)] ml-auto flex-shrink-0 capitalize">{node.type}</span>
							</button>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Zoom controls -->
			<div class="flex items-center gap-1 bg-[var(--bg-tertiary)] rounded border border-[var(--border-subtle)] px-1">
				<button onclick={() => handleZoom('out')} class="p-1 hover:bg-white/10 rounded transition-colors" title="Zoom out">
					<ZoomOut class="w-4 h-4 text-[var(--text-secondary)]" />
				</button>
				<span class="text-[10px] font-mono text-[var(--text-muted)] px-1 min-w-[50px] text-center capitalize">{zoomLevel}</span>
				<button onclick={() => handleZoom('in')} class="p-1 hover:bg-white/10 rounded transition-colors" title="Zoom in">
					<ZoomIn class="w-4 h-4 text-[var(--text-secondary)]" />
				</button>
			</div>
		</div>
	</div>

	<div class="flex-1 relative overflow-hidden">
		{#if loading}
			<div class="flex items-center justify-center h-full">
				<div class="text-center">
					<Skeleton class="w-64 h-64 rounded-full mx-auto mb-4" />
					<p class="text-sm text-[var(--text-muted)]">Building graph...</p>
				</div>
			</div>
		{:else if error}
			<div class="flex items-center justify-center h-full">
				<p class="text-sm text-[var(--color-error)]">{error}</p>
			</div>
		{:else if !graphData?.nodes?.length}
			<div class="flex items-center justify-center h-full">
				<div class="text-center">
					<Network class="w-12 h-12 text-[var(--text-disabled)] mx-auto mb-3" />
					<p class="text-sm text-[var(--text-muted)]">No data to visualize yet</p>
					<p class="text-xs text-[var(--text-disabled)] mt-1">Add tracks to your library to see the map</p>
				</div>
			</div>
		{:else}
			<div bind:this={container} class="w-full h-full"></div>

			<!-- Legend overlay -->
			<div class="absolute bottom-4 left-4 bg-[var(--bg-secondary)]/90 border border-[var(--border-subtle)] rounded-lg px-3 py-2.5 backdrop-blur-sm max-w-xs">
				{#if viewMode === 'genre'}
					<p class="text-[10px] text-[var(--text-muted)] mb-2 uppercase tracking-wider font-medium">Legend</p>
					<div class="space-y-1.5">
						<div class="flex items-center gap-2">
							<div class="w-5 h-5 rounded-full bg-white/10 border border-white/20 flex-shrink-0"></div>
							<span class="text-[11px] text-[var(--text-secondary)]">Genre cluster (size = track count)</span>
						</div>
						<div class="flex items-center gap-2">
							<div class="w-3 h-3 rounded-full bg-[var(--color-map)] flex-shrink-0 ml-1"></div>
							<span class="text-[11px] text-[var(--text-secondary)]">Artist (colored by genre)</span>
						</div>
						<div class="flex items-center gap-2">
							<div class="relative ml-1 flex-shrink-0">
								<div class="w-3 h-3 rounded-full bg-gray-500"></div>
								<div class="w-1.5 h-1.5 rounded-full bg-red-500 absolute -top-0.5 -right-0.5"></div>
							</div>
							<span class="text-[11px] text-[var(--text-secondary)]">Favorited artist</span>
						</div>
						<div class="flex items-center gap-2">
							<div class="w-5 border-t border-white/20 flex-shrink-0 ml-0.5"></div>
							<span class="text-[11px] text-[var(--text-secondary)]">Genre connection</span>
						</div>
					</div>
				{:else if viewMode === 'play_heatmap'}
					<p class="text-[10px] text-[var(--text-muted)] mb-2 uppercase tracking-wider font-medium">Play Count</p>
					<div class="space-y-1.5">
						<div class="flex items-center gap-2">
							<span class="text-[11px] text-[var(--text-disabled)]">0</span>
							<div class="w-28 h-2.5 rounded-full" style="background: linear-gradient(to right, #334155, #3b82f6, #f59e0b, #ef4444)"></div>
							<span class="text-[11px] text-[var(--text-disabled)]">High</span>
						</div>
						<p class="text-[10px] text-[var(--text-disabled)]">Artist nodes colored by total plays</p>
					</div>
				{:else if viewMode === 'quality'}
					<p class="text-[10px] text-[var(--text-muted)] mb-2 uppercase tracking-wider font-medium">Audio Quality</p>
					<div class="space-y-1.5">
						<div class="flex items-center gap-2.5 flex-wrap">
							{#each [['#ef4444', 'Low'], ['#f97316', 'Mid'], ['#f59e0b', 'Good'], ['#84cc16', 'High'], ['#22c55e', 'Lossless']] as [color, label]}
								<div class="flex items-center gap-1">
									<div class="w-2.5 h-2.5 rounded-full" style="background: {color}"></div>
									<span class="text-[11px] text-[var(--text-secondary)]">{label}</span>
								</div>
							{/each}
						</div>
						<p class="text-[10px] text-[var(--text-disabled)]">Based on format + bitrate score</p>
					</div>
				{:else if viewMode === 'duplicates'}
					<p class="text-[10px] text-[var(--text-muted)] mb-2 uppercase tracking-wider font-medium">Duplicates</p>
					<div class="space-y-1.5">
						<div class="flex items-center gap-2">
							<div class="w-4 h-4 rounded-full border-2 border-amber-400 bg-amber-400/30 flex-shrink-0"></div>
							<span class="text-[11px] text-[var(--text-secondary)]">Artist with duplicate tracks</span>
						</div>
						<p class="text-[10px] text-[var(--text-disabled)]">{duplicateArtistIds.size} artist{duplicateArtistIds.size !== 1 ? 's' : ''} affected</p>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Detail panel -->
		{#if selectedNode}
			<div class="absolute top-0 right-0 w-80 h-full bg-[var(--bg-secondary)] border-l border-[var(--border-subtle)] p-4 overflow-y-auto shadow-lg">
				<div class="flex items-center justify-between mb-3">
					<div class="flex items-center gap-2">
						<div class="w-3 h-3 rounded-full" style="background-color: {getNodeColor(selectedNode)}"></div>
						<span class="text-[10px] font-mono text-[var(--text-muted)] uppercase">{selectedNode.type}</span>
					</div>
					<button onclick={() => selectedNode = null} class="p-1 hover:bg-white/10 rounded">
						<X class="w-4 h-4 text-[var(--text-muted)]" />
					</button>
				</div>
				<h3 class="text-lg font-semibold text-[var(--text-primary)] mb-2">{selectedNode.label}</h3>
				<div class="space-y-2 text-xs text-[var(--text-secondary)]">
					{#if selectedNode.type === 'genre'}
						<p><span class="text-[var(--text-muted)]">Tracks:</span> {selectedNode.size}</p>
					{:else if selectedNode.type === 'artist'}
						<p><span class="text-[var(--text-muted)]">Tracks:</span> {selectedNode.size}</p>
						{#if selectedNode.genre}
							<p><span class="text-[var(--text-muted)]">Primary genre:</span> {selectedNode.genre}</p>
						{/if}
						{#if selectedNode.is_favorite}
							<p class="text-[var(--color-favorites)]">Favorited</p>
						{/if}

						<!-- View-mode specific details -->
						{#if viewMode === 'play_heatmap' || selectedNode.play_count}
							<p><span class="text-[var(--text-muted)]">Total plays:</span> {selectedNode.play_count || 0}</p>
						{/if}
						{#if viewMode === 'quality' || selectedNode.primary_format}
							<p><span class="text-[var(--text-muted)]">Primary format:</span> {selectedNode.primary_format?.toUpperCase()}</p>
							{#if selectedNode.avg_bitrate}
								<p><span class="text-[var(--text-muted)]">Avg bitrate:</span> {Math.round(selectedNode.avg_bitrate / 1000)}kbps</p>
							{/if}
							<p><span class="text-[var(--text-muted)]">Quality score:</span> {selectedNode.avg_quality}</p>
						{/if}
						{#if viewMode === 'duplicates' && duplicateArtistIds.has(selectedNode.id.replace('artist:', ''))}
							<div class="mt-2 pt-2 border-t border-[var(--border-primary)]">
								<p class="text-amber-400 mb-2">Has duplicate tracks</p>
								<button onclick={() => goto('/duplicates')}
									class="text-xs text-[var(--color-accent)] hover:underline">
									View in Duplicates Manager
								</button>
							</div>
						{/if}
						{#if viewMode === 'quality' && (selectedNode.avg_quality || 0) < 60}
							<div class="mt-2 pt-2 border-t border-[var(--border-primary)]">
								<button onclick={() => goto(`/downloads?artist=${encodeURIComponent(selectedNode.label)}`)}
									class="text-xs text-[var(--color-accent)] hover:underline">
									Find Upgrades on Soulseek
								</button>
							</div>
						{/if}
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>
