from __future__ import annotations

import copy
import hashlib
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
import item_grade_cli as item_grades  # noqa: E402
from locator_relevance import assign_locator_credit, combined_state_errors  # noqa: E402
from test_dimension_scoring_v5 import (  # noqa: E402
    base_documents,
    calculation_files,
    digest,
    evaluation_projection,
    minimal_item_assessments,
    run_cli,
    web_projection,
    write_json,
)


def dimension(result: dict, dimension_id: str) -> dict:
    return next(item for item in result["dimensions"] if item["dimension_id"] == dimension_id)


def calculate(root: Path, locator: dict, missing: dict, structure: dict, audit_mode: str = "full") -> dict:
    config = calculation_files(root, locator, missing, structure, audit_mode)
    return v6.calculate_loaded(v5.load_inputs(config))


def set_all_locators(locator: dict, judgment: str, treatment: str, codes: list[str] | None = None) -> None:
    for item in locator["judgments"]:
        item["judgment"] = judgment
        item["treatment_class"] = treatment
        item["source_scope_status"] = "indexable"
        item["error_codes"] = list(codes or [])
        item["severity"] = "none" if judgment != "unsupported" else "minor"


def locator_state(
    judgment: str,
    treatment: str,
    *,
    scope: str = "indexable",
    codes: list[str] | None = None,
    locator_id: str = "LOC-TEST",
) -> dict:
    return {
        "locator_id": locator_id,
        "judgment": judgment,
        "treatment_class": treatment,
        "source_scope_status": scope,
        "error_codes": list(codes or []),
    }


def reliability_ledgers(
    locator_states: list[dict],
    treatment_statuses: list[tuple[str, str]] | None = None,
    *,
    locator_not_measured: list[str] | None = None,
    defects: list[dict] | None = None,
    attempt: str = "meaningful_attempt",
) -> dict:
    locators = []
    for index, state in enumerate(locator_states, start=1):
        record = copy.deepcopy(state)
        record.setdefault("locator_id", f"LOC-{index:04d}")
        record.setdefault("error_codes", [])
        record.setdefault("source_scope_status", "indexable")
        record["_source_unit_id"] = "CHUNK-001"
        locators.append(record)
    statuses = treatment_statuses or [("found", "principal")]
    treatments = [
        {
            "treatment_id": f"TREAT-{index:04d}",
            "status": status,
            "locator_class": locator_class,
        }
        for index, (status, locator_class) in enumerate(statuses, start=1)
    ]
    return {
        "locators": locators,
        "locator_original": len(locators) + len(locator_not_measured or []),
        "locator_not_measured": list(locator_not_measured or []),
        "locator_not_measured_units": ["CHUNK-001"] * len(locator_not_measured or []),
        "treatments": treatments,
        "treatment_original": len(treatments),
        "treatment_not_measured": [],
        "defects": list(defects or []),
        "source_units": ["CHUNK-001"],
        "context": {"candidate_attempt": {"status": attempt, "evidence_ids": []}},
    }


def v6_items(calculation: dict, root: Path, locator: dict, structure: dict) -> dict:
    base = minimal_item_assessments(calculation, root / "item-inventory.json")
    inventory = json.loads((root / "item-inventory.json").read_text(encoding="utf-8"))
    inventory_paths = {item["path_id"]: item for item in inventory["paths"]}
    for path in base["path_assessments"]:
        inventory_path = inventory_paths[path["path_id"]]
        path["locator_ids"] = inventory_path["locator_ids"]
        path["component_results"] = [{
            "dimension_id": "page_reference_reliability",
            "score": 100.0,
            "weight": 0.25,
            "measurement_status": "measured",
            "severity_caps": [],
            "applied_cap": None,
            "summary": "Synthetic V5 path-level locator diagnostic.",
            "evidence_ids": inventory_path["locator_ids"],
        }]
    return item_grades.build_v6_assessments(base, [locator], structure)


