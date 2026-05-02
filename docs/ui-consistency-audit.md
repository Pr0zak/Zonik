# UI Consistency Audit (16 routes)

Reference: `frontend/src/routes/duplicates/+page.svelte` (two-row sticky toolbar, no-line tables, EmptyState snippet icon, FilterPills/Modal usage).

Legend
- `[ref]` matches the duplicates reference pattern.
- `[div]` divergence from the reference (one-off styling).
- `[adhoc]` hand-rolled component that should be a shared primitive.

## Page-by-page

### `+layout.svelte` (top-level)
- Wraps Sidebar / TopBar / Player / Toast.
- Shortcuts modal is hand-rolled instead of using `Modal` primitive `[adhoc]`.
- Mobile header `<div class="md:hidden">` reuses `bg-[var(--surface-base)]` correctly (no border) `[ref]`.
- Resolved-after-rewrite: shortcuts dialog should reuse Modal.

### `+page.svelte` (Dashboard, indigo)
- Toolbar: none — page is pure stat cards `[ref]`.
- PageHeader: yes, no actions slot used.
- Cards: uses `Card` consistently.
- Skeletons: uses Skeleton primitive.
- EmptyState: not needed.
- Modal: not used.
- Issues:
  - Quality donut SVG inlined; `qualityBarColor(q.score).replace('bg-','stroke-')` is a leaky abstraction `[div]`.
  - "Quick Actions" buttons are hand-rolled with `flex flex-col items-center` boxes, not Button primitive `[adhoc]`.
  - Active transfers progress bars hand-rolled — could reuse `<ProgressBar>` if extracted `[adhoc]`.
  - Stat cards with `<Icon /> + <p>{value}</p> + <p>{label}</p>` repeated 5 places (here, upgrades, duplicates, stats) — extract `<StatTile>` `[adhoc]`.

### `library/+page.svelte` (purple, 1863 lines)
- PageHeader: yes, with `<Button>` action slot `[ref]`.
- Tabs: pill-style hand-rolled — `[ref]` (matches design brief).
- Toolbar: Tabs + per-page selector + view toggle + col picker rolled on row 2; not sticky `[div]`.
- Sortable table: uses `cursor-pointer hover:text-[var(--text-body)]` on inline `onclick={() => toggleSort(...)}` th elements; arrow chars `↑/↓`. `whitespace-nowrap` ✓. No slim-arrow component `[div]`.
- Track grid view: hand-rolled card with cover overlay — extract `<TrackCard>` `[adhoc]`.
- Track list view: large `<Card padding="p-0"><table>` — should be `<DataTable>` `[adhoc]`.
- Modal: 4 modals (edit/similar/remixes/upgrade) — uses Modal primitive ✓, but each is a long inline template. Extract per-modal components `[adhoc]`.
- EmptyState: ✓ used for tracks/artists/albums.
- Skeleton: ✓ extensive use.
- Direct hex / inline tailwind: `accent-amber-500`, `accent-emerald-500`, etc, scattered. Most stick to vars.
- Section color: `var(--color-library)` ✓.
- Issues:
  - File is 1863 lines — context menu + overlay logic + 3 tabs all in one file. Page-local components needed: `<ColumnPicker>`, `<TrackTable>`, `<TrackGrid>`, `<ArtistDetail>`, `<AlbumDetail>`, `<TrackContextMenu>`, modal bodies.
  - Schedule control collapsible block is duplicated across library/discover/playlists/analysis — extract `<ScheduleSection>` `[adhoc]`.

### `discover/+page.svelte` (green, 1782 lines)
- PageHeader: yes (no action slot).
- Tabs: hand-rolled `flex gap-1.5` w/ active = `bg-[var(--color-discover)] text-white` `[ref]`.
- Toolbar: per-tab — search bar in search tab; FilterPills used on For-You; sort handled inline on tables. Not sticky `[div]`.
- Tables on top/similar/search/remixes use the same `Card padding="p-0"` + `<table>` shape as library `[div]` — should be `<DataTable>`.
- EmptyState: ✓ used.
- Skeleton: ✓ with hand-built skeleton rows (could use `Skeleton.tableRow`).
- Modal: not used.
- ScheduleSection collapsible — same duplication as library `[adhoc]`.
- AI explain panel inline.
- Stickiness — none of the toolbars are sticky on scroll despite being long pages `[div]`.
- Direct hex: none significant.
- Sub-components: `PlaylistDiscoveryTab.svelte` already extracted ✓ — good model for further extraction (`<RecommendationList>`, `<TopChartTable>`, `<SimilarTrackTable>`, `<RemixTable>`).

