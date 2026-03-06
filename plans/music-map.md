# Music Map -- Library Visualization - Implementation Plan

## 1. Summary

An interactive full-screen force-directed graph visualizing the library as a network of genres, artists, and tracks. Uses D3.js (d3-force) with SVG rendering and three semantic zoom levels:

- **Genre Map** (zoomed out): Large genre cluster nodes sized by track count, connected by co-occurrence edges
- **Artist Network** (mid-zoom): Artists within genre clusters, connected by Last.fm similarity and shared genre
- **Track Constellation** (zoomed in): Tracks orbiting their artist, colored by energy, connected by CLAP embedding similarity

One new backend API (`backend/api/map.py`), one new frontend route (`/map`), sidebar nav entry. No new database models -- all computed from existing tables.

## 2. Graph Data Model

### Node Types

| Type | ID | Size Signal | Color Signal |
|------|-----|-------------|--------------|
| `genre` | `genre:<name>` | Track count | Fixed hue (hash of name) |
| `artist` | `artist:<id>` | Track count | Primary genre color |
| `track` | `track:<id>` | play_count | Energy (blue→red) |

### Edge Types

| Type | Source → Target | Weight Signal | Data Source |
|------|-----------------|---------------|-------------|
| `genre_cooccurrence` | genre → genre | Artists in both | SQL aggregation |
| `artist_genre` | artist → genre | Track count in genre | SQL group by |
| `artist_similarity` | artist → artist | Last.fm match (0-1) | Cached Last.fm API |
| `track_vibe` | track → track | Cosine similarity (0-1) | CLAP embeddings (threshold > 0.75) |
| `track_artist` | track → artist | 1.0 (structural) | track.artist_id |

### Cluster Assignment

Each artist assigned primary genre (most tracks). Genres become cluster centers. D3 cluster forces pull artists toward their genre. Tracks positioned near artist via strong link force.

## 3. Backend API: `backend/api/map.py`

### `GET /api/map/graph`

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `max_artists` | int | 200 | Cap artist nodes |
| `max_tracks_per_artist` | int | 50 | Cap tracks per artist |
| `min_genre_tracks` | int | 3 | Min tracks for genre to appear |
| `vibe_threshold` | float | 0.75 | Min cosine similarity for vibe edges |
| `vibe_limit` | int | 5 | Max vibe edges per track |
| `include_tracks` | bool | false | Include track-level nodes (expensive) |

**Response:**
```json
{
  "nodes": [
    {"id": "genre:Rock", "type": "genre", "label": "Rock", "size": 142, "color": "#e74c3c"},
    {"id": "artist:abc123", "type": "artist", "label": "Radiohead", "size": 28, "genre": "Rock", "is_favorite": true},
    {"id": "track:def456", "type": "track", "label": "Everything In Its Right Place", "size": 5, "energy": 0.72, "bpm": 123.4}
  ],
  "edges": [
    {"source": "genre:Rock", "target": "genre:Electronic", "type": "genre_cooccurrence", "weight": 12},
    {"source": "artist:abc123", "target": "genre:Rock", "type": "artist_genre", "weight": 28}
  ],
  "meta": {"total_tracks": 1842, "total_artists": 312, "total_genres": 24, "cached": true}
}
```

### `GET /api/map/artist/{artist_id}/detail`

Lazy-load tracks for a single artist on double-click. Returns tracks with analysis, vibe edges, similar artists.

### `GET /api/map/path`

BFS shortest path between two nodes. Params: `from_id`, `to_id`. Returns ordered nodes + edges.

## 4. Graph Builder: `backend/services/graph_builder.py`

### Algorithm

1. Query artists with track counts (ORDER BY count DESC, LIMIT max_artists)
2. Query genres with track counts (HAVING count >= min_genre_tracks)
3. Assign each artist primary genre (genre with most tracks)
4. Build genre nodes + artist nodes
5. Build artist_genre edges
6. Build genre co-occurrence edges (SQL cross-join on artist-genre pairs)
7. If include_tracks: query tracks with analysis + embeddings, build track nodes + vibe edges
8. Query favorite IDs, annotate is_favorite on nodes
9. Return {nodes, edges, meta}

### Database Queries

