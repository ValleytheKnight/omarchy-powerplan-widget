import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// One power-state's worth of a timeout section: a preset grid plus a
// Custom hour/minute editor. Owns its own custom-editor state so Panel.qml
// does not need ten copies of customEditorOpen/customHours/customMinutes
// hand-declared on itself, one set per section per power state.
Column {
  id: root

  property string stateLabel: ""
  property var presets: []
  property int currentSeconds: 0
  property int defaultCustomSeconds: 300
  property bool enabled: true
  property bool saving: false
  property bool panelOpen: false
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property int columns: 2

  signal valueSelected(int seconds)

  readonly property bool usesPreset: Model.isPreset(root.currentSeconds, root.presets)
  property bool customEditorOpen: !root.usesPreset
  property int customHours: 0
  property int customMinutes: 1
  property int customSecondsValue: 0
  readonly property int customTimeoutSeconds: Model.customSeconds(root.customHours, root.customMinutes, root.customSecondsValue)

  function loadCustomTimeout() {
    var parts = Model.customParts(root.currentSeconds > 0 ? root.currentSeconds : root.defaultCustomSeconds)
    root.customHours = parts.hours
    root.customMinutes = parts.minutes
    root.customSecondsValue = parts.seconds
  }

  function openCustomEditor() {
    root.loadCustomTimeout()
    root.customEditorOpen = true
  }

  function selectPreset(value) {
    root.customEditorOpen = false
    root.valueSelected(value)
  }

  function applyCustomTimeout() {
    if (root.customTimeoutSeconds > 0) root.valueSelected(root.customTimeoutSeconds)
  }

  // Mirrors the reset Panel.qml used to do once for all five sections on
  // open: pick up whichever editor mode (preset vs custom) the current
  // value actually needs, and seed the custom fields from it.
  onPanelOpenChanged: {
    if (!root.panelOpen) return
    root.customEditorOpen = !root.usesPreset
    if (root.customEditorOpen) root.loadCustomTimeout()
  }

  spacing: Style.space(6)

  Text {
    text: root.stateLabel
    color: Util.alpha(root.foreground, 0.8)
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  Grid {
    id: presetGrid
    width: parent.width
    columns: root.columns
    columnSpacing: Style.space(6)
    rowSpacing: Style.space(6)

    Repeater {
      model: root.presets

      Button {
        required property var modelData
        width: (presetGrid.width - presetGrid.columnSpacing * (root.columns - 1)) / root.columns
        text: Model.formatDuration(modelData)
        selected: !root.customEditorOpen && root.currentSeconds === Number(modelData)
        enabled: !root.saving && root.enabled
        opacity: enabled ? 1 : 0.38
        focusable: true
        bordered: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        onClicked: root.selectPreset(Number(modelData))
      }
    }

    Button {
      width: (presetGrid.width - presetGrid.columnSpacing * (root.columns - 1)) / root.columns
      text: "Custom"
      selected: root.customEditorOpen || !root.usesPreset
      enabled: !root.saving && root.enabled
      opacity: enabled ? 1 : 0.38
      focusable: true
      bordered: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      onClicked: root.openCustomEditor()
    }
  }

  Column {
    visible: root.customEditorOpen
    width: parent.width
    spacing: Style.space(6)
    enabled: !root.saving && root.enabled
    opacity: enabled ? 1 : 0.38

    Row {
      width: parent.width
      spacing: Style.space(6)

      NumberField {
        label: "Hours"
        value: root.customHours
        from: 0
        to: 24
        fieldWidth: (parent.width - Style.space(12)) / 3
        foreground: root.foreground
        fontFamily: root.fontFamily
        onModified: function(value) { root.customHours = value }
      }

      NumberField {
        label: "Minutes"
        value: root.customMinutes
        from: 0
        to: 59
        fieldWidth: (parent.width - Style.space(12)) / 3
        foreground: root.foreground
        fontFamily: root.fontFamily
        onModified: function(value) { root.customMinutes = value }
      }

      NumberField {
        label: "Seconds"
        value: root.customSecondsValue
        from: 0
        to: 59
        fieldWidth: (parent.width - Style.space(12)) / 3
        foreground: root.foreground
        fontFamily: root.fontFamily
        onModified: function(value) { root.customSecondsValue = value }
      }
    }

    Button {
      width: parent.width
      text: "Apply"
      enabled: !root.saving && root.enabled && root.customTimeoutSeconds > 0
      focusable: true
      bordered: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      onClicked: root.applyCustomTimeout()
    }
  }
}
