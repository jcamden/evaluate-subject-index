from __future__ import annotations

import sys
import unittest
import copy
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS))

from locator_utility import FIT_SCORES  # noqa: E402

try:
    import dimension_score_cli as v5  # noqa: E402
    import dimension_score_v7_cli as v7  # noqa: E402
except ModuleNotFoundError:
    v5 = None
    v7 = None

HAS_SCORING_DEPENDENCIES = v5 is not None and v7 is not None


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


def reliability_ledgers(
    locator_states: list[dict],
    treatment_statuses: list[tuple[str, str]] | None = None,
    *,
    locator_not_measured: list[str] | None = None,
    defects: list[dict] | None = None,
    attempt: str = "meaningful_attempt",
) -> dict:
    locators = []
    for index, locator_state in enumerate(locator_states, start=1):
        record = copy.deepcopy(locator_state)
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


def reliability_value(result: dict, field: str) -> Decimal:
    return Decimal(result["reliability_provenance"][field])


@unittest.skipUnless(HAS_SCORING_DEPENDENCIES, "scoring runtime dependencies are unavailable")
class V7SensitivityTests(unittest.TestCase):
    def test_approved_fit_values_are_frozen_regression_expectations(self) -> None:
        self.assertEqual(
            {
                "exact_fit": Decimal("1.00"),
                "material_partial_fit": Decimal("0.70"),
                "material_mismatch": Decimal("0.35"),
                "severe_mismatch": Decimal("0.15"),
                "no_fit": Decimal("0.00"),
            },
            FIT_SCORES,
        )

    def test_plausible_fit_alternatives_are_compared_without_changing_policy(self) -> None:
        # Ten substantive locators: four exact, two partial, two minor, one
        # major, and one no-fit. All treatment ceilings are 1, so this isolates
        # fit sensitivity and is unrelated to any named evaluation result.
        profiles = {
            "lower_credit": {
                "exact_fit": Decimal("1"),
                "material_partial_fit": Decimal("0.60"),
                "material_mismatch": Decimal("0.25"),
                "severe_mismatch": Decimal("0.10"),
                "no_fit": Decimal("0"),
            },
            "approved_v7": FIT_SCORES,
            "higher_credit": {
                "exact_fit": Decimal("1"),
                "material_partial_fit": Decimal("0.80"),
                "material_mismatch": Decimal("0.45"),
                "severe_mismatch": Decimal("0.25"),
                "no_fit": Decimal("0"),
            },
        }
        expected = {
            "lower_credit": (Decimal("0.58"), Decimal("3.5")),
            "approved_v7": (Decimal("0.625"), Decimal("4")),
            "higher_credit": (Decimal("0.675"), Decimal("4")),
        }
        counts = {
            "exact_fit": 4,
            "material_partial_fit": 2,
            "material_mismatch": 2,
            "severe_mismatch": 1,
            "no_fit": 1,
        }
        for name, profile in profiles.items():
            with self.subTest(name=name):
                numerator = sum(
                    (profile[tier] * count for tier, count in counts.items()),
                    Decimal(0),
                )
                precision = numerator / Decimal(10)
                rating = v5.round_half_step(Decimal(5) * v5.f1(precision, Decimal(1)))
                self.assertEqual(expected[name], (precision, rating))
        self.assertEqual(Decimal("0.70"), FIT_SCORES["material_partial_fit"])
        self.assertEqual(Decimal("0.35"), FIT_SCORES["material_mismatch"])
        self.assertEqual(Decimal("0.15"), FIT_SCORES["severe_mismatch"])


