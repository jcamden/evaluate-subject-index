from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run_cli(script: str, *arguments: object, ok: bool = True) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *(str(value) for value in arguments)],
        text=True,
        capture_output=True,
        check=False,
    )
    if ok and result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    if not ok and result.returncode == 0:
        raise AssertionError("Command unexpectedly succeeded: " + result.stdout)
    return json.loads(result.stdout)


class StateAndCheckpointTests(unittest.TestCase):
    def initialize(self, root: Path) -> Path:
        source = root / "source.pdf"
        source.write_bytes(b"source bytes")
        state = root / "evaluation-state.json"
        result = run_cli(
            "state_cli.py", "init",
            "--output", state,
            "--evaluation-id", "EVAL-CURRENT",
            "--source-title", "Example",
            "--source-file", source,
            "--document-page-start", 1,
            "--document-page-end", 10,
            "--intended-readership", "general",
        )
        self.assertTrue(result["ok"])
        return state

    def test_state_is_the_only_control_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_path = self.initialize(Path(temporary))
            state = json.loads(state_path.read_text())
            self.assertEqual(state["schema_version"], "subject-index-evaluation-state-v5")
            self.assertNotIn("artifact_manifest_path", state)
            self.assertEqual(state["configuration"]["rubric_version"], "subject-index-rubric-v7")
            self.assertEqual(
                state["configuration"]["scoring_identity"]["dimension_calculation_profile"],
                "subject-index-dimension-calculation-v3",
            )

    def test_changed_registered_bytes_warn_without_blocking_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = self.initialize(root)
            page_map = root / "page-map.json"
            page_map.write_text(json.dumps({"schema_version": "page-map-v1", "value": 1}))
            run_cli(
                "state_cli.py", "set-stage",
                "--state", state_path,
                "--stage", "page_mapping",
                "--status", "completed",
                "--artifact-path", page_map,
                "--artifact-type", "page_map",
            )
            page_map.write_text(json.dumps({"schema_version": "page-map-v1", "value": 2}))
            validation = run_cli("state_cli.py", "validate", "--state", state_path)
            self.assertTrue(validation["ok"])
            self.assertTrue(any("changed since registration" in warning for warning in validation["warnings"]))

    def test_checkpoint_import_is_structural_not_checksum_gated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = self.initialize(root)
            checkpoint = root / "checkpoint.zip"
            run_cli("bundle_cli.py", "checkpoint", "--state", state_path, "--output", checkpoint)
            with zipfile.ZipFile(checkpoint) as archive:
                metadata = json.loads(archive.read("bundle-metadata.json"))
                self.assertNotIn("sha256", metadata)
                self.assertNotIn("state_sha256", metadata)
                self.assertNotIn("artifact-manifest.json", archive.namelist())
            imported = root / "imported"
            result = run_cli("bundle_cli.py", "import-bundle", "--input", checkpoint, "--output-dir", imported)
            self.assertTrue(result["ok"])
            self.assertTrue((imported / "evaluation-state.json").is_file())


if __name__ == "__main__":
    unittest.main()
