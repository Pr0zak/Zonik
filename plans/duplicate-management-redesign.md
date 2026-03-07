# Duplicate Management Redesign

## Problem
The current duplicate UI is buried in Library's "Danger Zone" cleanup tools. It shows minimal track info (file path, format badge, bitrate, file size) and feels like a scary destructive operation rather than a useful library management tool.

## Solution
Create a dedicated `/duplicates` route with a rich, library-style list view for managing duplicate tracks.

### Backend Changes

**New endpoint: `GET /api/library/duplicates`**
- Returns enriched duplicate groups with full track details
- Each track includes: id, title, artist, album, format, bitrate, bit_depth, sample_rate, file_size, quality_score, play_count, rating, created_at, file_path, cover_art (album_id for getCoverArt)
- Summary stats: total_groups, total_duplicates, reclaimable_bytes
- Reuses `find_duplicates` logic from cleanup.py but enriched

**Existing endpoints stay** — `POST /api/library/cleanup/duplicates` for removal still works.

### Frontend Changes

**New route: `/duplicates`**
- Page header with stats: "X groups · Y extra files · Z reclaimable"
- Grouped cards, each showing all versions of a track
- Per-version info: cover art, title, artist, album, format badge (color-coded), bitrate, bit_depth/sample_rate, file size, quality score bar, play count, rating stars, added date
- Best version highlighted with green "BEST" badge
- Inferior versions have pre-checked checkboxes for removal
- Bulk actions: "Remove Selected from DB", "Remove + Delete Files", "Auto-select All Inferior"
- Per-group actions: Play, Find Upgrade (→ /downloads search)

**Sidebar: Add "Duplicates" nav entry**
- Icon: Copy (from lucide)
- Color: amber (--color-duplicates)
- Badge with duplicate count (loaded on mount)

**Library page: Replace dedup card with link**
- Keep orphan cleanup and organize tools in Danger Zone
- Replace dedup button with "View Duplicates →" link to /duplicates

## File Changes
- `backend/api/library.py` — add GET /api/library/duplicates endpoint
- `backend/services/cleanup.py` — add `find_duplicates_enriched()` function
- `frontend/src/routes/duplicates/+page.svelte` — new page
- `frontend/src/components/Sidebar.svelte` — add nav entry
- `frontend/src/lib/api.js` — add getDuplicates method
- `frontend/src/routes/library/+page.svelte` — replace dedup card with link
- `frontend/src/app.css` — add --color-duplicates CSS var
