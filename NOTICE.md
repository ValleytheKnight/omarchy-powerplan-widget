Power Plan is a fork of [Sandman](https://github.com/lgse/sandman) by Pierre
Berube, MIT licensed. See `LICENSE` for the full license text and both
copyright notices.

## What changed from Sandman

Sandman controls screensaver, display-off, auto-lock, sleep, hibernate, and
lid-close behavior for Omarchy, one value per setting. Power Plan splits
every one of those settings into a `{ac, battery}` pair, resolved live
against `Quickshell.Services.UPower.onBattery`, and adds a Power Profile
section for picking which Omarchy power profile applies on AC versus
battery.

Concretely:

- `Model.js`, `Service.qml`, `powerplan.py` (renamed from `sandman.py`), and
  `powerplan-configure-hibernate` (renamed from `sandman-configure-hibernate`)
  were reworked to store and resolve `{ac, battery}` pairs instead of bare
  values.
- `Panel.qml` was rebuilt around three new components (`TimeoutColumn.qml`,
  `TimeoutSection.qml`, `LidActionColumn.qml`) so each setting shows a
  "Plugged in" and "On battery" column instead of one.
- A new Power Profile section wraps Omarchy's own
  `omarchy-powerprofiles-list`/`omarchy-powerprofiles-set` CLI, letting you
  pick a profile per power state from the panel instead of only
  autodetecting.
- `LidService.qml` is unchanged internally; it now receives whichever lid
  action is effective for the current power state instead of a single
  configured value.
- Everything else (idle-cycle timing, DPMS handling via
  `hyprctl dispatch hl.dsp.dpms`, the logind lid inhibitor, the
  suspend-then-hibernate privileged helper) is Sandman's original design,
  unchanged.
