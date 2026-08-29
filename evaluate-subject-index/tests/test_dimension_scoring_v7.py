from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCHEMAS = ROOT / "references" / "schemas"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import dimension_score_cli as v5  # noqa: E402
import dimension_score_v6_cli as v6  # noqa: E402
import dimension_score_v7_cli as v7  # noqa: E402
from locator_utility import assign_locator_utility, combined_state_errors  # noqa: E402
from test_dimension_scoring_v5 import base_documents, calculation_files  # noqa: E402
from test_dimension_scoring_v6 import reliability_ledgers  # noqa: E402


def state(
    judgment: str,
    treatment: str,
    *,
    scope: str = "indexable",
    codes: list[str] | None = None,
    severity: str = "none",
    locator_id: str = "LOC-TEST",
) -> dict:
    return {
        "locator_id": locator_id,
        "judgment": judgment,
        "treatment_class": treatment,
        "source_scope_status": scope,
        "error_codes": list(codes or []),
        "severity": severity,
    }


def defect(
    code: str,
    kind: str,
    severity: str,
    *,
    locator_id: str = "LOC-TEST",
    defect_id: str = "DEFECT-TEST",
    root_cause_family: str = "synthetic_fit_failure",
) -> dict:
    return {
        "defect_id": defect_id,
        "code": code,
        "dimension_owner": "page_reference_reliability",
        "defect_kind": kind,
        "severity": severity,
        "root_cause_family": root_cause_family,
        "affected_item_ids": [locator_id],
    }


def dimension(calculation: dict, dimension_id: str) -> dict:
    return next(item for item in calculation["dimensions"] if item["dimension_id"] == dimension_id)


