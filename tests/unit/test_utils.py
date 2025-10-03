# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for utils."""

import shutil
import tempfile
import unittest

import utils


class TestLibUtils(unittest.TestCase):
    """Test cases for Utils."""

    def setUp(self):
        """Set up method for the tests."""
        self.tmpdir = tempfile.mkdtemp(prefix="charm-unittests-")
        self.addCleanup(shutil.rmtree, self.tmpdir)

    def test_logrotate_frequency(self):
        """Test log rotate frequency is updated."""
        with open("tests/unit/files/logrotate_frequency", "r", encoding="utf-8") as f:
            want = f.read()
        self.assertEqual(
            utils.update_logrotate_conf("tests/unit/files/logrotate", frequency="daily"), want
        )

    def test_logrotate_non_exists(self):
        """Test update log rotate with a non existent file returns empty string."""
        self.assertEqual(
            utils.update_logrotate_conf(
                "tests/unit/files/logrotate_file_does_not_exist", frequency="daily"
            ),
            "",
        )

    def test_logrotate_retention(self):
        """Test update log rotate retention is correctly updated."""
        with open("tests/unit/files/logrotate_retention", "r", encoding="utf-8") as f:
            want = f.read()
        self.assertEqual(
            utils.update_logrotate_conf("tests/unit/files/logrotate", retention=30), want
        )

    def test_logrotate_retention_no_dateext(self):
        """Test update log rotate retention without dateext."""
        with open("tests/unit/files/logrotate_retention_no_dateext", "r", encoding="utf-8") as f:
            want = f.read()
        self.assertEqual(
            utils.update_logrotate_conf("tests/unit/files/logrotate", retention=30, dateext=False),
            want,
        )

        with open("tests/unit/files/logrotate_retention_no_dateext", "r", encoding="utf-8") as f:
            want = f.read()
        self.assertEqual(
            utils.update_logrotate_conf(
                "tests/unit/files/logrotate_retention", retention=30, dateext=False
            ),
            want,
        )
