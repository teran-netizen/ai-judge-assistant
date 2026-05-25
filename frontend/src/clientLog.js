/**
 * Client-side logger — sends browser events to /api/client-log
 * Usage:
 *   import { clog } from "../clientLog"
 *   clog.info("camera", "Camera opened OK", { constraint: 0 })
 *   clog.warn("camera", "Fallback used")
 *   clog.error("camera", "getUserMedia failed", { err: "NotAllowedError" })
 */

const API = import.meta.env.VITE_API_URL || ""
const ENDPOINT = `${API}/api/client-log`

// Debounce: don't spam identical messages within 5 seconds
const _sent = new Map()
const DEBOUNCE_MS = 5000

function _getContext() {
  return {
    url: location.pathname,
    screen: `${screen.width}x${screen.height}`,
    vp: `${window.innerWidth}x${window.innerHeight}`,
    dpr: String(devicePixelRatio || 1),
    touch: String(navigator.maxTouchPoints > 0),
  }
}

function _send(level, tag, message, extra) {
  const key = `${level}:${tag}:${message}`
  const now = Date.now()
  if (_sent.has(key) && now - _sent.get(key) < DEBOUNCE_MS) return
  _sent.set(key, now)

  const body = {
    level,
    tag,
    message,
    context: { ..._getContext(), ...extra },
  }

  // Use sendBeacon if available (works even on page unload), fallback to fetch
  const json = JSON.stringify(body)
  if (navigator.sendBeacon) {
    navigator.sendBeacon(ENDPOINT, new Blob([json], { type: "application/json" }))
  } else {
    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: json,
      keepalive: true,
    }).catch(() => {}) // silent
  }
}

export const clog = {
  info:  (tag, message, extra) => _send("info",  tag, message, extra),
  warn:  (tag, message, extra) => _send("warn",  tag, message, extra),
  error: (tag, message, extra) => _send("error", tag, message, extra),
}

// ── Global error handlers ──
window.addEventListener("error", (e) => {
  clog.error("js-error", `${e.message} at ${e.filename}:${e.lineno}:${e.colno}`)
})

window.addEventListener("unhandledrejection", (e) => {
  const msg = e.reason?.message || e.reason?.toString?.() || "Unknown promise rejection"
  clog.error("promise", msg)
})
