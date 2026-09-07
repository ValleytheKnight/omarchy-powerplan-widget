import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Services.UPower
import "Model.js" as Model

Item {
  id: root
  
  property var shell: null
  property var configState: ({
  screensaver: { ac: 150, battery: 150 },
  display: { ac: 0, battery: 0 },
  lock: { ac: 300, battery: 300 },
  sleep: { ac: 0, battery: 0 },
  hibernate: { ac: 0, battery: 0 },
  lid: { ac: "system", battery: "system" }
  })
  readonly property bool onBattery: UPower.onBattery
  property bool saving: false
  property string lastError: ""
  property string hibernateDiagnostic: ""
  property bool suspendPending: false
  property int pendingHibernateSeconds: 0
  property string pendingHibernateState: "ac"
  property bool displaysOff: false
  property bool idleCycleRunning: false
  property bool idleMonitorRearming: false
  property var screensaverWindows: ({})
  property int screensaverWindowCount: 0

  readonly property string home: Quickshell.env("HOME")
  readonly property string configPath: home + "/.config/omarchy/powerplan.json"
  readonly property string screensaverClass: "org.omarchy.screensaver"
  readonly property int screensaverSeconds: Model.effectiveSeconds(configState.screensaver, root.onBattery, 150, true)
  readonly property int displaySeconds: Model.effectiveSeconds(configState.display, root.onBattery, 0, true)
  readonly property int lockSeconds: Model.effectiveSeconds(configState.lock, root.onBattery, 300, true)
  readonly property int sleepSeconds: Model.effectiveSeconds(configState.sleep, root.onBattery, 0, true)
  readonly property int hibernateSeconds: Model.effectiveSeconds(configState.hibernate, root.onBattery, 0, true)
  readonly property string lidAction: Model.effectiveLidAction(configState.lid, root.onBattery)
  readonly property bool lidPresent: lidService.present
  readonly property bool lidClosed: lidService.closed
  readonly property string internalDisplay: lidService.internalDisplay
  readonly property bool hibernateAvailable: lidService.hibernateAvailable
  readonly property bool suspendThenHibernateAvailable: lidService.suspendThenHibernateAvailable
  readonly property bool displayEnabled: displaySeconds > 0
  readonly property bool sleepEnabled: sleepSeconds > 0
  // The screensaver, display-off, and sleep stages are all self-observed here so
  // the cycle can survive the screensaver's brief activity blip (see below). The
  // shared monitor fires at the earliest of the enabled stage boundaries.
  readonly property bool cycleEnabled: displayEnabled || sleepEnabled
  readonly property int firstIdleSeconds: {
    if (!cycleEnabled) return 1
    var candidates = []
    if (screensaverSeconds > 0) candidates.push(screensaverSeconds)
    if (displayEnabled) candidates.push(displaySeconds)
    if (sleepEnabled) candidates.push(sleepSeconds)
    return Math.min.apply(Math, candidates)
  }
  readonly property int displayDelaySeconds: displayEnabled ? Math.max(0, displaySeconds - firstIdleSeconds) : 0
  readonly property int sleepDelaySeconds: sleepEnabled ? Math.max(0, sleepSeconds - firstIdleSeconds) : 0
  readonly property string helperPath: {
    var url = String(Qt.resolvedUrl("powerplan.py"))
    return decodeURIComponent(url.indexOf("file://") === 0 ? url.substring(7) : url)
  }
  // This helper is installed root-owned; never execute plugin code through pkexec.
  readonly property string hibernateHelperPath: "/usr/local/libexec/powerplan-configure-hibernate"

  function runHelper(arguments) {
    if (settingsProcess.running || hibernateConfigProcess.running) return false
    root.saving = true
    root.lastError = ""
    settingsProcess.command = ["python3", root.helperPath].concat(arguments)
    settingsProcess.running = true
    return true
  }

  function runSetter(command, state, seconds) {
    var powerState = Model.normalizedPowerState(state)
    var value = Model.requestedSeconds(seconds)
    if (value < 0) {
      root.lastError = "Ignored an invalid timeout"
      return false
    }
    return runHelper([command, powerState, String(value)])
  }

  function setScreensaver(state, seconds) {
    return runSetter("set-screensaver", state, seconds)
  }

  function setLock(state, seconds) {
    return runSetter("set-lock", state, seconds)
  }

  function setDisplay(state, seconds) {
    return runSetter("set-display", state, seconds)
  }

  function setSleep(state, seconds) {
    return runSetter("set-sleep", state, seconds)
  }

  // Hibernate delay is one systemd-wide knob (HibernateDelaySec), not a
  // per-app setting like DPMS or a lock command, so only one side of the
  // {ac, battery} pair can be the "real" configured value at any moment.
  // Editing the side that matches root.onBattery right now reconfigures it
  // immediately via the privileged helper. Editing the other (inactive)
  // side just saves the number; it takes effect the next time that side is
  // edited while active. Reconfiguring on every AC plug/unplug instead
  // would mean a polkit auth prompt every time the laptop changes power
  // source, which is worse.
  function setHibernate(state, seconds) {
    var powerState = Model.normalizedPowerState(state)
    var value = Model.requestedSeconds(seconds)
    if (value < 0) {
      root.lastError = "Ignored an invalid timeout"
      return false
    }
    if (value > 0 && !root.suspendThenHibernateAvailable) {
      root.lastError = "Suspend then hibernate is not available on this computer"
      return false
    }
    if (hibernateConfigProcess.running || settingsProcess.running) return false

    var isActiveSide = (powerState === "battery") === root.onBattery
    if (!isActiveSide) {
      return runHelper(["set-hibernate", powerState, String(value)])
    }

    root.saving = true
    root.lastError = ""
    root.pendingHibernateState = powerState
    root.pendingHibernateSeconds = value
    hibernateConfigProcess.command = ["pkexec", root.hibernateHelperPath,
      "configure-hibernate", String(value)]
    hibernateConfigProcess.running = true
    return true
  }

  function setLid(state, action) {
    var powerState = Model.normalizedPowerState(state)
    var value = String(action)
    if (Model.lidActions.indexOf(value) < 0) {
      root.lastError = "Ignored an invalid lid action"
      return false
    }
    return runHelper(["set-lid", powerState, value])
  }

  function refresh() {
    configFile.reload()
  }

  function rearmIdleMonitor() {
    cancelIdleCycle()
    if (!root.cycleEnabled) return
    root.idleMonitorRearming = true
    Qt.callLater(function() { root.idleMonitorRearming = false })
  }

  function resetScreensaverWindows() {
    root.screensaverWindows = ({})
    root.screensaverWindowCount = 0
  }

  function setScreensaverWindow(address, visible) {
    var key = String(address || "")
    if (!key) return
    var next = Object.assign({}, root.screensaverWindows)
    if (visible) next[key] = true
    else delete next[key]
    root.screensaverWindows = next
    root.screensaverWindowCount = Object.keys(next).length
  }

  function eventParts(event, count) {
    try {
      if (event && event.parse) return event.parse(count)
    } catch (error) {
    }
    return String(event && event.data ? event.data : "").split(",")
  }

  function handleHyprlandEvent(event) {
    var name = String(event && event.name ? event.name : "")
    var parts = eventParts(event, name === "openwindow" ? 4 : 1)
    if (name === "openwindow" && String(parts[2] || "") === root.screensaverClass) {
      setScreensaverWindow(parts[0], true)
      screensaverGrace.stop()
    } else if (name === "closewindow" && root.screensaverWindows[String(parts[0] || "")]) {
      setScreensaverWindow(parts[0], false)
      if (root.screensaverWindowCount === 0) cancelIdleCycle()
    }
  }

  function startIdleCycle() {
    if (!root.cycleEnabled || root.idleCycleRunning) return
    root.idleCycleRunning = true
    resetScreensaverWindows()

    // Omarchy starts the screensaver at the screensaver boundary. It briefly
    // reports compositor activity while opening, so allow its window event to
    // arrive before deciding that the user really returned. Arm the grace now if
    // the screensaver is the first stage, otherwise schedule it for the later
    // screensaver boundary (e.g. Display=2m, Screensaver=5m) so launching it
    // then does not cancel the cycle and turn the displays back on.
    if (root.screensaverSeconds > 0) {
      if (root.firstIdleSeconds === root.screensaverSeconds) screensaverGrace.restart()
      else screensaverBoundaryTimer.restart()
    }

    if (root.displayEnabled) {
      if (root.displayDelaySeconds === 0) turnDisplaysOff()
      else displayTimer.restart()
    }

    if (root.sleepEnabled) {
      if (root.sleepDelaySeconds === 0) requestSuspend()
      else sleepTimer.restart()
    }
  }

  function cancelIdleCycle() {
    displayTimer.stop()
    sleepTimer.stop()
    screensaverGrace.stop()
    screensaverBoundaryTimer.stop()
    root.idleCycleRunning = false
    resetScreensaverWindows()
    if (root.displaysOff) turnDisplaysOn()
  }

  function handleIdleChanged() {
    if (idleMonitor.isIdle) startIdleCycle()
    else if (root.idleCycleRunning
             && root.screensaverWindowCount === 0
             && !screensaverGrace.running) cancelIdleCycle()
  }

  function turnDisplaysOff() {
    if (!root.displayEnabled || displayOffProcess.running) return
    root.displaysOff = true
    root.lastError = ""
    displayOffProcess.running = true
  }

  function turnDisplaysOn() {
    root.displaysOff = false
    if (displayOnProcess.running) return
    displayOnProcess.running = true
  }

  function requestSuspend() {
    if (!root.sleepEnabled || suspendProcess.running) return
    root.suspendPending = true
    root.lastError = ""
    suspendProcess.command = ["systemctl", root.hibernateSeconds > 0
      ? "suspend-then-hibernate" : "suspend"]
    suspendProcess.running = true
  }

  // Quickshell's IdleMonitor does not re-register its idle notification when
  // only `timeout` changes. Toggle it off and back on so changed settings take
  // effect without requiring an omarchy-shell restart.
  onScreensaverSecondsChanged: rearmIdleMonitor()
  onDisplaySecondsChanged: rearmIdleMonitor()
  onSleepSecondsChanged: rearmIdleMonitor()

  LidService {
    id: lidService
    action: root.lidAction
    hibernateAfterSleep: root.hibernateSeconds > 0
    onErrorOccurred: function(message) { root.lastError = message }
  }

  Process {
    id: hibernateDiagnosticProcess
    command: ["python3", root.helperPath, "diagnose-hibernate"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var result = JSON.parse(String(text))
          root.hibernateDiagnostic = String(result.summary || "")
        } catch (error) {
          root.hibernateDiagnostic = ""
        }
      }
    }
    Component.onCompleted: running = true
  }

  Process {
    id: initializeProcess
    command: ["python3", root.helperPath, "init"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.configState = Model.parseConfig(text)
    }
    Component.onCompleted: running = true
    onExited: function(exitCode) {
      if (exitCode !== 0) root.lastError = "Could not initialize Power Plan settings"
      configFile.reload()
    }
  }

  Process {
    id: hibernateConfigProcess
    onExited: function(exitCode) {
      if (exitCode === 0) {
        root.runHelper(["set-hibernate", root.pendingHibernateState, String(root.pendingHibernateSeconds)])
      } else {
        root.saving = false
        root.lastError = "Could not change the system hibernate delay"
      }
    }
  }

  Process {
    id: settingsProcess
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.configState = Model.parseConfig(text)
    }
    onExited: function(exitCode) {
      root.saving = false
      if (exitCode !== 0) root.lastError = "Could not save that setting"
      configFile.reload()
    }
  }

  FileView {
    id: configFile
    path: root.configPath
    watchChanges: true
    printErrors: false
    onLoaded: root.configState = Model.parseConfig(text())
    onFileChanged: reload()
  }

  IdleMonitor {
    id: idleMonitor
    enabled: root.cycleEnabled && !root.idleMonitorRearming
    timeout: root.firstIdleSeconds
    respectInhibitors: true
    onIsIdleChanged: root.handleIdleChanged()
  }

  Timer {
    id: displayTimer
    interval: root.displayDelaySeconds * 1000
    repeat: false
    onTriggered: root.turnDisplaysOff()
  }

  Timer {
    id: sleepTimer
    interval: root.sleepDelaySeconds * 1000
    repeat: false
    onTriggered: root.requestSuspend()
  }

  Timer {
    id: screensaverGrace
    interval: 3000
    repeat: false
    onTriggered: if (root.idleCycleRunning && !idleMonitor.isIdle
                     && root.screensaverWindowCount === 0) root.cancelIdleCycle()
  }

  // When the screensaver boundary comes after the first idle stage (e.g. displays
  // off before the screensaver), arm the grace as that boundary arrives so the
  // screensaver launch's brief activity does not cancel the cycle.
  Timer {
    id: screensaverBoundaryTimer
    interval: Math.max(0, root.screensaverSeconds - root.firstIdleSeconds) * 1000
    repeat: false
    onTriggered: if (root.idleCycleRunning) screensaverGrace.restart()
  }

  Connections {
    target: Hyprland
    function onRawEvent(event) { root.handleHyprlandEvent(event) }
  }

  // UPower.onBattery drives every effectiveSeconds()/effectiveLidAction()
  // binding above automatically (they're plain QML property bindings), so
  // the values themselves update the instant the signal fires. What does
  // NOT rebind on its own is the running idle cycle: IdleMonitor keeps its
  // already-armed timeout, and Timer intervals don't retroactively rewind a
  // timer that's mid-countdown. Rearm on every power-source flip so the new
  // side's timers take effect immediately instead of after the current
  // cycle happens to finish.
  Connections {
    target: UPower
    function onOnBatteryChanged() { root.rearmIdleMonitor() }
  }

  // Hyprland's Lua config parses `hyprctl dispatch` args as Lua, so the classic
  // `dpms off` form is a syntax error there; use the `hl.dsp` shorthand and fall
  // back to the classic form for older Hyprland, mirroring omarchy-launch-screensaver.
  // The action MUST be passed as a table (`{ action = "off" }`); a bare string is
  // treated as the default *toggle*, so an explicit "on" after input already woke
  // the displays would toggle them back off.
  Process {
    id: displayOffProcess
    command: ["bash", "-lc", "hyprctl dispatch 'hl.dsp.dpms({ action = \"off\" })' || hyprctl dispatch dpms off"]
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        root.displaysOff = false
        root.lastError = "Could not turn the displays off"
      }
    }
  }

  Process {
    id: displayOnProcess
    command: ["bash", "-lc", "hyprctl dispatch 'hl.dsp.dpms({ action = \"on\" })' || hyprctl dispatch dpms on"]
    onExited: lidService.reapplyAfterGlobalDisplayOn()
  }

  Process {
    id: suspendProcess
    command: ["systemctl", "suspend"]
    onExited: function(exitCode) {
      root.suspendPending = false
      root.cancelIdleCycle()
      if (exitCode !== 0)
        root.lastError = root.hibernateSeconds > 0
          ? "Suspend then hibernate was blocked or unavailable"
          : "Sleep was blocked by the system or an application"
    }
  }

  IpcHandler {
    target: "valleytheknight.powerplan"

    function status(): string {
      return JSON.stringify({
        onBattery: root.onBattery,
        screensaver: root.screensaverSeconds,
        display: root.displaySeconds,
        lock: root.lockSeconds,
        sleep: root.sleepSeconds,
        hibernate: root.hibernateSeconds,
        lid: root.lidAction,
        screensaverPair: configState.screensaver,
        displayPair: configState.display,
        lockPair: configState.lock,
        sleepPair: configState.sleep,
        hibernatePair: configState.hibernate,
        lidPair: configState.lid,
        lidPresent: root.lidPresent,
        lidClosed: root.lidClosed,
        internalDisplay: root.internalDisplay,
        hibernateAvailable: root.hibernateAvailable,
        suspendThenHibernateAvailable: root.suspendThenHibernateAvailable,
        hibernateDiagnostic: root.hibernateDiagnostic,
        idle: idleMonitor.isIdle,
        idleCycleRunning: root.idleCycleRunning,
        displayDelay: root.displayDelaySeconds,
        displaysOff: root.displaysOff,
        sleepDelay: root.sleepDelaySeconds,
        screensaverWindows: root.screensaverWindowCount,
        saving: root.saving,
        suspendPending: root.suspendPending,
        error: root.lastError
      })
    }

    function setScreensaver(state: string, seconds: int): bool { return root.setScreensaver(state, seconds) }
    function setDisplay(state: string, seconds: int): bool { return root.setDisplay(state, seconds) }
    function setLock(state: string, seconds: int): bool { return root.setLock(state, seconds) }
    function setSleep(state: string, seconds: int): bool { return root.setSleep(state, seconds) }
    function setHibernate(state: string, seconds: int): bool { return root.setHibernate(state, seconds) }
    function setLid(state: string, action: string): bool { return root.setLid(state, action) }
    function refresh(): void { root.refresh() }
  }
}
