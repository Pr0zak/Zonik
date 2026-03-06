# Settings Page UI Overhaul Plan

## Current Issues
- **Sections not clear**: Soulseek, Lidarr, Last.fm lumped into one massive "Service Connections" card with internal dividers
- **Sync schedule orphaned**: Last.fm Favorites Sync floats in a separate card between Service Connections and Subsonic — disconnected from Last.fm
- **Share Library misplaced**: Soulseek "Share Library" toggle buried in Service Connections — belongs in Library section with better description
- **Test buttons look like badges**: Styled as clickable `<Badge>` text (e.g., green "Connected"), not recognizable as action buttons
- **Save button unclear scope**: Single Save in Service Connections header — not obvious it covers all fields below
- **Subsonic is read-only info** but styled identically to configurable sections — misleading
- **No section icons**: Unlike every other page, sections lack visual identity

## Proposed Section Order

### 1. Library & Storage (icon: Music, color: purple)
- Music Directory (read-only, from zonik.toml)
- Track / Artist / Album counts
- Download Directory (editable)
- Cover Art Cache (editable)
- File Naming Scheme (editable + variable help)
- **Share Library toggle** (moved from Soulseek) — "Share your music with Soulseek peers so others can browse and download from your library"
- Sub-label group: "Paths" and "Sharing"

### 2. Soulseek (icon: Network, color: blue)
- Username / Password / Listen Port (3-col)
- Download Queue / Sources per Track / Source Strategy (3-col)
- Test Connection button (real `<Button>`, not Badge)
- Sub-label groups: "Connection", "Download Settings"

### 3. Last.fm (icon: Radio, color: red)
- Read API Key / Write API Key / Write API Secret (3-col)
- Authentication status + Authenticate button + token paste
- **Favorites Sync schedule** (moved here from separate card)
- Test Connection button
- Sub-label groups: "API Keys", "Authentication", "Sync"

### 4. Lidarr (icon: HardDrive, color: green)
- Enable/disable toggle inline with header
- URL / API Key (2-col, shown only when enabled)
- Helper text when disabled
- Test button (only when enabled)

### 5. Subsonic — info only (icon: Server, color: slate)
- Server name, API version, endpoint, default user
- Test button
- Styled as info card (no edit fields, lighter bg treatment)

### 6. Users & Access (icon: Users, color: amber)
- User list (password, API key management)
- Add user form

### 7. Database (icon: Database, color: cyan)
- Create Backup button
- Backup list + restore

### 8. About & Updates (icon: Info, color: slate)
- Version, check updates, upgrade — bottom of page

## Design Patterns

### Section Headers
```
[Icon] Section Title                    [Test] [Save]
```
- 32px colored icon circle (matches page theming)
- Title: `text-base font-semibold`
- Buttons: right-aligned, consistent `<Button>` components

### Test Buttons → Real Buttons
- `<Button variant="secondary" size="sm">` with Wifi icon
- NOT clickable `<Badge>` — badges show status, buttons trigger actions
- Connection result shown as separate dot/badge next to title

### Save Approach
- Floating/sticky Save bar at page bottom when dirty
- Single bar covers all editable fields (one API call)
- Pulse animation when dirty
- Ctrl+S keyboard shortcut

### Sub-group Labels
- Subtle uppercase mono labels like other pages: `text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider`
- Groups: "Connection", "Performance", "Paths", "Sharing", "API Keys", etc.

## TODO (other pages)
- [ ] Notification bell: clicking a job should navigate to /logs with that job expanded
- [ ] Library cleanup section: show Orphan Cleanup, Dedup, Rename & Sort in a dedicated "Danger Zone" area with amber/red caution styling
