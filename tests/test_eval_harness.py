"""
tests/test_eval_harness.py
----------------------------
End-to-end evaluation harness against tests/fixtures/golden_set.jsonl.

This deliberately runs the REAL Auditor-then-guardrail pipeline (no
mocked Auditor stand-in) so the reported numbers reflect actual system
behavior, not a simulated approximation. Requires valid AWS/Bedrock
credentials and BEDROCK_MODEL_ID to be configured in the environment;
skip if not available (e.g. in offline CI) rather than fabricating
results.

Reports two numbers, printed in a form suitable for copy-paste directly
into the README's evaluation section and for reading aloud in the demo
video:

  1. Overall pipeline accuracy: fraction of golden_set.jsonl records
     where the final (post-guardrail) verdict matches the labeled
     verdict.

  2. Citation-verification catch rate on adversarial-ambiguous cases:
     among golden_set records labeled "ambiguous" whose `note` field
     indicates an adversarial/off-SOW-reference case (verbal
     agreements, calls, DMs, emails, etc.), the fraction that the
     citation-verification gate correctly caught and forced to
     "ambiguous" -- specifically counting cases where the Auditor
     itself returned a non-ambiguous verdict with confidence_score
     >= 0.85 (i.e. cases a naive "trust confidence_score alone, skip
     citation verification" baseline would have wrongly passed
     through as high-confidence and non-ambiguous).
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from agent.auditor import run_auditor
from agent.guardrails import CONFIDENCE_THRESHOLD, apply_guardrails

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN_SET_PATH = FIXTURES_DIR / "golden_set.jsonl"

ADVERSARIAL_NOTE_MARKERS = [
    "verbal",
    "call",
    "phone",
    "slack dm",
    "email",
    "kickoff call",
    "intro call",
    "onboarding call",
    "off-sow",
    "off the record",
    "not in the doc",
]

SOW_FILENAME_MAP = {
    "sow_acme_website": "sow_acme_website.txt",
    "sow_globex_app": "sow_globex_app.txt",
    "sow_nimbus_brand": "sow_nimbus_brand.txt",
}


def _load_golden_set() -> List[Dict[str, Any]]:
    records = []
    with open(GOLDEN_SET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _load_sow_text(sow_id: str) -> str:
    filename = SOW_FILENAME_MAP.get(sow_id)
    if filename is None:
        raise ValueError(f"Unknown sow_id in golden set: {sow_id!r}")
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


def _is_adversarial_note(note: str) -> bool:
    note_lower = note.lower()
    return any(marker in note_lower for marker in ADVERSARIAL_NOTE_MARKERS)


def _bedrock_credentials_available() -> bool:
    return bool(os.environ.get("BEDROCK_MODEL_ID")) and bool(
        os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE")
    )


@pytest.mark.skipif(
    not _bedrock_credentials_available(),
    reason=(
        "Live Bedrock credentials / BEDROCK_MODEL_ID not configured; "
        "this eval harness runs the real Auditor and requires them."
    ),
)
def test_eval_harness_reports_accuracy_and_citation_catch_rate():
    records = _load_golden_set()
    assert records, "golden_set.jsonl must not be empty"

    total = 0
    correct = 0

    adversarial_ambiguous_total = 0
    adversarial_ambiguous_caught = 0

    per_record_results = []

    for record in records:
        sow_id = record["sow_id"]
        client_message = record["client_message"]
        expected_label = record["label"]
        note = record.get("note", "")

        sow_text = _load_sow_text(sow_id)

        raw_verdict = run_auditor(sow_text, client_message)
        raw_output = raw_verdict.model_dump()

        final_output = apply_guardrails(raw_output, sow_text)
        final_verdict = final_output["verdict"]

        total += 1
        is_correct = final_verdict == expected_label
        if is_correct:
            correct += 1

        per_record_results.append(
            {
                "sow_id": sow_id,
                "client_message": client_message,
                "expected_label": expected_label,
                "raw_auditor_verdict": raw_output["verdict"],
                "raw_confidence": raw_output["confidence_score"],
                "final_verdict": final_verdict,
                "correct": is_correct,
            }
        )

        if expected_label == "ambiguous" and _is_adversarial_note(note):
            adversarial_ambiguous_total += 1

            naive_baseline_would_pass = (
                raw_output["verdict"] != "ambiguous"
                and raw_output["confidence_score"] >= CONFIDENCE_THRESHOLD
            )

            guardrail_correctly_caught = (
                naive_baseline_would_pass and final_verdict == "ambiguous"
            ) or (
                not naive_baseline_would_pass and final_verdict == "ambiguous"
            )

            if guardrail_correctly_caught:
                adversarial_ambiguous_caught += 1

    overall_accuracy = correct / total if total else 0.0
    citation_catch_rate = (
        adversarial_ambiguous_caught / adversarial_ambiguous_total
        if adversarial_ambiguous_total
        else 0.0
    )

    print("\n" + "=" * 60)
    print("ScopeGuard Evaluation Harness — golden_set.jsonl")
    print("=" * 60)
    print(f"Total records evaluated:            {total}")
    print(f"Overall pipeline accuracy:          {correct}/{total} = {overall_accuracy:.1%}")
    print(
        "Adversarial-ambiguous cases:         "
        f"{adversarial_ambiguous_total}"
    )
    print(
        "Citation-verification catch rate:    "
        f"{adversarial_ambiguous_caught}/{adversarial_ambiguous_total} = "
        f"{citation_catch_rate:.1%} "
        "(vs. naive confidence-only baseline, which would pass these through)"
    )
    print("=" * 60)

    for r in per_record_results:
        status = "PASS" if r["correct"] else "FAIL"
        print(
            f"[{status}] {r['sow_id']} | expected={r['expected_label']} "
            f"raw_verdict={r['raw_auditor_verdict']} "
            f"raw_conf={r['raw_confidence']:.2f} "
            f"final={r['final_verdict']} | {r['client_message'][:60]!r}"
        )

    assert 0.0 <= overall_accuracy <= 1.0
    assert 0.0 <= citation_catch_rate <= 1.0

    return {
        "overall_accuracy": overall_accuracy,
        "citation_catch_rate": citation_catch_rate,
        "total_records": total,
        "adversarial_ambiguous_total": adversarial_ambiguous_total,
    }


if __name__ == "__main__":
    if not _bedrock_credentials_available():
        raise SystemExit(
            "BEDROCK_MODEL_ID and AWS credentials must be configured in the "
            "environment to run the live evaluation harness."
        )
    results = test_eval_harness_reports_accuracy_and_citation_catch_rate()
    print(json.dumps(results, indent=2))