**Genre aggregation:**
```sql
SELECT genre, COUNT(*) FROM tracks WHERE genre IS NOT NULL
GROUP BY genre HAVING COUNT(*) >= :min ORDER BY COUNT(*) DESC
```

**Artist primary genre:**
```sql
SELECT artist_id, genre, COUNT(*) FROM tracks
WHERE genre IS NOT NULL AND artist_id IN (:ids) GROUP BY artist_id, genre
```

**Genre co-occurrence:**
```sql
SELECT a.genre, b.genre, COUNT(DISTINCT a.artist_id)
FROM (SELECT DISTINCT artist_id, genre FROM tracks WHERE genre IS NOT NULL) a
JOIN (...) b ON a.artist_id = b.artist_id AND a.genre < b.genre
GROUP BY a.genre, b.genre HAVING COUNT(*) > 0
```

### Caching

- In-memory LRU cache keyed by query params hash
- TTL: 5 minutes
- Invalidate on library scan completion

## 5. D3.js Integration

### Dependencies

Add to `frontend/package.json`:
```json
"d3": "^7.9.0"
```

Only import needed modules (tree-shakeable): `d3-force`, `d3-selection`, `d3-zoom`, `d3-scale`, `d3-drag`. ~80KB gzipped.

### Force Simulation

```javascript
const simulation = d3.forceSimulation(nodes)
  .force('charge', d3.forceManyBody()
    .strength(d => d.type === 'genre' ? -300 : d.type === 'artist' ? -80 : -20))
  .force('link', d3.forceLink(edges).id(d => d.id)
    .distance(d => {
      if (d.type === 'artist_genre') return 100;
      if (d.type === 'genre_cooccurrence') return 200;
      if (d.type === 'track_artist') return 30;
      return 120;
    }))
  .force('center', d3.forceCenter(width / 2, height / 2))
  .force('collision', d3.forceCollide().radius(d => d.radius + 2));
```

### Zoom Level Detection

```javascript
const zoom = d3.zoom()
  .scaleExtent([0.1, 8])
  .on('zoom', (event) => {
    const k = event.transform.k;
    if (k < 0.5) level = 'genre';
    else if (k < 2.0) level = 'artist';
    else level = 'track';
    updateVisibility(k);
  });
```

### Node Visibility by Zoom

| Level | Genres | Artists | Tracks | Genre Labels | Artist Labels |
|-------|--------|---------|--------|--------------|---------------|
| genre (k<0.5) | Visible | Hidden | Hidden | Visible | Hidden |
| artist (0.5-2) | Dim 0.2 | Visible | Hidden | Small | Visible |
| track (k>2) | Hidden | Dim 0.3 | Visible | Hidden | Small |

## 6. Frontend Route: `/map`

### Layout

Full-screen, breaks out of standard `<main>` padding. Map fills viewport minus sidebar width.

### Toolbar

- **Search**: Text input, highlights + centers matching nodes
- **Filters**: Genre checkboxes, favorites-only toggle, analyzed-only toggle
- **Zoom level indicator**: Three dots (Genre / Artist / Track), click to snap
- **Fullscreen**: Toggle browser fullscreen
- **Stats**: "312 artists, 24 genres, 1842 tracks"

### Detail Side Panel (320px, slide-in on right)

- **Genre**: Name, track count, top 5 artists
- **Artist**: Name, image, track count, genres, top tracks, similar artists, favorite toggle
- **Track**: Title, artist, album, BPM, key, energy bar, play count, favorite toggle, Play button

### Sidebar Integration

Add to nav in `Sidebar.svelte`:
```javascript
{ href: '/map', label: 'Music Map', icon: Network, color: 'var(--color-map)' }
```

Add `--color-map: #14b8a6` (teal-500) to `app.css`. Keyboard shortcut `M`.

## 7. Interaction Design

| Action | Behavior |
|--------|----------|
| Click node | Open detail panel |
| Click edge | Show tooltip (type, weight) |
| Click empty | Close detail panel |
| Double-click genre | Zoom into cluster (animated) |
| Double-click artist | Lazy-load tracks, zoom to track level |
| Double-click track | Start playback |
| Hover node | Highlight connections, dim everything else |
| Drag node | Pin position (fx/fy); double-click to unpin |
| Search | Filter + highlight matching nodes, center view |
| Right-click | Context menu: path start, open in library, find similar |
| Path finding | Right-click two nodes → BFS path highlighted |

