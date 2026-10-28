"""Documentation contract tests: links, JSON snippets and CLI entry points.

These checks are intentionally network-free and run on Ubuntu and openEuler.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

from agentos.plan_lint import validate_plan

ROOT = Path(__file__).resolve().parent.parent
MARKDOWN = [ROOT / "README.md", ROOT / "ui-gpui" / "README.md",
            *sorted((ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
TICK = chr(96)
JSON_FENCE = re.compile(r"(?m)^" + TICK * 3 + r"json\s*\n(.*?)^" +
                        TICK * 3, re.DOTALL)
FENCE = re.compile(r"(?m)^" + TICK * 3)


class DocumentationContractTests(unittest.TestCase):
    def test_indexed_docs_exist_and_local_links_resolve(self):
        self.assertGreaterEqual(len(MARKDOWN), 9)
        for document in MARKDOWN:
            with self.subTest(document=str(document.relative_to(ROOT))):
                content = document.read_text(encoding="utf-8")
                self.assertTrue(content.startswith("# "))
                self.assertEqual(len(FENCE.findall(content)) % 2, 0,
                                 "Markdown code fences must be balanced")
                self.assertNotIn("\\" + TICK, content,
                                 "Backticks must not have escape prefixes")
                for raw_link in LINK.findall(content):
                    path = raw_link.split("#", 1)[0]
                    if (not path or path.startswith(("https://", "http://", "mailto:"))):
                        continue
                    link = (document.parent / path).resolve()
                    self.assertTrue(link.is_relative_to(ROOT.resolve()),
                                    f"relative link leaves docs: {raw_link}")
                    self.assertTrue(link.exists(),
                                    f"broken relative doc link: {document}: {raw_link}")

    def test_all_json_code_blocks_are_parseable(self):
        for document in MARKDOWN:
            content = document.read_text(encoding="utf-8")
            for index, snippet in enumerate(JSON_FENCE.findall(content)):
                with self.subTest(document=document.name, code_fence=index):
                    obj = json.loads(snippet)
                    if (document.name == "configuration.md" and
                            isinstance(obj, dict) and "tasks" in obj):
                        specs, _, order = validate_plan(obj)
                        self.assertEqual(len(specs), len(order))

    def test_readme_links_every_primary_section(self):
        readme = (ROOT / "README.md").read_text()
        for path in ("docs/README.md", "docs/configuration.md", "docs/architecture.md",
                     "docs/deployment.md", "docs/harness-ui.md", "docs/layerfs-fc.md",
                     "docs/testing.md", "docs/troubleshooting.md", "docs/security.md",
                     "ui-gpui/README.md"):
            with self.subTest(path=path):
                self.assertIn(path, readme)

    def test_json_schema_matches_agent_spec_and_budget_fields(self):
        from agentos.models import AgentSpec, Budget

        schema = json.loads((ROOT / "docs" / "agentos-plan.schema.json").read_text())
        self.assertEqual(schema["type"], "object")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["properties"]), {"budget", "tasks"})
        task_fields = set(schema["$defs"]["task"]["properties"])
        budget_fields = set(schema["$defs"]["budget"]["properties"])
        self.assertEqual(task_fields, set(AgentSpec.__dataclass_fields__))
        self.assertEqual(budget_fields, set(Budget.__dataclass_fields__))
        self.assertEqual(schema["$defs"]["task"]["properties"]["retries"]["maximum"], 5)
        self.assertEqual(schema["$defs"]["budget"]["properties"]["max_tasks"]["maximum"], 10000)

    def test_documented_cli_help_is_runnable_without_side_effects(self):
        for module in ("agentos.plan_lint", "agentos.doctor", "agentos.cli",
                       "agentos.harness_run", "agentos.harness_ui",
                       "agentos.layerfs_fc", "agentos.layerfs_init"):
            with self.subTest(module=module):
                completed = subprocess.run(
                    [sys.executable, "-m", module, "--help"],
                    cwd=ROOT, capture_output=True, text=True, timeout=10,
                    check=False)
                self.assertEqual(completed.returncode, 0,
                                 completed.stdout + completed.stderr)
                self.assertIn("usage:", completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()
