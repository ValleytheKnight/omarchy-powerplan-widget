# Power Plan

## Install

```sh
omarchy plugin add https://github.com/ValleytheKnight/omarchy-powerplan-widget.git --enable
```

The privileged helper installs as a pacman package signed by the
maintainer's key, not built or self-signed on your machine:

```sh
git clone https://github.com/ValleytheKnight/omarchy-powerplan-widget.git
cd omarchy-powerplan-widget
```

Before your first install on a given machine, trust that key once, the
same way you'd trust any third-party repository's signing key:

```sh
sudo pacman-key --add packaging/keys/valleytheknight-powerplan.asc
sudo pacman-key --lsign-key A8238083DE096BC875CD1EB572BD2077B316056A
```

One-time per machine. After this, every install or update from this
key is verified automatically, no repeated trust decision.

Then install the helper, and restart the shell if it is already
running:

```sh
./scripts/install-privileged-helper
omarchy restart shell
```

`install-privileged-helper` runs as your own user. It reads the
pre-built, pre-signed package and its signature from
`packaging/release/` once, then pipes those exact bytes to a single
`pkexec` command. This script's own interpreter, `pkexec`, and the
shell it runs are all invoked by absolute path, never resolved through
this process's own `PATH`. Root stages the bytes in a directory it
creates itself, verifies the signature against pacman's own trusted
keyring with `pacman-key --verify`, and only then runs `pacman -U`.
Any tampering or truncation invalidates the signature, so the
signature check covers the whole package, not a piece of it, and root
never installs anything that wasn't verified against the key you
trusted above.

Residual: a local process that can already write to your clone could
still rewrite the installer itself before you run it. No install
script can protect against that; it's the same trust the first command
you ever type from a checkout always requires.

If needed, add it to the bar explicitly:

```sh
omarchy bar plugin add valleytheknight.powerplan --section right
```

## Overview

Set screensaver, displays-off, auto-lock, sleep, hibernate, and lid-close
behavior independently for plugged in versus on battery, from the Omarchy
Quattro bar.

![Power Plan screensaver, displays-off, auto-lock, and sleep settings, split by power state](preview.png)

On laptops, Power Plan also shows lid-close actions, split the same way:

![Power Plan laptop lid-close actions, split by power state](preview-laptop.png)

![Power Plan panel, scrolled from top to bottom](demo.gif)

Power Plan provides seven controls, each set independently for **Plugged in**
and **On battery**:

- **Lid close**: keeps the system default or does nothing, turns off the laptop display, suspends, or hibernates when the lid closes.
- **Screen saver**: starts the screen saver after the selected period of inactivity.
- **Displays off**: turns the displays off (DPMS) after the selected period of inactivity while respecting idle inhibitors.
- **Auto-lock**: locks the session after the selected period of inactivity.
- **Sleep**: suspends the computer after the selected period of inactivity while respecting idle inhibitors.
- **Hibernate after sleep**: wakes a suspended computer after the selected delay and hibernates it.
- **Power profile**: picks which Omarchy power profile applies on AC versus battery.

Each timeout offers presets, Off, and a custom hours/minutes/seconds entry.
Omarchy requires positive screen-saver and lock values, so Power Plan
simulates Off with safe seven-day timeouts while displaying and persisting
Off as `0`.

## Usage

Click the bar icon and choose a lid-close action or a timeout for each idle
stage, once for **Plugged in** and once for **On battery**. Presets apply
immediately; Custom accepts hours, minutes, and seconds, and applies on
confirmation for screen saver, displays off, auto-lock, sleep, and
hibernate-after-sleep. Existing values that do not match a preset open as
Custom. Changes survive shell reloads and reboots, and take effect
immediately when the power source changes.

The lid controls appear only when UPower reports a laptop lid. **System
default** leaves logind in charge. The other actions use a low-level
lid-switch inhibitor while Power Plan is running, then handle the event
without changing system-wide logind configuration. For managed lid actions,
Power Plan also installs a small managed block in `~/.config/hypr/bindings.lua`
that replaces Omarchy's default `switch:on:Lid Switch` binding. Omarchy's
default binding locks immediately on lid close, before Power Plan can apply
**Do nothing** or **Display off**, so Power Plan unbinds it and keeps only
Omarchy's clamshell monitor reconciliation. Selecting **System default**
removes Power Plan's managed Hyprland block again. **Display off** targets
the internal eDP/LVDS/DSI output and turns it back on when the lid opens.
Hibernate is selectable only when logind reports that it is available.

