"""Keep the README's paths and sample commands aligned with weekflow."""

from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

from test_weekflow import ROOT, TOOL

sys.path.insert(0, str(TOOL.parent))

from weekflow_tool.changes import CHANGES
from weekflow_tool.corrections import CORRECTIONS
from weekflow_tool.meetings import content_file, page_file, pdf_file, week_file
from weekflow_tool.promises import PROMISES
from weekflow_tool.screens import SCREENS_FILE
from weekflow_tool.setup import PROJECT_FILE


def table_keys(section):
    return set(re.findall(r"(?m)^\|\s*`([^`]+)`\s*\|", section))


def code_blocks(section, language):
    return re.findall(rf"(?m)^```{language}\n(.*?)^```$", section, re.DOTALL)


class GuideTests(unittest.TestCase):
    def run_tool(self, *args):
        result = subprocess.run(
            [sys.executable, str(TOOL), *args], capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def example(self, section, language):
        matches = code_blocks(section, language)
        self.assertEqual(len(matches), 1, f"Expected one {language} sample in the README")
        return matches[0]

    def test_readme_names_real_files_and_runs_the_sample(self):
        guide = (ROOT / "README.md").read_text(encoding="utf-8")
        outputs = guide.partition("\n## What you get\n")[2].partition("\n## ")[0]
        paths = (page_file(1), pdf_file(1), content_file(1), week_file(1), PROJECT_FILE,
                 CHANGES, PROMISES, SCREENS_FILE, CORRECTIONS)
        expected = {Path(path).as_posix().replace("/week-1", "/week-<number>") for path in paths}
        self.assertEqual(table_keys(outputs), expected)

        help_text = self.run_tool("--help")
        choices = re.search(r"\{([^}]+)\}", help_text)
        self.assertIsNotNone(choices, help_text)
        use = guide.partition("\n## Use it\n")[2].partition("\n## ")[0]
        commands = table_keys(use)
        self.assertSetEqual(commands, set(choices[1].split(",")), "List every CLI command in Use it")

        sample = use.partition("\n### Try it first\n")[2]
        prd = self.example(sample, "markdown")
        menu = self.example(sample, "text")
        draft = self.example(sample, "json")
        page = page_file(1)
        page_paths = set(re.findall(r"`(docs/weekly/pages/[^`]+\.html)`", sample))
        self.assertEqual(page_paths, {page.as_posix()}, "The sample should name the first meeting page")

        # Run the documented arguments through Python so the check needs neither shell.
        for shell, launcher, target in (
            ("sh", "python3", "$weekflow_target"),
            ("powershell", "py -3", "$weekflowTarget"),
        ):
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as scratch:
                script_text = "\n".join(code_blocks(sample, shell))
                lines = script_text.splitlines()
                calls = [shlex.split(line[len(launcher) + 1:].removesuffix(" &&")) for line in lines
                         if line.startswith(launcher + " ")]
                self.assertEqual(len(calls), 2, f"Expected start and prepare in the {shell} sample")
                start, prepare = calls
                script = f"{target}/scripts/{TOOL.name}"
                self.assertEqual(start[:3], [script, "start", "$sample"])
                self.assertEqual(prepare[:3], [script, "prepare", "$sample"])

                project = Path(scratch) / "corner bakery"
                (project / "docs").mkdir(parents=True)
                (project / "docs/prd.md").write_text(prd, encoding="utf-8")
                (project / "menu.txt").write_text(menu, encoding="utf-8")
                self.run_tool("start", str(project), *start[3:])
                relative_draft = page.with_name("draft.json")
                self.assertIn("--content", prepare)
                content_index = prepare.index("--content") + 1
                self.assertEqual(prepare[content_index:content_index + 1], [relative_draft.as_posix()])
                draft_path = project / relative_draft
                draft_path.parent.mkdir(parents=True, exist_ok=True)
                draft_path.write_text(draft, encoding="utf-8")
                self.run_tool("prepare", str(project), *prepare[3:])
                self.assertTrue((project / page).is_file(), page)
