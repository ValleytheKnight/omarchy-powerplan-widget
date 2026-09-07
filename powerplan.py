#!/usr/bin/env python3
"""Persist Power Plan settings without discarding unrelated Omarchy config."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_SCREENSAVER = 150
DEFAULT_DISPLAY = 0
DEFAULT_LOCK = 300
DEFAULT_SLEEP = 0
DEFAULT_HIBERNATE = 0
DEFAULT_LID_ACTION = "system"
LID_ACTIONS = ("system", "nothing", "display", "sleep", "hibernate")
POWER_STATES = ("ac", "battery")
OFF_TIMEOUT = 7 * 24 * 60 * 60
MAX_TIMEOUT = OFF_TIMEOUT
HYPR_OVERRIDE_BEGIN = "-- BEGIN Power Plan lid action override"
HYPR_OVERRIDE_END = "-- END Power Plan lid action override"
HYPR_OVERRIDE_BLOCK = f"""{HYPR_OVERRIDE_BEGIN}
-- Power Plan manages laptop lid-close actions. Omarchy's default lid-close
-- binding locks immediately on lid close, before Power Plan can apply Do
-- nothing or Display off, so replace it with monitor/clamshell
-- reconciliation only.
hl.unbind("switch:on:Lid Switch")
o.bind("switch:on:Lid Switch", nil, "omarchy-hyprland-monitor-clamshell", {{ locked = true }})
{HYPR_OVERRIDE_END}
"""
MANAGED_LID_ACTIONS = {"nothing", "display", "sleep", "hibernate"}
SYSTEMD_SLEEP_CONFIG = Path("/etc/systemd/sleep.conf.d/90-powerplan.conf")


class ConfigError(Exception):
    """An existing config file could not be read, so we must not rewrite it."""


def shell_path() -> Path:
    override = os.environ.get("OMARCHY_SHELL_CONFIG_PATH")
    return Path(override).expanduser() if override else Path.home() / ".config/omarchy/shell.json"


def config_path() -> Path:
    override = os.environ.get("POWERPLAN_CONFIG_PATH")
    return Path(override).expanduser() if override else Path.home() / ".config/omarchy/powerplan.json"


def hypr_bindings_path() -> Path:
    override = os.environ.get("POWERPLAN_HYPR_BINDINGS_PATH")
    return Path(override).expanduser() if override else Path.home() / ".config/hypr/bindings.lua"


def systemd_sleep_config_path() -> Path:
    override = os.environ.get("POWERPLAN_SYSTEMD_SLEEP_CONFIG_PATH")
    return Path(override) if override else SYSTEMD_SLEEP_CONFIG


def diagnostic_path(environment_name: str, default: str) -> Path:
    override = os.environ.get(environment_name)
    return Path(override).expanduser() if override else Path(default)


def read_json(
    path: Path, fallback: dict[str, Any], *, strict: bool = False
) -> dict[str, Any]:
    """Load a JSON object, distinguishing "absent" from "present but unusable".

    A missing file legitimately means "no settings yet", so the fallback applies.
    Anything else - unreadable, malformed, or not a JSON object - means the file
    holds content we failed to understand. When strict, refuse rather than return
    a fallback: callers merge into the result and write it back, so returning a
    fallback here would replace a config we could not read with a bare stub.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return fallback.copy()
    except (OSError, UnicodeError) as error:
        # UnicodeDecodeError subclasses ValueError, not OSError, so a file
        # holding invalid UTF-8 would otherwise escape as a traceback.
        if strict:
            raise ConfigError(f"Could not read {path}: {error}") from error
        return fallback.copy()

    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        if strict:
            raise ConfigError(
                f"{path} is not valid JSON ({error}). "
                "Fix or remove the file; refusing to overwrite it."
            ) from error
        return fallback.copy()

    if not isinstance(value, dict):
        if strict:
            raise ConfigError(
                f"{path} does not contain a JSON object; refusing to overwrite it."
            )
        return fallback.copy()
    return value


