/**
 * Kiosk UI controller: polls playback, renders state, wires gestures → API.
 *
 * Architecture split:
 *   - gestures.js: touch geometry + spin/tap classification
 *   - app.js (this file): DOM, timers, fetch to Flask, optimistic UI
 *
 * TODO: Replace polling with push/SSE if playback sync must be tighter on-device.
 */

import { attachCircularGestureController } from "./gestures.js";

const POLL_MS = 2000;
const IDLE_MS = 5000;
const SEEK_MS_PER_CHUNK = 5200;
const CIRCUMFERENCE = 2 * Math.PI * 332;

const appRoot = document.getElementById("app");
const stage = document.getElementById("circle-stage");
const albumArt = document.getElementById("album-art");
const titleEl = document.getElementById("track-title");
const artistsEl = document.getElementById("track-artists");
const elapsedEl = document.getElementById("time-elapsed");
const totalEl = document.getElementById("time-total");
const progressArc = document.getElementById("progress-arc");
const toastEl = document.getElementById("toast");
const mockPill = document.getElementById("mock-pill");
const ringDebug = document.getElementById("ring-debug");

/** @type {null | ReturnType<typeof setTimeout>} */
let idleTimer = null;
/** @type {number | null} */
let localProgressAnchorMs = null;
/** @type {number | null} */
let localProgressAnchorTs = null;
let lastServerPlaying = false;
let uiProgressMs = 0;
let uiDurationMs = 0;

function wakeUi() {
  appRoot.classList.remove("app--idle");
  if (idleTimer) clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    appRoot.classList.add("app--idle");
  }, IDLE_MS);
}

function bumpIdleOnActivity() {
  wakeUi();
}

function showToast(message, ms = 1400) {
  toastEl.textContent = message;
  toastEl.classList.add("toast--visible");
  window.setTimeout(() => toastEl.classList.remove("toast--visible"), ms);
}

function formatMs(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

function setProgressUi(progressMs, durationMs) {
  const dur = Math.max(0, durationMs);
  const prog = dur > 0 ? Math.min(Math.max(progressMs, 0), dur) : 0;
  uiProgressMs = prog;
  uiDurationMs = dur;
  const frac = dur > 0 ? prog / dur : 0;
  const offset = CIRCUMFERENCE * (1 - frac);
  progressArc.style.strokeDasharray = `${CIRCUMFERENCE}`;
  progressArc.style.strokeDashoffset = `${offset}`;
  elapsedEl.textContent = formatMs(prog);
  totalEl.textContent = formatMs(dur);
}

async function fetchJson(url, options) {
  const r = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options && options.headers ? options.headers : {}),
    },
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(data.error || `HTTP ${r.status}`);
    err.details = data;
    throw err;
  }
  return data;
}

function applyPlaybackPayload(data) {
  const name = data.track?.name || "Unknown";
  const artists = (data.track?.artists || []).join(", ");
  titleEl.textContent = name;
  artistsEl.textContent = artists;

  const art = data.album_art_url;
  if (art) {
    albumArt.src = art;
    albumArt.alt = `${data.track?.album || "Album"} cover`;
  } else {
    albumArt.removeAttribute("src");
    albumArt.alt = "";
  }

  mockPill.hidden = !data.mock;

  const playing = Boolean(data.is_playing);
  lastServerPlaying = playing;

  const now = performance.now();
  localProgressAnchorMs = Number(data.progress_ms || 0);
  localProgressAnchorTs = now;

  setProgressUi(localProgressAnchorMs, Number(data.duration_ms || 0));
}

function tickLocalProgress() {
  if (localProgressAnchorMs == null || localProgressAnchorTs == null) return;
  if (!lastServerPlaying) {
    setProgressUi(localProgressAnchorMs, uiDurationMs);
    return;
  }
  const elapsed = performance.now() - localProgressAnchorTs;
  const dur = uiDurationMs;
  const next = Math.min(localProgressAnchorMs + elapsed, dur);
  setProgressUi(next, dur);
}

async function refreshPlayback() {
  const data = await fetchJson("/api/playback");
  applyPlaybackPayload(data);
}

async function togglePlayback() {
  bumpIdleOnActivity();
  const prev = lastServerPlaying;
  lastServerPlaying = !prev;
  wakeUi();

  try {
    const res = await fetchJson("/api/playback/toggle", { method: "POST" });
    if (typeof res.is_playing === "boolean") {
      lastServerPlaying = res.is_playing;
    } else {
      await refreshPlayback();
    }
  } catch (e) {
    lastServerPlaying = prev;
    showToast("Could not toggle playback");
    await refreshPlayback();
  }

  const now = performance.now();
  localProgressAnchorMs = uiProgressMs;
  localProgressAnchorTs = now;
}

async function seekChunks(direction, chunkCount) {
  bumpIdleOnActivity();
  const delta = direction * chunkCount * SEEK_MS_PER_CHUNK;

  const dur = uiDurationMs;
  let base = localProgressAnchorMs != null ? localProgressAnchorMs : uiProgressMs;
  if (localProgressAnchorTs) {
    const drift = lastServerPlaying ? performance.now() - localProgressAnchorTs : 0;
    base = Math.min(base + drift, dur);
  }
  const optimistic = Math.max(0, Math.min(dur, base + delta));
  localProgressAnchorMs = optimistic;
  localProgressAnchorTs = performance.now();
  lastServerPlaying = true;
  setProgressUi(optimistic, dur);

  try {
    await fetchJson("/api/playback/seek", {
      method: "POST",
      body: JSON.stringify({ delta_ms: delta }),
    });
  } catch {
    showToast("Seek failed — check Spotify device");
    await refreshPlayback();
  }
}

// Gesture wiring (outer ring only for scrub; center still receives tap via short press)
const detachGestures = attachCircularGestureController({
  element: stage,
  stageSize: 720,
  ringInnerRatio: 0.62,
  ringOuterRatio: 0.985,
  deadzonePx: 12,
  tapMaxMs: 300,
  tapMaxMovePx: 16,
  seekChunkRad: 0.4,
  onTap: () => {
    togglePlayback();
  },
  onSeekChunk: (dir, chunks) => {
    seekChunks(dir, chunks);
  },
  onActivity: (s) => {
    bumpIdleOnActivity();
    if (!ringDebug.hidden) {
      ringDebug.textContent = `${s.inRing ? "ring" : "center"} · ${s.spinning ? "spin" : "—"}`;
    }
  },
});

window.addEventListener("keydown", (e) => {
  if (e.code === "Space" || e.code === "Enter") {
    e.preventDefault();
    togglePlayback();
  }
  if (e.code === "KeyD" && (e.metaKey || e.ctrlKey)) {
    ringDebug.hidden = !ringDebug.hidden;
  }
});

function loopLocalProgress() {
  tickLocalProgress();
  requestAnimationFrame(loopLocalProgress);
}

wakeUi();

refreshPlayback()
  .then(() => showToast("Loaded playback state", 900))
  .catch(() => {
    titleEl.textContent = "Offline";
    artistsEl.textContent = "Start Flask backend on the Pi";
    showToast("Backend unreachable");
  });

setInterval(() => {
  refreshPlayback().catch(() => {});
}, POLL_MS);

window.addEventListener("pagehide", () => {
  detachGestures();
});

requestAnimationFrame(loopLocalProgress);
