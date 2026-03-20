const BASE_URL = '/api';

async function request(path, options = {}) {
	const { signal, ...rest } = options;
	const res = await fetch(`${BASE_URL}${path}`, {
		headers: { 'Content-Type': 'application/json', ...rest.headers },
		...rest,
		...(signal ? { signal } : {}),
	});
	if (!res.ok) {
		let detail;
		try { detail = (await res.json()).detail; } catch {}
		throw new Error(detail || `API error: ${res.status}`);
	}
	return res.json();
}

function buildUrl(path, params = {}) {
	const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null));
	const qs = new URLSearchParams(clean).toString();
	return qs ? `${path}?${qs}` : path;
}

export const api = {
	// Library
	getStats: () => request('/library/stats'),
	scanLibrary: () => request('/library/scan', { method: 'POST' }),
	getRecent: (limit = 20) => request(`/library/recent?limit=${limit}`),
	getGenres: () => request('/library/genres'),

	// Tracks
	getTracks: (params = {}, signal) => request(buildUrl('/tracks', params), { signal }),
	getTrack: (id) => request(`/tracks/${id}`),
	deleteTrack: (id) => request(`/tracks/${id}`, { method: 'DELETE' }),
	updateTrack: (id, data) => request(`/tracks/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
	recordPlay: (id) => request(`/tracks/${id}/play`, { method: 'POST' }),
	bulkDeleteTracks: (ids) => request('/tracks/bulk-delete', { method: 'POST', body: JSON.stringify({ track_ids: ids }) }),
	bulkAnalyzeTracks: (ids) => request('/tracks/bulk-analyze', { method: 'POST', body: JSON.stringify({ track_ids: ids }) }),

	// Artists & Albums
	getArtists: (params = {}) => request(buildUrl('/library/artists', params)),
	getAlbums: (params = {}) => request(buildUrl('/library/albums', params)),

	// Favorites
	getFavorites: (offset = 0, limit = 25) => request(`/favorites?offset=${offset}&limit=${limit}`),
	getFavoriteIds: () => request('/favorites/ids'),
	star: (data) => request('/favorites/star', { method: 'POST', body: JSON.stringify(data) }),
	unstar: (data) => request('/favorites/unstar', { method: 'POST', body: JSON.stringify(data) }),
	importFavorites: (tracks) => request('/favorites/import', { method: 'POST', body: JSON.stringify({ tracks }) }),

	// Playlists
	getPlaylists: () => request('/playlists'),
	getPlaylist: (id) => request(`/playlists/${id}`),
	createPlaylist: (data) => request('/playlists', { method: 'POST', body: JSON.stringify(data) }),
	updatePlaylist: (id, data) => request(`/playlists/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
	deletePlaylist: (id) => request(`/playlists/${id}`, { method: 'DELETE' }),

	// Jobs
	getJobs: (params = {}) => request(buildUrl('/jobs', params)),
	getActiveJobs: () => request('/jobs/active'),
	getJob: (id) => request(`/jobs/${id}`),
	retryJob: (id) => request(`/jobs/${id}/retry`, { method: 'POST' }),
	cancelJob: (id) => request(`/jobs/${id}/cancel`, { method: 'POST' }),

	// Discovery / Similar
	getSimilarTracks: (artist, track, limit = 20) =>
		request(`/discovery/similar-by-track?artist=${encodeURIComponent(artist)}&track=${encodeURIComponent(track)}&limit=${limit}`),
	echoMatch: (trackId, limit = 20) =>
		request('/analysis/echo-match', { method: 'POST', body: JSON.stringify({ track_id: trackId, limit }) }),

	// Transfers
	cancelTransfer: (username, filename) =>
		request('/download/cancel-transfer', { method: 'POST', body: JSON.stringify({ username, filename }) }),
	getDownloadHistory: (offset = 0, limit = 20) =>
		request(`/jobs?type=download,bulk_download&offset=${offset}&limit=${limit}`),
	clearDownloadHistory: () =>
		request('/jobs/clear?type=download,bulk_download', { method: 'DELETE' }),

	// Blacklist
	addToBlacklist: (artist, track = null, reason = null) =>
		request('/download/blacklist', { method: 'POST', body: JSON.stringify({ artist, track, reason }) }),

	// Ratings
	setRating: (trackId, rating) => request(`/tracks/${trackId}/rating?rating=${rating}`, { method: 'PUT' }),

	// Play History
	getPlayHistory: (period = '7d') => request(`/library/stats/play-history?period=${period}`),

	// Remixes
	getRemixes: (artist, track, limit = 30) =>
		request(`/discovery/remixes?artist=${encodeURIComponent(artist)}&track=${encodeURIComponent(track)}&limit=${limit}`),

	// Duplicates
	getDuplicates: () => request('/library/duplicates'),
	getDuplicateArtists: () => request('/library/duplicates/artists'),
	removeDuplicates: (removeIds, deleteFiles = false) =>
		request('/library/cleanup/duplicates', { method: 'POST', body: JSON.stringify({ remove_ids: removeIds, delete_files: deleteFiles }) }),

	// Recommendations
	getRecommendations: (params = {}) => request(buildUrl('/recommendations', params)),
	refreshRecommendations: (limit = 100, useClaude = false) =>
		request('/recommendations/refresh', { method: 'POST', body: JSON.stringify({ limit, use_claude: useClaude }) }),
	submitFeedback: (recommendationId, action) =>
		request('/recommendations/feedback', { method: 'POST', body: JSON.stringify({ recommendation_id: recommendationId, action }) }),
	getTasteProfile: () => request('/recommendations/profile'),

	// Upgrades
	getUpgrades: (params = {}) => request(buildUrl('/upgrades', params)),
	getUpgradeStats: () => request('/upgrades/stats'),
	scanUpgrades: (data) => request('/upgrades/scan', { method: 'POST', body: JSON.stringify(data) }),
	startUpgrades: (data = {}) => request('/upgrades/start', { method: 'POST', body: JSON.stringify(data) }),
	skipUpgrade: (id) => request(`/upgrades/${id}/skip`, { method: 'POST' }),
	retryUpgrade: (id) => request(`/upgrades/${id}/retry`, { method: 'POST' }),
	clearUpgrades: (status = 'completed') => request(`/upgrades/clear?status=${status}`, { method: 'DELETE' }),

	// Remix Suggestions
	getRemixSuggestions: (params = {}) => request(buildUrl('/discovery/remix-suggestions', params)),

	// Music Map
	getMapGraph: (params = {}) => request(buildUrl('/map/graph', params)),

	// Config
	getServices: () => request('/config/services'),
	saveServices: (data) => request('/config/services', { method: 'PUT', body: JSON.stringify(data) }),
	getVersion: () => request('/config/version'),
	checkUpdates: () => request('/config/updates'),
	restart: () => request('/config/restart', { method: 'POST' }),
	upgrade: () => request('/config/upgrade', { method: 'POST' }),
	testService: (service) => request(`/config/test/${service}`, { method: 'POST' }),
	getBackups: () => request('/config/backups'),
	createBackup: () => request('/config/backup', { method: 'POST' }),
	restoreBackup: (filename) => request(`/config/restore/${filename}`, { method: 'POST' }),

	// Users
	getUsers: () => request('/users'),
	createUser: (data) => request('/users', { method: 'POST', body: JSON.stringify(data) }),
	deleteUser: (id) => request(`/users/${id}`, { method: 'DELETE' }),
	changePassword: (id, data) => request(`/users/${id}/password`, { method: 'PUT', body: JSON.stringify(data) }),
	generateApiKey: (id) => request(`/users/${id}/api-key`, { method: 'POST' }),
	revokeApiKey: (id) => request(`/users/${id}/api-key`, { method: 'DELETE' }),

	// Schedule
	getSchedule: () => request('/schedule'),

	// Last.fm Auth
	getLastfmAuthUrl: () => request('/discovery/lastfm/auth-url'),
	lastfmCallback: (token) => request(`/discovery/lastfm/callback?token=${encodeURIComponent(token)}`),

	// AI Usage
	getAIUsage: () => request('/config/ai-usage'),

	// Discovery Search (Last.fm)
	discoverySearch: (q, limit = 5, signal) => request(buildUrl('/discovery/search', { q, limit }), { signal }),

	// P2P Search (Soulseek)
	p2pSearch: (data, signal) => request('/download/search', { method: 'POST', body: JSON.stringify(data), signal }),

	// AI Search
	aiSearch: (query, limit = 50, signal) => request('/search/ai', { method: 'POST', body: JSON.stringify({ query, limit }), signal }),
	detectNL: (query) => request('/search/detect-nl', { method: 'POST', body: JSON.stringify({ query }) }),

	// AI Playlist Generation
	aiGeneratePlaylist: (prompt, name = null, limit = 30) =>
		request('/playlists/ai-generate', { method: 'POST', body: JSON.stringify({ prompt, name, limit }) }),

	// Job Dashboard
	getJobDashboard: () => request('/jobs/dashboard'),

	// AI Features
	explainRecommendation: (id) => request(`/recommendations/${id}/explain`, { method: 'POST' }),
	aiTagTracks: (trackIds) => request('/tracks/ai-tag', { method: 'POST', body: JSON.stringify({ track_ids: trackIds }) }),
	applyAITags: (tags) => request('/tracks/ai-tag/apply', { method: 'POST', body: JSON.stringify({ tags }) }),
	getInsights: () => request('/library/stats/insights'),
	aiResolveDuplicates: () => request('/library/duplicates/ai-resolve', { method: 'POST' }),

	// Mood Tags
	tagMoods: (trackIds) => request('/tracks/ai-moods', { method: 'POST', body: JSON.stringify({ track_ids: trackIds }) }),
	getMoods: (trackIds = null) => request(buildUrl('/tracks/moods', { track_ids: trackIds?.join(',') })),

	// Playlist Discovery
	discoverPlaylists: (limit = 10) =>
		request('/discovery/playlists', { method: 'POST', body: JSON.stringify({ limit }) }),
	aiRankPlaylists: (playlists) =>
		request('/discovery/playlists/ai-rank', { method: 'POST', body: JSON.stringify(playlists) }),
	aiReviewImport: (tracks) =>
		request('/playlists/import/ai-review', { method: 'POST', body: JSON.stringify({ tracks }) }),

	// Playlist Import
	fetchExternalPlaylist: (url, source = null) =>
		request('/playlists/import/fetch', { method: 'POST', body: JSON.stringify({ url, source }) }),
	searchExternalPlaylists: (query, sources = null, limit = 10) =>
		request('/playlists/import/search', { method: 'POST', body: JSON.stringify({ query, sources, limit }) }),
	importExternalPlaylist: (name, tracks, downloadMissing = false) =>
		request('/playlists/import/import', { method: 'POST', body: JSON.stringify({ name, tracks, download_missing: downloadMissing }) }),

	// App Logs
	getAppLogs: (params = {}) => request(buildUrl('/logs/app', params)),
	getAppLog: (id) => request(`/logs/app/${id}`),
	deleteAppLog: (id) => request(`/logs/app/${id}`, { method: 'DELETE' }),
};