def seconds(value: Any, fallback: int, *, allow_off: bool = False) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        result = int(value)
    except (TypeError, ValueError):
        return fallback
    if allow_off and result == 0:
        return 0
    if result <= 0:
        return fallback
    # Bound persisted values too, not just setter input. A powerplan.json
    # written by an older version - or edited by hand - can hold a value
    # large enough to overflow sleepDelaySeconds * 1000 in the QML timer.
    return min(result, MAX_TIMEOUT)


def power_state(value: Any) -> str:
    result = str(value or "ac")
    return result if result in POWER_STATES else "ac"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    text = json.dumps(value, indent=2) + "\n"
    atomic_write_text(path, text)


def lid_action(value: Any) -> str:
    return value if isinstance(value, str) and value in LID_ACTIONS else DEFAULT_LID_ACTION


def pair(value: Any, default: int, *, allow_off: bool = True) -> dict[str, int]:
    """Normalize a persisted {ac, battery} timeout pair.

    A missing or malformed side falls back to `default`, same rule
    normalizedSeconds/effectiveSeconds apply in Model.js, so a config
    written by hand, or missing one side entirely, still loads cleanly.
    """
    raw = value if isinstance(value, dict) else {}
    return {
        "ac": seconds(raw.get("ac"), default, allow_off=allow_off),
        "battery": seconds(raw.get("battery"), default, allow_off=allow_off),
    }


def lid_pair(value: Any) -> dict[str, str]:
    raw = value if isinstance(value, dict) else {}
    return {"ac": lid_action(raw.get("ac")), "battery": lid_action(raw.get("battery"))}


def remove_hypr_override(text: str) -> str:
    pattern = re.compile(
        rf"\n?{re.escape(HYPR_OVERRIDE_BEGIN)}.*?{re.escape(HYPR_OVERRIDE_END)}\n?",
        re.DOTALL,
    )
    return pattern.sub("\n", text).rstrip() + ("\n" if text else "")


def sync_hypr_lid_override(action: str) -> None:
    """Install/remove the Hyprland lid binding override for managed actions.

    `action` is the effective action for whichever power state applies right
    now (QML resolves this; see apply_effective), not a stored pair - only
    one side can be "in force" for a static Hyprland keybind at any moment.
    """
    if os.environ.get("POWERPLAN_DISABLE_HYPR_SYNC"):
        return

    path = hypr_bindings_path()
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        original = ""
    except (OSError, UnicodeError):
        return

    without_override = remove_hypr_override(original)
    if action in MANAGED_LID_ACTIONS:
        next_text = without_override.rstrip() + "\n\n" + HYPR_OVERRIDE_BLOCK
    else:
        next_text = without_override

    if next_text == original:
        return

    try:
        atomic_write_text(path, next_text)
    except OSError:
        return

    if os.environ.get("POWERPLAN_SKIP_HYPR_RELOAD") or os.environ.get("POWERPLAN_HYPR_BINDINGS_PATH"):
        return
    try:
        subprocess.run(["hyprctl", "reload"], check=False, capture_output=True, timeout=2)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass


def current_config() -> dict[str, dict[str, int] | dict[str, str]]:
    # shell.json belongs to Omarchy and holds unrelated settings, so it is read
    # strictly. powerplan.json is ours and fully derivable, so a damaged copy
    # may be rebuilt from defaults.
    shell = read_json(shell_path(), {}, strict=True)
    idle = shell.get("idle") if isinstance(shell.get("idle"), dict) else {}
    stored = read_json(config_path(), {})
    shell_screensaver = seconds(idle.get("screensaver"), DEFAULT_SCREENSAVER)
    shell_lock = seconds(idle.get("lock"), DEFAULT_LOCK)

    # A fresh install (no stored screensaver/lock pair yet) seeds both the ac
    # and battery sides from whatever Omarchy's native idle service already
    # has configured, the same continuity a single-value config gave a
    # first-time install. Once a pair exists on disk it is authoritative and
    # shell.json is no longer consulted for these two keys.
    screensaver_default = DEFAULT_SCREENSAVER if "screensaver" in stored else shell_screensaver
    lock_default = DEFAULT_LOCK if "lock" in stored else shell_lock

    return {
        "screensaver": pair(stored.get("screensaver"), screensaver_default),
        "display": pair(stored.get("display"), DEFAULT_DISPLAY),
        "lock": pair(stored.get("lock"), lock_default),
        "sleep": pair(stored.get("sleep"), DEFAULT_SLEEP),
        "hibernate": pair(stored.get("hibernate"), DEFAULT_HIBERNATE),
        "lid": lid_pair(stored.get("lid")),
    }