Power Plan stores its state in `~/.config/omarchy/powerplan.json`, as an
`{ac, battery}` pair for every setting. The effective screen-saver and
auto-lock values for whichever power source is active right now stay
mirrored into Omarchy's standard `~/.config/omarchy/shell.json`; lid
actions, and the displays-off, sleep, and hibernate-after-sleep timers, are
handled by Power Plan itself and are not written there. Changing the
hibernate delay asks for administrator authorization because systemd's RTC
wake timer is configured system-wide, and only one side of the AC/battery
pair can be the active configured value at any moment.

## How displays off works

Power Plan uses Quickshell's idle monitor with inhibitor support and turns
the displays off through Hyprland's `dpms` dispatcher. Applications holding
an idle inhibitor can prevent the timer from firing, and any key press or
mouse movement turns the displays back on.

## How sleep and hibernate work

Power Plan uses Quickshell's idle monitor with inhibitor support and
requests suspend through `systemctl suspend`. Applications holding an idle
inhibitor can prevent the timer from firing, and system-level sleep
inhibitors can reject the suspend request.

When **Hibernate after sleep** is enabled, Power Plan instead requests
`systemctl suspend-then-hibernate`. systemd sets an RTC wake alarm, wakes
after the chosen delay, and hibernates. Power Plan stores the delay in
`/etc/systemd/sleep.conf.d/90-powerplan.conf`; changing or disabling it
requires administrator authorization. The option is available only when
logind reports that suspend-then-hibernate is supported. When it is
unavailable, Power Plan disables the positive timeout choices and reports
any prerequisite it can detect, including missing disk-backed swap, missing
kernel hibernation support, missing resume discovery, or restrictive kernel
lockdown. **Off** remains available so an old setting can always be cleared.

## Requirements

- Omarchy Quattro
- Python 3
- systemd
- UPower
- GLib (`gdbus`)
- Polkit (`pkexec`), to change the systemd hibernate delay
- `pacman-key` (part of pacman), to install and verify the privileged helper

The helper is deliberately separate from `powerplan.py`, because the latter
is loaded from the user-owned plugin directory and must never be executed
as root.

## Validate

```sh
npm test
omarchy plugin validate .
./scripts/lint-qml
```

`lint-qml` calls Qt6's `qmllint` (`/usr/lib/qt6/bin/qmllint`) explicitly
rather than whatever `qmllint` resolves to on `PATH`: on a system with
both Qt5 and Qt6 installed, the plain command usually resolves to Qt5's
build, which can't resolve this project's Qt6 Quickshell module types
and aborts silently (no output, no crash dump) instead of reporting an
error. It also aliases the `qs` namespace Quickshell registers for its
own shell root at runtime, which a bare `-I` path can't resolve on its
own; without that alias, every type `qs.Commons`/`qs.Ui` would have
provided cascades into unrelated-looking warnings throughout every file.

With both of those fixed, 39 warnings remain, all from typing this
project doesn't own: the `bar` context object Quickshell hands every
bar widget is typed as a plain `QtObject`, so member access on it can't
be statically verified; the same is true of `Style.font` in the shared
Omarchy shell's `Commons/Style.qml`, whose `font` property is a plain
`QtObject` rather than a named type with declared properties; and
`Quickshell.Io`'s `Process.exited` signal's second parameter type
(`QProcess::ExitStatus`) isn't resolvable by qmllint even when a
handler declares it explicitly (confirmed by testing a minimal handler
in isolation), so every `onExited` handler warns regardless of what it
does. None of these are fixable by editing this plugin's own files.

## Remove

```sh
omarchy plugin remove valleytheknight.powerplan
rm -f ~/.config/omarchy/powerplan.json
sudo rm -f /etc/systemd/sleep.conf.d/90-powerplan.conf
sudo pacman -Rns omarchy-powerplan-helper
```

Removing Power Plan does not revert the screen-saver and lock timeouts
already written to `shell.json`. If Power Plan is removed while a managed
lid action is selected, remove the managed block between `-- BEGIN Power
Plan lid action override` and `-- END Power Plan lid action override` from
`~/.config/hypr/bindings.lua`, or reinstall Power Plan and select **System
default** before removing it.

This matters if either setting was left **Off** for the currently active
power source. Off is stored in `shell.json` as a seven-day timeout, so
removing Power Plan while auto-lock is Off leaves a machine that
effectively never locks, with no Power Plan UI left to notice it. Set
anything you want back on *before* removing, or restore Omarchy's defaults
afterwards:

```sh
python3 - <<'PY'
import json, pathlib
path = pathlib.Path.home() / ".config/omarchy/shell.json"
config = json.loads(path.read_text())
config.setdefault("idle", {}).update({"screensaver": 150, "lock": 300})
path.write_text(json.dumps(config, indent=2) + "\n")
PY
```

## Fork

Power Plan is a fork of [Sandman](https://github.com/lgse/sandman) by Pierre
Berube, MIT licensed. See [`NOTICE.md`](NOTICE.md) for what changed.

## License

MIT
