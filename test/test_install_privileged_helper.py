import hashlib
import os
import shutil
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = ROOT / "scripts" / "install-privileged-helper"
HELPER_PATH = ROOT / "powerplan-configure-hibernate"


def load_installer():
    """Load the installer, which has no .py extension.

    Compiled from the source text on every call. Importing it instead would
    let a bytecode cache satisfy the load, and a cache holding a superseded
    EXPECTED_SHA256 would make the digest test pass against a pin the file no
    longer carries.
    """
    module = types.ModuleType("install_privileged_helper")
    module.__file__ = str(INSTALLER_PATH)
    source = INSTALLER_PATH.read_text()
    exec(compile(source, str(INSTALLER_PATH), "exec"), module.__dict__)
    return module


class PinnedDigestTest(unittest.TestCase):
    def setUp(self):
        self.installer = load_installer()

    def test_pinned_digest_matches_the_helper(self):
        actual = hashlib.sha256(HELPER_PATH.read_bytes()).hexdigest()
        self.assertEqual(self.installer.EXPECTED_SHA256, actual)

    def test_destination_matches_the_path_the_panel_invokes(self):
        self.assertEqual(
            str(self.installer.DEST),
            "/usr/local/libexec/powerplan-configure-hibernate",
        )


@unittest.skipUnless(
    os.geteuid() == 0,
    "the installer refuses to run unprivileged, so these need root",
)
class InstallVerificationTest(unittest.TestCase):
    def setUp(self):
        self.installer = load_installer()
        destination = tempfile.TemporaryDirectory()
        source = tempfile.TemporaryDirectory()
        self.addCleanup(destination.cleanup)
        self.addCleanup(source.cleanup)
        self.destination_dir = Path(destination.name)
        self.source_dir = Path(source.name)
        self.destination = self.destination_dir / "powerplan-configure-hibernate"

    def run_install(self, *arguments):
        argv = ["-", *arguments]
        with mock.patch.object(self.installer, "DEST", self.destination), \
                mock.patch.object(sys, "argv", argv):
            try:
                return self.installer.main()
            except SystemExit as exit_signal:
                return exit_signal.code

    def reviewed_source(self):
        source = self.source_dir / "powerplan-configure-hibernate"
        shutil.copy(HELPER_PATH, source)
        os.chmod(source, 0o755)
        return source

    def staging_files(self):
        return [
            entry.name
            for entry in self.destination_dir.iterdir()
            if "staging" in entry.name
        ]

    def test_installs_the_reviewed_helper(self):
        self.assertEqual(self.run_install(str(self.reviewed_source())), 0)
        self.assertTrue(self.destination.exists())
        installed = hashlib.sha256(self.destination.read_bytes()).hexdigest()
        self.assertEqual(installed, self.installer.EXPECTED_SHA256)

    def test_installs_root_owned_and_executable(self):
        self.run_install(str(self.reviewed_source()))
        info = os.stat(self.destination)
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o755)
        self.assertEqual((info.st_uid, info.st_gid), (0, 0))

    def test_leaves_no_staging_file_after_a_successful_install(self):
        self.run_install(str(self.reviewed_source()))
        self.assertEqual(self.staging_files(), [])

    def test_rejects_a_tampered_source(self):
        source = self.source_dir / "powerplan-configure-hibernate"
        source.write_bytes(HELPER_PATH.read_bytes() + b"\nprint('extra')\n")
        os.chmod(source, 0o755)
        self.assertEqual(self.run_install(str(source)), 1)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.staging_files(), [])

    def test_rejects_a_symlinked_source(self):
        link = self.source_dir / "link"
        link.symlink_to(HELPER_PATH)
        self.assertEqual(self.run_install(str(link)), 1)
        self.assertFalse(self.destination.exists())

    def test_rejects_a_world_writable_source(self):
        source = self.reviewed_source()
        os.chmod(source, 0o777)
        self.assertEqual(self.run_install(str(source)), 1)
        self.assertFalse(self.destination.exists())

    def test_rejects_a_directory_source(self):
        directory = self.source_dir / "directory"
        directory.mkdir()
        self.assertEqual(self.run_install(str(directory)), 1)

    def test_rejects_a_missing_source(self):
        self.assertEqual(self.run_install("/nonexistent/helper"), 1)

    def test_rejects_a_wrong_argument_count(self):
        self.assertEqual(self.run_install(), 1)
        self.assertEqual(self.run_install("first", "second"), 1)

    def test_removes_staging_when_the_written_copy_fails_verification(self):
        source = self.reviewed_source()
        digests = [self.installer.EXPECTED_SHA256, "0" * 64]

        class SequencedDigest:
            def hexdigest(self):
                return digests.pop(0) if digests else "0" * 64

        with mock.patch.object(
            self.installer.hashlib, "sha256", lambda data=b"": SequencedDigest()
        ):
            status = self.run_install(str(source))

        self.assertEqual(status, 1)
        self.assertEqual(self.staging_files(), [])
        self.assertFalse(self.destination.exists())

    def test_replaces_an_existing_destination(self):
        self.destination.write_text("superseded\n")
        self.assertEqual(self.run_install(str(self.reviewed_source())), 0)
        installed = hashlib.sha256(self.destination.read_bytes()).hexdigest()
        self.assertEqual(installed, self.installer.EXPECTED_SHA256)


if __name__ == "__main__":
    unittest.main()