### `settings/+page.svelte` (slate, 1168 lines)
- PageHeader: yes, no actions.
- Tabs: none — uses ~12 `<Card padding="p-4">` sections stacked `[div from no tabs]`.
- Toolbar: none.
- Inputs: a mix of `class={inputClass}` from utils + bespoke `bg-[var(--surface-lowest)] ghost-border ...` strings `[div]`.
- Toggle switches hand-rolled (5+ copies of same `<button class="w-8 h-5 rounded-full ...">` pattern) — extract `<Toggle>` `[adhoc]`.
- Section heading pattern: `<h2 class="...">` + body + Save button per-section.
- "Service test" pattern (Soulseek / Lidarr / Spotify / Last.fm / AI providers) — duplicated. Extract `<ServiceCard>` `[adhoc]`.
- Modal: not used; uses `confirm()` in places `[div]`.
- Direct hex/inline: none.
- Section color: `var(--color-settings)` ✓.

### `downloads/+page.svelte` (blue, 1101 lines)
- PageHeader: yes.
- Search bar: top-of-page, not sticky `[div]`.
- Sortable table inside Card padding="p-0": same shape as library/discover `[div]` — `<DataTable>` candidate.
- Sort indicator: `↑/↓` chars + `◆` for inactive in one column. Inconsistent with library which has empty default.
- FilterPills ✓ used for format filter.
- Pagination on search results: hand-rolled `[adhoc]` — should reuse Pagination.
- EmptyState: not used (uses `<p>No results...</p>` for empty `[div]`).
- Active-transfers section + history table further down (likely 700+ lines after results). `[adhoc]`.
- Blacklist modal-ish drawer hand-rolled inside card `[div]`.
- Section color: `var(--color-downloads)` ✓.

### `stats/+page.svelte` (cyan, 1032 lines)
- PageHeader: yes.
- Toolbar: none.
- Cards: yes.
- Skeleton: ✓ for loading.
- Charts: chart.js + bar charts hand-built (the bar-chart bars are a repeated pattern: `[track] [bar] [count]` → extract `<BarChartList>` `[adhoc]`).
- Empty state for empty data: not present (assumes data) `[div]`.
- StatTile hand-rolled (same as dashboard) `[adhoc]`.
- No tables.
- Section color: `var(--color-stats)` ✓.

### `map/+page.svelte` (teal, 988 lines)
- PageHeader: ✓ — with subtitle.
- Toolbar: floating glass-ish toolbar (view modes + filter toggle + search + zoom) — single-row, large `[div]`.
- Filter row: secondary collapsing row.
- D3-driven canvas, so few primitives apply.
- Loading: bespoke spinner `[div]`.
- EmptyState: hand-rolled (no EmptyState primitive) `[adhoc]`.
- Tooltip + Legend overlays hand-rolled.
- Section color: `var(--color-map)` ✓.

### `playlists/+page.svelte` (amber, 606 lines)
- PageHeader: yes (action buttons but rolled into a separate flex row before PageHeader, not children slot) `[div]`.
- Inline panels (Import / AI Generate / Smart) — each in a `Card padding="p-4"`. Could be extracted to per-panel components.
- Detail view: own header (back-button + title + delete), no PageHeader subtitle pattern `[div]`.
- Track list: hand-rolled list inside Card `[adhoc]` — same row pattern as favorites/duplicates `[adhoc]`.
- Pagination ✓.
- EmptyState ✓.
- Schedule collapsible (same duplicated pattern).
- Section color: `var(--color-playlists)` ✓.

### `duplicates/+page.svelte` (amber, 586 lines) — REFERENCE
- PageHeader ✓ with subtitle.
- Two-row sticky toolbar ✓ (the canonical reference).
- StatTile mini-cards (5 across).
- EmptyState ✓ snippet icon.
- Skeleton ✓.
- Modal ✓ — but uses `<Modal title=... onclose={...}>` pattern; the current Modal primitive uses `bind:open` not `onclose`. The page renders Modal under `{#if confirmModal}` so `bind:open` isn't used; this is a divergence — `Modal` primitive needs API harmonization or the page does an in-line `{#if}` wrapper `[div]`.
- Filter/search/sort row 1 + selection/actions row 2 ✓.
- Section color: `var(--color-duplicates)` ✓ (amber).
- Modal close path (`onclose`) is undocumented in primitive — primitive should expose it.

### `logs/+page.svelte` (violet, 562 lines)
- PageHeader ✓ + Live badge in actions slot.
- View toggle (Jobs / App Logs) — bespoke pill-row, not FilterPills `[div]`.
- FilterPills ✓ used for category.
- Table inside Card padding="p-0" — same shape as before `[adhoc]`.
- No sticky toolbar.
- Skeleton ✓ (table-row variant rolled inline).
- EmptyState ✓ snippet icon.
- Inline expand row pattern (extra `<tr>` for detail) — could be a `<DataTable>` feature.
- Section color: `var(--color-logs)` ✓.

