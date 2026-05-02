<script>
	import { onMount, onDestroy, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api.js';
	import { qualityHex } from '$lib/colors.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import { Network, ZoomIn, ZoomOut, Search, X, Eye, Copy, Music, BarChart3, Gem, Zap, Heart, Calendar, Play, Crosshair, Filter, Shuffle } from 'lucide-svelte';
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
	let viewMode = $state('genre');
	let duplicateArtistIds = $state(new Set());

	// Layout mode
	let useVibeLayout = $state(false);

	// Filters
	let showFilters = $state(false);
	let filterMinTracks = $state(1);
	let filterFavOnly = $state(false);
	let filterGenre = $state('');

	// Detail panel
	let detailTracks = $state([]);
	let detailLoading = $state(false);

	// Tooltip
	let tooltip = $state({ show: false, x: 0, y: 0, node: null });

	const VIEW_MODES = [
		{ id: 'genre', label: 'Genre', icon: Network },
		{ id: 'play_heatmap', label: 'Plays', icon: BarChart3 },
		{ id: 'energy', label: 'Energy', icon: Zap },
		{ id: 'mood', label: 'Mood', icon: Heart },
		{ id: 'decade', label: 'Era', icon: Calendar },
		{ id: 'quality', label: 'Quality', icon: Gem },
		{ id: 'duplicates', label: 'Dupes', icon: Copy },
	];

	const MOOD_COLORS = {
		energetic: '#f97316', aggressive: '#ef4444', dark: '#7c3aed', melancholic: '#6366f1',
		sad: '#3b82f6', chill: '#06b6d4', relaxing: '#14b8a6', peaceful: '#10b981',
		happy: '#84cc16', upbeat: '#eab308', romantic: '#ec4899', dreamy: '#a78bfa',
		atmospheric: '#8b5cf6', intense: '#dc2626', groovy: '#f59e0b',
	};

	const DECADE_COLORS = {
		1960: '#d946ef', 1970: '#f97316', 1980: '#eab308', 1990: '#84cc16',
		2000: '#06b6d4', 2010: '#3b82f6', 2020: '#8b5cf6',
	};

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
		if (!playCount || maxPlays === 0) return '#334155';
		const t = Math.min(1, playCount / maxPlays);
		if (t < 0.33) return d3.interpolateRgb('#334155', '#3b82f6')(t / 0.33);
		if (t < 0.66) return d3.interpolateRgb('#3b82f6', '#f59e0b')((t - 0.33) / 0.33);
		return d3.interpolateRgb('#f59e0b', '#ef4444')((t - 0.66) / 0.34);
	}

	function energyColor(energy) {
		if (energy == null) return '#334155';
		const t = Math.min(1, Math.max(0, energy));
		if (t < 0.33) return d3.interpolateRgb('#06b6d4', '#3b82f6')(t / 0.33);
		if (t < 0.66) return d3.interpolateRgb('#3b82f6', '#f59e0b')((t - 0.33) / 0.33);
		return d3.interpolateRgb('#f59e0b', '#ef4444')((t - 0.66) / 0.34);
	}

	function moodColor(mood) {
		if (!mood) return '#334155';
		const key = mood.toLowerCase();
		return MOOD_COLORS[key] || '#6b7280';
	}

	function decadeColor(decade) {
		if (!decade) return '#334155';
		return DECADE_COLORS[decade] || DECADE_COLORS[Math.floor(decade / 10) * 10] || '#6b7280';
	}

	const qualityColor = qualityHex;

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
			case 'energy':
				return energyColor(node.avg_energy);
			case 'mood':
				return moodColor(node.primary_mood);
			case 'decade':
				return decadeColor(node.primary_decade);
			case 'quality':
				return qualityColor(node.avg_quality || 0);
			case 'duplicates':
				return duplicateArtistIds.has(node.id.replace('artist:', '')) ? '#f59e0b' : node.color;
			default:
				return node.color || '#888';
		}
	}

	function matchesFilter(d) {
		if (d.type === 'genre') return true;
		if (filterFavOnly && !d.is_favorite) return false;
		if (filterMinTracks > 1 && (d.size || 0) < filterMinTracks) return false;
		if (filterGenre && d.genre !== filterGenre) return false;
		return true;
	}

	function applyViewMode() {
		if (!nodeSelection || !processedNodes) return;

		nodeSelection.select('circle')
			.transition().duration(400)
			.attr('fill', d => getNodeColor(d))
			.attr('fill-opacity', d => {
				if (!matchesFilter(d)) return 0.05;
				return d.type === 'genre' ? 0.25 : 0.6;
			})
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

		nodeSelection.select('.node-label')
			.transition().duration(400)
			.attr('opacity', d => matchesFilter(d) ? null : 0);

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

	function getTooltipStat(node) {
		switch (viewMode) {
			case 'play_heatmap': return `${node.play_count || 0} plays`;
			case 'energy': return node.avg_energy != null ? `Energy: ${(node.avg_energy * 100).toFixed(0)}%` : '';
			case 'mood': return node.primary_mood || '';
			case 'decade': return node.primary_decade ? `${node.primary_decade}s` : '';
			case 'quality': return `Quality: ${node.avg_quality || 0}`;
			default: return `${node.size} tracks`;
		}
	}

	async function loadGraph() {
		loading = true;
		error = null;
		try {
			const params = { max_artists: 200, min_genre_tracks: 3 };
			if (useVibeLayout) {
				params.layout = 'vibe';
				params.similarity_threshold = 0.7;
			}
			graphData = await api.getMapGraph(params);
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

		const defs = svgEl.append('defs');

		// CSS animation for pulsing ring
		defs.append('style').text(`
			@keyframes pulse-ring {
				0%, 100% { stroke-opacity: 0.6; }
				50% { stroke-opacity: 0.15; }
			}
		`);

		// Glow filter for selected node
		const glow = defs.append('filter').attr('id', 'glow');
		glow.append('feGaussianBlur').attr('stdDeviation', '4').attr('result', 'blur');
		const merge = glow.append('feMerge');
		merge.append('feMergeNode').attr('in', 'blur');
		merge.append('feMergeNode').attr('in', 'SourceGraphic');

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

		// Vibe layout: set fixed positions if available
		const vibePositions = graphData.vibe_positions;
		if (useVibeLayout && vibePositions) {
			nodes.forEach(n => {
				if (n.type === 'artist') {
					const aid = n.id.replace('artist:', '');
					const pos = vibePositions[aid];
					if (pos) {
						n.fx = pos[0] + width / 2;
						n.fy = pos[1] + height / 2;
					}
				}
			});
			// Position genre nodes at centroid of their artists
			nodes.filter(n => n.type === 'genre').forEach(gNode => {
				const genreArtists = nodes.filter(n => n.type === 'artist' && n.genre === gNode.label && n.fx != null);
				if (genreArtists.length) {
					gNode.fx = d3.mean(genreArtists, n => n.fx);
					gNode.fy = d3.mean(genreArtists, n => n.fy);
				} else {
					gNode.fx = width / 2;
					gNode.fy = height / 2;
				}
			});
		}

		// Links
		linkSelection = g.append('g')
			.attr('class', 'links')
			.selectAll('line')
			.data(edges)
			.join('line')
			.attr('stroke', d => {
				if (d.type === 'vibe_similarity') return 'rgba(139,92,246,0.3)';
				if (d.type === 'genre_cooccurrence') return 'rgba(255,255,255,0.08)';
				return 'rgba(255,255,255,0.04)';
			})
			.attr('stroke-width', d => {
				if (d.type === 'vibe_similarity') return Math.max(1, d.weight * 3);
				if (d.type === 'genre_cooccurrence') return Math.min(3, d.weight * 0.5);
				return 0.5;
			})
			.attr('stroke-dasharray', d => d.type === 'vibe_similarity' ? '4,3' : null);

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

		// Artist thumbnails (hidden initially, shown at high zoom)
		const artistsWithImages = nodeSelection.filter(d => d.type === 'artist' && d.image_url);
		artistsWithImages.each(function(d) {
			const node = d3.select(this);
			const clipId = `clip-${d.id.replace(':', '-')}`;
			node.append('clipPath')
				.attr('id', clipId)
				.append('circle')
				.attr('r', d.radius - 1);
			node.append('image')
				.attr('class', 'artist-thumb')
				.attr('href', d.image_url)
				.attr('x', -d.radius)
				.attr('y', -d.radius)
				.attr('width', d.radius * 2)
				.attr('height', d.radius * 2)
				.attr('clip-path', `url(#${clipId})`)
				.attr('opacity', 0)
				.attr('preserveAspectRatio', 'xMidYMid slice');
		});

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
			// Remove previous glow, add to selected
			nodeSelection.select('circle').attr('filter', null);
			d3.select(event.currentTarget).select('circle').attr('filter', 'url(#glow)');
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
			// Tooltip
			tooltip = { show: true, x: event.pageX + 12, y: event.pageY - 10, node: d };

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

		nodeSelection.on('mousemove', (event) => {
			tooltip = { ...tooltip, x: event.pageX + 12, y: event.pageY - 10 };
		});

		nodeSelection.on('mouseleave', () => {
			tooltip = { show: false, x: 0, y: 0, node: null };
			nodeSelection.select('circle').attr('fill-opacity', d => {
				if (!matchesFilter(d)) return 0.05;
				return d.type === 'genre' ? 0.25 : 0.6;
			});
			linkSelection.attr('stroke-opacity', 1);
			linkSelection.attr('stroke', d => {
				if (d.type === 'vibe_similarity') return 'rgba(139,92,246,0.3)';
				if (d.type === 'genre_cooccurrence') return 'rgba(255,255,255,0.08)';
				return 'rgba(255,255,255,0.04)';
			});
		});

		// Click empty to deselect
		svgEl.on('click', () => {
			selectedNode = null;
			nodeSelection.select('circle').attr('filter', null);
		});

		// Simulation
		const forceStrength = useVibeLayout ? 0 : 1;
		simulation = d3.forceSimulation(nodes)
			.force('charge', d3.forceManyBody()
				.strength(d => (d.type === 'genre' ? -300 : -60) * forceStrength))
			.force('link', d3.forceLink(edges)
				.id(d => d.id)
				.distance(d => {
					if (d.type === 'vibe_similarity') return 150;
					if (d.type === 'artist_genre') return 120;
					if (d.type === 'genre_cooccurrence') return 250;
					return 80;
				})
				.strength(d => {
					if (useVibeLayout) return 0;
					return d.type === 'artist_genre' ? 0.3 : 0.1;
				}))
			.force('center', useVibeLayout ? null : d3.forceCenter(width / 2, height / 2))
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
			nodeSelection.select('circle')
				.transition().duration(200)
				.attr('opacity', d => {
					if (!matchesFilter(d)) return 0.05;
					if (level === 'genre') return d.type === 'genre' ? 1 : 0.15;
					if (level === 'artist') return d.type === 'genre' ? 0.2 : 1;
					return d.type === 'track' ? 1 : 0.3;
				});
			nodeSelection.select('.node-label')
				.transition().duration(200)
				.attr('opacity', d => {
					if (!matchesFilter(d)) return 0;
					if (level === 'genre') return d.type === 'genre' ? 1 : 0;
					if (level === 'artist') return d.type === 'artist' ? 1 : (d.type === 'genre' ? 0.5 : 0);
					return d.type === 'track' ? 1 : 0.3;
				});
			// Show artist thumbnails at high zoom
			nodeSelection.select('.artist-thumb')
				.transition().duration(200)
				.attr('opacity', k > 2.0 ? 0.85 : 0);
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
			if (!useVibeLayout) {
				d.fx = null;
				d.fy = null;
			}
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

	async function toggleVibeLayout() {
		useVibeLayout = !useVibeLayout;
		await loadGraph();
		if (graphData) {
			await tick();
			initGraph();
		}
	}

	function highlightSimilar(node) {
		if (!processedNodes || !graphData) return;
		const edges = graphData.edges;
		const connectedIds = new Set();
		connectedIds.add(node.id);
		let found = false;
		edges.forEach(e => {
			if (e.type === 'vibe_similarity') {
				const src = typeof e.source === 'object' ? e.source.id : e.source;
				const tgt = typeof e.target === 'object' ? e.target.id : e.target;
				if (src === node.id) { connectedIds.add(tgt); found = true; }
				if (tgt === node.id) { connectedIds.add(src); found = true; }
			}
		});
		if (!found) {
			if (!useVibeLayout) {
				addToast('Switch to Vibe layout to find similar artists', 'info');
			} else {
				addToast('No similar artists found for this node', 'info');
			}
			return;
		}
		nodeSelection.select('circle')
			.transition().duration(400)
			.attr('fill-opacity', d => connectedIds.has(d.id) ? 0.9 : 0.05);
		nodeSelection.select('.node-label')
			.transition().duration(400)
			.attr('opacity', d => connectedIds.has(d.id) ? 1 : 0);
	}

	async function loadDetailTracks(artistId) {
		detailLoading = true;
		try {
			const data = await api.getTracks({ artist_id: artistId, sort: 'play_count', order: 'desc', limit: 5 });
			detailTracks = data.tracks || data || [];
		} catch {
			detailTracks = [];
		}
		detailLoading = false;
	}

	// Load detail tracks when artist selected
	$effect(() => {
		if (selectedNode?.type === 'artist') {
			const aid = selectedNode.id.replace('artist:', '');
			loadDetailTracks(aid);
		} else {
			detailTracks = [];
		}
	});

	// Get available genres for filter
	let availableGenres = $derived(
		graphData?.nodes?.filter(n => n.type === 'genre').map(n => n.label).sort() || []
	);

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
	<div class="px-3 sm:px-6 pt-5 pb-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
		<PageHeader title="Music Map" icon={Network} color="var(--color-map)"
			subtitle={graphData ? `${graphData.meta.total_artists} artists \u00b7 ${graphData.meta.total_genres} genres \u00b7 ${graphData.meta.total_tracks} tracks` : ''} />

		<div class="flex items-center gap-2 flex-wrap">
			<!-- View mode selector -->
			<div class="flex items-center bg-[var(--surface-container)] rounded ghost-border overflow-hidden">
				{#each VIEW_MODES as mode}
					{@const Icon = mode.icon}
					<button onclick={() => switchViewMode(mode.id)}
						class="flex items-center gap-1 px-2 py-1.5 text-xs transition-colors
							{viewMode === mode.id
								? 'bg-[var(--color-map)]/20 text-[var(--color-map)]'
								: 'text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-white/5'}"
						title={mode.label}>
						<Icon class="w-3.5 h-3.5" />
						<span class="hidden lg:inline">{mode.label}</span>
					</button>
				{/each}
			</div>

			<!-- Layout toggle -->
			<button onclick={toggleVibeLayout}
				class="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border transition-colors
					{useVibeLayout
						? 'bg-purple-500/20 text-purple-400 border-purple-500/30'
						: 'bg-[var(--surface-container)] text-[var(--text-muted)] border-[var(--border-subtle)] hover:text-[var(--text-secondary)]'}"
				title={useVibeLayout ? 'Switch to Force layout' : 'Switch to Vibe layout (sound-based)'}>
				<Shuffle class="w-3.5 h-3.5" />
				<span class="hidden sm:inline">{useVibeLayout ? 'Vibe' : 'Force'}</span>
			</button>

			<!-- Filter toggle -->
			<button onclick={() => showFilters = !showFilters}
				class="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border transition-colors
					{showFilters || filterFavOnly || filterMinTracks > 1 || filterGenre
						? 'bg-[var(--color-map)]/20 text-[var(--color-map)] border-[var(--color-map)]/30'
						: 'bg-[var(--surface-container)] text-[var(--text-muted)] border-[var(--border-subtle)] hover:text-[var(--text-secondary)]'}"
				title="Filters">
				<Filter class="w-3.5 h-3.5" />
			</button>

			<!-- Search -->
			<div class="relative">
				<input type="text" bind:value={searchQuery}
					oninput={updateSearchResults}
					onfocus={() => { searchFocused = true; updateSearchResults(); }}
					onblur={() => setTimeout(() => searchFocused = false, 200)}
					onkeydown={(e) => e.key === 'Enter' && handleSearch()}
					placeholder="Search..."
					class="bg-[var(--surface-container)] text-[var(--text-primary)] text-xs px-3 py-1.5 pl-8 rounded ghost-border w-28 sm:w-40 focus:outline-none focus:border-[var(--color-map)]" />
				<Search class="w-3.5 h-3.5 text-[var(--text-muted)] absolute left-2.5 top-1/2 -translate-y-1/2" />
				{#if searchFocused && searchResults.length}
					<div class="absolute top-full left-0 right-0 mt-1 bg-[var(--surface-base)] ghost-border rounded shadow-lg z-50 max-h-64 overflow-y-auto">
						{#each searchResults as node}
							<button onclick={() => navigateToNode(node)}
								class="w-full text-left px-3 py-1.5 hover:bg-[var(--surface-container-high)] flex items-center gap-2 transition-colors">
								<div class="w-2 h-2 rounded-full flex-shrink-0" style="background-color: {node.color}"></div>
								<span class="text-xs text-[var(--text-primary)] truncate">{node.label}</span>
								<span class="text-xs text-[var(--text-disabled)] ml-auto flex-shrink-0 capitalize">{node.type}</span>
							</button>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Zoom controls -->
			<div class="flex items-center gap-1 bg-[var(--surface-container)] rounded ghost-border px-1">
				<button onclick={() => handleZoom('out')} class="p-1 hover:bg-white/10 rounded transition-colors" title="Zoom out">
					<ZoomOut class="w-4 h-4 text-[var(--text-secondary)]" />
				</button>
				<span class="text-xs font-mono text-[var(--text-muted)] px-1 min-w-[40px] text-center capitalize">{zoomLevel}</span>
				<button onclick={() => handleZoom('in')} class="p-1 hover:bg-white/10 rounded transition-colors" title="Zoom in">
					<ZoomIn class="w-4 h-4 text-[var(--text-secondary)]" />
				</button>
			</div>
		</div>
	</div>

	<!-- Filter bar -->
	{#if showFilters}
		<div class="px-3 sm:px-6 pb-2 flex items-center gap-3 flex-wrap">
			<label class="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
				Genre
				<select bind:value={filterGenre} onchange={() => applyViewMode()}
					class="bg-[var(--surface-container)] text-[var(--text-primary)] text-xs px-2 py-1 rounded ghost-border">
					<option value="">All</option>
					{#each availableGenres as g}
						<option value={g}>{g}</option>
					{/each}
				</select>
			</label>
			<label class="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
				Min tracks
				<input type="range" min="1" max="30" bind:value={filterMinTracks} oninput={() => applyViewMode()}
					class="w-20 h-1 accent-[var(--color-map)]" />
				<span class="text-xs font-mono w-5">{filterMinTracks}</span>
			</label>
			<label class="flex items-center gap-1.5 text-xs text-[var(--text-muted)] cursor-pointer">
				<input type="checkbox" bind:checked={filterFavOnly} onchange={() => applyViewMode()}
					class="accent-[var(--color-favorites)]" />
				Favorites only
			</label>
			{#if filterGenre || filterMinTracks > 1 || filterFavOnly}
				<button onclick={() => { filterGenre = ''; filterMinTracks = 1; filterFavOnly = false; applyViewMode(); }}
					class="text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]">
					Clear filters
				</button>
			{/if}
		</div>
	{/if}

	<div class="flex-1 relative overflow-hidden">
		{#if loading}
			<div class="flex items-center justify-center h-full">
				<div class="text-center">
					<div class="w-16 h-16 border-2 border-[var(--color-map)] border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
					<p class="text-sm text-[var(--text-muted)]">Building graph{useVibeLayout ? ' (computing vibe layout...)' : '...'}</p>
				</div>
			</div>
		{:else if error}
			<div class="flex items-center justify-center h-full">
				<p class="text-sm text-[var(--color-error)]">{error}</p>
			</div>
		{:else if !graphData?.nodes?.length}
			<div class="flex items-center justify-center h-full">
				<EmptyState title="No data to visualize yet" description="Add tracks to your library to see the map">
					{#snippet icon()}<Network class="w-12 h-12" />{/snippet}
				</EmptyState>
			</div>
		{:else}
			<div bind:this={container} class="w-full h-full"></div>

			<!-- Tooltip -->
			{#if tooltip.show && tooltip.node}
				<div class="fixed pointer-events-none z-[100] bg-[var(--surface-base)] ghost-border rounded-lg px-3 py-2 shadow-lg"
					style="left: {tooltip.x}px; top: {tooltip.y}px; max-width: 220px;">
					<p class="text-xs font-semibold text-[var(--text-primary)] truncate">{tooltip.node.label}</p>
					<p class="text-xs text-[var(--text-muted)]">{getTooltipStat(tooltip.node)}</p>
				</div>
			{/if}

			<!-- Legend overlay -->
			<div class="absolute bottom-4 left-4 bg-[var(--surface-base)]/90 ghost-border rounded-lg px-3 py-2.5 backdrop-blur-sm max-w-xs">
				{#if viewMode === 'genre'}
					<p class="text-xs text-[var(--text-muted)] mb-2 uppercase tracking-wider font-medium">Legend</p>
					<div class="space-y-1.5">
						<div class="flex items-center gap-2">
							<div class="w-5 h-5 rounded-full bg-white/10 border border-white/20 flex-shrink-0"></div>
							<span class="text-xs text-[var(--text-secondary)]">Genre cluster</span>
						</div>
						<div class="flex items-center gap-2">
							<div class="w-3 h-3 rounded-full bg-[var(--color-map)] flex-shrink-0 ml-1"></div>
							<span class="text-xs text-[var(--text-secondary)]">Artist (by genre)</span>
						</div>
						<div class="flex items-center gap-2">
							<div class="relative ml-1 flex-shrink-0">
								<div class="w-3 h-3 rounded-full bg-gray-500"></div>
								<div class="w-1.5 h-1.5 rounded-full bg-red-500 absolute -top-0.5 -right-0.5"></div>
							</div>
							<span class="text-xs text-[var(--text-secondary)]">Favorited</span>
						</div>
					</div>
				{:else if viewMode === 'play_heatmap'}
					<p class="text-xs text-[var(--text-muted)] mb-2 uppercase tracking-wider font-medium">Play Count</p>
					<div class="flex items-center gap-2">
						<span class="text-xs text-[var(--text-disabled)]">0</span>
						<div class="w-28 h-2.5 rounded-full" style="background: linear-gradient(to right, #334155, #3b82f6, #f59e0b, #ef4444)"></div>
						<span class="text-xs text-[var(--text-disabled)]">High</span>
					</div>
				{:else if viewMode === 'energy'}
					<p class="text-xs text-[var(--text-muted)] mb-2 uppercase tracking-wider font-medium">Energy</p>
					<div class="flex items-center gap-2">
						<span class="text-xs text-[var(--text-disabled)]">Low</span>
						<div class="w-28 h-2.5 rounded-full" style="background: linear-gradient(to right, #06b6d4, #3b82f6, #f59e0b, #ef4444)"></div>
						<span class="text-xs text-[var(--text-disabled)]">High</span>
					</div>
					<p class="text-xs text-[var(--text-disabled)] mt-1">Based on audio analysis</p>
				{:else if viewMode === 'mood'}
					<p class="text-xs text-[var(--text-muted)] mb-2 uppercase tracking-wider font-medium">Mood</p>
					<div class="flex flex-wrap gap-1.5">
						{#each Object.entries(MOOD_COLORS).slice(0, 8) as [mood, color]}
							<div class="flex items-center gap-1">
								<div class="w-2 h-2 rounded-full" style="background: {color}"></div>
								<span class="text-xs text-[var(--text-secondary)] capitalize">{mood}</span>
							</div>
						{/each}
					</div>
				{:else if viewMode === 'decade'}
					<p class="text-xs text-[var(--text-muted)] mb-2 uppercase tracking-wider font-medium">Era</p>
					<div class="flex flex-wrap gap-1.5">
						{#each Object.entries(DECADE_COLORS) as [decade, color]}
							<div class="flex items-center gap-1">
								<div class="w-2 h-2 rounded-full" style="background: {color}"></div>
								<span class="text-xs text-[var(--text-secondary)]">{decade}s</span>
							</div>
						{/each}
					</div>
				{:else if viewMode === 'quality'}
					<p class="text-xs text-[var(--text-muted)] mb-2 uppercase tracking-wider font-medium">Quality</p>
					<div class="flex items-center gap-2.5 flex-wrap">
						{#each [['#ef4444', 'Low'], ['#f97316', 'Mid'], ['#f59e0b', 'Good'], ['#84cc16', 'High'], ['#22c55e', 'Lossless']] as [color, label]}
							<div class="flex items-center gap-1">
								<div class="w-2.5 h-2.5 rounded-full" style="background: {color}"></div>
								<span class="text-xs text-[var(--text-secondary)]">{label}</span>
							</div>
						{/each}
					</div>
				{:else if viewMode === 'duplicates'}
					<p class="text-xs text-[var(--text-muted)] mb-2 uppercase tracking-wider font-medium">Duplicates</p>
					<div class="flex items-center gap-2">
						<div class="w-4 h-4 rounded-full border-2 border-amber-400 bg-amber-400/30 flex-shrink-0"></div>
						<span class="text-xs text-[var(--text-secondary)]">Has duplicates ({duplicateArtistIds.size})</span>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Detail panel -->
		{#if selectedNode}
			<div class="absolute inset-x-0 bottom-0 sm:inset-x-auto sm:top-0 sm:right-0 sm:bottom-0 w-full sm:w-80 h-2/3 sm:h-full bg-[var(--surface-container)] p-4 overflow-y-auto shadow-float rounded-t-xl sm:rounded-none">
				<div class="flex items-center justify-between mb-3">
					<div class="flex items-center gap-2">
						<div class="w-3 h-3 rounded-full" style="background-color: {getNodeColor(selectedNode)}"></div>
						<span class="text-xs font-mono text-[var(--text-muted)] uppercase">{selectedNode.type}</span>
					</div>
					<button onclick={() => { selectedNode = null; nodeSelection?.select('circle').attr('filter', null); }} class="p-1 hover:bg-white/10 rounded">
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
							<p><span class="text-[var(--text-muted)]">Genre:</span> {selectedNode.genre}</p>
						{/if}
						{#if selectedNode.is_favorite}
							<p class="text-[var(--color-favorites)]">Favorited</p>
						{/if}
						{#if selectedNode.play_count}
							<p><span class="text-[var(--text-muted)]">Plays:</span> {selectedNode.play_count}</p>
						{/if}
						{#if selectedNode.avg_energy != null}
							<p><span class="text-[var(--text-muted)]">Energy:</span> {(selectedNode.avg_energy * 100).toFixed(0)}%</p>
						{/if}
						{#if selectedNode.avg_danceability != null}
							<p><span class="text-[var(--text-muted)]">Danceability:</span> {(selectedNode.avg_danceability * 100).toFixed(0)}%</p>
						{/if}
						{#if selectedNode.avg_bpm}
							<p><span class="text-[var(--text-muted)]">Avg BPM:</span> {selectedNode.avg_bpm}</p>
						{/if}
						{#if selectedNode.primary_mood}
							<p><span class="text-[var(--text-muted)]">Mood:</span>
								<span class="capitalize" style="color: {moodColor(selectedNode.primary_mood)}">{selectedNode.primary_mood}</span>
							</p>
						{/if}
						{#if selectedNode.primary_decade}
							<p><span class="text-[var(--text-muted)]">Era:</span> {selectedNode.primary_decade}s</p>
						{/if}
						{#if selectedNode.primary_format}
							<p><span class="text-[var(--text-muted)]">Format:</span> {selectedNode.primary_format.toUpperCase()}</p>
						{/if}

						<!-- Top tracks with play button -->
						{#if detailTracks.length}
							<div class="mt-3 pt-3 ">
								<p class="text-xs font-mono text-[var(--text-muted)] uppercase tracking-wider mb-2">Top Tracks</p>
								{#each detailTracks.slice(0, 5) as track}
									<button onclick={() => storePlayTrack(track, detailTracks)}
										class="w-full text-left flex items-center gap-2 py-1 hover:bg-[var(--surface-container-high)] rounded px-1 transition-colors group">
										<Play class="w-3 h-3 text-[var(--text-disabled)] group-hover:text-[var(--color-accent)] flex-shrink-0" />
										<span class="text-xs text-[var(--text-body)] truncate">{track.title}</span>
										{#if track.play_count}
											<span class="text-xs text-[var(--text-disabled)] ml-auto flex-shrink-0">{track.play_count}x</span>
										{/if}
									</button>
								{/each}
							</div>
						{/if}

						<!-- Action buttons -->
						<div class="mt-3 pt-3 flex flex-wrap gap-2">
							<button onclick={() => highlightSimilar(selectedNode)}
								class="flex items-center gap-1 text-xs text-purple-400 hover:text-purple-300 transition-colors">
								<Crosshair class="w-3 h-3" /> Find Similar
							</button>
							<button onclick={() => goto(`/downloads?artist=${encodeURIComponent(selectedNode.label)}`)}
								class="flex items-center gap-1 text-xs text-[var(--color-downloads)] hover:underline">
								<Search class="w-3 h-3" /> Search P2P
							</button>
							<button onclick={() => goto(`/library?search=${encodeURIComponent(selectedNode.label)}`)}
								class="flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline">
								<Music class="w-3 h-3" /> View in Library
							</button>
						</div>

						{#if viewMode === 'duplicates' && duplicateArtistIds.has(selectedNode.id.replace('artist:', ''))}
							<div class="mt-3 pt-3">
								<button onclick={() => goto('/duplicates')}
									class="text-xs text-amber-400 hover:underline">
									View in Duplicates Manager
								</button>
							</div>
						{/if}
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>
