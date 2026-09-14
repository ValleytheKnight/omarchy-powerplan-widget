import base64
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-privileged-helper"
RELEASE_DIR = ROOT / "packaging" / "release"
PACKAGE = RELEASE_DIR / "omarchy-powerplan-helper.pkg.tar.zst"
SIGNATURE = RELEASE_DIR / "omarchy-powerplan-helper.pkg.tar.zst.sig"


def load_installer():
    """Import the installer, which has no .py extension."""
    loader = importlib.machinery.SourceFileLoader(
        "install_privileged_helper", str(INSTALLER)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def make_scratch_release(checkout, pkg_bytes=b"fake package bytes", sig_bytes=b"fake sig bytes"):
    release = checkout / "packaging" / "release"
    release.mkdir(parents=True)
    (release / "omarchy-powerplan-helper.pkg.tar.zst").write_bytes(pkg_bytes)
    (release / "omarchy-powerplan-helper.pkg.tar.zst.sig").write_bytes(sig_bytes)


class InstallerShebangTest(unittest.TestCase):
    """Runs the installer via its own shebang, the way a user actually
    invokes it, not via `python3 <path>`. This is the invocation mode
    prior review rounds found had zero coverage, which is exactly the
    mode a PATH-resolved interpreter or a decoy-module shadow would
    only show up in."""

    def setUp(self):
        self.checkout = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.checkout, ignore_errors=True)
        (self.checkout / "scripts").mkdir()
        shutil.copy(INSTALLER, self.checkout / "scripts" / "install-privileged-helper")
        os.chmod(self.checkout / "scripts" / "install-privileged-helper", 0o755)
        make_scratch_release(self.checkout)

        self.fakebin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.fakebin, ignore_errors=True)
        pkexec = self.fakebin / "pkexec"
        pkexec.write_text("#!/bin/sh\necho PKEXEC_RAN\nexit 0\n")
        pkexec.chmod(0o755)

    def test_shebang_is_pinned_absolute_interpreter(self):
        source = INSTALLER.read_text()
        first_line = source.splitlines()[0]
        self.assertEqual(first_line, "#!/usr/bin/python3 -I")
        self.assertNotIn("env", first_line)

    def test_direct_exec_rejects_tampered_release_and_never_reaches_pkexec(self):
        (self.checkout / "packaging" / "release" / "omarchy-powerplan-helper.pkg.tar.zst.sig").write_bytes(b"")
        env = dict(os.environ)
        env["PATH"] = f"{self.fakebin}:{env.get('PATH', '')}"
        result = subprocess.run(
            [str(self.checkout / "scripts" / "install-privileged-helper")],
            cwd=self.checkout,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        # This exec happens against whatever /usr/bin/pkexec this machine
        # actually has (PKEXEC is a pinned absolute path, not resolved
        # through fakebin on PATH). A box without pkexec/polkit installed
        # bails out earlier with a different message; either way, the
        # tampered signature must never reach the elevated install step.
        self.assertTrue(
            "missing or empty" in result.stderr or "not found" in result.stderr,
            result.stderr,
        )
        self.assertNotIn("PKEXEC_RAN", result.stdout)

    def test_direct_exec_isolated_mode_ignores_decoy_module(self):
        # A same-uid decoy module in scripts/ must not get imported ahead
        # of the real stdlib module of the same name when run via the
        # shebang, since that's the whole point of `-I`.
        (self.checkout / "scripts" / "base64.py").write_text(
            "def b64encode(_):\n    raise AssertionError('decoy module was imported')\n"
        )
        env = dict(os.environ)
        env["PATH"] = f"{self.fakebin}:{env.get('PATH', '')}"
        result = subprocess.run(
            [str(self.checkout / "scripts" / "install-privileged-helper")],
            cwd=self.checkout,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotIn("decoy module was imported", result.stderr)


class InstallerUnprivilegedUnitTest(unittest.TestCase):
    """Exercises main() in-process with subprocess.run mocked, so no real
    pkexec/polkit call is ever made, against a scratch release dir."""

    def setUp(self):
        self.module = load_installer()
        self.checkout = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.checkout, ignore_errors=True)
        make_scratch_release(self.checkout)
        self.repo_root_patch = mock.patch.object(
            self.module, "repo_root", return_value=str(self.checkout)
        )
        self.repo_root_patch.start()
        self.addCleanup(self.repo_root_patch.stop)

        # PKEXEC/SH are pinned absolute paths by design (see module
        # docstring); this class mocks subprocess.run so no real pkexec
        # call happens, but the presence check ahead of it must not
        # depend on whether this machine actually has pkexec installed.
        real_isfile = os.path.isfile

        def fake_isfile(path):
            if path in (self.module.PKEXEC, self.module.SH):
                return True
            return real_isfile(path)

        self.isfile_patch = mock.patch("os.path.isfile", side_effect=fake_isfile)
        self.isfile_patch.start()
        self.addCleanup(self.isfile_patch.stop)

    def release_file(self, name):
        return self.checkout / "packaging" / "release" / name

    def test_success_path_invokes_pkexec_by_absolute_path_only(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with mock.patch.object(sys, "argv", [str(INSTALLER)]), \
             mock.patch("os.geteuid", return_value=1000), \
             mock.patch("subprocess.run", return_value=completed) as run:
            self.module.main()

        run.assert_called_once()
        (call_args,), call_kwargs = run.call_args
        self.assertEqual(call_args[0], "/usr/bin/pkexec")
        self.assertEqual(call_args[1], "/usr/bin/sh")
        self.assertEqual(call_args[2], "-c")
        command = call_args[3]

        self.assertNotIn(str(self.checkout), command)
        self.assertIn("mktemp -d", command)
        self.assertIn("pacman-key --verify", command)
        self.assertIn("pacman -U --noconfirm", command)

        expected_pkg = self.release_file("omarchy-powerplan-helper.pkg.tar.zst").read_bytes()
        self.assertEqual(call_kwargs["input"], expected_pkg)

        expected_sig_b64 = base64.b64encode(
            self.release_file("omarchy-powerplan-helper.pkg.tar.zst.sig").read_bytes()
        ).decode("ascii")
        self.assertIn(expected_sig_b64, command)

    @unittest.skipUnless(shutil.which("gpg"), "gpg not available")
    def test_install_command_semantics_reject_tampered_or_truncated_input(self):
        """Actually executes the constructed one-liner (unprivileged, with
        `pacman-key --verify` swapped for a plain `gpg --verify` against a
        throwaway key generated just for this test, and `pacman -U`
        swapped for an inert marker) to prove the staging, base64
        round-trip, and set -e error propagation genuinely reject bad
        input, not just that the command contains the right substrings."""
        gnupghome = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, gnupghome, ignore_errors=True)
        env = dict(os.environ, GNUPGHOME=str(gnupghome))

        subprocess.run(
            ["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
             "--quick-generate-key", "test <test@example.invalid>", "ed25519", "sign", "0"],
            env=env, check=True, capture_output=True,
        )
        fpr = subprocess.run(
            ["gpg", "--list-secret-keys", "--with-colons"], env=env,
            check=True, capture_output=True, text=True,
        ).stdout
        fpr = next(line.split(":")[9] for line in fpr.splitlines() if line.startswith("fpr:"))

        pkg_bytes = os.urandom(4096)
        pkg = self.release_file("omarchy-powerplan-helper.pkg.tar.zst")
        pkg.write_bytes(pkg_bytes)
        sig = self.release_file("omarchy-powerplan-helper.pkg.tar.zst.sig")
        subprocess.run(
            ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback", "--passphrase", "",
             "--local-user", fpr, "--detach-sign", "-o", str(sig), str(pkg)],
            env=env, check=True, capture_output=True,
        )

        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with mock.patch.object(sys, "argv", [str(INSTALLER)]), \
             mock.patch("os.geteuid", return_value=1000), \
             mock.patch("subprocess.run", return_value=completed) as run:
            self.module.main()
        command = run.call_args[0][0][3]
        sent_bytes = run.call_args[1]["input"]
        self.assertEqual(sent_bytes, pkg_bytes)

        test_command = command.replace(
            "pacman-key --verify", f'gpg --batch --homedir "{gnupghome}" --verify'
        ).replace('pacman -U --noconfirm "$STAGE/pkg.tar.zst"', "echo INSTALLED")

        def run_one_liner(data):
            return subprocess.run(
                ["/usr/bin/sh", "-c", test_command], input=data,
                capture_output=True, env=env,
            )

        good = run_one_liner(sent_bytes)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertIn(b"INSTALLED", good.stdout)

        tampered = bytes([sent_bytes[0] ^ 0xFF]) + sent_bytes[1:]
        bad = run_one_liner(tampered)
        self.assertNotEqual(bad.returncode, 0)
        self.assertNotIn(b"INSTALLED", bad.stdout)

        truncated = sent_bytes[: len(sent_bytes) // 2]
        bad = run_one_liner(truncated)
        self.assertNotEqual(bad.returncode, 0)
        self.assertNotIn(b"INSTALLED", bad.stdout)

    def test_refuses_to_run_as_root(self):
        with mock.patch.object(sys, "argv", [str(INSTALLER)]), \
             mock.patch("os.geteuid", return_value=0), \
             self.assertRaises(SystemExit) as ctx:
            self.module.main()
        self.assertEqual(ctx.exception.code, 1)

    def test_rejects_extra_argv(self):
        with mock.patch.object(sys, "argv", [str(INSTALLER), "extra"]), \
             mock.patch("os.geteuid", return_value=1000), \
             self.assertRaises(SystemExit) as ctx:
            self.module.main()
        self.assertEqual(ctx.exception.code, 1)

    def test_rejects_missing_signature(self):
        self.release_file("omarchy-powerplan-helper.pkg.tar.zst.sig").unlink()
        with mock.patch.object(sys, "argv", [str(INSTALLER)]), \
             mock.patch("os.geteuid", return_value=1000), \
             self.assertRaises(SystemExit) as ctx, \
             mock.patch("subprocess.run") as run:
            self.module.main()
        self.assertEqual(ctx.exception.code, 1)
        run.assert_not_called()

    def test_rejects_empty_signature(self):
        self.release_file("omarchy-powerplan-helper.pkg.tar.zst.sig").write_bytes(b"")
        with mock.patch.object(sys, "argv", [str(INSTALLER)]), \
             mock.patch("os.geteuid", return_value=1000), \
             self.assertRaises(SystemExit) as ctx, \
             mock.patch("subprocess.run") as run:
            self.module.main()
        self.assertEqual(ctx.exception.code, 1)
        run.assert_not_called()

    def test_rejects_symlinked_package(self):
        pkg = self.release_file("omarchy-powerplan-helper.pkg.tar.zst")
        pkg.unlink()
        pkg.symlink_to("/etc/passwd")
        with mock.patch.object(sys, "argv", [str(INSTALLER)]), \
             mock.patch("os.geteuid", return_value=1000), \
             self.assertRaises(SystemExit) as ctx, \
             mock.patch("subprocess.run") as run:
            self.module.main()
        self.assertEqual(ctx.exception.code, 1)
        run.assert_not_called()

    def test_rejects_group_writable_package(self):
        pkg = self.release_file("omarchy-powerplan-helper.pkg.tar.zst")
        os.chmod(pkg, 0o664)
        with mock.patch.object(sys, "argv", [str(INSTALLER)]), \
             mock.patch("os.geteuid", return_value=1000), \
             self.assertRaises(SystemExit) as ctx, \
             mock.patch("subprocess.run") as run:
            self.module.main()
        self.assertEqual(ctx.exception.code, 1)
        run.assert_not_called()

    def test_exit_code_126_reports_cancelled(self):
        completed = subprocess.CompletedProcess(args=[], returncode=126)
        with mock.patch.object(sys, "argv", [str(INSTALLER)]), \
             mock.patch("os.geteuid", return_value=1000), \
             mock.patch("subprocess.run", return_value=completed), \
             self.assertRaises(SystemExit), \
             mock.patch("builtins.print") as p:
            self.module.main()
        messages = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("cancelled or denied", messages)

    def test_exit_code_127_does_not_claim_binary_missing(self):
        completed = subprocess.CompletedProcess(args=[], returncode=127)
        with mock.patch.object(sys, "argv", [str(INSTALLER)]), \
             mock.patch("os.geteuid", return_value=1000), \
             mock.patch("subprocess.run", return_value=completed), \
             self.assertRaises(SystemExit), \
             mock.patch("builtins.print") as p:
            self.module.main()
        messages = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("not authorized", messages)
        self.assertNotIn("could not find", messages)

    def test_constants_are_absolute_paths(self):
        self.assertEqual(self.module.PKEXEC, "/usr/bin/pkexec")
        self.assertEqual(self.module.SH, "/usr/bin/sh")


if __name__ == "__main__":
    unittest.main()
