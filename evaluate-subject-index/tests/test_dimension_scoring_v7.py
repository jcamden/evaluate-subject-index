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
from locator_utility import (  # noqa: E402
    LEGACY_FIT_COMPATIBILITY_RULE_ID,
    LEGACY_FIT_CONFLICT_REASON_CODE,
    LEGACY_FIT_CONFLICT_RULE_ID,
    assign_locator_utility,
    combined_state_errors,
    locator_fit_state_analysis,
)
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


def legacy_defect(
    code: str,
    severity: str | None,
    *,
    locator_id: str = "LOC-TEST",
    defect_id: str = "DEFECT-LEGACY-TEST",
) -> dict:
    record = {
        "defect_id": defect_id,
        "code": code,
        "summary": "Synthetic legacy display prose is not a classifier.",
        "affected_ids": [locator_id],
    }
    if severity is not None:
        record["severity"] = severity
    return record


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
        legacy_defects: list[dict] | None = None,
    ) -> dict:
        assignment = assign_locator_utility(
            record, defects or [], legacy_defects or []
        ).as_dict()
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
            state("supported", "substantive", codes=["CON"], severity="cosmetic"),
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

    def test_unique_legacy_code_severity_projection_uses_frozen_fit_values(self) -> None:
        cases = (
            ("CON", "minor", "0.35", "material_mismatch", "F-MINOR-MISMATCH-035"),
            ("STA", "major", "0.15", "severe_mismatch", "F-MAJOR-MISMATCH-015"),
            ("CMP", "minor", "0.35", "material_mismatch", "F-MINOR-MISMATCH-035"),
            ("HED", "major", "0.15", "severe_mismatch", "F-MAJOR-MISMATCH-015"),
            ("SUB", "minor", "0.35", "material_mismatch", "F-MINOR-MISMATCH-035"),
            ("SCP", "critical", "0", "no_fit", "F-NO-FIT-000"),
        )
        for code, severity, fit, category, rule in cases:
            with self.subTest(code=code, severity=severity):
                assignment = self.assert_utility(
                    state(
                        "unsupported",
                        "substantive",
                        codes=["LOC_POS"],
                        severity="minor",
                    ),
                    "1",
                    fit,
                    fit,
                    legacy_defects=[legacy_defect(code, severity)],
                )
                self.assertEqual(category, assignment["fit_category"])
                self.assertEqual(rule, assignment["fit_rule_id"])
                self.assertEqual(
                    "legacy_code_severity_compatibility",
                    assignment["fit_classification_source"],
                )
                self.assertEqual(
                    ["F-COMPAT-LEGACY-CODE-SEVERITY-ONLY-V1"],
                    assignment["compatibility_rule_ids"],
                )

    def test_conflicting_valid_legacy_fit_classifiers_route_to_supplement(self) -> None:
        record = state(
            "unsupported",
            "substantive",
            codes=["CON"],
            severity="minor",
        ) | {"path_id": "PATH-SYNTHETIC-CONFLICT"}
        historical = [legacy_defect("STA", "major")]
        frozen_record = copy.deepcopy(record)
        frozen_historical = copy.deepcopy(historical)

        analysis = locator_fit_state_analysis(
            record, legacy_defects=historical
        )
        self.assertEqual([], analysis["hard_errors"])
        self.assertEqual(
            [LEGACY_FIT_CONFLICT_REASON_CODE],
            analysis["unresolved_reason_codes"],
        )
        conflict = analysis["fit_conflict"]
        self.assertEqual(LEGACY_FIT_CONFLICT_RULE_ID, conflict["conflict_rule_id"])
        self.assertEqual(
            "derived_complete_path_fit_category_only", conflict["conflict_scope"]
        )
        self.assertEqual(
            ["material_mismatch", "severe_mismatch"],
            conflict["independently_implied_fit_categories"],
        )
        self.assertFalse(conflict["classifier_precedence_applied"])
        self.assertTrue(conflict["supplement_eligible"])
        self.assertFalse(conflict["prose_inference_used"])
        classifiers = conflict["structured_classifiers"]
        self.assertEqual(2, len(classifiers))
        self.assertEqual(
            {"locator_audit", "historical_structure_audit"},
            {item["source_artifact_role"] for item in classifiers},
        )
        self.assertEqual(
            {"material_mismatch", "severe_mismatch"},
            {item["implied_fit_category"] for item in classifiers},
        )
        self.assertTrue(
            all(
                item["bound_locator_id"] == record["locator_id"]
                and item["path_id"] == record["path_id"]
                and item["prose_inference_used"] is False
                for item in classifiers
            )
        )
        with self.assertRaisesRegex(
            ValueError, LEGACY_FIT_CONFLICT_REASON_CODE
        ):
            assign_locator_utility(record, legacy_defects=historical)

        assignment = assign_locator_utility(
            record,
            legacy_defects=historical,
            supplemental_fit_decision={
                "decision_id": "FITDEC-123456789ABC",
                "fit_category": "material_partial_fit",
                "evidence_ids": [record["locator_id"]],
            },
        ).as_dict()
        self.assertEqual("supplemental_locator_fit", assignment["fit_classification_source"])
        self.assertEqual("material_partial_fit", assignment["fit_category"])
        self.assertEqual(
            [LEGACY_FIT_COMPATIBILITY_RULE_ID, LEGACY_FIT_CONFLICT_RULE_ID],
            assignment["compatibility_rule_ids"],
        )
        self.assertEqual(frozen_record, record)
        self.assertEqual(frozen_historical, historical)

    def test_absent_legacy_fit_conflict_is_schema_valid_and_keeps_zero_treatment(self) -> None:
        record = state(
            "unsupported",
            "absent",
            codes=["CON"],
            severity="minor",
            locator_id="LOC-SYNTHETIC-ABSENT-CONFLICT",
        ) | {"path_id": "PATH-SYNTHETIC-ABSENT-CONFLICT"}
        historical = [
            legacy_defect(
                "STA",
                "major",
                locator_id=record["locator_id"],
                defect_id="DEFECT-SYNTHETIC-ABSENT-CONFLICT",
            )
        ]
        frozen_record = copy.deepcopy(record)
        frozen_historical = copy.deepcopy(historical)

        analysis = locator_fit_state_analysis(
            record, legacy_defects=historical
        )
        self.assertEqual([], analysis["hard_errors"])
        self.assertEqual(
            [LEGACY_FIT_CONFLICT_REASON_CODE],
            analysis["unresolved_reason_codes"],
        )
        conflict = analysis["fit_conflict"]
        self.assertEqual(LEGACY_FIT_CONFLICT_RULE_ID, conflict["conflict_rule_id"])
        self.assertEqual(
            ["material_mismatch", "severe_mismatch"],
            conflict["independently_implied_fit_categories"],
        )
        self.assertEqual(2, len(conflict["structured_classifiers"]))
        for classifier in conflict["structured_classifiers"]:
            self.assertEqual(record["locator_id"], classifier["bound_locator_id"])
            self.assertEqual(record["path_id"], classifier["path_id"])
            self.assertTrue(classifier["source_artifact_role"])
            self.assertTrue(classifier["stable_record_id"])
            self.assertTrue(classifier["classifier_basis"])
            self.assertTrue(classifier["binding_basis"])
            self.assertIn(
                classifier["implied_fit_category"],
                {"material_mismatch", "severe_mismatch"},
            )
            self.assertFalse(classifier["prose_inference_used"])

        ledgers = reliability_ledgers([record])
        first = v7.public_locator_fit_preflight(
            v7.locator_fit_preflight(
                ledgers, "full", legacy_defects=historical
            )
        )
        second = v7.public_locator_fit_preflight(
            v7.locator_fit_preflight(
                copy.deepcopy(ledgers),
                "full",
                legacy_defects=copy.deepcopy(historical),
            )
        )
        self.assertEqual(first, second)
        self.assertEqual(
            {
                "deterministically_compatible": 0,
                "unresolved_complete_path_fit": 1,
                "invalid_or_contradictory_state": 0,
            },
            first["group_counts"],
        )
        self.assertEqual([], first["invalid_or_contradictory_state"])
        unresolved = first["unresolved_complete_path_fit"]
        self.assertEqual(1, len(unresolved))
        self.assertEqual(record["locator_id"], unresolved[0]["locator_id"])
        self.assertEqual("unsupported", unresolved[0]["present_judgment"])
        self.assertEqual("absent", unresolved[0]["treatment_class"])
        self.assertEqual("indexable", unresolved[0]["source_scope_status"])
        self.assertEqual(
            LEGACY_FIT_CONFLICT_REASON_CODE, unresolved[0]["reason_code"]
        )
        self.assertEqual(
            v5.canonical_hash({"unresolved_locator_fit": unresolved}),
            first["unresolved_set_sha256"],
        )
        v5.validate_schema_document(
            first,
            "v7-locator-fit-preflight.schema.json",
            "Synthetic absent legacy-fit conflict preflight",
        )

        prohibited_preflight_keys = {
            "fit_credit",
            "treatment_credit",
            "fit_score",
            "treatment_score",
            "combined_credit",
            "diagnostic_grade",
            "grade",
            "dimension_score",
            "total_score",
        }

        def nested_keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(
                    *(nested_keys(item) for item in value.values())
                )
            if isinstance(value, list):
                return set().union(*(nested_keys(item) for item in value))
            return set()

        self.assertFalse(prohibited_preflight_keys & nested_keys(first))
        self.assertFalse(first["aggregate_v7_score_available"])

        assignment = assign_locator_utility(
            record,
            legacy_defects=historical,
            supplemental_fit_decision={
                "decision_id": "FITDEC-ABSENT000001",
                "fit_category": "material_partial_fit",
                "evidence_ids": [record["locator_id"]],
            },
        ).as_dict()
        self.assertEqual("absent", assignment["treatment_class"])
        self.assertEqual("0", assignment["treatment_score"])
        self.assertEqual("material_partial_fit", assignment["fit_category"])
        self.assertEqual("0.7", assignment["fit_score"])
        self.assertEqual("0", assignment["combined_credit"])
        self.assertEqual(0, assignment["diagnostic_grade"])
        self.assertEqual(
            [LEGACY_FIT_COMPATIBILITY_RULE_ID, LEGACY_FIT_CONFLICT_RULE_ID],
            assignment["compatibility_rule_ids"],
        )
        self.assertEqual(frozen_record, record)
        self.assertEqual(frozen_historical, historical)

    def test_absent_without_conflict_and_unavailable_keep_existing_routes(self) -> None:
        ordinary_absent = state(
            "unsupported",
            "absent",
            codes=["LOC_POS"],
            severity="major",
            locator_id="LOC-SYNTHETIC-ABSENT-DETERMINISTIC",
        ) | {"path_id": "PATH-SYNTHETIC-ABSENT-DETERMINISTIC"}
        absent_report = v7.public_locator_fit_preflight(
            v7.locator_fit_preflight(
                reliability_ledgers([ordinary_absent]), "full"
            )
        )
        self.assertEqual(
            {
                "deterministically_compatible": 1,
                "unresolved_complete_path_fit": 0,
                "invalid_or_contradictory_state": 0,
            },
            absent_report["group_counts"],
        )
        self.assertEqual(
            "frozen_absent_treatment",
            absent_report["deterministically_compatible"][0][
                "fit_classification_source"
            ],
        )
        v5.validate_schema_document(
            absent_report,
            "v7-locator-fit-preflight.schema.json",
            "Synthetic ordinary absent preflight",
        )

        unavailable = state(
            "uninspectable",
            "unavailable",
            scope="indexable",
            locator_id="LOC-SYNTHETIC-UNAVAILABLE",
        ) | {"path_id": "PATH-SYNTHETIC-UNAVAILABLE"}
        jsonschema.validate(
            unavailable,
            json.loads(
                (SCHEMAS / "locator-evidence-state-v3.schema.json").read_text()
            ),
        )
        unavailable_analysis = locator_fit_state_analysis(unavailable)
        self.assertEqual([], unavailable_analysis["hard_errors"])
        self.assertEqual([], unavailable_analysis["unresolved_reason_codes"])
        self.assertIsNone(unavailable_analysis["fit_conflict"])
        unavailable_report = v7.public_locator_fit_preflight(
            v7.locator_fit_preflight(
                reliability_ledgers([unavailable]), "full"
            )
        )
        self.assertEqual(
            {
                "deterministically_compatible": 1,
                "unresolved_complete_path_fit": 0,
                "invalid_or_contradictory_state": 0,
            },
            unavailable_report["group_counts"],
        )
        self.assertEqual(
            "frozen_uninspectable_state",
            unavailable_report["deterministically_compatible"][0][
                "fit_classification_source"
            ],
        )
        v5.validate_schema_document(
            unavailable_report,
            "v7-locator-fit-preflight.schema.json",
            "Synthetic unavailable deterministic preflight",
        )

        invalid_unavailable = state(
            "unsupported",
            "unavailable",
            codes=["CON"],
            severity="minor",
            locator_id="LOC-SYNTHETIC-UNAVAILABLE-INVALID",
        ) | {"path_id": "PATH-SYNTHETIC-UNAVAILABLE-INVALID"}
        invalid_analysis = locator_fit_state_analysis(
            invalid_unavailable,
            legacy_defects=[
                legacy_defect(
                    "STA",
                    "major",
                    locator_id=invalid_unavailable["locator_id"],
                    defect_id="DEFECT-SYNTHETIC-UNAVAILABLE-INVALID",
                )
            ],
        )
        self.assertIn(
            "inconsistent:unavailable_treatment_requires_uninspectable",
            invalid_analysis["hard_errors"],
        )
        self.assertEqual([], invalid_analysis["unresolved_reason_codes"])
        self.assertIsNone(invalid_analysis["fit_conflict"])

    def test_treatment_indication_and_valid_legacy_classifier_conflict_narrowly(self) -> None:
        record = state(
            "unsupported", "passing_mention", severity="minor"
        ) | {"path_id": "PATH-SYNTHETIC-TREATMENT-CONFLICT"}
        analysis = locator_fit_state_analysis(
            record,
            legacy_defects=[legacy_defect("HED", "minor")],
        )
        self.assertEqual([], analysis["hard_errors"])
        self.assertEqual(
            [LEGACY_FIT_CONFLICT_REASON_CODE],
            analysis["unresolved_reason_codes"],
        )
        classifiers = analysis["fit_conflict"]["structured_classifiers"]
        self.assertEqual(
            {
                "unsupported_weak_treatment_fit_indication": "exact_fit",
                "legacy_code_severity_compatibility": "material_mismatch",
            },
            {
                item["classifier_basis"]: item["implied_fit_category"]
                for item in classifiers
            },
        )
        with self.assertRaisesRegex(ValueError, LEGACY_FIT_CONFLICT_REASON_CODE):
            assign_locator_utility(
                record,
                legacy_defects=[legacy_defect("HED", "minor")],
            )

    def test_conflict_preflight_is_score_free_unique_and_schema_valid(self) -> None:
        record = state(
            "unsupported",
            "substantive",
            codes=["CON"],
            severity="minor",
            locator_id="LOC-SYNTHETIC-CONFLICT",
        ) | {"path_id": "PATH-SYNTHETIC-CONFLICT"}
        ledgers = reliability_ledgers([record])
        report = v7.locator_fit_preflight(
            ledgers,
            "full",
            legacy_defects=[
                legacy_defect(
                    "STA",
                    "major",
                    locator_id=record["locator_id"],
                    defect_id="DEFECT-SYNTHETIC-CONFLICT",
                )
            ],
        )
        public = v7.public_locator_fit_preflight(report)
        self.assertEqual(
            {
                "deterministically_compatible": 0,
                "unresolved_complete_path_fit": 1,
                "invalid_or_contradictory_state": 0,
            },
            public["group_counts"],
        )
        self.assertEqual(
            {LEGACY_FIT_CONFLICT_REASON_CODE: 1},
            public["unresolved_reason_counts"],
        )
        self.assertEqual(
            [record["locator_id"]],
            [
                item["locator_id"]
                for item in public["unresolved_complete_path_fit"]
            ],
        )
        self.assertFalse(public["aggregate_v7_score_available"])
        self.assertNotIn("total_score", public)
        self.assertNotIn("dimension_score", public)
        self.assertEqual(
            v5.canonical_hash(
                {
                    "unresolved_locator_fit": public[
                        "unresolved_complete_path_fit"
                    ]
                }
            ),
            public["unresolved_set_sha256"],
        )
        v5.validate_schema_document(
            public,
            "v7-locator-fit-preflight.schema.json",
            "Synthetic legacy-fit conflict preflight",
        )

    def test_legacy_fit_neutral_invalid_and_ambiguous_states_fail_closed(self) -> None:
        base = state(
            "unsupported",
            "substantive",
            codes=["LOC_POS"],
            severity="minor",
        )
        cases = (
            [legacy_defect("CON", "cosmetic")],
            [legacy_defect("MEC", "minor")],
            [legacy_defect("SEL", "major")],
            [legacy_defect("LOC_POS", "critical")],
            [legacy_defect("UNKNOWN", "minor")],
            [legacy_defect("CON", None)],
            [legacy_defect("CON", "minor") | {"summary": None}],
            [legacy_defect("CON", "minor") | {"affected_ids": None, "affected_item_ids": ["LOC-TEST"]}],
            [
                legacy_defect("CON", "minor"),
                legacy_defect("HED", "minor"),
            ],
            [
                legacy_defect("CON", "minor", defect_id="DEFECT-LEGACY-A"),
                legacy_defect("STA", "major", defect_id="DEFECT-LEGACY-B"),
            ],
        )
        for defects in cases:
            with self.subTest(defects=defects), self.assertRaises(ValueError):
                assign_locator_utility(base, legacy_defects=defects)

        ambiguous_scope = copy.deepcopy(base)
        ambiguous_scope.update(
            judgment="uninspectable",
            treatment_class="unavailable",
            source_scope_status="ambiguous",
        )
        ambiguous_assignment = self.assert_utility(
            ambiguous_scope,
            None,
            None,
            None,
            legacy_defects=[legacy_defect("SCP", "minor")],
        )
        self.assertEqual("uninspectable", ambiguous_assignment["fit_category"])
        self.assertEqual([], ambiguous_assignment["compatibility_rule_ids"])

        same_category = self.assert_utility(
            base,
            "1",
            "0.35",
            "0.35",
            legacy_defects=[
                legacy_defect("CON", "minor", defect_id="DEFECT-LEGACY-A"),
                legacy_defect("HED", "minor", defect_id="DEFECT-LEGACY-B"),
            ],
        )
        self.assertEqual("material_mismatch", same_category["fit_category"])

        no_fit_precedence = self.assert_utility(
            base,
            "1",
            "0",
            "0",
            legacy_defects=[
                legacy_defect("CON", "minor")
                | {"root_cause_family": "no_path_fit"}
            ],
        )
        self.assertEqual("no_fit", no_fit_precedence["fit_category"])
        self.assertEqual(
            "structured_no_fit_precedence",
            no_fit_precedence["fit_classification_source"],
        )
        self.assertEqual([], no_fit_precedence["compatibility_rule_ids"])

    def test_positive_judgments_keep_their_existing_fit_treatment(self) -> None:
        supported = self.assert_utility(
            state("supported", "substantive"), "1", "1", "1"
        )
        partial = self.assert_utility(
            state("partially_supported", "mixed", severity="minor"),
            "0.7",
            "0.7",
            "0.7",
            legacy_defects=[legacy_defect("CON", "minor")],
        )
        self.assertEqual("frozen_supported_judgment", supported["fit_classification_source"])
        self.assertEqual(
            "frozen_partially_supported_judgment",
            partial["fit_classification_source"],
        )
        self.assertEqual([], partial["compatibility_rule_ids"])
        for record in (
            state("supported", "substantive"),
            state("partially_supported", "mixed", severity="minor"),
        ):
            with self.subTest(record=record), self.assertRaisesRegex(
                ValueError, "deterministic_locator"
            ):
                assign_locator_utility(
                    record,
                    supplemental_fit_decision={
                        "decision_id": "FITDEC-000000000000",
                        "fit_category": "no_fit",
                        "evidence_ids": [record["locator_id"]],
                    },
                )

    def test_legacy_projection_is_available_only_at_the_v3_history_boundary(self) -> None:
        historical = {
            "schema_version": "structure-audit-v3",
            "defects": [legacy_defect("CON", "minor")],
        }
        modern = copy.deepcopy(historical)
        modern["schema_version"] = "structure-audit-v4"
        self.assertEqual(
            historical["defects"], v7.historical_locator_fit_defects(historical)
        )
        self.assertEqual([], v7.historical_locator_fit_defects(modern))
        with self.assertRaisesRegex(ValueError, "bare_loc_pos"):
            assign_locator_utility(
                state(
                    "unsupported",
                    "substantive",
                    codes=["LOC_POS"],
                    severity="minor",
                ),
                legacy_defects=v7.historical_locator_fit_defects(modern),
            )

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

    def test_incomplete_full_audit_cannot_produce_a_calculation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            locator["judgments"] = locator["judgments"][:-1]
            config = calculation_files(root, locator, missing, structure)
            loaded = v5.load_inputs(config)
            with self.assertRaises(v5.CalculationError) as raised:
                v7.calculate_loaded(loaded)
            self.assertEqual("v7_inputs_insufficient", raised.exception.code)

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
