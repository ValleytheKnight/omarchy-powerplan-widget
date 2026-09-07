.pragma library

var quickTimeoutPresets = [0, 60, 120, 300, 600, 900, 1800]
var screensaverPresets = quickTimeoutPresets
var displayPresets = quickTimeoutPresets
var lockPresets = [0, 300, 600, 900, 1800, 3600]
var sleepPresets = [0, 900, 1800, 3600, 7200]
var hibernatePresets = [0, 1800, 3600, 7200, 14400, 28800]
var lidActions = ["system", "nothing", "display", "sleep", "hibernate"]
var powerStates = ["ac", "battery"]

var maxTimeoutSeconds = 7 * 24 * 60 * 60

// Validate a caller-supplied timeout, including one arriving over IPC.
// Returns whole seconds in [0, maxTimeoutSeconds], or -1 when the value is
// unusable. Callers must treat -1 as "reject" and never as 0: coercing a bad
// value to 0 would read as "Off" and stand auto-lock down.
//
// Out-of-range values are rejected rather than clamped, matching the CLI. A
// clamp would turn an absurd setLock into a seven-day timeout, which is the
// same silent weakening this is meant to prevent.
function requestedSeconds(value) {
  var number = Number(value)
  if (!isFinite(number)) return -1
  number = Math.round(number)
  if (number < 0 || number > maxTimeoutSeconds) return -1
  return number
}

// Normalize a value already on disk. Unlike requestedSeconds there is no caller
// to report back to, so an oversized value is clamped rather than rejected -
// the bound is what keeps sleepDelaySeconds * 1000 inside a 32-bit int.
function normalizedSeconds(value, fallback, allowOff) {
  var number = Number(value)
  if (!isFinite(number)) return fallback
  number = Math.round(number)
  if (allowOff && number === 0) return 0
  if (number <= 0) return fallback
  return Math.min(number, maxTimeoutSeconds)
}

function normalizedLidAction(value) {
  var action = String(value || "system")
  return lidActions.indexOf(action) >= 0 ? action : "system"
}

function lidActionLabel(action) {
  switch (normalizedLidAction(action)) {
  case "nothing": return "Do nothing"
  case "display": return "Display off"
  case "sleep": return "Sleep"
  case "hibernate": return "Hibernate"
  default: return "System default"
  }
}

function normalizedPowerState(value) {
  var state = String(value || "ac")
  return powerStates.indexOf(state) >= 0 ? state : "ac"
}

// Every timeout is stored as {ac, battery} rather than one bare value, so AC
// and battery behavior can differ. A persisted value missing one or both
// sides falls back to the same default either side would have used alone,
// so a config written before this shape existed, or a hand-edited partial
// object, still loads cleanly.
function normalizedPair(value, fallback, allowOff) {
  var pair = value || {}
  return {
    ac: normalizedSeconds(pair.ac, fallback, allowOff),
    battery: normalizedSeconds(pair.battery, fallback, allowOff)
  }
}

function normalizedLidPair(value) {
  var pair = value || {}
  return {
    ac: normalizedLidAction(pair.ac),
    battery: normalizedLidAction(pair.battery)
  }
}

// Resolve a stored pair down to the one value that applies right now. This is
// the function Service.qml calls every time UPower reports a power-source
// change, and on every timer rearm in between.
function effectiveSeconds(pair, onBattery, fallback, allowOff) {
  if (!pair) return fallback
  var value = onBattery ? pair.battery : pair.ac
  return normalizedSeconds(value, fallback, allowOff)
}

function effectiveLidAction(pair, onBattery) {
  if (!pair) return "system"
  return normalizedLidAction(onBattery ? pair.battery : pair.ac)
}

function parseConfig(raw) {
  var parsed = {}
  try { parsed = JSON.parse(String(raw || "{}")) }
  catch (error) { parsed = {} }

  return {
    screensaver: normalizedPair(parsed.screensaver, 150, true),
    display: normalizedPair(parsed.display, 0, true),
    lock: normalizedPair(parsed.lock, 300, true),
    sleep: normalizedPair(parsed.sleep, 0, true),
    hibernate: normalizedPair(parsed.hibernate, 0, true),
    lid: normalizedLidPair(parsed.lid)
  }
}

function formatDuration(seconds) {
  var value = Number(seconds)
  if (!isFinite(value) || value <= 0) return "Off"
  if (value < 60) return Math.round(value) + " sec"

  var minutes = value / 60
  if (minutes < 60) {
    var minuteLabel = minutes === Math.round(minutes)
      ? String(Math.round(minutes)) : minutes.toFixed(1).replace(/\.0$/, "")
    return minuteLabel + " min"
  }

  var hours = minutes / 60
  return (hours === Math.round(hours) ? String(Math.round(hours)) : hours.toFixed(1)) + (hours === 1 ? " hour" : " hours")
}

function isPreset(value, presets) {
  var seconds = Number(value)
  for (var i = 0; i < presets.length; i++) {
    if (seconds === Number(presets[i])) return true
  }
  return false
}

function customParts(seconds) {
  var total = Math.max(1, Math.round(Number(seconds)))
  return {
    hours: Math.floor(total / 3600),
    minutes: Math.floor((total % 3600) / 60),
    seconds: total % 60
  }
}

function customSeconds(hours, minutes, seconds) {
  var safeHours = Math.max(0, Math.min(24, Math.round(Number(hours) || 0)))
  var safeMinutes = Math.max(0, Math.min(59, Math.round(Number(minutes) || 0)))
  var safeSeconds = Math.max(0, Math.min(59, Math.round(Number(seconds) || 0)))
  return safeHours * 3600 + safeMinutes * 60 + safeSeconds
}

// Summarizes the values actually in effect right now (already resolved by
// the caller via effectiveSeconds/effectiveLidAction), not both sides of
// every pair - that's what's on screen in the bar widget tooltip.
function statusSummary(screensaver, display, lock, sleep, hibernate) {
  var summary = "Screen " + formatDuration(screensaver)
    + " · Displays " + formatDuration(display)
    + " · Lock " + formatDuration(lock)
    + " · Sleep " + formatDuration(sleep)
  if (Number(hibernate) > 0) summary += " · Hibernate +" + formatDuration(hibernate)
  return summary
}