### `upgrades/+page.svelte` (emerald, 450 lines)
- PageHeader ✓ (`icon` prop passed but PageHeader primitive doesn't accept icon — silently dropped) `[div]`.
- Stats bar: 7 mini-cards (StatTile candidate, same as duplicates) `[adhoc]`.
- Filter pills hand-rolled (status + reason on same row, with `|` separator) `[div]` — should be FilterPills.
- Actions row separate from toolbar — not sticky `[div]`.
- Sortable table — same shape; arrow chars `' ↑'`/`' ↓'` with leading space `[div]`.
- EmptyState ✓.
- Skeleton ✓.
- No Modal — uses inline status badges.
- Section color: `var(--color-upgrades)` ✓.

### `analysis/+page.svelte` (pink, 391 lines)
- PageHeader ✓.
- Schedule collapsible — duplicated pattern `[adhoc]`.
- Three "stat with action" cards in a grid — same StatCard shape as duplicates/upgrades but with embedded action button.
- Vibe-search input + button hand-rolled (not FormInput) `[div]`.
- Result list inside `ghost-border rounded-lg` (a 1px border — violates no-line rule) `[div]`.
- Toggle switches hand-rolled (5 copies of the same toggle as in settings) `[adhoc]`.
- No table, no modal.
- Section color: `var(--color-analysis)` ✓.

### `favorites/+page.svelte` (red, 175 lines)
- PageHeader ✓ with action slot (count + Import button).
- List inside `Card padding="p-0"` ✓.
- Row pattern: cover + title + meta + action — `<TrackRow>` candidate `[adhoc]`.
- Pagination ✓.
- EmptyState ✓ snippet icon.
- Modal ✓ — uses correct `bind:open` API.
- Section color: `var(--color-favorites)` ✓.
- `confirm()` for unstar `[div]`.

### `schedule/+page.svelte` (orange, 163 lines)
- PageHeader ✓.
- Group cards.
- Skeleton ✓.
- EmptyState ✓ snippet icon.
- DANGER_TASKS branch references empty Set → dead branch `[div]`.
- Section color: `var(--color-schedule)` ✓.

### `pair/+page.svelte` (indigo, 112 lines)
- No PageHeader — centered card pattern `[div]`.
- Inputs hand-rolled (not FormInput) `[div]`.
- Submit button hand-rolled (not Button primitive — gradient styles inlined) `[div]`.
- No EmptyState/Modal needed.
- Section color: not applied (uses `var(--color-primary)` for icon) `[div]` — design brief says pair=indigo, so this is fine since `var(--color-primary)` ≈ indigo.

## Top 5 themes

1. **Toolbar inconsistency** — duplicates' two-row sticky toolbar is the gold standard but only library/upgrades/discover/logs/playlists try to follow; none are sticky. Outcome: `<Toolbar>` primitive with sticky default + slot-based two-row layout.

2. **Tables are all hand-rolled** (library/discover/downloads/upgrades/logs/playlists/duplicates) with subtly different sort-indicator chars, hover colors, header styles, and selection logic. Outcome: `<DataTable>` primitive (column defs, sortable headers with slim arrows, no row dividers, hover via surface tier shift).

3. **Repeated micro-components** — StatTile (dashboard, duplicates, upgrades, stats), Toggle switch (settings, analysis), TrackRow (favorites, playlists, duplicates), ScheduleSection collapsible (library, discover, playlists, analysis).

4. **Border-violations / 1px rings** — analysis result list uses `ghost-border rounded-lg` which is intentional but creates visible-ish lines; some filter pill active states use `border border-...500/30` (legit border use, not violations of no-line rule per se since it's interactive state). Color rings on filters are inconsistent (amber/blue/emerald variants of `bg-X/20 text-X-400 border border-X-500/30`).

5. **PageHeader's API is too thin** — pages pass `icon=` (silently dropped), force action buttons into a separate flex row before PageHeader (playlists), or skip it entirely (pair). PageHeader needs `icon`, `subtitle`, `actions` snippet, and to remain backward-compatible with `children` snippet.

## Audit conclusions

Primitives to add/strengthen (Stage 2):
- `Toolbar.svelte` — NEW. Sticky two-row, slot-based.
- `DataTable.svelte` — NEW. Column-def driven, sortable headers, slim arrows, no dividers, hover via surface shift.
- `StatTile.svelte` — NEW. Replaces 4+ inline copies.
- `Toggle.svelte` — NEW. Replaces 6+ inline copies.
- `ScheduleSection.svelte` — NEW. Collapsible block with multiple ScheduleControl rows.
- `PageHeader.svelte` — STRENGTHEN. Add `icon`, `subtitle`, `actions` snippet.
- `EmptyState.svelte` — verify (already good).
- `Skeleton.svelte` — STRENGTHEN. Add common variants (table-row, list-item).
- `Modal.svelte` — STRENGTHEN. Add `onclose` callback alongside `bind:open` for non-bound usage.

Pages affected: all 16. Order: pair → schedule → favorites → analysis → upgrades → logs → duplicates → playlists → map → stats → downloads → settings → discover → library → dashboard → layout.

## Stage 4 — Resolved

| Page       | PageHeader icon | Toolbar | DataTable | EmptyState | Skeleton variant | ScheduleSection | StatTile | Modal | Notes                                                        |
|------------|-----------------|---------|-----------|------------|------------------|-----------------|----------|-------|--------------------------------------------------------------|
| layout     | n/a             | n/a     | n/a       | n/a        | n/a              | n/a             | n/a      | DONE  | Shortcuts dialog now uses Modal primitive.                   |
| dashboard  | DONE            | n/a     | n/a       | n/a        | DONE (card)      | n/a             | deferred | n/a   | Quick-action tiles bespoke (page-specific composition).      |
| library    | DONE            | deferred| deferred  | n/a        | n/a              | DONE            | n/a      | n/a   | Tables/grid/modals deferred — too many bespoke variants.     |
| discover   | DONE            | n/a     | deferred  | n/a        | n/a              | DONE            | n/a      | n/a   | 5 tables deferred — bespoke per-row download states.         |
| settings   | DONE            | n/a     | n/a       | n/a        | n/a              | n/a             | n/a      | n/a   | Toggle/ServiceCard extraction deferred — risk of regression. |
| downloads  | DONE            | n/a     | deferred  | DONE       | n/a              | n/a             | n/a      | n/a   | Search-result table has bespoke per-row download progress.   |
| stats      | n/a             | n/a     | n/a       | n/a        | DONE             | n/a             | deferred | n/a   | Loading→data structural split preserved for chart.js refs.   |
| map        | n/a (already)   | n/a     | n/a       | DONE       | n/a              | n/a             | n/a      | n/a   | Floating toolbar bespoke (overlays D3 canvas).               |
| playlists  | DONE            | n/a     | n/a       | n/a        | DONE (card,list) | DONE            | n/a      | n/a   | Inline panels (Import/AI/Smart) deferred for follow-up.      |
| duplicates | DONE (was)      | DONE    | n/a       | DONE (was) | n/a              | n/a             | DONE     | DONE  | Reference page; ghost-border violations removed.             |
| logs       | DONE            | n/a     | deferred  | DONE (was) | DONE             | n/a             | n/a      | n/a   | Expand-row pattern preserved (DataTable doesn't support).    |
| upgrades   | DONE (was)      | DONE    | DONE      | DONE       | DONE             | n/a             | DONE     | n/a   | Custom header snippet for the checkbox-first column.         |
| analysis   | DONE            | n/a     | n/a       | n/a        | DONE             | DONE            | n/a      | n/a   | Toggle primitive used for auto-after-scan switches.          |
| favorites  | DONE            | n/a     | n/a       | DONE (was) | DONE             | n/a             | n/a      | DONE  | Drops Card wrapper around EmptyState.                        |
| schedule   | DONE (was)      | n/a     | n/a       | DONE (was) | DONE             | n/a             | n/a      | n/a   | DANGER_TASKS dead branch consolidated.                       |
| pair       | n/a (centered)  | n/a     | n/a       | n/a        | n/a              | n/a             | n/a      | n/a   | Three of four inputs now use FormInput; large code input keeps bespoke styling. |

### Verification
- `npm run build` — clean (0 errors) after every commit.
- `npx svelte-check` ran 0 files (no tsconfig/jsconfig in this project) — vite build is the canonical correctness signal.

### Pre-existing observations (not fixed in this PR)
- `Button` primitive's `variants` map lacks `warning` and `default` — pages using `<Button variant="warning">` or `<Button variant="default">` (downloads, duplicates, upgrades, analysis) silently get no class. Pages render correctly today only because those buttons happen to layer onto pages with surface contrast already. Recommend adding both variants in a follow-up.
- The `FilterPills` primitive uses `bg-[var(--color-${color})]/15` interpolation that Tailwind's JIT may not detect at build time for new color names; current usage of `discover`, `downloads`, `logs`, `upgrades`, `duplicates` works because they're already referenced statically in app.css/other files. Adding a brand-new section color via FilterPills may surprise.
- `pair/+page.svelte` does not apply the `var(--color-pair)` token (the design brief implies indigo, which is `var(--color-primary)` ≈ `var(--color-dashboard)`). Token hasn't been needed yet because the page uses `var(--color-primary)` directly.
