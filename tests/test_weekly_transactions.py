"""Check journal recovery using disposable project folders."""

from base64 import b64encode
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "weekflow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from weekflow_tool.storage import ProjectFiles, Refusal, WEEKLY
from weekflow_tool import lock_transaction as transaction


WEEK = WEEKLY / "weeks/week-3.json"
CHANGES = WEEKLY / "changes.json"
PROMISES = WEEKLY / "promises.json"
PAGE = WEEKLY / "pages/week-3.html"


class WeeklyTransactions(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.files = ProjectFiles(scratch.name)
        self.files.write_text(WEEK, "draft")
        self.files.write_text(CHANGES, "waiting")
        self.files.write_text(PAGE, "old page")

    def test_interrupted_multi_file_write_restores_originals_on_next_command(self):
        crash = """
import os
import sys
sys.path.insert(0, sys.argv[1])
from weekflow_tool.lock_transaction import write_transaction
from weekflow_tool.storage import ProjectFiles, WEEKLY
replace = os.replace

def interrupt(source, destination):
    replace(source, destination)
    if destination.name == 'promises.json':
        os._exit(91)

os.replace = interrupt
write_transaction(ProjectFiles(sys.argv[2]), [
    (WEEKLY / 'weeks/week-3.json', 'locked'),
    (WEEKLY / 'changes.json', 'decided'),
    (WEEKLY / 'promises.json', 'open'),
], retire=(WEEKLY / 'pages/week-3.html',))
"""
        result = subprocess.run([sys.executable, "-B", "-c", crash, str(SCRIPTS),
                                 str(self.files.root)], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 91, result.stderr.decode())
        self.assertEqual(self.files.read_text(PROMISES), "open")
        self.assertIsNone(self.files.read_text(PAGE, optional=True))

        transaction.recover_transactions(self.files)
        self.assertEqual(self.files.read_text(WEEK), "draft")
        self.assertEqual(self.files.read_text(CHANGES), "waiting")
        self.assertEqual(self.files.read_text(PAGE), "old page")
        self.assertIsNone(self.files.read_text(PROMISES, optional=True))
        self.assertFalse(self.files.path(transaction.UNDO_FILE).exists())

        transaction.write_transaction(self.files, [(WEEK, "locked"), (PROMISES, "open")],
                                      retire=(PAGE,))
        self.assertEqual(self.files.read_text(WEEK), "locked")
        self.assertEqual(self.files.read_text(PROMISES), "open")
        self.assertIsNone(self.files.read_text(PAGE, optional=True))

    def test_prior_two_file_lock_journal_still_recovers(self):
        self.files.write_json(WEEKLY / ".weekflow-lock.json", {
            "number": 3,
            "week": b64encode(b"earlier week").decode("ascii"),
            "changes": b64encode(b"earlier changes").decode("ascii"),
        })
        transaction.recover_transactions(self.files)
        self.assertEqual(self.files.read_text(WEEK), "earlier week")
        self.assertEqual(self.files.read_text(CHANGES), "earlier changes")
        self.assertFalse(self.files.path(WEEKLY / ".weekflow-lock.json").exists())

    def test_redaction_undo_data_is_never_staged_and_recovery_publishes_only_new_bytes(self):
        publish = transaction.publish_redaction_entry
        with patch.object(transaction, "publish_redaction_entry", side_effect=OSError):
            with self.assertRaises(OSError):
                transaction.write_redaction(self.files, [(WEEK, "removed")], retire=(PAGE,), weeks=[3])
        journal = self.files.read_text(transaction.REDACTION_FILE)
        for original in (b"draft", b"old page"):
            self.assertNotIn(b64encode(original).decode("ascii"), journal)
        with patch.object(transaction, "publish_redaction_entry", wraps=publish) as replay:
            self.assertEqual(transaction.recover_transactions(self.files).weeks, [3])
        self.assertEqual(replay.call_count, 2)
        self.assertEqual(self.files.read_text(WEEK), "removed")
        self.assertIsNone(self.files.read_text(PAGE, optional=True))
        self.assertFalse(self.files.path(transaction.REDACTION_FILE).exists())

    def test_a_journal_cannot_write_an_unrelated_weekly_file(self):
        self.files.write_json(transaction.UNDO_FILE, [{"path": "docs/weekly/other.txt", "data": None}])
        with self.assertRaises(Refusal):
            transaction.recover_transactions(self.files)
        self.assertEqual(self.files.read_text(WEEK), "draft")