def initialize() -> dict[str, Any]:
    config = current_config()
    # Always persist the normalized shape so existing installs gain new fields.
    atomic_write(config_path(), config)
    return config


def effective_idle_timeouts(screensaver: int, lock: int) -> tuple[int, int]:
    lock_timeout = lock if lock > 0 else OFF_TIMEOUT
    screensaver_timeout = screensaver if screensaver > 0 else lock_timeout + 1
    return screensaver_timeout, lock_timeout


def apply_idle_config(screensaver: int, lock: int) -> None:
    shell = read_json(shell_path(), {"version": 1}, strict=True)
    idle = shell.get("idle") if isinstance(shell.get("idle"), dict) else {}
    screensaver_timeout, lock_timeout = effective_idle_timeouts(screensaver, lock)
    shell["idle"] = {
        **idle,
        "screensaver": screensaver_timeout,
        "lock": lock_timeout,
    }
    atomic_write(shell_path(), shell)


def rearm_native_idle(screensaver: int, lock: int) -> None:
    """Re-register Omarchy's IdleMonitor after changing its timeout.

    Quickshell currently leaves the old idle notification registered when only
    IdleMonitor.timeout changes. Toggling an enabled service fixes that without
    restarting the shell. Never override an intentional Stay Awake state.
    """
    if os.environ.get("OMARCHY_SHELL_CONFIG_PATH"):
        return

    screensaver_timeout, lock_timeout = effective_idle_timeouts(screensaver, lock)
    for _ in range(20):
        try:
            completed = subprocess.run(
                ["omarchy-shell", "idle", "status"],
                check=True,
                capture_output=True,
                text=True,
                timeout=1,
            )
            status = json.loads(completed.stdout)
        except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError):
            return

        if not status.get("enabled", False):
            return
        if (
            status.get("screensaver") == screensaver_timeout
            and status.get("lock") == lock_timeout
        ):
            try:
                subprocess.run(
                    ["omarchy-shell", "idle", "disable"],
                    check=True,
                    capture_output=True,
                    timeout=1,
                )
                subprocess.run(
                    ["omarchy-shell", "idle", "enable"],
                    check=True,
                    capture_output=True,
                    timeout=1,
                )
            except (FileNotFoundError, subprocess.SubprocessError):
                pass
            return
        time.sleep(0.05)


def apply_effective(screensaver: int, lock: int, lid: str) -> dict[str, Any]:
    """Sync system-wide state to whichever values are effective right now.

    QML is the one thing that reliably knows the current AC/battery state
    moment-to-moment (Quickshell.Services.UPower), so it resolves the
    {ac, battery} pairs down to one value each and calls this instead of
    Python re-deriving the power state itself and racing that signal.
    Called after any setting change, and again on every power-source flip
    even when nothing was stored, since the effective value still changed.
    """
    apply_idle_config(screensaver, lock)
    rearm_native_idle(screensaver, lock)
    sync_hypr_lid_override(lid)
    return {"screensaver": screensaver, "lock": lock, "lid": lid}


def set_screensaver(state: str, value: int) -> dict[str, Any]:
    st = power_state(state)
    config = current_config()
    # Fall back to the default, never to DEFAULT_SLEEP: with allow_off a 0
    # fallback would turn an unusable value into "Off" and silently stand the
    # screen saver down. Only an explicit 0 from the caller means Off.
    config["screensaver"][st] = seconds(value, DEFAULT_SCREENSAVER, allow_off=True)
    atomic_write(config_path(), config)
    return config


