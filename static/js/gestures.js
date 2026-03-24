/**
 * Circular touch gesture layer for an outer "virtual jog wheel" + tap discrimination.
 *
 * Implemented:
 *  - Ring hit-test using inner/outer radius (normalized coords, 720×720 stage)
 *  - Pointer capture for clean tracking on the round panel
 *  - Minimum movement deadzone to ignore jitter
 *  - Signed angle deltas with wraparound handled via shortest arc
 *  - Accumulated spin → discrete seek steps (caller maps to ms)
 *  - Short, low-motion pointer sequences classified as taps
 *
 * TODO (hardware verification on Waveshare 4\" round DSI):
 *  - Tune RING_INNER_RATIO / RING_OUTER_RATIO for bezel and finger ergonomics
 *  - Multi-touch: currently single-pointer only; decide if pinch is needed
 *  - Optional: inertia after lift for natural scrubbing
 */

const TWO_PI = Math.PI * 2;

/**
 * @param {number} a
 * @param {number} b
 * @returns {number} shortest signed difference b - a in radians, range (-π, π]
 */
export function shortestAngleDelta(a, b) {
  let d = b - a;
  while (d <= -Math.PI) d += TWO_PI;
  while (d > Math.PI) d -= TWO_PI;
  return d;
}

/**
 * @param { { x: number, y: number } } point
 * @param { { x: number, y: number } } center
 * @returns {number} angle in radians, atan2 convention
 */
export function angleAt(point, center) {
  return Math.atan2(point.y - center.y, point.x - center.x);
}

/**
 * @param { { x: number, y: number } } point
 * @param { { x: number, y: number } } center
 * @returns {number} distance from center
 */
export function radiusAt(point, center) {
  const dx = point.x - center.x;
  const dy = point.y - center.y;
  return Math.hypot(dx, dy);
}

/**
 * Attach pointer handlers to `element` for ring + tap behavior.
 *
 * @param {Object} opts
 * @param {HTMLElement} opts.element
 * @param {number} [opts.stageSize=720]
 * @param {number} [opts.ringInnerRatio=0.62] inner normalized radius of active ring
 * @param {number} [opts.ringOuterRatio=0.985] outer normalized radius of active ring
 * @param {number} [opts.deadzonePx=10] ignore movement smaller than this (device px)
 * @param {number} [opts.tapMaxMs=320]
 * @param {number} [opts.tapMaxMovePx=14]
 * @param {number} [opts.seekChunkRad=0.42] radians of accumulated spin before onSeekChunk
 * @param {(direction: 1 | -1, chunkCount: number) => void} [opts.onSeekChunk] +1 clockwise
 * @param {() => void} [opts.onTap]
 * @param {(state: { inRing: boolean, spinning: boolean }) => void} [opts.onActivity]
 */
export function attachCircularGestureController(opts) {
  const {
    element,
    stageSize = 720,
    ringInnerRatio = 0.62,
    ringOuterRatio = 0.985,
    deadzonePx = 10,
    tapMaxMs = 320,
    tapMaxMovePx = 14,
    seekChunkRad = 0.42,
    onSeekChunk,
    onTap,
    onActivity,
  } = opts;

  const center = { x: stageSize / 2, y: stageSize / 2 };
  const rInner = (stageSize / 2) * ringInnerRatio;
  const rOuter = (stageSize / 2) * ringOuterRatio;

  /** @type {PointerEvent | null} */
  let active = null;
  let startedInRing = false;
  /** @type {number | null} */
  let lastAngle = null;
  let spinAccum = 0;
  let spinning = false;
  /** @type { { x: number, y: number } | null } */
  let startPoint = null;
  let startTime = 0;
  let movedSq = 0;

  function clientToStage(evt) {
    const rect = element.getBoundingClientRect();
    const scaleX = stageSize / rect.width;
    const scaleY = stageSize / rect.height;
    const x = (evt.clientX - rect.left) * scaleX;
    const y = (evt.clientY - rect.top) * scaleY;
    return { x, y };
  }

  function inRing(point) {
    const r = radiusAt(point, center);
    return r >= rInner && r <= rOuter;
  }

  function emitActivity() {
    onActivity?.({ inRing: startedInRing, spinning });
  }

  function flushSpinChunks() {
    if (!onSeekChunk) return;
    const absAccum = Math.abs(spinAccum);
    const chunks = Math.floor(absAccum / seekChunkRad);
    if (chunks <= 0) return;
    const direction = spinAccum >= 0 ? 1 : -1;
    onSeekChunk(direction, chunks);
    const consumed = chunks * seekChunkRad;
    spinAccum += spinAccum >= 0 ? -consumed : consumed;
  }

  function onPointerDown(evt) {
    if (active) return;
    active = evt;
    element.setPointerCapture(evt.pointerId);
    const p = clientToStage(evt);
    startPoint = p;
    startTime = performance.now();
    movedSq = 0;
    startedInRing = inRing(p);
    lastAngle = startedInRing ? angleAt(p, center) : null;
    spinAccum = 0;
    spinning = false;
    emitActivity();
  }

  function onPointerMove(evt) {
    if (!active || evt.pointerId !== active.pointerId) return;
    const p = clientToStage(evt);
    if (startPoint) {
      const dx = p.x - startPoint.x;
      const dy = p.y - startPoint.y;
      movedSq = dx * dx + dy * dy;
    }

    if (!startedInRing || lastAngle === null) {
      emitActivity();
      return;
    }

    const ang = angleAt(p, center);
    let delta = shortestAngleDelta(lastAngle, ang);
    lastAngle = ang;

    if (Math.abs(delta) < 0.00001) return;
    if (!spinning) {
      if (Math.abs(delta) * (stageSize / 2) < deadzonePx) {
        return;
      }
      spinning = true;
    }

    spinAccum += delta;
    flushSpinChunks();
    emitActivity();
  }

  function onPointerUp(evt) {
    if (!active || evt.pointerId !== active.pointerId) return;
    const dt = performance.now() - startTime;
    const moved = Math.sqrt(movedSq);

    try {
      element.releasePointerCapture(evt.pointerId);
    } catch {
      /* ignore */
    }

    if (
      onTap &&
      dt <= tapMaxMs &&
      moved <= tapMaxMovePx &&
      !spinning &&
      startPoint
    ) {
      onTap();
    }

    flushSpinChunks();
    active = null;
    lastAngle = null;
    startedInRing = false;
    spinning = false;
    spinAccum = 0;
    emitActivity();
  }

  function onPointerCancel(evt) {
    onPointerUp(evt);
  }

  element.addEventListener("pointerdown", onPointerDown);
  element.addEventListener("pointermove", onPointerMove);
  element.addEventListener("pointerup", onPointerUp);
  element.addEventListener("pointercancel", onPointerCancel);

  return function detach() {
    element.removeEventListener("pointerdown", onPointerDown);
    element.removeEventListener("pointermove", onPointerMove);
    element.removeEventListener("pointerup", onPointerUp);
    element.removeEventListener("pointercancel", onPointerCancel);
  };
}
