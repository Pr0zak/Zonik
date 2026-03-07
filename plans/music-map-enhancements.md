# Music Map Enhancements — Phase 1

## Overview
Add view mode selector to the Music Map page with three quick-win overlay modes that recolor/resize existing nodes without changing the graph layout.

## View Modes

### 1. Genre Map (current, default)
No changes needed — existing D3 force graph with genre clusters and artist nodes.

### 2. Duplicate Overlay
- Toggle on/off from view mode selector
- Fetches duplicate groups from `/api/library/duplicates`
- Artist nodes with duplicates get pulsing orange ring
- Click a highlighted node shows duplicate details in the detail panel
- "Keep Best" / "Remove" actions available in panel

### 3. Play Heatmap
- Recolor nodes by play_count
- Hot (red/orange) = frequently played, cold (blue/gray) = never played
- Legend showing gradient scale
- Backend sends play_count data on artist/track nodes (already present on track nodes)
- Artist nodes: aggregate play_count from all tracks

### 4. Quality Map
- Recolor nodes by audio quality
- Green = FLAC/lossless, yellow = 320kbps, orange = mid quality, red = low quality
- Backend adds avg_quality field to artist nodes
- Click low-quality cluster → "Find Upgrades" action in detail panel

## Backend Changes

**Enhance `GET /api/map/graph`**
- Add `mode` query param: "genre" (default), "play_heatmap", "quality"
- For play_heatmap: add `play_count` to artist nodes (sum of track play_counts)
- For quality: add `avg_quality`, `primary_format`, `avg_bitrate` to artist nodes
- Duplicate overlay uses the existing `/api/library/duplicates` endpoint

**New endpoint: `GET /api/library/duplicates/artists`**
- Returns artist IDs that have duplicate tracks (lightweight, for map overlay)

## Frontend Changes

**View mode selector** (dropdown in header bar)
- Options: Genre, Duplicates, Play Heatmap, Quality
- Switching mode recolors nodes without rebuilding the graph
- Each mode has appropriate legend/color scale

**Detail panel enhancements**
- Show mode-specific info (play count, quality, duplicate count)
- Mode-specific actions (Find Upgrade, Remove Duplicates, etc.)

## File Changes
- `backend/api/map.py` — add mode param
- `backend/services/graph_builder.py` — add play/quality data to nodes
- `frontend/src/routes/map/+page.svelte` — view mode selector + recoloring logic