def set_lock(state: str, value: int) -> dict[str, Any]:
    st = power_state(state)
    config = current_config()
    # Same reasoning as set_screensaver, and it matters more here: a 0
    # fallback would disable auto-lock on malformed input.
    config["lock"][st] = seconds(value, DEFAULT_LOCK, allow_off=True)
    atomic_write(config_path(), config)
    return config


def set_display(state: str, value: int) -> dict[str, Any]:
    st = power_state(state)
    config = current_config()
    config["display"][st] = seconds(value, DEFAULT_DISPLAY, allow_off=True)
    atomic_write(config_path(), config)
    return config


def set_sleep(state: str, value: int) -> dict[str, Any]:
    st = power_state(state)
    config = current_config()
    config["sleep"][st] = seconds(value, DEFAULT_SLEEP, allow_off=True)
    atomic_write(config_path(), config)
    return config


def set_hibernate(state: str, value: int) -> dict[str, Any]:
    st = power_state(state)
    config = current_config()
    config["hibernate"][st] = seconds(value, DEFAULT_HIBERNATE, allow_off=True)
    atomic_write(config_path(), config)
    return config


def hibernate_diagnostics() -> dict[str, Any]:
    """Report safe, read-only checks for common hibernation prerequisites."""
    issues: list[str] = []

    power_state_path = diagnostic_path("POWERPLAN_POWER_STATE_PATH", "/sys/power/state")
    resume_path = diagnostic_path("POWERPLAN_POWER_RESUME_PATH", "/sys/power/resume")
    swaps_path = diagnostic_path("POWERPLAN_PROC_SWAPS_PATH", "/proc/swaps")
    meminfo_path = diagnostic_path("POWERPLAN_PROC_MEMINFO_PATH", "/proc/meminfo")
    lockdown_path = diagnostic_path(
        "POWERPLAN_LOCKDOWN_PATH", "/sys/kernel/security/lockdown"
    )
    efi_path = diagnostic_path("POWERPLAN_EFI_PATH", "/sys/firmware/efi")

    try:
        kernel_hibernate = "disk" in power_state_path.read_text(encoding="utf-8").split()
    except (OSError, UnicodeError):
        kernel_hibernate = False
    if not kernel_hibernate:
        issues.append("The kernel does not advertise hibernation support.")

    memory_kib = 0
    try:
        for line in meminfo_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                memory_kib = int(line.split()[1])
                break
    except (OSError, UnicodeError, ValueError, IndexError):
        pass

    suitable_swap_kib = 0
    try:
        lines = swaps_path.read_text(encoding="utf-8").splitlines()[1:]
        for line in lines:
            fields = line.split()
            if len(fields) >= 3 and not fields[0].startswith("/dev/zram"):
                suitable_swap_kib += int(fields[2])
    except (OSError, UnicodeError, ValueError):
        pass
    if suitable_swap_kib == 0:
        issues.append(
            "No disk-backed swap is active. Configure a swap file or partition "
            "large enough for hibernation; zram alone cannot store the image."
        )
    elif memory_kib and suitable_swap_kib < memory_kib:
        issues.append(
            "Disk-backed swap is smaller than RAM. Hibernation may need a larger "
            "swap area when memory use is high."
        )

    try:
        resume_value = resume_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        resume_value = ""
    resume_configured = bool(resume_value and resume_value != "0:0")
    efi_available = efi_path.is_dir()
    if not resume_configured and not efi_available:
        issues.append(
            "No kernel resume device is configured and EFI resume discovery is unavailable."
        )

    lockdown_mode = "unknown"
    try:
        lockdown = lockdown_path.read_text(encoding="utf-8")
        selected = re.search(r"\[([^]]+)]", lockdown)
        lockdown_mode = selected.group(1) if selected else lockdown.strip() or "unknown"
    except (OSError, UnicodeError):
        pass
    if lockdown_mode == "confidentiality":
        issues.append("Kernel lockdown confidentiality mode can prevent hibernation.")

    if not issues:
        issues.append(
            "The basic checks passed, but logind still reports hibernation as unavailable. "
            "Check system logs and firmware support."
        )

    return {
        "kernelHibernate": kernel_hibernate,
        "memoryKiB": memory_kib,
        "suitableSwapKiB": suitable_swap_kib,
        "resumeConfigured": resume_configured,
        "efiAvailable": efi_available,
        "lockdownMode": lockdown_mode,
        "issues": issues,
        "summary": " ".join(issues),
    }