class LocatorUtilityPolicyTests(unittest.TestCase):
    def assert_utility(
        self,
        record: dict,
        expected_treatment: str | None,
        expected_fit: str | None,
        expected_combined: str | None,
        *,
        defects: list[dict] | None = None,
    ) -> dict:
        assignment = assign_locator_utility(record, defects or []).as_dict()
        self.assertEqual(expected_treatment, assignment["treatment_score"])
        self.assertEqual(expected_fit, assignment["fit_score"])
        self.assertEqual(expected_combined, assignment["combined_credit"])
        if expected_combined is None:
            self.assertIsNone(assignment["diagnostic_grade"])
        else:
            self.assertEqual(
                Decimal(expected_combined) * Decimal(100),
                Decimal(str(assignment["diagnostic_grade"])),
            )
        return assignment

    def test_required_arithmetic_examples(self) -> None:
        self.assert_utility(state("supported", "substantive"), "1", "1", "1")
        self.assert_utility(
            state("partially_supported", "substantive", codes=["CON"], severity="minor"),
            "1",
            "0.7",
            "0.7",
        )
        self.assert_utility(
            state("partially_supported", "mixed", codes=["CON"], severity="minor"),
            "0.7",
            "0.7",
            "0.7",
        )
        self.assert_utility(
            state("unsupported", "substantive", codes=["CON"], severity="minor"),
            "1",
            "0.35",
            "0.35",
        )
        self.assert_utility(
            state("unsupported", "substantive", codes=["STA"], severity="major"),
            "1",
            "0.15",
            "0.15",
        )
        self.assert_utility(
            state("unsupported", "passing_mention", severity="minor"),
            "0.25",
            "1",
            "0.25",
        )
        self.assert_utility(
            state("partially_supported", "passing_mention", severity="minor"),
            "0.25",
            "0.7",
            "0.25",
        )
        self.assert_utility(
            state("unsupported", "passing_mention", codes=["HED"], severity="minor"),
            "0.25",
            "0.35",
            "0.25",
        )

    def test_weak_presence_plus_no_fit_is_zero(self) -> None:
        self.assert_utility(
            state("unsupported", "citation_only", severity="major"),
            "0.25",
            "0",
            "0",
            defects=[
                defect(
                    "CON",
                    "generic",
                    "major",
                    root_cause_family="wrong_sense",
                )
            ],
        )

    def test_absent_is_zero_regardless_of_nominal_fit_code(self) -> None:
        assignment = self.assert_utility(
            state("unsupported", "absent", codes=["LOC_POS"], severity="major"),
            "0",
            "0",
            "0",
        )
        self.assertEqual("F-NO-FIT-000", assignment["fit_rule_id"])

    def test_invalid_destinations_are_zero(self) -> None:
        excluded = self.assert_utility(
            state("unsupported", "substantive", scope="excluded", codes=["SCP"], severity="critical"),
            "0",
            "0",
            "0",
        )
        self.assertEqual("invalid_destination", excluded["treatment_category"])
        for kind in ("fabricated_locator", "nonexistent_locator", "out_of_scope_locator"):
            with self.subTest(kind=kind):
                self.assert_utility(
                    state("unsupported", "substantive", codes=["SCP"], severity="critical"),
                    "0",
                    "0",
                    "0",
                    defects=[defect("SCP", kind, "critical")],
                )

    def test_uninspectable_is_neutral_with_full_bounds(self) -> None:
        assignment = self.assert_utility(
            state(
                "uninspectable",
                "unavailable",
                scope="unavailable",
                severity="none",
            ),
            None,
            None,
            None,
        )
        self.assertEqual("bounded", assignment["disposition"])
        self.assertEqual({"lower": "0", "upper": "1"}, assignment["uncertainty_bounds"])

    def test_strongest_fit_severity_controls(self) -> None:
        record = state("unsupported", "substantive", codes=["HED"], severity="minor")
        assignment = self.assert_utility(
            record,
            "1",
            "0.15",
            "0.15",
            defects=[defect("CON", "misleading_relationship", "major")],
        )
        self.assertEqual("major", assignment["effective_fit_severity"])

    def test_contradictory_and_ambiguous_states_fail_closed(self) -> None:
        cases = (
            state("supported", "passing_mention"),
            state("partially_supported", "absent"),
            state("unsupported", "substantive", severity="major"),
            state("unsupported", "passing_mention", codes=["LOC_POS"], severity="minor"),
            state("unsupported", "passing_mention", codes=["XRF"], severity="minor"),
        )
        for record in cases:
            with self.subTest(record=record), self.assertRaises(ValueError):
                assign_locator_utility(record)
        self.assertIn("missing:severity", combined_state_errors({
            "locator_id": "LOC-X",
            "judgment": "supported",
            "treatment_class": "substantive",
            "source_scope_status": "indexable",
            "error_codes": [],
        }))

    def test_rationale_and_evidence_summary_are_never_mapping_inputs(self) -> None:
        ambiguous = state(
            "unsupported",
            "substantive",
            codes=["LOC_POS"],
            severity="minor",
        ) | {
            "rationale": "This prose says the relationship is only slightly wrong.",
            "evidence_summary": "This prose would support a favorable category.",
        }
        with self.assertRaisesRegex(ValueError, "bare_loc_pos"):
            assign_locator_utility(ambiguous)

    def test_locator_evidence_schema_accepts_partial_weak_presence(self) -> None:
        schema = json.loads((SCHEMAS / "locator-evidence-state-v3.schema.json").read_text())
        jsonschema.validate(
            state("partially_supported", "passing_mention", codes=["STA"], severity="minor"),
            schema,
        )