@unittest.skipUnless(HAS_SCORING_DEPENDENCIES, "scoring runtime dependencies are unavailable")
class V7AdversarialMixtureTests(unittest.TestCase):
    def test_concordance_like_weak_locator_mix_stays_low_and_strict_precision_public(self) -> None:
        locators = [
            state("supported", "substantive", locator_id=f"LOC-{index:04d}")
            for index in range(1, 11)
        ] + [
            state(
                "unsupported",
                "passing_mention",
                severity="minor",
                locator_id=f"LOC-{index:04d}",
            )
            for index in range(11, 101)
        ]
        result = v7.calculate_reliability(reliability_ledgers(locators), "full")
        self.assertEqual(Decimal("0.325"), reliability_value(result, "weighted_locator_precision"))
        self.assertEqual(Decimal("0.1"), reliability_value(result, "strict_substantive_precision"))
        self.assertEqual(Decimal("2.5"), Decimal(str(result["final_rating"])))

    def test_high_locator_precision_with_poor_recall_is_depressed_by_unchanged_f1(self) -> None:
        locators = [
            state("supported", "substantive", locator_id=f"LOC-{index:04d}")
            for index in range(1, 10)
        ] + [
            state(
                "unsupported",
                "absent",
                codes=["LOC_POS"],
                severity="major",
                locator_id="LOC-0010",
            )
        ]
        result = v7.calculate_reliability(
            reliability_ledgers(
                locators,
                [("found", "supporting"), *[("missed", "supporting")] * 3],
            ),
            "full",
        )
        self.assertEqual(Decimal("0.9"), reliability_value(result, "weighted_locator_precision"))
        self.assertEqual(Decimal("0.25"), reliability_value(result, "treatment_recall"))
        self.assertEqual(
            Decimal("0.3913043478260869565217391304"),
            reliability_value(result, "weighted_f1"),
        )
        self.assertEqual(Decimal("2"), Decimal(str(result["final_rating"])))

    def test_one_fabricated_locator_keeps_critical_cap_despite_high_precision(self) -> None:
        locators = [
            state("supported", "substantive", locator_id=f"LOC-{index:04d}")
            for index in range(1, 100)
        ] + [
            state(
                "unsupported",
                "substantive",
                codes=["SCP"],
                severity="critical",
                locator_id="LOC-0100",
            )
        ]
        result = v7.calculate_reliability(
            reliability_ledgers(
                locators,
                defects=[
                    defect(
                        "SCP",
                        "fabricated_locator",
                        "critical",
                        locator_id="LOC-0100",
                        defect_id="DEFECT-FABRICATED",
                    )
                ],
            ),
            "full",
        )
        self.assertEqual(Decimal("0.99"), reliability_value(result, "weighted_locator_precision"))
        self.assertEqual("reliability.critical_locator", result["applied_cap"]["cap_id"])
        self.assertEqual(Decimal("2"), Decimal(str(result["final_rating"])))

    def test_wrong_relationship_and_stance_retain_treatment_but_receive_fit_penalties(self) -> None:
        result = v7.calculate_reliability(
            reliability_ledgers(
                [
                    state(
                        "unsupported",
                        "substantive",
                        codes=["CON"],
                        severity="minor",
                        locator_id="LOC-0001",
                    ),
                    state(
                        "unsupported",
                        "substantive",
                        codes=["STA"],
                        severity="major",
                        locator_id="LOC-0002",
                    ),
                ]
            ),
            "full",
        )
        assignments = result["reliability_provenance"]["locator_utility_assignments"]
        self.assertEqual(["1", "1"], [item["treatment_score"] for item in assignments])
        self.assertEqual(["0.35", "0.15"], [item["fit_score"] for item in assignments])
        self.assertEqual(Decimal("0.25"), reliability_value(result, "weighted_locator_precision"))

    def test_weak_locator_mixture_obeys_quarter_ceiling_and_no_fit_floor(self) -> None:
        result = v7.calculate_reliability(
            reliability_ledgers(
                [
                    state(
                        "unsupported",
                        "passing_mention",
                        severity="minor",
                        locator_id="LOC-0001",
                    ),
                    state(
                        "partially_supported",
                        "citation_only",
                        severity="minor",
                        locator_id="LOC-0002",
                    ),
                    state(
                        "unsupported",
                        "incidental_example",
                        codes=["HED"],
                        severity="minor",
                        locator_id="LOC-0003",
                    ),
                    state(
                        "unsupported",
                        "attribution_only",
                        codes=["CON"],
                        severity="major",
                        locator_id="LOC-0004",
                    ),
                ],
                defects=[
                    defect(
                        "CON",
                        "generic",
                        "major",
                        locator_id="LOC-0004",
                        defect_id="DEFECT-NO-FIT",
                        root_cause_family="wrong_sense",
                    )
                ],
            ),
            "full",
        )
        assignments = result["reliability_provenance"]["locator_utility_assignments"]
        self.assertEqual(
            ["0.25", "0.25", "0.25", "0"],
            [item["combined_credit"] for item in assignments],
        )
        self.assertEqual(Decimal("0.1875"), reliability_value(result, "weighted_locator_precision"))


if __name__ == "__main__":
    unittest.main()
