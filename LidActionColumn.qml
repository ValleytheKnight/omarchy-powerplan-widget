import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// One power-state's worth of the lid-close action grid. No custom editor
// here, unlike TimeoutColumn - lid actions are a fixed enum, not a timeout.
Column {
  id: root

  property string stateLabel: ""
  property string currentAction: "system"
  property bool hibernateAvailable: false
  property bool saving: false
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property int columns: 2

  signal actionSelected(string action)

  spacing: Style.space(6)

  Text {
    text: root.stateLabel
    color: Util.alpha(root.foreground, 0.8)
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  Grid {
    id: actionGrid
    width: parent.width
    columns: root.columns
    columnSpacing: Style.space(6)
    rowSpacing: Style.space(6)

    Repeater {
      model: Model.lidActions

      Button {
        required property var modelData
        width: (actionGrid.width - actionGrid.columnSpacing * (root.columns - 1)) / root.columns
        text: Model.lidActionLabel(modelData)
        selected: root.currentAction === String(modelData)
        enabled: !root.saving && (String(modelData) !== "hibernate" || root.hibernateAvailable)
        opacity: enabled ? 1 : 0.38
        focusable: true
        bordered: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        onClicked: root.actionSelected(String(modelData))
      }
    }
  }
}
