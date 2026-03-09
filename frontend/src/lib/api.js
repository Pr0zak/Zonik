const BASE_URL = '/api';

async function request(path, options = {}) {
	const res = await fetch(`${BASE_URL}${path}`, {
		headers: { 'Content-Type': 'application/json', ...options.headers },
		...options
	});
	if (!res.ok) throw new Error(`API error: ${res.status}`);
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
	getTracks: (params = {}) => request(buildUrl('/tracks', params)),
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

	// AI Usage
	getAIUsage: () => request('/config/ai-usage'),

	// AI Search
	aiSearch: (query, limit = 50) => request('/search/ai', { method: 'POST', body: JSON.stringify({ query, limit }) }),
	detectNL: (query) => request('/search/detect-nl', { method: 'POST', body: JSON.stringify({ query }) }),

	// AI Playlist Generation
	aiGeneratePlaylist: (prompt, name = null, limit = 30) =>
		request('/playlists/ai-generate', { method: 'POST', body: JSON.stringify({ prompt, name, limit }) }),

	// AI Features
	explainRecommendation: (id) => request(`/recommendations/${id}/explain`, { method: 'POST' }),
	aiTagTracks: (trackIds) => request('/tracks/ai-tag', { method: 'POST', body: JSON.stringify({ track_ids: trackIds }) }),
	applyAITags: (tags) => request('/tracks/ai-tag/apply', { method: 'POST', body: JSON.stringify({ tags }) }),
	getInsights: () => request('/library/stats/insights'),
	aiResolveDuplicates: () => request('/library/duplicates/ai-resolve', { method: 'POST' }),
};
