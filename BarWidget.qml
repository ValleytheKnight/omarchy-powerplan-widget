import QtQuick
import Quickshell
import qs.Ui
import "Model.js" as Model

BarWidget {
  id: root
  moduleName: "valleytheknight.powerplan"

  readonly property var powerplanService: bar && bar.shell
    ? bar.shell.serviceFor("valleytheknight.powerplan") : null
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item
    ? panelLoader.item.popoutSwitchClosing === true : false

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  function injectPanel() {
    if (!panelLoader.item) return
    panelLoader.item.bar = root.bar
    panelLoader.item.anchorItem = button
    panelLoader.item.hostWidget = root
    panelLoader.item.powerplanService = root.powerplanService
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onPowerplanServiceChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰒲"
    tooltipText: root.powerplanService
      ? Model.statusSummary(root.powerplanService.screensaverSeconds, root.powerplanService.displaySeconds, root.powerplanService.lockSeconds, root.powerplanService.sleepSeconds, root.powerplanService.hibernateSeconds)
      : "Power Plan"
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.toggle()
    }
  }
}