class V7ReliabilityIntegrationTests(unittest.TestCase):
    def test_precision_uses_combined_credits_and_complete_provenance(self) -> None:
        ledgers = reliability_ledgers(
            [
                state("supported", "substantive", locator_id="LOC-0001"),
                state("partially_supported", "mixed", severity="minor", locator_id="LOC-0002"),
                state("unsupported", "substantive", codes=["CON"], severity="minor", locator_id="LOC-0003"),
                state("unsupported", "passing_mention", severity="minor", locator_id="LOC-0004"),
                state("unsupported", "substantive", codes=["STA"], severity="major", locator_id="LOC-0005"),
                state("unsupported", "absent", codes=["LOC_POS"], severity="major", locator_id="LOC-0006"),
            ]
        )
        result = v7.calculate_reliability(ledgers, "full")
        provenance = result["reliability_provenance"]
        self.assertEqual("2.45", provenance["weighted_precision_numerator"])
        self.assertEqual(6, provenance["weighted_precision_denominator"])
        self.assertEqual("0.4083333333333333333333333333", provenance["weighted_locator_precision"])
        self.assertEqual("0.1666666666666666666666666667", provenance["strict_substantive_precision"])
        self.assertEqual("locator_utility_assignments[].combined_credit", provenance["calculation_credit_source"])
        self.assertFalse(provenance["diagnostic_grades_used_in_dimension_arithmetic"])
        self.assertEqual(6, len(provenance["locator_utility_assignments"]))
        self.assertFalse(provenance["mapping_rejections"])
        self.assertEqual(
            {"1": 1, "0.7": 1, "0.35": 1, "0.25": 1, "0.15": 1, "0": 1, "uninspectable": 0, "not_measured": 0},
            provenance["counts_by_combined_credit_value"],
        )

    def test_mixed_partial_and_weak_partial_are_not_multiplied(self) -> None:
        for record, expected in (
            (state("partially_supported", "mixed", severity="minor"), "0.7"),
            (state("partially_supported", "passing_mention", severity="minor"), "0.25"),
        ):
            with self.subTest(record=record):
                result = v7.calculate_reliability(reliability_ledgers([record]), "full")
                assignment = result["reliability_provenance"]["locator_utility_assignments"][0]
                self.assertEqual(expected, assignment["combined_credit"])

    def test_uninspectable_affects_lower_and_upper_endpoints(self) -> None:
        result = v7.calculate_reliability(
            reliability_ledgers(
                [
                    state("supported", "substantive", locator_id="LOC-0001"),
                    state("uninspectable", "unavailable", scope="unavailable", locator_id="LOC-0002"),
                ]
            ),
            "full",
        )
        provenance = result["reliability_provenance"]
        self.assertEqual({"lower": "0.5", "central": "1", "upper": "1"}, provenance["weighted_precision_uncertainty"])
        self.assertEqual({"lower": "0.5", "central": "1", "upper": "1"}, provenance["treatment_score_uncertainty"])
        self.assertEqual({"lower": "0.5", "central": "1", "upper": "1"}, provenance["fit_score_uncertainty"])

    def test_full_mode_not_measured_is_a_preflight_failure(self) -> None:
        ledgers = reliability_ledgers(
            [state("supported", "substantive", locator_id="LOC-0001")],
            locator_not_measured=["LOC-0002"],
        )
        failures = v7.locator_state_requirements(ledgers, "full")
        self.assertEqual("required_locator_not_measured", failures[-1]["code"])
        self.assertFalse(v7.locator_state_requirements(ledgers, "pilot"))

    def test_non_reliability_dimensions_are_value_identical_to_v6(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            config = calculation_files(root, locator, missing, structure)
            loaded = v5.load_inputs(config)
            old = v6.calculate_loaded(loaded)
            new = v7.calculate_loaded(loaded)
            for dimension_id in v5.WEIGHTS:
                if dimension_id == "page_reference_reliability":
                    continue
                old_dimension = copy.deepcopy(dimension(old, dimension_id))
                new_dimension = copy.deepcopy(dimension(new, dimension_id))
                old_dimension.pop("formula_id")
                new_dimension.pop("formula_id")
                self.assertEqual(old_dimension, new_dimension, dimension_id)
            v5.validate_schema_document(
                new,
                "dimension-calculations-v3.schema.json",
                "Synthetic V7 calculation",
            )

    def test_native_v7_structure_audit_identity_uses_v5_schema_without_rewriting_v4(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            structure["schema_version"] = "structure-audit-v5"
            structure["v7_architecture_review_decisions"] = []
            config = calculation_files(root, locator, missing, structure)
            loaded = v7.load_v7_inputs(config)
            self.assertEqual("structure-audit-v5", loaded["frozen_structure"]["schema_version"])
            self.assertEqual("structure-audit-v4", loaded["structure"]["schema_version"])
            calculation = v7.calculate_loaded(loaded)
            self.assertEqual("subject-index-rubric-v7", calculation["rubric_version"])
            v5.validate_schema_document(
                calculation,
                "dimension-calculations-v3.schema.json",
                "Native V7 structure calculation",
            )


if __name__ == "__main__":
    unittest.main()
