#!/usr/bin/env python3
"""Compatibility guardrails for additive parallel candidate-audit support."""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from state_cli import STAGES, candidate_audit_parallel_actions, next_stage  # noqa: E402


class ProtectedCandidatePreparationContracts(unittest.TestCase):
    """Pin the authorized candidate-preparation compatibility implementation."""

    EXPECTED = {
        "scripts/candidate_preparation_cli.py": "066af8382a05ee0da69853f38f29db980bac8626684552c31fe962d367d4aa6d",
        "scripts/candidate_layout_adapters.py": "b92c44e2a824a879f7fe34883329cfcfff3b5ac6a3121b2e92d46ebadb3c9493",
        "scripts/page_chunk_cli.py": "4375f029e46680d2d6ff2c1ff6b8b4c36978ba0469e3925fc7fa251220747e3f",
        "references/schemas/candidate-index-v2.schema.json": "6503e9754153b0ba1a6407bed7c902e7ed8f2464ac98645038544334b5ce0f2c",
        "references/schemas/item-inventory-v2.schema.json": "7684d6a97019ffc7a0f941fd01ee9e20681e6e1ee4ec4041909f42d402849b6a",
        "references/schemas/candidate-locator-chunk.schema.json": "a88cee2ce015de43853881b7970a1f32d9784e09463ddddbec31fc276e2443c9",
        "references/schemas/candidate-preparation-receipt.schema.json": "caed1cf3f565c06ee9d5b8a3ff6b6235a6364255e4eb9a6f78013502d627b963",
        "references/schemas/candidate-preparation-bundle-metadata.schema.json": "4dbe094dea5ee186cebe748c2ea6ed7af170f904ba7c6c9181df7d223a493743",
        "references/schemas/candidate-preparation-integration.schema.json": "3cc0d6879fb8668c0c2d5c399e63d6584c09320c6eeb3e271a91888217159525",
    }

    def test_protected_files_are_byte_for_byte_unchanged(self) -> None:
        actual = {
            relative: hashlib.sha256((SKILL_ROOT / relative).read_bytes()).hexdigest()
            for relative in self.EXPECTED
        }
        self.assertEqual(self.EXPECTED, actual)


class V4StateCompatibilityTests(unittest.TestCase):
    @staticmethod
    def state_through(last_completed: str) -> dict:
        cutoff = STAGES.index(last_completed)
        return {
            "stages": {
                stage: {
                    "status": "completed" if index <= cutoff else "not_started",
                    "updated_at": None,
                    "notes": [],
                }
                for index, stage in enumerate(STAGES)
            }
        }

    def test_locator_workers_are_auxiliary_and_canonical_next_is_unchanged(self) -> None:
        state = self.state_through("locator_chunk_preparation")
        self.assertEqual("audit-locators", next_stage(state)["command"])
        actions = candidate_audit_parallel_actions(state)
        self.assertEqual("available", actions[0]["status"])
        self.assertEqual("blocked", actions[1]["status"])
        self.assertTrue(all(action["canonical_next_unchanged"] for action in actions))
        self.assertIn("complete frozen locator-packet set", actions[0]["selection_rule"])

    def test_missing_access_workers_require_full_canonical_locator_completion(self) -> None:
        state = self.state_through("locator_audit")
        self.assertEqual("audit-missing-access", next_stage(state)["command"])
        actions = candidate_audit_parallel_actions(state)
        self.assertEqual("completed", actions[0]["status"])
        self.assertEqual("available", actions[1]["status"])


if __name__ == "__main__":
    unittest.main()
