import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// One full timeout setting (screensaver, displays off, auto-lock, sleep, or
// hibernate): a section header, description, an optional warning line, and
// two TimeoutColumns side by side, one per power state.
Column {
  id: root

  property string title: ""
  property string description: ""
  property var presets: []
  property var pair: ({ ac: 0, battery: 0 })
  property int defaultCustomSeconds: 300
  property bool enabled: true
  property bool saving: false
  property bool panelOpen: false
  property string warningText: ""
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family

  signal setValue(string state, int seconds)

  width: parent.width
  spacing: Style.space(7)

  PanelSectionHeader {
    width: parent.width
    text: root.title
    foreground: root.foreground
    fontFamily: root.fontFamily
  }

  Text {
    width: parent.width
    text: root.description
    color: Util.alpha(root.foreground, 0.64)
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Row {
    width: parent.width
    spacing: Style.space(12)

    TimeoutColumn {
      width: (parent.width - parent.spacing) / 2
      stateLabel: "Plugged in"
      presets: root.presets
      currentSeconds: root.pair.ac
      defaultCustomSeconds: root.defaultCustomSeconds
      enabled: root.enabled
      saving: root.saving
      panelOpen: root.panelOpen
      foreground: root.foreground
      fontFamily: root.fontFamily
      onValueSelected: function(seconds) { root.setValue("ac", seconds) }
    }

    TimeoutColumn {
      width: (parent.width - parent.spacing) / 2
      stateLabel: "On battery"
      presets: root.presets
      currentSeconds: root.pair.battery
      defaultCustomSeconds: root.defaultCustomSeconds
      enabled: root.enabled
      saving: root.saving
      panelOpen: root.panelOpen
      foreground: root.foreground
      fontFamily: root.fontFamily
      onValueSelected: function(seconds) { root.setValue("battery", seconds) }
    }
  }

  Text {
    visible: root.warningText !== ""
    width: parent.width
    text: root.warningText
    color: Color.urgent
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }
}
