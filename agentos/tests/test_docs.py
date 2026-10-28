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
from agentos.harness_ui import ROUTES, build_state
from agentos.models import AgentResult, Status

ROOT = Path(__file__).resolve().parent.parent
MARKDOWN = [ROOT / "README.md", ROOT / "CONTRIBUTING.md",
            ROOT / "CHANGELOG.md",
            ROOT / "ui-gpui" / "README.md",
            *sorted((ROOT / "docs").rglob("*.md"))]
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

    def test_run_manifest_schema_is_aligned_with_emitted_fields(self):
        import ast

        schema = json.loads((ROOT / "docs" / "session-manifest.schema.json").read_text())
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schema"]["const"], 1)
        required = set(schema["required"])
        runtime = (ROOT / "agentos" / "harness_run.py").read_text()
        for field in required:
            self.assertIn('"' + field + '"', runtime)
        for field in ("report_sha256", "trace_sha256"):
            self.assertIn(field, schema["properties"])
            self.assertIn(field, runtime)

    def test_openapi_matches_runtime_routes_and_state(self):
        api = json.loads((ROOT / "docs" / "openapi.json").read_text())
        self.assertEqual(api["openapi"], "3.1.0")
        paths = set(api["paths"])
        self.assertEqual(paths, set(ROUTES) | {
            "/healthz", "/api/state", "/api/task/{id}", "/api/changes",
            "/api/records"
        })
        self.assertTrue(all("post" not in value and "put" not in value
                            and "delete" not in value for value in api["paths"].values()))
        schemas = api["components"]["schemas"]
        self.assertEqual(set(schemas["Task"]["properties"]),
                         set(AgentResult.__dataclass_fields__))
        enum = schemas["Task"]["properties"]["status"]["enum"]
        self.assertEqual(set(enum), {status.value for status in Status})
        state = build_state({}, [])
        required = schemas["Snapshot"]["required"]
        self.assertTrue(set(required).issubset(state))
        self.assertEqual(state["schema"], schemas["Snapshot"]["properties"]["schema"]["const"])
        for field in state["counts"]:
            self.assertIn(field, schemas["Snapshot"]["properties"]["counts"]["properties"])

    def test_record_cursor_contract_matches_server_bounds(self):
        from agentos.record_stream import MAX_WINDOW, MAX_CURSOR
        api = json.loads((ROOT / "docs" / "openapi.json").read_text())
        params = {p["name"]: p for p in api["paths"]["/api/records"]["get"]["parameters"]}
        self.assertEqual(params["limit"]["schema"]["maximum"], MAX_WINDOW)
        self.assertEqual(params["after"]["schema"]["maximum"], MAX_CURSOR)
        self.assertIn("409", api["paths"]["/api/records"]["get"]["responses"])

    def test_openapi_page_contract_matches_server_bounds(self):
        from agentos.harness_ui import MAX_PAGE_OFFSET, MAX_PAGE_SIZE

        api = json.loads((ROOT / "docs" / "openapi.json").read_text())
        query = {p["name"]: p for p in api["paths"]["/api/state"]["get"]["parameters"]}
        self.assertEqual(query["limit"]["schema"]["maximum"], MAX_PAGE_SIZE)
        self.assertEqual(query["offset"]["schema"]["maximum"], MAX_PAGE_OFFSET)
        self.assertIn("400", api["paths"]["/api/state"]["get"]["responses"])

    def test_openapi_event_catalog_is_exactly_code_emissions(self):
        api = json.loads((ROOT / "docs" / "openapi.json").read_text())
        declared = set(api["components"]["schemas"]["Event"]["properties"]["event"]["enum"])
        runtime = (ROOT / "agentos" / "core.py").read_text()
        observed = set(re.findall(r'self\._event\("([a-z_]+)"', runtime))
        self.assertEqual(declared, observed)
        doc = (ROOT / "docs" / "trace-format.md").read_text()
        for event in declared:
            self.assertIn(chr(96) + event + chr(96), doc)

    def test_version_consistency_with_python_package_and_changelog(self):
        import tomllib
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        openapi = json.loads((ROOT / "docs" / "openapi.json").read_text())
        version = project["project"]["version"]
        self.assertEqual(version, openapi["info"]["version"])
        self.assertIn("v" + ".".join(version.split(".")[:2]),
                      (ROOT / "CHANGELOG.md").read_text())

    def test_openapi_references_all_exist(self):
        api = json.loads((ROOT / "docs" / "openapi.json").read_text())
        def walk(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    ref = value["$ref"]
                    self.assertTrue(ref.startswith("#/components/schemas/"), ref)
                    self.assertIn(ref.removeprefix("#/components/schemas/"),
                                  api["components"]["schemas"])
                for entry in value.values():
                    walk(entry)
            elif isinstance(value, list):
                for entry in value:
                    walk(entry)
        walk(api)

    def test_documented_cli_help_is_runnable_without_side_effects(self):
        for module in ("agentos.plan_lint", "agentos.doctor", "agentos.cli",
                       "agentos.harness_run", "agentos.harness_ui",
                       "agentos.layerfs_fc", "agentos.layerfs_init",
                       "agentos.capabilities",
                       "agentos.sessions"):
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