## 8. Performance Considerations

| Library Size | Max Artists | Max Tracks | Strategy |
|-------------|-------------|------------|----------|
| < 500 | All | All (on demand) | Full graph |
| 500-2000 | 200 | 50/artist | Default caps |
| 2000-10000 | 150 | 30/artist | Reduce caps |
| > 10000 | 100 | 20/artist | Aggressive caps |

- Keep total SVG elements under 3000 for 60fps
- Track nodes lazy-loaded on artist double-click (not in initial payload)
- Vibe edges computed with numpy vectorized ops (fast for 50 tracks/artist)
- Cached 5 minutes, ~50KB initial payload for 2000-track library
- Pause simulation when tab is backgrounded (`document.hidden`)
- Future: Canvas 2D renderer for 5000+ track views

## 9. Implementation Steps (Phased)

### Phase 1: Genre Map
1. Create `backend/api/map.py` (genre-level endpoint)
2. Create `backend/services/graph_builder.py` (genre queries)
3. Register router in `main.py`
4. Add `d3` to `package.json`
5. Create `frontend/src/routes/map/+page.svelte` (SVG + D3 force, genre nodes)
6. Add sidebar nav entry, CSS variable, keyboard shortcut
7. Basic zoom/pan, hover highlight

### Phase 2: Artist Network
8. Extend graph_builder with artist queries + primary genre
9. Extend API with `max_artists` param
10. Update frontend: artist nodes, zoom-level visibility, detail panel
11. Add artist click/double-click interactions
12. Add search bar with node highlighting

### Phase 3: Track Constellation + Vibe
13. Add `/api/map/artist/{id}/detail` endpoint
14. Extend graph_builder with vibe edge computation (CLAP embeddings)
15. Update frontend: track nodes (energy color), lazy load on artist double-click
16. Add playback on track double-click
17. Favorite heart badges

### Phase 4: Advanced
18. Add `/api/map/path` endpoint (BFS)
19. Right-click context menu
20. Path visualization (animated dashed edges)
21. Filter toolbar (genre toggles, favorites-only)
22. Fullscreen mode

### Phase 5: Polish
23. Loading/skeleton states
24. Empty state (no tracks)
25. Animation refinements
26. Mobile responsive (touch zoom, bottom sheet detail)
27. Cache invalidation after library scan

## 10. Edge Cases

| Case | Handling |
|------|----------|
| No genre data | Group under synthetic "Untagged" node, hidden by default with toggle |
| No embeddings | Skip vibe edges; banner: "Enable vibe embeddings for track connections" |
| Single-genre library | Skip genre level, start at artist level |
| Artist with 1 track | Include with minimum node size; consider "hide small artists" filter |
| Disconnected components | Weak center force keeps them on-screen |
| Genre string variations | Normalize to title case on backend |
| Last.fm rate limiting | Only use cached similar artist data; "Discover connections" button for fresh calls |
| Empty library | EmptyState component |
| Very long names | Truncate to 20 chars with ellipsis; full name in tooltip |

## 11. Testing Checklist

### Backend
- [ ] `GET /api/map/graph` returns valid nodes + edges
- [ ] Genre node track counts match `/api/library/genres`
- [ ] Artists capped at `max_artists`
- [ ] Genre co-occurrence edges are symmetric
- [ ] `include_tracks=true` adds track nodes + track_artist edges
- [ ] Vibe edges respect threshold and limit
- [ ] Empty library returns `{nodes: [], edges: []}`
- [ ] Cache works within TTL
- [ ] `/api/map/artist/{id}/detail` returns tracks + analysis
- [ ] `/api/map/path` returns shortest path or empty
- [ ] Response < 500ms for 2000-track library

### Frontend
- [ ] Map renders without errors on empty library
- [ ] Genre nodes at low zoom, artist at mid zoom
- [ ] Zoom transitions smooth
- [ ] Click opens detail panel
- [ ] Double-click genre zooms in
- [ ] Double-click artist loads tracks
- [ ] Double-click track plays
- [ ] Search highlights and centers
- [ ] Drag + pin works
- [ ] Hover dims unconnected nodes
- [ ] Sidebar "Music Map" link with teal color
- [ ] Keyboard shortcut `M` works
- [ ] No memory leaks on navigate away
