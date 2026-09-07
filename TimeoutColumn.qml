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
  property int customMinutes: 0
  property int customSecondsValue: 0
  readonly property int customTimeoutSeconds: Model.customSeconds(root.customHours, root.customMinutes, root.customSecondsValue)

  // The three fields below only push into customHours/customMinutes/
  // customSecondsValue when a SpinBox commits (Enter, Tab, or losing focus),
  // which is standard Qt SpinBox behavior. Reading straight from each
  // field's live typed text instead means Apply reacts to typing directly,
  // not only after a commit - and a disabled Apply button never gets the
  // click that would have caused a commit, so gating on the committed
  // value alone could strand the button disabled regardless of what was
  // typed into the fields.
  function liveFieldSeconds(field) {
    var parsed = field.valueFromText(field.contentItem.text, field.locale)
    return isFinite(parsed) ? parsed : 0
  }

  readonly property int liveCustomSeconds: root.customEditorOpen
    ? Model.customSeconds(
        root.liveFieldSeconds(hoursField.field),
        root.liveFieldSeconds(minutesField.field),
        root.liveFieldSeconds(secondsField.field))
    : 0

  // Seed only from a real current value. Guessing a default (e.g. 5 minutes)
  // when the section is currently Off would pre-fill the fields with a
  // number nobody chose; start blank at 0:0:0 instead.
  function loadCustomTimeout() {
    var parts = root.currentSeconds > 0 ? Model.customParts(root.currentSeconds) : { hours: 0, minutes: 0, seconds: 0 }
    root.customHours = parts.hours
    root.customMinutes = parts.minutes
    root.customSecondsValue = parts.seconds
  }

  // onPanelOpenChanged only fires on a transition. A column created while
  // the panel is already open (the normal case) never sees that transition,
  // so a section already holding a real custom value needs seeding here too.
  Component.onCompleted: {
    if (root.customEditorOpen) root.loadCustomTimeout()
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
    if (root.liveCustomSeconds > 0) root.valueSelected(root.liveCustomSeconds)
  }

  // Runs on every panel open: pick up whichever editor mode (preset vs
  // custom) the current value actually needs, and seed the custom fields
  // from it.
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
        id: hoursField
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
        id: minutesField
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
        id: secondsField
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
      enabled: !root.saving && root.enabled && root.liveCustomSeconds > 0
      focusable: true
      bordered: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      onClicked: root.applyCustomTimeout()
    }
  }
}