def configure_hibernate(value: int) -> None:
    """Set systemd's suspend-then-hibernate delay.

    systemd owns the RTC wake alarm needed while the computer is suspended, so
    this drop-in is necessarily system-wide - one value in force at a time,
    whichever side of the {ac, battery} pair is currently active. The normal
    UI invokes a separately installed, root-owned helper through pkexec. This
    development helper never redirects its privileged write through the
    environment.
    """
    path = systemd_sleep_config_path()
    if os.geteuid() != 0:
        raise ConfigError("administrator authorization is required to change the hibernate delay")
    try:
        if value == 0:
            path.unlink(missing_ok=True)
            return
        atomic_write_text(
            path,
            "[Sleep]\n"
            f"HibernateDelaySec={value}s\n"
            "HibernateOnACPower=yes\n",
        )
    except OSError as error:
        raise ConfigError(f"Could not update {path}: {error}") from error


def set_lid(state: str, value: str) -> dict[str, Any]:
    st = power_state(state)
    config = current_config()
    config["lid"][st] = lid_action(value)
    atomic_write(config_path(), config)
    return config


def timeout(raw: str) -> int:
    """Accept 0 (Off) or a positive timeout no larger than MAX_TIMEOUT.

    Rejecting out-of-range values here keeps a bad number from reaching the
    QML side, where the sleep timer multiplies seconds by 1000 into a 32-bit
    int and would overflow past roughly 24 days.
    """
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a whole number of seconds")
    if value < 0:
        raise argparse.ArgumentTypeError("timeout cannot be negative")
    if value > MAX_TIMEOUT:
        raise argparse.ArgumentTypeError(f"timeout cannot exceed {MAX_TIMEOUT} seconds")
    return value


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("get")
    commands.add_parser("diagnose-hibernate")

    def add_state_timeout(name: str) -> None:
        sub = commands.add_parser(name)
        sub.add_argument("state", choices=POWER_STATES)
        sub.add_argument("seconds", type=timeout)

    add_state_timeout("set-screensaver")
    add_state_timeout("set-display")
    add_state_timeout("set-lock")
    add_state_timeout("set-sleep")
    add_state_timeout("set-hibernate")

    configure_hibernate_parser = commands.add_parser("configure-hibernate")
    configure_hibernate_parser.add_argument("seconds", type=timeout)

    lid = commands.add_parser("set-lid")
    lid.add_argument("state", choices=POWER_STATES)
    lid.add_argument("action", choices=LID_ACTIONS)

    apply_effective_parser = commands.add_parser("apply-effective")
    apply_effective_parser.add_argument("screensaver", type=timeout)
    apply_effective_parser.add_argument("lock", type=timeout)
    apply_effective_parser.add_argument("lid", choices=LID_ACTIONS)

    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "init":
            config = initialize()
        elif args.command == "get":
            config = current_config()
        elif args.command == "diagnose-hibernate":
            config = hibernate_diagnostics()
        elif args.command == "set-screensaver":
            config = set_screensaver(args.state, args.seconds)
        elif args.command == "set-display":
            config = set_display(args.state, args.seconds)
        elif args.command == "set-lock":
            config = set_lock(args.state, args.seconds)
        elif args.command == "set-sleep":
            config = set_sleep(args.state, args.seconds)
        elif args.command == "set-hibernate":
            config = set_hibernate(args.state, args.seconds)
        elif args.command == "configure-hibernate":
            configure_hibernate(args.seconds)
            config = {"hibernate": args.seconds}
        elif args.command == "apply-effective":
            config = apply_effective(args.screensaver, args.lock, args.lid)
        else:
            config = set_lid(args.state, args.action)
    except ConfigError as error:
        print(f"powerplan: {error}", file=sys.stderr)
        return 1
    print(json.dumps(config, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
