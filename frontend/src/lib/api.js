const BASE_URL = '/api';

async function request(path, options = {}) {
	const res = await fetch(`${BASE_URL}${path}`, {
		headers: { 'Content-Type': 'application/json', ...options.headers },
		...options
	});
	if (!res.ok) throw new Error(`API error: ${res.status}`);
	return res.json();
}

export const api = {
	// Library
	getStats: () => request('/library/stats'),
	scanLibrary: () => request('/library/scan', { method: 'POST' }),
	getRecent: (limit = 20) => request(`/library/recent?limit=${limit}`),
	getGenres: () => request('/library/genres'),

	// Tracks
	getTracks: (params = {}) => {
		const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null));
		const qs = new URLSearchParams(clean).toString();
		return request(`/tracks?${qs}`);
	},
	getTrack: (id) => request(`/tracks/${id}`),
	deleteTrack: (id) => request(`/tracks/${id}`, { method: 'DELETE' }),
	updateTrack: (id, data) => request(`/tracks/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
	recordPlay: (id) => request(`/tracks/${id}/play`, { method: 'POST' }),
	bulkDeleteTracks: (ids) => request('/tracks/bulk-delete', { method: 'POST', body: JSON.stringify({ track_ids: ids }) }),
	bulkAnalyzeTracks: (ids) => request('/tracks/bulk-analyze', { method: 'POST', body: JSON.stringify({ track_ids: ids }) }),

	// Artists & Albums
	getArtists: (params = {}) => {
		const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null));
		const qs = new URLSearchParams(clean).toString();
		return request(`/library/artists?${qs}`);
	},
	getAlbums: (params = {}) => {
		const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null));
		const qs = new URLSearchParams(clean).toString();
		return request(`/library/albums?${qs}`);
	},

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
	getJobs: async (params = {}) => {
		const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null));
		const qs = new URLSearchParams(clean).toString();
		return request(`/jobs?${qs}`);
	},
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

	// Music Map
	getMapGraph: (params = {}) => {
		const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null));
		const qs = new URLSearchParams(clean).toString();
		return request(`/map/graph?${qs}`);
	},
};
