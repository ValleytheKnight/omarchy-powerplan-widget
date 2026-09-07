import QtQuick
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "valleytheknight.powerplan"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var powerplanService: null
  readonly property var barIdentity: hostWidget || root
  readonly property color contentForeground: bar ? bar.foreground : Color.foreground
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family

  // These reflect whichever power source is effective right now (the
  // service resolves the {ac, battery} pair itself), used for the status
  // summary line and the cross-section warning texts below. The sections
  // themselves read both sides of each pair directly from configState.
  readonly property int screensaverSeconds: powerplanService ? powerplanService.screensaverSeconds : 150
  readonly property int displaySeconds: powerplanService ? powerplanService.displaySeconds : 0
  readonly property int lockSeconds: powerplanService ? powerplanService.lockSeconds : 300
  readonly property int sleepSeconds: powerplanService ? powerplanService.sleepSeconds : 0
  readonly property int hibernateSeconds: powerplanService ? powerplanService.hibernateSeconds : 0
  readonly property bool lidPresent: powerplanService ? powerplanService.lidPresent : false
  readonly property bool stayAwake: powerplanService ? powerplanService.stayAwake : false
  readonly property bool hibernateAvailable: powerplanService ? powerplanService.hibernateAvailable : false
  readonly property bool suspendThenHibernateAvailable: powerplanService ? powerplanService.suspendThenHibernateAvailable : false
  readonly property string hibernateDiagnostic: powerplanService ? powerplanService.hibernateDiagnostic : ""
  readonly property bool saving: powerplanService ? powerplanService.saving : false
  readonly property var configState: powerplanService ? powerplanService.configState : Model.parseConfig("{}")
  readonly property var availableProfiles: powerplanService ? powerplanService.availableProfiles : []
  readonly property string acProfile: powerplanService ? powerplanService.acProfile : ""
  readonly property string batteryProfile: powerplanService ? powerplanService.batteryProfile : ""

  function open() { root.controller.show() }
  function close() { root.controller.hide() }
  function toggle() { root.opened ? root.close() : root.open() }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function scrollPanel(delta) {
    panelFlick.contentY = Math.max(0, Math.min(
      panelFlick.contentY + delta,
      Math.max(0, panelFlick.contentHeight - panelFlick.height)))
  }

  function profileOptions() {
    return root.availableProfiles.map(function(name) {
      var label = String(name).split("-")
        .map(function(word) { return word.charAt(0).toUpperCase() + word.slice(1) })
        .join(" ")
      return { value: name, label: label }
    })
  }

  onOpenedChanged: {
    if (!opened) return
    if (root.powerplanService) root.powerplanService.refreshPowerProfiles()
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(480))
    // Capped at half the screen height rather than the full available card
    // height (KeyboardPanel's default): with seven sections plus two
    // columns each, the uncapped panel ran the full screen, leaving a
    // Dropdown's popup with nowhere to open into. The Flickable below
    // already scrolls whenever content exceeds this height.
    contentHeight: panel.fittedContentHeight(content.implicitHeight, panel.screenH * 0.5)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onMoveRequested: function(dx, dy) {
        if (dy !== 0) root.scrollPanel(dy * Style.space(56))
      }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        // No custom wheel handling here: a WheelHandler receives zero
        // events from either a trackpad or a mouse wheel in this
        // environment, even with a cleared QML cache. No stock Omarchy
        // panel implements custom wheel scrolling either, pointing at a
        // platform-level limitation in how Quickshell panel windows
        // deliver wheel input, not a bug in this file. Scrolling works
        // through the ScrollBar drag above and keyboard navigation
        // (PanelKeyCatcher's onMoveRequested -> scrollPanel) below.

        Column {
          id: content
          width: panelFlick.width
          spacing: Style.space(12)

        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(14)

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "󰒲"
            color: Color.accent
            font.family: root.contentFontFamily
            font.pixelSize: Style.space(42)
          }

          Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              text: "Power Plan"
              color: root.contentForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.title
              font.bold: true
            }

            Text {
              text: Model.statusSummary(root.screensaverSeconds, root.displaySeconds, root.lockSeconds, root.sleepSeconds, root.hibernateSeconds)
              color: Util.alpha(root.contentForeground, 0.64)
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }

        PanelSeparator { width: parent.width }

        // Placed high in the panel, not at the bottom: the panel already
        // runs the full height of the screen, so a dropdown's popup opened
        // near the very bottom has nowhere below it to render into and gets
        // clipped by the window edge. Dropdown.qml is one of Omarchy's own
        // shared components (not ours to edit), so the fix is positioning,
        // not the popup itself.
        Column {
          width: parent.width
          spacing: Style.space(7)

          PanelSectionHeader {
            width: parent.width
            text: "POWER PROFILE"
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
          }

          Text {
            width: parent.width
            text: "Which performance profile applies for each power source"
            color: Util.alpha(root.contentForeground, 0.64)
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.caption
          }

          Row {
            width: parent.width
            spacing: Style.space(12)

            Dropdown {
              width: (parent.width - parent.spacing) / 2
              label: "Plugged in"
              value: root.acProfile
              options: root.profileOptions()
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              onChanged: function(value) {
                if (root.powerplanService) root.powerplanService.setPowerProfile("ac", value)
              }
            }

            Dropdown {
              width: (parent.width - parent.spacing) / 2
              label: "On battery"
              value: root.batteryProfile
              options: root.profileOptions()
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              onChanged: function(value) {
                if (root.powerplanService) root.powerplanService.setPowerProfile("battery", value)
              }
            }
          }
        }

        PanelSeparator { width: parent.width }

        Column {
          visible: root.lidPresent
          width: parent.width
          spacing: Style.space(7)

          PanelSectionHeader {
            width: parent.width
            text: "LID CLOSE"
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
          }

          Text {
            width: parent.width
            text: "Choose what happens when the laptop lid closes"
            color: Util.alpha(root.contentForeground, 0.64)
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.caption
          }

          Row {
            width: parent.width
            spacing: Style.space(12)

            LidActionColumn {
              width: (parent.width - parent.spacing) / 2
              stateLabel: "Plugged in"
              currentAction: root.configState.lid.ac
              hibernateAvailable: root.hibernateAvailable
              saving: root.saving
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              onActionSelected: function(action) {
                if (root.powerplanService) root.powerplanService.setLid("ac", action)
              }
            }

            LidActionColumn {
              width: (parent.width - parent.spacing) / 2
              stateLabel: "On battery"
              currentAction: root.configState.lid.battery
              hibernateAvailable: root.hibernateAvailable
              saving: root.saving
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              onActionSelected: function(action) {
                if (root.powerplanService) root.powerplanService.setLid("battery", action)
              }
            }
          }
        }

        PanelSeparator {
          visible: root.lidPresent
          width: parent.width
        }

        TimeoutSection {
          width: parent.width
          title: "SCREEN SAVER"
          description: "Start after inactivity"
          presets: Model.screensaverPresets
          pair: root.configState.screensaver
          saving: root.saving
          panelOpen: root.opened
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          warningText: root.stayAwake
            ? "Stay Awake is on. The screen saver will not trigger until it's turned off."
            : (root.screensaverSeconds > 0 && root.lockSeconds > 0 && root.lockSeconds <= root.screensaverSeconds)
              ? "Auto-lock is set before the screen saver can appear."
              : ""
          onSetValue: function(state, seconds) {
            if (root.powerplanService) root.powerplanService.setScreensaver(state, seconds)
          }
        }

        PanelSeparator { width: parent.width }

        TimeoutSection {
          width: parent.width
          title: "DISPLAYS OFF"
          description: "Turn off the displays after inactivity"
          presets: Model.displayPresets
          pair: root.configState.display
          saving: root.saving
          panelOpen: root.opened
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          warningText: (root.screensaverSeconds > 0 && root.displaySeconds > 0 && root.displaySeconds <= root.screensaverSeconds)
            ? "Displays turn off before the screen saver can appear."
            : ""
          onSetValue: function(state, seconds) {
            if (root.powerplanService) root.powerplanService.setDisplay(state, seconds)
          }
        }

        PanelSeparator { width: parent.width }

        TimeoutSection {
          width: parent.width
          title: "AUTO-LOCK"
          description: "Lock the session after inactivity"
          presets: Model.lockPresets
          pair: root.configState.lock
          saving: root.saving
          panelOpen: root.opened
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          warningText: root.stayAwake
            ? "Stay Awake is on. Auto-lock will not trigger until it's turned off."
            : ""
          onSetValue: function(state, seconds) {
            if (root.powerplanService) root.powerplanService.setLock(state, seconds)
          }
        }

        PanelSeparator { width: parent.width }

        TimeoutSection {
          width: parent.width
          title: "SLEEP"
          description: "Suspend the computer after inactivity"
          presets: Model.sleepPresets
          pair: root.configState.sleep
          saving: root.saving
          panelOpen: root.opened
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          warningText: (root.screensaverSeconds > 0 && root.sleepSeconds > 0 && root.sleepSeconds <= root.screensaverSeconds)
            ? "Sleep is set before the screen saver can appear."
            : ""
          onSetValue: function(state, seconds) {
            if (root.powerplanService) root.powerplanService.setSleep(state, seconds)
          }
        }

        PanelSeparator { width: parent.width }

        Column {
          width: parent.width
          spacing: Style.space(7)

          TimeoutSection {
            width: parent.width
            title: "HIBERNATE AFTER SLEEP"
            description: "Wake from suspend and hibernate after this delay"
            presets: Model.hibernatePresets
            pair: root.configState.hibernate
            enabled: root.suspendThenHibernateAvailable
            saving: root.saving
            panelOpen: root.opened
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
            onSetValue: function(state, seconds) {
              if (root.powerplanService) root.powerplanService.setHibernate(state, seconds)
            }
          }

          Text {
            visible: !root.suspendThenHibernateAvailable
            width: parent.width
            text: "Suspend then hibernate is not available on this computer. "
              + (root.hibernateDiagnostic !== ""
                ? root.hibernateDiagnostic
                : "Check swap, kernel resume configuration, and firmware support.")
            color: Color.urgent
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          Text {
            visible: root.hibernateSeconds > 0 && root.sleepSeconds === 0
            width: parent.width
            text: "Enable Sleep for automatic hibernation after inactivity."
            color: Color.urgent
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          Text {
            visible: root.hibernateSeconds > 0
            width: parent.width
            text: "Changing this delay requires administrator authorization."
            color: Util.alpha(root.contentForeground, 0.64)
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }

          Text {
            visible: root.powerplanService && root.powerplanService.lastError !== ""
            width: parent.width
            text: root.powerplanService ? root.powerplanService.lastError : ""
            color: Color.urgent
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
          }
        }
      }
    }
  }
}