class LocatorCreditPolicyTests(unittest.TestCase):
    def test_all_credit_tiers_and_diagnostic_grades(self) -> None:
        cases = (
            (locator_state("supported", "substantive"), "1", 100.0),
            (locator_state("partially_supported", "mixed"), "0.5", 70.0),
            (
                locator_state(
                    "partially_supported", "passing_mention", codes=["CON", "LOC_POS"]
                ),
                "0.5",
                70.0,
            ),
            (locator_state("unsupported", "passing_mention"), "0.25", 25.0),
            (locator_state("unsupported", "absent", codes=["LOC_POS"]), "0", 0.0),
            (locator_state("uninspectable", "unavailable", scope="unavailable"), None, None),
        )
        for record, expected_credit, expected_grade in cases:
            with self.subTest(record=record):
                assignment = assign_locator_credit(record)
                self.assertEqual(expected_credit, assignment.as_dict()["reliability_credit"])
                self.assertEqual(expected_grade, assignment.diagnostic_grade)

    def test_partial_support_accepts_each_relevant_treatment_class_and_diagnostic_code(self) -> None:
        for treatment in (
            "substantive",
            "mixed",
            "passing_mention",
            "attribution_only",
            "citation_only",
            "incidental_example",
        ):
            for code in ("SCP", "CMP", "CON", "STA"):
                with self.subTest(treatment=treatment, code=code):
                    assignment = assign_locator_credit(
                        locator_state("partially_supported", treatment, codes=[code])
                    )
                    self.assertEqual("partially_supported", assignment.credit_tier)
                    self.assertEqual(Decimal("0.50"), assignment.reliability_credit)
                    self.assertEqual(70.0, assignment.diagnostic_grade)
                    self.assertEqual((), assignment.disqualifying_codes)

    def test_each_weak_presence_class_is_quarter_credit(self) -> None:
        for treatment in (
            "passing_mention",
            "attribution_only",
            "citation_only",
            "incidental_example",
        ):
            with self.subTest(treatment=treatment):
                assignment = assign_locator_credit(locator_state("unsupported", treatment))
                self.assertEqual(Decimal("0.25"), assignment.reliability_credit)
                self.assertEqual(25.0, assignment.diagnostic_grade)

    def test_wrong_sense_relationship_or_stance_is_zero_despite_surface_presence(self) -> None:
        for defect_kind, code in (
            ("wrong_sense", "CON"),
            ("false_relationship", "CON"),
            ("stance_reversal", "STA"),
        ):
            with self.subTest(defect_kind=defect_kind):
                assignment = assign_locator_credit(locator_state(
                    "unsupported", "passing_mention", codes=[code]
                ))
                self.assertEqual(Decimal(0), assignment.reliability_credit)
                self.assertIn(code, assignment.disqualifying_codes)

    def test_every_independent_weak_presence_disqualifier_forces_zero(self) -> None:
        for code in ("SCP", "CMP", "CON", "STA"):
            with self.subTest(code=code):
                assignment = assign_locator_credit(
                    locator_state("unsupported", "incidental_example", codes=[code])
                )
                self.assertEqual(Decimal(0), assignment.reliability_credit)
                self.assertEqual("other_unsupported", assignment.credit_tier)
                self.assertIn(code, assignment.disqualifying_codes)

    def test_scope_and_compound_failures_are_zero(self) -> None:
        out_of_scope = assign_locator_credit(
            locator_state("unsupported", "absent", scope="excluded", codes=["SCP"])
        )
        compound = assign_locator_credit(
            locator_state("unsupported", "incidental_example", codes=["CMP"])
        )
        self.assertEqual(Decimal(0), out_of_scope.reliability_credit)
        self.assertEqual(Decimal(0), compound.reliability_credit)

    def test_structured_nonexistent_defect_has_zero_precedence(self) -> None:
        record = locator_state("unsupported", "passing_mention")
        defect = {
            "defect_id": "DEFECT-1",
            "dimension_owner": "page_reference_reliability",
            "defect_kind": "nonexistent_locator",
            "affected_item_ids": ["LOC-TEST"],
        }
        assignment = assign_locator_credit(record, [defect])
        self.assertEqual(Decimal(0), assignment.reliability_credit)
        self.assertEqual(("DEFECT-1",), assignment.disqualifying_defect_ids)

    def test_structured_disqualifying_code_reduces_only_unsupported_weak_presence_to_zero(self) -> None:
        record = locator_state("unsupported", "citation_only")
        defect = {
            "defect_id": "DEFECT-STA",
            "code": "STA",
            "dimension_owner": "conceptual_stance_fidelity",
            "defect_kind": "stance_reversal",
            "affected_item_ids": ["LOC-TEST"],
        }
        assignment = assign_locator_credit(record, [defect])
        self.assertEqual(Decimal(0), assignment.reliability_credit)
        self.assertEqual(("STA",), assignment.disqualifying_codes)
        self.assertEqual(("DEFECT-STA",), assignment.disqualifying_defect_ids)

        partial = assign_locator_credit(
            locator_state("partially_supported", "citation_only"), [defect]
        )
        self.assertEqual(Decimal("0.50"), partial.reliability_credit)
        self.assertEqual((), partial.disqualifying_codes)
        self.assertEqual((), partial.disqualifying_defect_ids)

        supported = assign_locator_credit(
            locator_state("supported", "substantive"), [defect]
        )
        self.assertEqual(Decimal("1.00"), supported.reliability_credit)
        self.assertEqual((), supported.disqualifying_codes)
        self.assertEqual((), supported.disqualifying_defect_ids)

    def test_inconsistent_states_are_rejected_by_schema_and_runtime(self) -> None:
        inconsistent = locator_state("supported", "passing_mention")
        schema = json.loads((SCHEMAS / "locator-evidence-state-v2.schema.json").read_text())
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(inconsistent, schema)
        self.assertIn(
            "inconsistent:supported_judgment_requires_material_treatment",
            combined_state_errors(inconsistent),
        )
        self.assertIn("missing:error_codes", combined_state_errors({"locator_id": "LOC-X"}))
        for treatment in (
            "substantive",
            "mixed",
            "passing_mention",
            "attribution_only",
            "citation_only",
            "incidental_example",
        ):
            jsonschema.validate(
                locator_state("partially_supported", treatment, codes=["STA"]), schema
            )
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(locator_state("partially_supported", "absent"), schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(locator_state("unsupported", "substantive"), schema)


class WeightedPrecisionIntegrationTests(unittest.TestCase):
    def test_all_supported_and_all_partial(self) -> None:
        for judgment, treatment, weighted, strict in (
            ("supported", "substantive", "1", "1"),
            ("partially_supported", "mixed", "0.5", "0"),
        ):
            with self.subTest(judgment=judgment), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                locator, missing, structure = base_documents()
                set_all_locators(locator, judgment, treatment)
                result = calculate(root, locator, missing, structure)
                provenance = dimension(result, "page_reference_reliability")[
                    "reliability_provenance"
                ]
                self.assertEqual(weighted, provenance["weighted_locator_precision"])
                self.assertEqual(strict, provenance["strict_substantive_precision"])

    def test_each_weak_class_has_zero_selectivity(self) -> None:
        for treatment in (
            "passing_mention",
            "attribution_only",
            "citation_only",
            "incidental_example",
        ):
            with self.subTest(treatment=treatment), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                locator, missing, structure = base_documents()
                set_all_locators(locator, "unsupported", treatment)
                result = calculate(root, locator, missing, structure)
                reliability = dimension(result, "page_reference_reliability")
                selectivity = dimension(result, "editorial_selectivity")
                self.assertEqual(
                    "0.25", reliability["reliability_provenance"]["weighted_locator_precision"]
                )
                self.assertEqual(
                    "0", reliability["reliability_provenance"]["strict_substantive_precision"]
                )
                substantive = next(
                    item
                    for item in selectivity["components"]
                    if item["component_id"] == "substantive_selectivity"
                )
                self.assertEqual("0", substantive["normalized_value"])

    def test_completely_absent_is_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            set_all_locators(locator, "unsupported", "absent", ["LOC_POS"])
            result = calculate(root, locator, missing, structure)
            provenance = dimension(result, "page_reference_reliability")[
                "reliability_provenance"
            ]
            self.assertEqual("0", provenance["weighted_locator_precision"])
            items = v6_items(result, root, locator, structure)
            self.assertTrue(all(item["grade"]["score"] == 0 for item in items["locator_assessments"]))

    def test_one_locator_in_each_tier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            states = (
                ("supported", "substantive", []),
                ("partially_supported", "mixed", []),
                ("unsupported", "passing_mention", []),
                ("unsupported", "absent", ["LOC_POS"]),
            )
            for record, (judgment, treatment, codes) in zip(locator["judgments"], states, strict=True):
                record.update(
                    judgment=judgment,
                    treatment_class=treatment,
                    error_codes=codes,
                    severity="none" if judgment != "unsupported" else "minor",
                )
            result = calculate(root, locator, missing, structure)
            provenance = dimension(result, "page_reference_reliability")[
                "reliability_provenance"
            ]
            self.assertEqual("1.75", provenance["weighted_precision_numerator"])
            self.assertEqual("0.4375", provenance["weighted_locator_precision"])
            self.assertEqual("0.25", provenance["strict_substantive_precision"])
            self.assertEqual(
                ["0", "0.25", "0.5", "1"],
                sorted(
                    item["reliability_credit"]
                    for item in provenance["locator_credit_assignments"]
                ),
            )

    def test_result_contains_reconstructable_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = calculate(root, *base_documents())
            provenance = dimension(result, "page_reference_reliability")[
                "reliability_provenance"
            ]
            required = {
                "original_locator_denominator",
                "assessable_locator_denominator",
                "uninspectable_locator_count",
                "not_measured_locator_count",
                "counts_by_judgment",
                "counts_by_treatment_class",
                "counts_by_reliability_credit_tier",
                "locator_credit_assignments",
                "weighted_precision_numerator",
                "weighted_precision_denominator",
                "weighted_locator_precision",
                "strict_precision_numerator",
                "strict_precision_denominator",
                "strict_substantive_precision",
                "treatment_recall_numerator",
                "treatment_recall_denominator",
                "weighted_f1",
                "cap_evaluations",
                "uncertainty_lower",
                "uncertainty_upper",
                "rounding",
                "final_rating",
                "dimension_weight",
                "awarded_points",
            }
            self.assertTrue(required.issubset(provenance))
            self.assertEqual(
                provenance["original_locator_denominator"],
                len(provenance["locator_credit_assignments"]),
            )


class ArithmeticUncertaintyAndCapTests(unittest.TestCase):
    def test_recall_one_weighted_precision_cases(self) -> None:
        cases = (
            (locator_state("supported", "substantive"), "1", "1", "5"),
            (locator_state("partially_supported", "mixed"), "0.5", "0.6666666666666666666666666667", "3.333333333333333333333333334"),
            (locator_state("unsupported", "passing_mention"), "0.25", "0.4", "2"),
            (locator_state("unsupported", "absent", codes=["LOC_POS"]), "0", "0", "0"),
        )
        for state, precision, weighted_f1, base in cases:
            with self.subTest(precision=precision):
                result = v6.calculate_reliability(reliability_ledgers([state]), "full")
                provenance = result["reliability_provenance"]
                self.assertEqual(precision, provenance["weighted_locator_precision"])
                self.assertEqual(weighted_f1, provenance["weighted_f1"])
                self.assertEqual(base, result["base_rating"])

    def test_zero_recall_and_zero_precision_plus_recall(self) -> None:
        supported = locator_state("supported", "substantive")
        zero_recall = v6.calculate_reliability(
            reliability_ledgers([supported], [("missed", "principal")]), "full"
        )
        self.assertEqual("0", zero_recall["base_rating"])
        both_zero = v6.calculate_reliability(
            reliability_ledgers(
                [locator_state("unsupported", "absent", codes=["LOC_POS"])],
                [("missed", "principal")],
            ),
            "full",
        )
        self.assertEqual("0", both_zero["reliability_provenance"]["weighted_f1"])
        self.assertEqual("0", both_zero["base_rating"])

    def test_empty_candidate_and_expected_treatments_without_assessable_locators(self) -> None:
        empty = v6.calculate_reliability(
            reliability_ledgers([], [("found", "principal")], attempt="empty"), "full"
        )
        self.assertEqual("0", empty["base_rating"])
        self.assertTrue(
            all(
                item["defined_zero_rule"]
                for item in empty["denominators"]["components"]
            )
        )
        unknown = v6.calculate_reliability(
            reliability_ledgers(
                [locator_state("uninspectable", "unavailable", scope="unavailable")]
            ),
            "full",
        )
        provenance = unknown["reliability_provenance"]
        self.assertEqual(0, provenance["assessable_locator_denominator"])
        self.assertEqual("0", provenance["weighted_precision_uncertainty"]["central"])
        self.assertEqual("1", provenance["weighted_precision_uncertainty"]["upper"])

    def test_uninspectable_bounds_can_change_rounding(self) -> None:
        states = [locator_state("supported", "substantive", locator_id=f"LOC-{i}") for i in range(3)]
        states.append(locator_state("uninspectable", "unavailable", scope="unavailable", locator_id="LOC-U"))
        result = v6.calculate_reliability(reliability_ledgers(states), "full")
        provenance = result["reliability_provenance"]
        self.assertEqual("0.75", provenance["weighted_precision_uncertainty"]["lower"])
        self.assertEqual("1", provenance["weighted_precision_uncertainty"]["central"])
        self.assertEqual("1", provenance["weighted_precision_uncertainty"]["upper"])
        self.assertFalse(result["missing_data_bounds"]["stable_rating"])
        self.assertEqual("not_scored_insufficient_evidence", result["status"])

    def test_uncertainty_can_change_cap_identity(self) -> None:
        result = v6.calculate_reliability(
            reliability_ledgers(
                [locator_state("supported", "substantive")],
                [("uninspectable", "principal")],
            ),
            "full",
        )
        bounds = result["missing_data_bounds"]
        self.assertNotEqual(
            bounds["lower"]["applied_cap_id"], bounds["upper"]["applied_cap_id"]
        )
        self.assertFalse(bounds["stable_cap_outcome"])
        self.assertIsNone(result["final_rating"])

    def test_decimal_half_up_immediately_around_every_half_step(self) -> None:
        epsilon = Decimal("0.0000001")
        for boundary in (Decimal("0.25"), Decimal("0.75"), Decimal("1.25"), Decimal("1.75"), Decimal("2.25"), Decimal("2.75"), Decimal("3.25"), Decimal("3.75"), Decimal("4.25"), Decimal("4.75")):
            with self.subTest(boundary=boundary):
                lower = v5.round_half_step(boundary - epsilon)
                exact = v5.round_half_step(boundary)
                upper = v5.round_half_step(boundary + epsilon)
                self.assertEqual(boundary - Decimal("0.25"), lower)
                self.assertEqual(boundary + Decimal("0.25"), exact)
                self.assertEqual(exact, upper)

    def test_existing_high_value_and_distributed_caps_are_unchanged(self) -> None:
        self.assertEqual((Decimal(4), True, "75_to_below_90_percent"), v5.high_value_cap(3, 4))
        self.assertEqual(
            (Decimal("3.5"), True, "7_5_to_below_15_percent"),
            v5.reliability_pattern_cap(10, 100, 1, 4),
        )

        high_value = v6.calculate_reliability(
            reliability_ledgers(
                [locator_state("supported", "substantive")],
                [
                    ("found", "principal"),
                    ("found", "principal"),
                    ("found", "synthesis_or_conclusion"),
                    ("missed", "principal"),
                ],
            ),
            "full",
        )
        self.assertEqual(
            "reliability.high_value_treatment_recall", high_value["applied_cap"]["cap_id"]
        )
        self.assertEqual(4, high_value["final_rating"])

        pattern = v6.calculate_reliability(
            reliability_ledgers([
                locator_state(
                    "unsupported",
                    "passing_mention",
                    codes=["LOC_POS"],
                    locator_id=f"LOC-{index:04d}",
                )
                for index in range(1, 11)
            ]),
            "full",
        )
        self.assertEqual("0.25", pattern["reliability_provenance"]["weighted_locator_precision"])
        self.assertEqual(
            "reliability.distributed_unsupported_pattern", pattern["applied_cap"]["cap_id"]
        )
        self.assertEqual(1.5, pattern["final_rating"])

    def test_critical_false_destination_cap_still_applies(self) -> None:
        for defect_kind in (
            "fabricated_locator",
            "nonexistent_locator",
            "out_of_scope_locator",
        ):
            with self.subTest(defect_kind=defect_kind):
                defect = {
                    "defect_id": "DEFECT-CRITICAL",
                    "dimension_owner": "page_reference_reliability",
                    "severity": "critical",
                    "defect_kind": defect_kind,
                }
                result = v6.calculate_reliability(
                    reliability_ledgers(
                        [locator_state("supported", "substantive")], defects=[defect]
                    ),
                    "full",
                )
                self.assertEqual(
                    "reliability.critical_locator", result["applied_cap"]["cap_id"]
                )
                self.assertEqual(2, result["final_rating"])


class DiagnosticProjectionMigrationAndCompatibilityTests(unittest.TestCase):
    def test_diagnostic_grades_and_complete_path_use_v6_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            states = (
                ("supported", "substantive", []),
                ("partially_supported", "mixed", []),
                ("unsupported", "passing_mention", []),
                ("unsupported", "absent", ["LOC_POS"]),
            )
            for record, (judgment, treatment, codes) in zip(locator["judgments"], states, strict=True):
                record.update(judgment=judgment, treatment_class=treatment, error_codes=codes)
            calculation = calculate(root, locator, missing, structure)
            items = v6_items(calculation, root, locator, structure)
            scores = sorted(item["grade"]["score"] for item in items["locator_assessments"])
            self.assertEqual([0.0, 25.0, 70.0, 100.0], scores)
            weak = next(item for item in items["locator_assessments"] if item["grade"]["score"] == 25)
            for phrase in (
                "only weakly",
                "not substantive index treatment",
                "editorially unjustified",
                "wholly false destination",
            ):
                self.assertIn(phrase, weak["popover"]["summary"].lower())
            path_factor = next(
                factor
                for path in items["path_assessments"]
                for factor in path["component_results"]
                if factor["dimension_id"] == "page_reference_reliability"
            )
            self.assertIn("100/70/25/0", path_factor["summary"])
            v5.validate_schema_document(items, "item-assessments-v3.schema.json", "V6 items")

    def test_failed_gate_is_preserved_despite_quarter_credit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            set_all_locators(locator, "unsupported", "passing_mention")
            calculation = calculate(root, locator, missing, structure)
            calculation_path = root / "calculation.v2.json"
            v6.write_json(calculation_path, calculation)
            items = v6_items(calculation, root, locator, structure)
            items_path = root / "item-assessments.v3.json"
            v6.write_json(items_path, items)
            gates = [{"gate_id": "systematic_incidental", "status": "failed"}]
            metadata = {
                "schema_version": "subject-index-v6-projection-metadata-v1",
                "candidate_label": "Synthetic",
                "inclusion_policy": "standard",
                "uncertainty_policy": "v6_bounds",
                "critical_gates": gates,
            }
            metadata_path = root / "metadata.json"
            v6.write_json(metadata_path, metadata)
            result_path = root / "result.v7.json"
            web_path = root / "web.v5.json"
            result, web = v6.build_projections(
                calculation_path, items_path, metadata_path, result_path, web_path
            )
            v6.write_json(result_path, result)
            v6.write_json(web_path, web)
            validation = v6.validate_projection_artifacts(
                calculation_path, result_path, web_path
            )
            self.assertTrue(validation["ok"])
            self.assertFalse(validation["migration_validated"])
            self.assertEqual(gates, result["critical_gates"])
            self.assertEqual(gates, web["gate_status"]["critical_gates"])
            self.assertEqual(0, items["locator_grading_provenance"]["weak_presence_selectivity_credit"])

    def test_counterfactual_score_view_is_built_and_fully_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canonical_root = root / "canonical"
            adjusted_root = root / "adjusted"
            canonical_root.mkdir()
            adjusted_root.mkdir()
            locator, missing, structure = base_documents()
            calculation = calculate(canonical_root, locator, missing, structure)
            calculation_path = canonical_root / "dimension-calculations.v2.json"
            v6.write_json(calculation_path, calculation)
            items = v6_items(calculation, canonical_root, locator, structure)
            items_path = canonical_root / "item-assessments.v3.json"
            v6.write_json(items_path, items)

            adjusted_locator = copy.deepcopy(locator)
            adjusted_locator["judgments"][0].update(
                judgment="unsupported",
                treatment_class="passing_mention",
                error_codes=[],
                severity="minor",
            )
            adjusted = calculate(
                adjusted_root,
                adjusted_locator,
                copy.deepcopy(missing),
                copy.deepcopy(structure),
            )
            adjusted_path = adjusted_root / "dimension-calculations.v2.json"
            v6.write_json(adjusted_path, adjusted)
            provenance_path = root / "representation-correction-ledger.json"
            write_json(
                provenance_path,
                {
                    "schema_version": "synthetic-representation-correction-v1",
                    "status": "frozen",
                },
            )
            metadata_path = root / "metadata.json"
            v6.write_json(
                metadata_path,
                {
                    "schema_version": "subject-index-v6-projection-metadata-v1",
                    "candidate_label": "Synthetic",
                    "inclusion_policy": "standard",
                    "uncertainty_policy": "v6_bounds",
                    "critical_gates": [],
                    "counterfactual_score_views": [
                        {
                            "view_id": "representation_adjusted",
                            "label": "Representation adjusted",
                            "calculation": {
                                "schema_version": "subject-index-dimension-calculations-v2",
                                "artifact_path": v5.portable_relative_reference(
                                    adjusted_path,
                                    metadata_path,
                                    label="adjusted calculation",
                                ),
                                "sha256": digest(adjusted_path),
                                "calculation_sha256": adjusted["calculation_sha256"],
                                "rubric_version": "subject-index-rubric-v6",
                                "calculation_profile": "subject-index-dimension-calculation-v2",
                            },
                            "provenance_artifacts": [
                                {
                                    "role": "character_fidelity_correction_ledger",
                                    "schema_version": "synthetic-representation-correction-v1",
                                    "artifact_path": v5.portable_relative_reference(
                                        provenance_path,
                                        metadata_path,
                                        label="representation provenance",
                                    ),
                                    "sha256": digest(provenance_path),
                                }
                            ],
                        }
                    ],
                },
            )
            result_path = root / "evaluation-result.v7.json"
            web_path = root / "web-report.v5.json"
            result, web = v6.build_projections(
                calculation_path,
                items_path,
                metadata_path,
                result_path,
                web_path,
            )
            self.assertEqual(
                "separate_evidentiary_correction",
                web["score_views"]["adjustment_status"],
            )
            self.assertEqual(
                ["canonical_as_delivered", "representation_adjusted"],
                [view["view_id"] for view in web["score_views"]["views"]],
            )
            adjusted_view = web["score_views"]["views"][1]
            self.assertEqual(adjusted["total_score"], adjusted_view["score"])
            self.assertEqual(
                "separate_evidentiary_correction_not_methodology_effect",
                adjusted_view["causal_attribution"],
            )
            v6.write_json(result_path, result)
            v6.write_json(web_path, web)
            validation = v6.validate_projection_artifacts(
                calculation_path, result_path, web_path
            )
            self.assertEqual(2, validation["score_views_validated"])
            self.assertEqual(
                ["representation_adjusted"],
                validation["counterfactual_score_views_validated"],
            )

            missing_calculation = copy.deepcopy(web)
            missing_reference = missing_calculation["score_views"]["views"][1][
                "calculation"
            ]
            missing_reference["artifact_path"] = "missing-adjusted-calculation.json"
            missing_reference["sha256"] = "1" * 64
            v6.write_json(web_path, missing_calculation)
            with self.assertRaises(v5.CalculationError) as missing_error:
                v6.validate_projection_artifacts(
                    calculation_path, result_path, web_path
                )
            self.assertEqual("projection_binding_mismatch", missing_error.exception.code)

            missing_provenance = copy.deepcopy(web)
            provenance_reference = missing_provenance["score_views"]["views"][1][
                "provenance_artifacts"
            ][0]
            provenance_reference["artifact_path"] = "missing-provenance.json"
            provenance_reference["sha256"] = "2" * 64
            v6.write_json(web_path, missing_provenance)
            with self.assertRaises(v5.CalculationError) as provenance_error:
                v6.validate_projection_artifacts(
                    calculation_path, result_path, web_path
                )
            self.assertEqual("projection_binding_mismatch", provenance_error.exception.code)

    def test_v4_and_v5_historical_contracts_remain_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            config = calculation_files(root, locator, missing, structure)
            old = v5.calculate_loaded(v5.load_inputs(config))
            v5.validate_schema_document(old, "dimension-calculations.schema.json", "Historical V5")
            self.assertEqual("subject-index-rubric-v5", old["rubric_version"])
            historical_v4 = {
                "schema_version": "subject-index-evaluation-result-v5",
                "evaluation_id": "history",
                "candidate": {"label": "Historical", "sha256": "a" * 64},
                "provenance": {"source_sha256": "b" * 64, "policy_sha256": "c" * 64, "benchmark_sha256": "d" * 64, "page_map_sha256": "e" * 64, "chunk_manifest_sha256": "f" * 64, "normalized_candidate_file_sha256": "1" * 64, "item_inventory_file_sha256": "2" * 64, "rubric_version": "subject-index-rubric-v4"},
                "audit_scope": {"mode": "full", "complete": True},
                "scorecard": [{"dimension_id": dimension_id, "label": dimension_id, "weight": weight, "rating": 5, "points": weight, "rationale": "history", "evidence_ids": []} for dimension_id, weight in v5.WEIGHTS.items()],
                "total_score": 100,
                "interpretation": "history",
                "metrics": {},
                "item_assessments": {"schema_version": "subject-index-item-assessments-v1", "grading_policy": "subject-index-item-grading-v1", "artifact_path": "items.json", "sha256": "3" * 64, "summary": {}},
                "critical_gates": [],
                "defect_counts": {},
                "comparison_key": {},
                "limitations": [],
            }
            v5.validate_schema_document(historical_v4, "evaluation-result.schema.json", "Historical V4")

    def test_score_only_migration_preserves_frozen_bytes_and_builds_web_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            locator["judgments"][0].update(
                judgment="unsupported", treatment_class="passing_mention", error_codes=[]
            )
            config = calculation_files(root, locator, missing, structure)
            old_calculation = v5.calculate_loaded(v5.load_inputs(config))
            old_calculation_path = root / "dimension-calculations.v1.json"
            v6.write_json(old_calculation_path, old_calculation)
            old_items = minimal_item_assessments(old_calculation, root / "item-inventory.json")
            old_items_path = root / "item-assessments.v2.json"
            v6.write_json(old_items_path, old_items)
            gates = [{"gate_id": "systematic_incidental", "status": "failed"}]
            old_result = evaluation_projection(
                old_calculation, old_calculation_path, old_items_path, gates
            )
            old_result_path = root / "evaluation-result.v6.json"
            v6.write_json(old_result_path, old_result)
            old_web = web_projection(old_calculation, old_calculation_path, old_items_path, gates)
            old_web_path = root / "web-report.v4.json"
            v6.write_json(old_web_path, old_web)
            frozen_paths = [
                config,
                old_calculation_path,
                old_items_path,
                old_result_path,
                old_web_path,
                *v5.load_inputs(config)["input_paths"],
            ]
            before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in frozen_paths}
            new_calculation_path = root / "dimension-calculations.v2.json"
            migration_path = root / "score-migration.v5-to-v6.json"
            migrated = run_cli(
                "dimension_score_v6_cli.py",
                "score-only-migration",
                "--input",
                config,
                "--historical-calculation",
                old_calculation_path,
                "--historical-result",
                old_result_path,
                "--historical-web-report",
                old_web_path,
                "--calculations-output",
                new_calculation_path,
                "--migration-record-output",
                migration_path,
                "--methodology-commit",
                "1" * 40,
                "--migration-timestamp",
                "2026-08-29T12:00:00Z",
            )
            self.assertFalse(migrated["frozen_evidence_mutated"])
            self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in frozen_paths})
            migration = json.loads(migration_path.read_text())
            self.assertEqual(v6.TOOL_VERSION, migration["tool"]["version"])
            self.assertEqual(
                {
                    "path": ".",
                    "resolution": "migration_record_relative_ancestor_v1",
                },
                migration["artifact_path_root"],
            )
            for historical_tool_version in (
                "dimension-score-cli-v6.0.0",
                "dimension-score-cli-v6.0.1",
                "dimension-score-cli-v6.0.2",
            ):
                historical_migration = copy.deepcopy(migration)
                historical_migration["tool"]["version"] = historical_tool_version
                historical_migration.pop("artifact_path_root")
                v5.validate_schema_document(
                    historical_migration,
                    "score-migration-v5-to-v6.schema.json",
                    f"Historical {historical_tool_version} migration",
                )
            missing_current_root = copy.deepcopy(migration)
            missing_current_root.pop("artifact_path_root")
            with self.assertRaises(v5.CalculationError) as missing_root:
                v5.validate_schema_document(
                    missing_current_root,
                    "score-migration-v5-to-v6.schema.json",
                    "Current migration without artifact root",
                )
            self.assertEqual(
                "input_schema_validation_failed", missing_root.exception.code
            )
            self.assertTrue(migration["precision_comparison"]["strict_precision_unchanged"])
            self.assertEqual(gates, migration["gate_preservation"]["preserved_outcomes"])
            self.assertFalse(migration["invalidation"]["upstream_evidence_invalidated"])

            new_calculation = json.loads(new_calculation_path.read_text())
            new_items_path = root / "item-assessments.v3.json"
            upgraded = run_cli(
                "item_grade_cli.py",
                "upgrade-v6-assessments",
                "--item-assessments",
                old_items_path,
                "--locator-audit",
                root / "locator.json",
                "--structure-audit",
                root / "structure.json",
                "--output",
                new_items_path,
            )
            self.assertEqual("subject-index-item-assessments-v3", upgraded["schema_version"])
            new_items = json.loads(new_items_path.read_text())
            metadata_path = root / "projection-metadata.json"
            v6.write_json(
                metadata_path,
                {
                    "schema_version": "subject-index-v6-projection-metadata-v1",
                    "candidate_label": "Synthetic",
                    "inclusion_policy": "standard",
                    "uncertainty_policy": "v6_bounds",
                    "critical_gates": gates,
                },
            )
            result_path = root / "evaluation-result.v7.json"
            web_path = root / "web-report.v5.json"
            result, web = v6.build_projections(
                new_calculation_path,
                new_items_path,
                metadata_path,
                result_path,
                web_path,
                migration_path,
            )
            v6.write_json(result_path, result)
            v6.write_json(web_path, web)
            validation = v6.validate_projection_artifacts(
                new_calculation_path, result_path, web_path
            )
            self.assertTrue(validation["ok"])
            self.assertEqual(
                result["metrics"]["locator_precision"], web["precision_diagnostics"]
            )
            self.assertEqual("v5_to_v6", web["migration_comparison"]["status"])

    def test_sibling_v5_v6_layout_is_rooted_contained_and_deterministic(self) -> None:
        def migrate_layout(layout_root: Path) -> dict[str, bytes]:
            historical_root = layout_root / "candidate" / "v5-migration"
            migrated_root = layout_root / "candidate" / "v6-migration"
            historical_root.mkdir(parents=True)
            migrated_root.mkdir(parents=True)
            locator, missing, structure = base_documents()
            locator["judgments"][0].update(
                judgment="unsupported",
                treatment_class="passing_mention",
                error_codes=[],
            )
            config = calculation_files(historical_root, locator, missing, structure)
            old_calculation = v5.calculate_loaded(v5.load_inputs(config))
            old_calculation_path = historical_root / "dimension-calculations.v1.json"
            v6.write_json(old_calculation_path, old_calculation)
            old_items = minimal_item_assessments(
                old_calculation, historical_root / "item-inventory.json"
            )
            old_items_path = historical_root / "item-assessments.v2.json"
            v6.write_json(old_items_path, old_items)
            gates = [{"gate_id": "systematic_incidental", "status": "failed"}]
            old_result_path = historical_root / "evaluation-result.v6.json"
            v6.write_json(
                old_result_path,
                evaluation_projection(
                    old_calculation,
                    old_calculation_path,
                    old_items_path,
                    gates,
                ),
            )
            old_web_path = historical_root / "web-report.v4.json"
            v6.write_json(
                old_web_path,
                web_projection(
                    old_calculation,
                    old_calculation_path,
                    old_items_path,
                    gates,
                ),
            )
            new_calculation_path = migrated_root / "dimension-calculations.v2.json"
            migration_path = migrated_root / "score-migration.v5-to-v6.v1.json"
            run_cli(
                "dimension_score_v6_cli.py",
                "score-only-migration",
                "--input",
                config,
                "--historical-calculation",
                old_calculation_path,
                "--historical-result",
                old_result_path,
                "--historical-web-report",
                old_web_path,
                "--calculations-output",
                new_calculation_path,
                "--migration-record-output",
                migration_path,
                "--methodology-commit",
                "1" * 40,
                "--migration-timestamp",
                "2026-08-29T20:14:39Z",
            )
            migration = json.loads(migration_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "path": "..",
                    "resolution": "migration_record_relative_ancestor_v1",
                },
                migration["artifact_path_root"],
            )
            self.assertEqual(
                "v5-migration/dimension-calculations.v1.json",
                migration["from"]["calculation"]["path"],
            )
            self.assertEqual(
                "v6-migration/dimension-calculations.v2.json",
                migration["to"]["calculation"]["path"],
            )
            for reference in (
                migration["from"]["calculation"],
                migration["from"]["evaluation_result"],
                migration["from"]["item_assessments"],
                migration["from"]["web_report"],
                migration["to"]["calculation"],
            ):
                self.assertNotIn("..", Path(reference["path"]).parts)

            new_items_path = migrated_root / "item-assessments.v3.json"
            run_cli(
                "item_grade_cli.py",
                "upgrade-v6-assessments",
                "--item-assessments",
                old_items_path,
                "--locator-audit",
                historical_root / "locator.json",
                "--structure-audit",
                historical_root / "structure.json",
                "--output",
                new_items_path,
            )
            metadata_path = migrated_root / "projection-metadata.json"
            v6.write_json(
                metadata_path,
                {
                    "schema_version": "subject-index-v6-projection-metadata-v1",
                    "candidate_label": "Synthetic",
                    "inclusion_policy": "standard",
                    "uncertainty_policy": "v6_bounds",
                    "critical_gates": gates,
                },
            )
            result_path = migrated_root / "evaluation-result.v7.json"
            web_path = migrated_root / "web-report.v5.json"
            result, web = v6.build_projections(
                new_calculation_path,
                new_items_path,
                metadata_path,
                result_path,
                web_path,
                migration_path,
            )
            v6.write_json(result_path, result)
            v6.write_json(web_path, web)
            validation = v6.validate_projection_artifacts(
                new_calculation_path, result_path, web_path
            )
            self.assertTrue(validation["migration_validated"])
            return {
                path.name: path.read_bytes()
                for path in (
                    new_calculation_path,
                    migration_path,
                    new_items_path,
                    result_path,
                    web_path,
                )
            }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = migrate_layout(root / "layout-a")
            second = migrate_layout(root / "layout-b")
            self.assertEqual(first, second)

    def test_migration_artifact_root_rejects_nonancestor_and_root_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record_path = root / "candidate" / "v6-migration" / "migration.json"
            record_path.parent.mkdir(parents=True)
            record_path.write_text("{}", encoding="utf-8")
            with self.assertRaises(v5.CalculationError) as nonancestor:
                v6.migration_artifact_root(
                    {
                        "artifact_path_root": {
                            "path": "v5-migration",
                            "resolution": "migration_record_relative_ancestor_v1",
                        }
                    },
                    record_path,
                )
            self.assertEqual(
                "migration_artifact_root_invalid", nonancestor.exception.code
            )
            with self.assertRaises(v5.CalculationError) as traversal:
                v6.resolve_migration_artifact_path(
                    {}, "../outside.json", record_path, label="test.path"
                )
            self.assertEqual("nonportable_artifact_path", traversal.exception.code)

    def test_migration_requires_and_preserves_historical_counterfactual_view(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canonical_root = root / "canonical"
            adjusted_root = root / "adjusted"
            canonical_root.mkdir()
            adjusted_root.mkdir()
            locator, missing, structure = base_documents()
            config = calculation_files(canonical_root, locator, missing, structure)
            old_calculation = v5.calculate_loaded(v5.load_inputs(config))
            old_calculation_path = canonical_root / "dimension-calculations.v1.json"
            v6.write_json(old_calculation_path, old_calculation)
            old_items = minimal_item_assessments(
                old_calculation, canonical_root / "item-inventory.json"
            )
            old_items_path = canonical_root / "item-assessments.v2.json"
            v6.write_json(old_items_path, old_items)
            gates = [{"gate_id": "representation_test", "status": "failed"}]
            old_result = evaluation_projection(
                old_calculation, old_calculation_path, old_items_path, gates
            )
            old_result_path = canonical_root / "evaluation-result.v6.json"
            v6.write_json(old_result_path, old_result)

            adjusted_locator = copy.deepcopy(locator)
            adjusted_locator["judgments"][0].update(
                judgment="unsupported",
                treatment_class="passing_mention",
                error_codes=[],
                severity="minor",
            )
            adjusted_config = calculation_files(
                adjusted_root,
                adjusted_locator,
                copy.deepcopy(missing),
                copy.deepcopy(structure),
            )
            old_adjusted = v5.calculate_loaded(v5.load_inputs(adjusted_config))
            old_adjusted_path = adjusted_root / "dimension-calculations.v1.json"
            v6.write_json(old_adjusted_path, old_adjusted)
            provenance_path = root / "representation-correction-ledger.json"
            write_json(
                provenance_path,
                {
                    "schema_version": "synthetic-representation-correction-v1",
                    "status": "frozen",
                },
            )
            old_web_path = canonical_root / "web-report.v4.json"
            old_web = web_projection(
                old_calculation, old_calculation_path, old_items_path, gates
            )
            old_web["score_views"]["adjustment_status"] = (
                "separate_evidentiary_correction"
            )
            old_web["score_views"]["views"].append(
                {
                    "view_id": "representation_adjusted",
                    "label": "Representation adjusted",
                    "view_kind": "counterfactual",
                    "score": old_adjusted["total_score"],
                    "maximum": 100,
                    "calculation": {
                        "schema_version": "subject-index-dimension-calculations-v1",
                        "artifact_path": v5.portable_relative_reference(
                            old_adjusted_path,
                            old_web_path,
                            label="historical adjusted calculation",
                        ),
                        "sha256": digest(old_adjusted_path),
                        "calculation_sha256": old_adjusted["calculation_sha256"],
                        "rubric_version": "subject-index-rubric-v5",
                        "calculation_profile": "subject-index-dimension-calculation-v1",
                    },
                    "causal_attribution": (
                        "separate_evidentiary_correction_not_methodology_effect"
                    ),
                    "provenance_artifacts": [
                        {
                            "role": "character_fidelity_correction_ledger",
                            "schema_version": "synthetic-representation-correction-v1",
                            "artifact_path": v5.portable_relative_reference(
                                provenance_path,
                                old_web_path,
                                label="historical representation provenance",
                            ),
                            "sha256": digest(provenance_path),
                        }
                    ],
                }
            )
            v6.write_json(old_web_path, old_web)

            new_calculation_path = canonical_root / "dimension-calculations.v2.json"
            migration_path = canonical_root / "score-migration.v5-to-v6.json"
            run_cli(
                "dimension_score_v6_cli.py",
                "score-only-migration",
                "--input",
                config,
                "--historical-calculation",
                old_calculation_path,
                "--historical-result",
                old_result_path,
                "--historical-web-report",
                old_web_path,
                "--calculations-output",
                new_calculation_path,
                "--migration-record-output",
                migration_path,
                "--methodology-commit",
                "1" * 40,
                "--migration-timestamp",
                "2026-08-29T12:00:00Z",
            )
            new_calculation = json.loads(new_calculation_path.read_text())
            new_items_path = canonical_root / "item-assessments.v3.json"
            run_cli(
                "item_grade_cli.py",
                "upgrade-v6-assessments",
                "--item-assessments",
                old_items_path,
                "--locator-audit",
                canonical_root / "locator.json",
                "--structure-audit",
                canonical_root / "structure.json",
                "--output",
                new_items_path,
            )
            adjusted_v6 = v6.calculate_loaded(v5.load_inputs(adjusted_config))
            adjusted_v6_path = adjusted_root / "dimension-calculations.v2.json"
            v6.write_json(adjusted_v6_path, adjusted_v6)

            metadata_path = canonical_root / "projection-metadata.json"
            base_metadata = {
                "schema_version": "subject-index-v6-projection-metadata-v1",
                "candidate_label": "Synthetic",
                "inclusion_policy": "standard",
                "uncertainty_policy": "v6_bounds",
                "critical_gates": gates,
            }
            v6.write_json(metadata_path, base_metadata)
            result_path = canonical_root / "evaluation-result.v7.json"
            web_path = canonical_root / "web-report.v5.json"
            result, web = v6.build_projections(
                new_calculation_path,
                new_items_path,
                metadata_path,
                result_path,
                web_path,
                migration_path,
            )
            v6.write_json(result_path, result)
            v6.write_json(web_path, web)
            with self.assertRaises(v5.CalculationError) as omitted_error:
                v6.validate_projection_artifacts(
                    new_calculation_path, result_path, web_path
                )
            self.assertEqual(
                "migration_score_view_mismatch", omitted_error.exception.code
            )

            metadata = copy.deepcopy(base_metadata)
            metadata["counterfactual_score_views"] = [
                {
                    "view_id": "representation_adjusted",
                    "label": "Representation adjusted",
                    "calculation": {
                        "schema_version": "subject-index-dimension-calculations-v2",
                        "artifact_path": v5.portable_relative_reference(
                            adjusted_v6_path,
                            metadata_path,
                            label="V6 adjusted calculation",
                        ),
                        "sha256": digest(adjusted_v6_path),
                        "calculation_sha256": adjusted_v6["calculation_sha256"],
                        "rubric_version": "subject-index-rubric-v6",
                        "calculation_profile": "subject-index-dimension-calculation-v2",
                    },
                    "provenance_artifacts": [
                        {
                            "role": "character_fidelity_correction_ledger",
                            "schema_version": "synthetic-representation-correction-v1",
                            "artifact_path": v5.portable_relative_reference(
                                provenance_path,
                                metadata_path,
                                label="V6 representation provenance",
                            ),
                            "sha256": digest(provenance_path),
                        }
                    ],
                }
            ]
            v6.write_json(metadata_path, metadata)
            result, web = v6.build_projections(
                new_calculation_path,
                new_items_path,
                metadata_path,
                result_path,
                web_path,
                migration_path,
            )
            v6.write_json(result_path, result)
            v6.write_json(web_path, web)
            validation = v6.validate_projection_artifacts(
                new_calculation_path, result_path, web_path
            )
            self.assertTrue(validation["migration_validated"])
            self.assertEqual(
                ["representation_adjusted"],
                validation["counterfactual_score_views_validated"],
            )
            self.assertEqual(
                digest(provenance_path),
                web["score_views"]["views"][1]["provenance_artifacts"][0][
                    "sha256"
                ],
            )

    def test_migration_preflight_reports_missing_or_inconsistent_fields_without_inference(self) -> None:
        ledgers = reliability_ledgers(
            [locator_state("supported", "passing_mention")]
        )
        report = v6.locator_state_requirements(ledgers)
        self.assertEqual("inconsistent_or_incomplete_locator_state", report[0]["code"])
        self.assertIn("supported_judgment_requires_material_treatment", " ".join(report[0]["state_errors"]))

        clarified_positive_state = reliability_ledgers(
            [locator_state("partially_supported", "passing_mention", codes=["STA"])],
            defects=[{
                "defect_id": "DEFECT-STA",
                "code": "STA",
                "affected_item_ids": ["LOC-TEST"],
            }],
        )
        self.assertEqual([], v6.locator_state_requirements(clarified_positive_state))

        false_destination = reliability_ledgers(
            [locator_state("partially_supported", "passing_mention")],
            defects=[{
                "defect_id": "DEFECT-FALSE",
                "code": "SCP",
                "defect_kind": "nonexistent_locator",
                "affected_item_ids": ["LOC-TEST"],
            }],
        )
        report = v6.locator_state_requirements(false_destination)
        self.assertEqual("inconsistent_or_incomplete_locator_state", report[0]["code"])
        self.assertIn(
            "inconsistent:positive_judgment_with_false_destination",
            report[0]["state_errors"],
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = calculation_files(root, *base_documents())
            locator_path = root / "locator.json"
            locator = json.loads(locator_path.read_text(encoding="utf-8"))
            del locator["judgments"][0]["treatment_class"]
            write_json(locator_path, locator)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["inputs"]["locator_audits"][0]["sha256"] = digest(locator_path)
            write_json(config_path, config)
            payload = run_cli(
                "dimension_score_v6_cli.py",
                "migration-preflight",
                "--input",
                config_path,
                "--historical-calculation",
                root / "historical-calculation.json",
                "--historical-result",
                root / "historical-result.json",
                "--historical-web-report",
                root / "historical-web.json",
            )
            self.assertFalse(payload["sufficient"])
            self.assertEqual(
                "missing:treatment_class",
                payload["missing_requirements"][0]["state_errors"][0],
            )
            self.assertFalse(payload["source_reopened"])
            self.assertFalse(payload["prose_inference_used"])

    def test_full_mode_required_not_measured_locator_fails_v6_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            locator["expected_locator_ids"].append("LOC-MISSING")
            locator["completion"] = {
                "expected": len(locator["expected_locator_ids"]),
                "judged": len(locator["judgments"]),
                "unique": True,
                "complete": False,
            }
            structure["metrics"]["expanded_locators"] += 1
            structure["density"]["chapter_measurements"][0]["locator_occurrences"] += 1
            config = calculation_files(root, locator, missing, structure)
            payload = run_cli(
                "dimension_score_v6_cli.py", "preflight", "--input", config
            )
            self.assertFalse(payload["sufficient"])
            self.assertTrue(
                any(
                    item["code"] == "incomplete_full_audit"
                    for item in payload["missing_requirements"]
                )
            )

    def test_documented_sensitivity_and_adversarial_mixtures(self) -> None:
        cases = {
            "all_supported": (Decimal("1"), Decimal("1"), Decimal("1"), Decimal("5")),
            "all_partial": (
                Decimal("0.5"),
                Decimal("1"),
                Decimal("0.6666666666666666666666666667"),
                Decimal("3.5"),
            ),
            "all_weak": (Decimal("0.25"), Decimal("1"), Decimal("0.4"), Decimal("2")),
            "one_each": (
                Decimal("0.4375"),
                Decimal("1"),
                Decimal("0.6086956521739130434782608696"),
                Decimal("3"),
            ),
            "concordance_like": (
                Decimal("0.325"),
                Decimal("1"),
                Decimal("0.4905660377358490566037735849"),
                Decimal("2.5"),
            ),
            "high_relevance_poor_recall": (
                Decimal("0.9"),
                Decimal("0.25"),
                Decimal("0.3913043478260869565217391304"),
                Decimal("2"),
            ),
        }
        for name, (precision, recall, expected_f1, expected_rating) in cases.items():
            with self.subTest(name=name):
                weighted_f1 = v5.f1(precision, recall)
                self.assertEqual(expected_f1, weighted_f1)
                self.assertEqual(expected_rating, v5.round_half_step(Decimal(5) * weighted_f1))

        fabricated = v6.calculate_reliability(
            reliability_ledgers(
                [
                    *[
                        locator_state(
                            "supported", "substantive", locator_id=f"LOC-{index:04d}"
                        )
                        for index in range(1, 100)
                    ],
                    locator_state(
                        "unsupported", "absent", codes=["LOC_POS"], locator_id="LOC-0100"
                    ),
                ],
                defects=[{
                    "defect_id": "DEFECT-FABRICATED",
                    "dimension_owner": "page_reference_reliability",
                    "severity": "critical",
                    "defect_kind": "fabricated_locator",
                    "affected_item_ids": ["LOC-0100"],
                }],
            ),
            "full",
        )
        self.assertEqual("0.99", fabricated["reliability_provenance"]["weighted_locator_precision"])
        self.assertEqual("reliability.critical_locator", fabricated["applied_cap"]["cap_id"])
        self.assertEqual(2, fabricated["final_rating"])
        self.assertEqual(10.0, fabricated["awarded_points"])

    def test_calculation_output_is_byte_identical_across_repeated_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = calculation_files(root, *base_documents())
            loaded = v5.load_inputs(config)
            first = v6.calculate_loaded(loaded)
            second = v6.calculate_loaded(v5.load_inputs(config))
            self.assertEqual(v5.canonical_json_text(first), v5.canonical_json_text(second))


if __name__ == "__main__":
    unittest.main()
