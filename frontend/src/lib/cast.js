import { writable } from 'svelte/store';
import { addToast, playNext } from '$lib/stores.js';

export const isCastAvailable = writable(false);
export const isCasting = writable(false);
export const castDeviceName = writable('');

let castSession = null;
let mediaSession = null;
let castInitialized = false;

function setupCastContext() {
	if (castInitialized) return;
	castInitialized = true;

	const ctx = cast.framework.CastContext.getInstance();
	ctx.setOptions({
		receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
		autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
	});

	// Check initial state + delayed recheck (discovery takes time)
	const checkState = () => {
		const s = ctx.getCastState();
		isCastAvailable.set(s !== cast.framework.CastState.NO_DEVICES_AVAILABLE);
	};
	checkState();
	setTimeout(checkState, 3000);
	setTimeout(checkState, 8000);

	ctx.addEventListener(cast.framework.CastContextEventType.CAST_STATE_CHANGED, (e) => {
		const available = e.castState !== cast.framework.CastState.NO_DEVICES_AVAILABLE;
		isCastAvailable.set(available);
	});

	ctx.addEventListener(cast.framework.CastContextEventType.SESSION_STATE_CHANGED, (e) => {
		const state = e.sessionState;
		if (state === cast.framework.SessionState.SESSION_STARTED ||
			state === cast.framework.SessionState.SESSION_RESUMED) {
			castSession = ctx.getCurrentSession();
			isCasting.set(true);
			castDeviceName.set(castSession.getCastDevice().friendlyName || 'Cast Device');
		} else if (state === cast.framework.SessionState.SESSION_ENDED) {
			castSession = null;
			mediaSession = null;
			isCasting.set(false);
			castDeviceName.set('');
		}
	});
}

// Set callback at module load time — cast_sender.js captures it via D()
// BEFORE it overwrites window.__onGCastApiAvailable with its internal counter.
// The SDK reads our callback, then calls it once both cast_framework.js
// and the extension script finish loading.
if (typeof window !== 'undefined') {
	window['__onGCastApiAvailable'] = (isAvailable) => {
		if (isAvailable) setupCastContext();
	};
}

export function initCast() {
	// If SDK already loaded (callback already fired), init now
	if (window.cast && cast.framework) {
		setupCastContext();
		return;
	}
	// Fallback poll — in case callback timing was missed
	let attempts = 0;
	const poll = setInterval(() => {
		attempts++;
		if (window.cast && cast.framework) {
			clearInterval(poll);
			setupCastContext();
		} else if (attempts >= 20) {
			clearInterval(poll);
		}
	}, 500);
}

function isLocalhost() {
	const h = window.location.hostname;
	return h === 'localhost' || h === '127.0.0.1' || h === '::1';
}

export async function startCasting(track, currentTimeSec = 0) {
	if (isLocalhost()) {
		addToast('Cast devices cannot reach localhost. Use your LAN IP or hostname.', 'error');
		return null;
	}
	try {
		const ctx = cast.framework.CastContext.getInstance();
		await ctx.requestSession();
		castSession = ctx.getCurrentSession();
		if (castSession && track) {
			await castLoadMedia(track, currentTimeSec);
		}
	} catch (e) {
		if (e !== 'cancel') {
			addToast('Cast failed: ' + (e.message || e), 'error');
		}
	}
}

export function stopCasting() {
	let position = 0;
	if (mediaSession) {
		position = mediaSession.getEstimatedTime() || 0;
	}
	const ctx = cast.framework.CastContext.getInstance();
	ctx.endCurrentSession(true);
	castSession = null;
	mediaSession = null;
	isCasting.set(false);
	castDeviceName.set('');
	return position;
}

export async function castLoadMedia(track, seekTo = 0) {
	if (!castSession) return;
	const origin = window.location.origin;
	const streamUrl = `${origin}/rest/stream?id=${track.id}&v=1.16.1&c=zonik-web`;
	const coverUrl = `${origin}/rest/getCoverArt?id=${track.id}&size=300`;

	const mediaInfo = new chrome.cast.media.MediaInfo(streamUrl, 'audio/mpeg');
	mediaInfo.metadata = new chrome.cast.media.MusicTrackMediaMetadata();
	mediaInfo.metadata.title = track.title || 'Unknown';
	mediaInfo.metadata.artist = track.artist || 'Unknown';
	mediaInfo.metadata.albumName = track.album || '';
	if (track.id) {
		mediaInfo.metadata.images = [new chrome.cast.Image(coverUrl)];
	}

	const request = new chrome.cast.media.LoadRequest(mediaInfo);
	request.currentTime = seekTo;
	request.autoplay = true;

	try {
		await castSession.loadMedia(request);
		mediaSession = castSession.getMediaSession();
		if (mediaSession) {
			mediaSession.addUpdateListener((isAlive) => {
				if (!isAlive) return;
				if (mediaSession.playerState === chrome.cast.media.PlayerState.IDLE &&
					mediaSession.idleReason === chrome.cast.media.IdleReason.FINISHED) {
					playNext();
				}
			});
		}
	} catch (e) {
		addToast('Cast load failed: ' + (e.message || e), 'error');
	}
}

export function castPlay() {
	if (mediaSession) {
		mediaSession.play(new chrome.cast.media.PlayRequest(), () => {}, () => {});
	}
}

export function castPause() {
	if (mediaSession) {
		mediaSession.pause(new chrome.cast.media.PauseRequest(), () => {}, () => {});
	}
}

export function castSeek(timeSec) {
	if (mediaSession) {
		const req = new chrome.cast.media.SeekRequest();
		req.currentTime = timeSec;
		mediaSession.seek(req, () => {}, () => {});
	}
}

export function getCastCurrentTime() {
	if (mediaSession) {
		return mediaSession.getEstimatedTime() || 0;
	}
	return 0;
}
