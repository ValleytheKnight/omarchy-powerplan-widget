import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "powerplan.py"


def full_config(**overrides):
    base = {
        "screensaver": {"ac": 150, "battery": 150},
        "display": {"ac": 0, "battery": 0},
        "lock": {"ac": 300, "battery": 300},
        "sleep": {"ac": 0, "battery": 0},
        "hibernate": {"ac": 0, "battery": 0},
        "lid": {"ac": "system", "battery": "system"},
    }
    base.update(overrides)
    return base


class PowerPlanHelperTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.shell = base / "shell.json"
        self.config = base / "powerplan.json"
        self.hypr_bindings = base / "bindings.lua"
        self.systemd_sleep_config = base / "90-powerplan.conf"
        self.power_state = base / "power-state"
        self.power_resume = base / "power-resume"
        self.proc_swaps = base / "proc-swaps"
        self.proc_meminfo = base / "proc-meminfo"
        self.lockdown = base / "lockdown"
        self.efi = base / "efi"
        self.power_state.write_text("freeze mem disk\n", encoding="utf-8")
        self.power_resume.write_text("0:0\n", encoding="utf-8")
        self.proc_swaps.write_text("Filename Type Size Used Priority\n", encoding="utf-8")
        self.proc_meminfo.write_text("MemTotal: 8388608 kB\n", encoding="utf-8")
        self.lockdown.write_text("[none] integrity confidentiality\n", encoding="utf-8")
        self.efi.mkdir()
        self.hypr_bindings.write_text("-- user bindings\n", encoding="utf-8")
        self.shell.write_text(
            json.dumps({"version": 1, "idle": {"screensaver": 150, "lock": 300}, "unrelated": True}),
            encoding="utf-8",
        )
        self.environment = {
            **os.environ,
            "OMARCHY_SHELL_CONFIG_PATH": str(self.shell),
            "POWERPLAN_CONFIG_PATH": str(self.config),
            "POWERPLAN_HYPR_BINDINGS_PATH": str(self.hypr_bindings),
            "POWERPLAN_SYSTEMD_SLEEP_CONFIG_PATH": str(self.systemd_sleep_config),
            "POWERPLAN_POWER_STATE_PATH": str(self.power_state),
            "POWERPLAN_POWER_RESUME_PATH": str(self.power_resume),
            "POWERPLAN_PROC_SWAPS_PATH": str(self.proc_swaps),
            "POWERPLAN_PROC_MEMINFO_PATH": str(self.proc_meminfo),
            "POWERPLAN_LOCKDOWN_PATH": str(self.lockdown),
            "POWERPLAN_EFI_PATH": str(self.efi),
            "POWERPLAN_SKIP_HYPR_RELOAD": "1",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def run_helper(self, *arguments):
        completed = subprocess.run(
            ["python3", str(HELPER), *arguments],
            env=self.environment,
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(completed.stdout)

    def run_helper_expecting_failure(self, *arguments):
        completed = subprocess.run(
            ["python3", str(HELPER), *arguments],
            env=self.environment,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        return completed

    def test_init_inherits_omarchy_idle_settings_on_both_sides(self):
        expected = full_config()
        self.assertEqual(self.run_helper("init"), expected)
        self.assertEqual(json.loads(self.config.read_text()), expected)

    def test_init_migrates_existing_config_to_include_new_fields(self):
        self.config.write_text(
            json.dumps({"screensaver": {"ac": 150, "battery": 60}, "sleep": {"ac": 3600, "battery": 900}}),
            encoding="utf-8",
        )

        expected = full_config(
            screensaver={"ac": 150, "battery": 60},
            sleep={"ac": 3600, "battery": 900},
        )
        self.assertEqual(self.run_helper("init"), expected)
        self.assertEqual(json.loads(self.config.read_text()), expected)

    def test_set_screensaver_only_changes_the_given_side(self):
        self.run_helper("init")
        self.assertEqual(
            self.run_helper("set-screensaver", "ac", "600"),
            full_config(screensaver={"ac": 600, "battery": 150}),
        )
        self.assertEqual(
            self.run_helper("set-screensaver", "battery", "60"),
            full_config(screensaver={"ac": 600, "battery": 60}),
        )

    def test_set_screensaver_does_not_touch_shell_json(self):
        # Persistence and system-state sync are now separate steps; QML
        # calls apply-effective itself after a successful set-*.
        self.run_helper("init")
        before = self.shell.read_text()
        self.run_helper("set-screensaver", "ac", "600")
        self.assertEqual(self.shell.read_text(), before)

    def test_lock_only_changes_the_given_side(self):
        self.run_helper("init")
        self.assertEqual(
            self.run_helper("set-lock", "battery", "900"),
            full_config(lock={"ac": 300, "battery": 900}),
        )

    def test_off_is_accepted_on_either_side(self):
        self.run_helper("init")
        self.run_helper("set-lock", "ac", "0")
        self.assertEqual(
            self.run_helper("set-screensaver", "battery", "0"),
            full_config(lock={"ac": 0, "battery": 300}, screensaver={"ac": 150, "battery": 0}),
        )

    def test_apply_effective_writes_shell_json_and_hypr_override(self):
        self.run_helper("init")
        self.assertEqual(
            self.run_helper("apply-effective", "600", "0", "display"),
            {"screensaver": 600, "lock": 0, "lid": "display"},
        )
        shell = json.loads(self.shell.read_text())
        self.assertEqual(shell["idle"], {"screensaver": 600, "lock": 604800})
        self.assertTrue(shell["unrelated"])
        bindings = self.hypr_bindings.read_text(encoding="utf-8")
        self.assertIn("BEGIN Power Plan lid action override", bindings)

    def test_apply_effective_removes_override_for_system_lid_action(self):
        self.run_helper("init")
        self.run_helper("apply-effective", "150", "300", "display")
        self.assertIn(
            "BEGIN Power Plan lid action override",
            self.hypr_bindings.read_text(encoding="utf-8"),
        )

        self.run_helper("apply-effective", "150", "300", "system")

        bindings = self.hypr_bindings.read_text(encoding="utf-8")
        self.assertNotIn("BEGIN Power Plan lid action override", bindings)
        self.assertEqual(bindings, "-- user bindings\n")

    def test_sleep_only_changes_powerplan_state(self):
        self.run_helper("init")
        before = self.shell.read_text()
        self.assertEqual(
            self.run_helper("set-sleep", "ac", "3600"),
            full_config(sleep={"ac": 3600, "battery": 0}),
        )
        self.assertEqual(self.shell.read_text(), before)

    def test_hibernate_diagnostics_explain_missing_disk_backed_swap(self):
        result = self.run_helper("diagnose-hibernate")

        self.assertTrue(result["kernelHibernate"])
        self.assertEqual(result["suitableSwapKiB"], 0)
        self.assertTrue(result["efiAvailable"])
        self.assertIn("No disk-backed swap is active", result["summary"])

    def test_hibernate_diagnostics_report_kernel_resume_and_lockdown_issues(self):
        self.power_state.write_text("freeze mem\n", encoding="utf-8")
        self.efi.rmdir()
        self.lockdown.write_text("none integrity [confidentiality]\n", encoding="utf-8")
        self.proc_swaps.write_text(
            "Filename Type Size Used Priority\n/dev/sda2 partition 16777216 0 -2\n",
            encoding="utf-8",
        )

        result = self.run_helper("diagnose-hibernate")

        self.assertFalse(result["kernelHibernate"])
        self.assertIn("kernel does not advertise", result["summary"])
        self.assertIn("No kernel resume device", result["summary"])
        self.assertIn("lockdown confidentiality", result["summary"])

    def test_hibernate_delay_changes_powerplan_state_only(self):
        self.run_helper("init")
        before = self.shell.read_text()
        self.assertEqual(
            self.run_helper("set-hibernate", "ac", "7200"),
            full_config(hibernate={"ac": 7200, "battery": 0}),
        )
        self.assertEqual(self.shell.read_text(), before)

    def test_configure_hibernate_writes_and_removes_systemd_dropin(self):
        completed = self.run_helper_expecting_failure("configure-hibernate", "7200")
        self.assertIn("administrator authorization is required", completed.stderr)
        self.assertFalse(self.systemd_sleep_config.exists())

    def test_display_only_changes_powerplan_state(self):
        self.run_helper("init")
        before = self.shell.read_text()
        self.assertEqual(
            self.run_helper("set-display", "ac", "300"),
            full_config(display={"ac": 300, "battery": 0}),
        )
        self.assertEqual(self.shell.read_text(), before)

    def test_set_lid_only_changes_the_given_side_and_does_not_touch_hypr(self):
        self.run_helper("init")
        before = self.hypr_bindings.read_text(encoding="utf-8")
        self.assertEqual(
            self.run_helper("set-lid", "battery", "display"),
            full_config(lid={"ac": "system", "battery": "display"}),
        )
        # set-lid only persists now; apply-effective is what touches Hyprland.
        self.assertEqual(self.hypr_bindings.read_text(encoding="utf-8"), before)

    def test_invalid_lid_action_is_rejected(self):
        self.run_helper("init")
        self.run_helper_expecting_failure("set-lid", "ac", "poweroff")
        self.assertEqual(json.loads(self.config.read_text())["lid"]["ac"], "system")

    def test_invalid_power_state_falls_back_to_ac(self):
        self.run_helper("init")
        self.run_helper_expecting_failure("set-lock", "laptop-only", "900")

    def test_invalid_utf8_shell_config_reports_cleanly_and_is_left_intact(self):
        self.run_helper("init")
        damaged = b'{"version": 1, "idle": {"lock": 300}, "x": "\xff\xfe"}'
        self.shell.write_bytes(damaged)

        completed = self.run_helper_expecting_failure("apply-effective", "150", "900", "system")

        # A controlled message, not a UnicodeDecodeError traceback.
        self.assertIn("powerplan:", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)
        self.assertEqual(self.shell.read_bytes(), damaged)

    def test_oversized_persisted_value_is_bounded(self):
        self.config.write_text(
            json.dumps({
                "screensaver": {"ac": 150, "battery": 150},
                "lock": {"ac": 300, "battery": 300},
                "sleep": {"ac": 2000000000, "battery": 2000000000},
            }),
            encoding="utf-8",
        )

        result = self.run_helper("init")

        # Must stay under the 32-bit limit of sleepDelaySeconds * 1000.
        self.assertEqual(result["sleep"]["ac"], 7 * 24 * 60 * 60)
        self.assertLess(result["sleep"]["ac"] * 1000, 2**31 - 1)
        self.assertEqual(json.loads(self.config.read_text())["sleep"]["ac"], 7 * 24 * 60 * 60)

    def test_malformed_shell_config_is_left_intact(self):
        self.run_helper("init")
        damaged = '{"version": 1, "idle": {"lock": 300}, "bar": {"position": "top"},}'
        self.shell.write_text(damaged, encoding="utf-8")

        self.run_helper_expecting_failure("apply-effective", "150", "900", "system")

        self.assertEqual(self.shell.read_text(encoding="utf-8"), damaged)

    def test_unreadable_shell_config_is_left_intact(self):
        self.run_helper("init")
        original = self.shell.read_text(encoding="utf-8")
        self.shell.chmod(0o000)
        try:
            self.run_helper_expecting_failure("apply-effective", "150", "900", "system")
        finally:
            self.shell.chmod(0o644)

        self.assertEqual(self.shell.read_text(encoding="utf-8"), original)

    def test_negative_timeout_is_rejected_rather_than_disabling_lock(self):
        self.run_helper("init")

        self.run_helper_expecting_failure("set-lock", "ac", "-5")

        self.assertEqual(json.loads(self.config.read_text())["lock"]["ac"], 300)

    def test_absurd_timeout_is_rejected(self):
        self.run_helper("init")

        self.run_helper_expecting_failure("set-sleep", "ac", "2000000000")

        self.assertEqual(json.loads(self.config.read_text())["sleep"]["ac"], 0)

    def test_missing_shell_config_still_initializes(self):
        self.shell.unlink()
        self.assertEqual(self.run_helper("init"), full_config())

    def test_damaged_powerplan_config_is_rebuilt_from_shell(self):
        self.config.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.run_helper("init"), full_config())


if __name__ == "__main__":
    unittest.main()
