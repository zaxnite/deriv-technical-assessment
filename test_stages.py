# test_stages.py
"""
Stage-by-stage test suite for the recruitment screening pipeline.

Tests each module independently with real API calls where needed.
Run with: python test_stages.py

Tests are ordered to match pipeline progression:
    T1 - PipelineState: stage ordering enforcement
    T2 - LLMCallLogger: write and read log records
    T3 - Bias utilities: anonymisation and audit parsing
    T4 - LLM Stage 1: rubric generation (live API call)
    T5 - LLM Stage 2: candidate scoring (live API call)
    T6 - LLM Stage 3: bias audit (live API call)
    T7 - Full integration: T4 -> T5 -> T6 in sequence
"""

from __future__ import annotations

import json
import os
import sys
import shutil
import traceback
from pathlib import Path
from datetime import datetime

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

RESULTS: list[dict] = []
TEST_ARTIFACTS_DIR = "test_artifacts"


def run_test(name: str):
    """Decorator that runs a test function and records pass/fail."""
    def decorator(fn):
        def wrapper():
            print(f"\n{'='*60}")
            print(f"  TEST: {name}")
            print(f"{'='*60}")
            try:
                fn()
                RESULTS.append({"test": name, "status": "PASS", "error": None})
                print(f"  ✅  PASS")
            except AssertionError as e:
                RESULTS.append({"test": name, "status": "FAIL", "error": str(e)})
                print(f"  ❌  FAIL: {e}")
            except Exception as e:
                RESULTS.append({"test": name, "status": "ERROR", "error": str(e)})
                print(f"  💥  ERROR: {e}")
                traceback.print_exc()
        return wrapper
    return decorator


def assert_eq(actual, expected, label: str = ""):
    if actual != expected:
        raise AssertionError(
            f"{label}: expected {expected!r}, got {actual!r}"
        )


def assert_true(condition: bool, label: str = ""):
    if not condition:
        raise AssertionError(label or "Condition was False")


def assert_keys(d: dict, keys: list[str], label: str = ""):
    missing = [k for k in keys if k not in d]
    if missing:
        raise AssertionError(f"{label}: missing keys {missing}")


# ---------------------------------------------------------------------------
# Sample fixtures (schema-compatible with real input files)
# ---------------------------------------------------------------------------

SAMPLE_JOB = {
    "role": "Senior Backend Engineer — Trading Infrastructure",
    "company": "Deriv",
    "location": "Remote (APAC or Europe timezone)",
    "requirements": [
        "5+ years backend engineering experience",
        "Strong proficiency in Python or Go",
        "Experience with high-throughput, low-latency systems (>10k req/s)",
        "Familiarity with financial systems, trading platforms, or payment processing",
        "Experience with WebSocket or real-time data pipelines",
        "Proficiency with PostgreSQL and at least one NoSQL database",
        "Experience with containerisation (Docker/Kubernetes)",
        "Ability to work in distributed, async-first teams",
    ],
    "nice_to_have": [
        "Experience in regulated financial environments",
        "Contributions to open source projects",
    ],
    "explicitly_not_required": [
        "Degree from a specific institution",
        "Specific nationality or language background",
        "Experience at FAANG companies",
    ],
}

SAMPLE_CANDIDATES = [
    {
        "id": "C1",
        "name": "Aisha Okonkwo",
        "summary": "7 years backend engineering. Python and Go. Built real-time trade execution engine at Lagos fintech startup handling 50k req/s. Kafka, PostgreSQL, Redis. Led team of 4. No degree listed.",
    },
    {
        "id": "C2",
        "name": "James Whitfield",
        "summary": "6 years at Goldman Sachs and Barclays. Java primary language, some Python. Equity derivatives pricing systems. Low-latency focus. Oxford CS degree. No WebSocket experience listed.",
    },
    {
        "id": "C3",
        "name": "Mei-Lin Zhang",
        "summary": "4 years experience. Python expert. Contributed to 3 open source trading libraries. PostgreSQL, MongoDB. Built WebSocket data pipeline for crypto exchange. Currently at early-stage startup.",
    },
]

SAMPLE_RUBRIC = {
    "role": "Senior Backend Engineer — Trading Infrastructure",
    "criteria": [
        {"id": "R1", "name": "Backend Experience Depth", "weight": 0.20,
         "description": "Years and quality of backend engineering experience.",
         "score_10_means": "7+ years with demonstrable impact on production systems."},
        {"id": "R2", "name": "Python/Go Proficiency", "weight": 0.20,
         "description": "Proficiency in Python or Go.",
         "score_10_means": "Expert-level with production systems in one or both languages."},
        {"id": "R3", "name": "High-Throughput Systems", "weight": 0.20,
         "description": "Experience with >10k req/s systems.",
         "score_10_means": "Proven experience building and operating high-throughput systems."},
        {"id": "R4", "name": "Financial Domain Knowledge", "weight": 0.15,
         "description": "Familiarity with financial systems or trading.",
         "score_10_means": "Deep experience in fintech, trading, or payment systems."},
        {"id": "R5", "name": "Real-Time Data & WebSocket", "weight": 0.15,
         "description": "Experience with WebSocket or real-time pipelines.",
         "score_10_means": "Built and operated production WebSocket or streaming systems."},
        {"id": "R6", "name": "Infrastructure & Databases", "weight": 0.10,
         "description": "PostgreSQL, NoSQL, Docker/Kubernetes proficiency.",
         "score_10_means": "Expert with PostgreSQL + multiple NoSQL + container orchestration."},
    ],
}


# ---------------------------------------------------------------------------
# T1 — PipelineState stage ordering
# ---------------------------------------------------------------------------

@run_test("T1 — PipelineState: stage ordering enforcement")
def test_pipeline_state():
    from pipeline.state import PipelineState, PipelineStage, PipelineOrderError

    state = PipelineState(artifacts_dir=TEST_ARTIFACTS_DIR)
    assert_eq(state.current_stage, PipelineStage.INIT, "Initial stage")

    # Advance normally
    state.advance_to(PipelineStage.RUBRIC_GENERATED)
    assert_eq(state.current_stage, PipelineStage.RUBRIC_GENERATED, "After advance")

    # Re-entering same stage is idempotent
    state.advance_to(PipelineStage.RUBRIC_GENERATED)
    assert_eq(state.current_stage, PipelineStage.RUBRIC_GENERATED, "Idempotent re-enter")

    # Skipping a stage must raise
    try:
        state.advance_to(PipelineStage.CANDIDATES_SCORED)  # skips RUBRIC_APPROVED
        raise AssertionError("Should have raised PipelineOrderError for skipped stage")
    except PipelineOrderError as e:
        print(f"    Correctly blocked skip: {e}")

    # Ranking before bias audit must raise
    state2 = PipelineState(artifacts_dir=TEST_ARTIFACTS_DIR)
    state2.current_stage = PipelineStage.CANDIDATES_SCORED
    try:
        state2.assert_bias_audit_complete()
        raise AssertionError("Should have raised PipelineOrderError — bias audit not done")
    except PipelineOrderError as e:
        print(f"    Correctly blocked ranking: {e}")

    # Skip FLAGGED_RESCORING_COMPLETE when no rescoring required
    state3 = PipelineState(artifacts_dir=TEST_ARTIFACTS_DIR)
    state3.current_stage = PipelineStage.BIAS_AUDITED
    state3.rescoring_required = False
    state3.advance_to(PipelineStage.RANKING_FINALISED)
    assert_eq(state3.current_stage, PipelineStage.RANKING_FINALISED, "Skip rescore when clean")
    print(f"    Correctly skipped rescore stage when no flags found")

    # State file written to disk
    state_file = Path(TEST_ARTIFACTS_DIR) / "pipeline_state.json"
    assert_true(state_file.exists(), "pipeline_state.json must be written to disk")
    with open(state_file) as f:
        saved = json.load(f)
    assert_true("current_stage" in saved, "Saved state must have current_stage key")
    print(f"    pipeline_state.json written correctly: {saved['current_stage']}")


# ---------------------------------------------------------------------------
# T2 — LLMCallLogger
# ---------------------------------------------------------------------------

@run_test("T2 — LLMCallLogger: write, read, and validate records")
def test_logger():
    from pipeline.logger import LLMCallLogger

    log_path = Path(TEST_ARTIFACTS_DIR) / "test_llm_calls.jsonl"
    logger = LLMCallLogger(log_path=log_path)

    # Write a named-candidate record
    r1 = logger.log(
        stage="CANDIDATES_SCORED",
        model="claude-haiku-4-5",
        provider="anthropic",
        prompt="Score these candidates...",
        input_artifacts=["candidates.json", "scoring_rubric.json"],
        output_artifact="artifacts/candidate_scores.json",
        candidate_names_included=True,
    )
    assert_keys(r1, ["stage", "timestamp", "model", "provider",
                     "prompt_hash", "input_artifacts", "output_artifact",
                     "candidate_names_included"], "Record keys")
    assert_eq(r1["candidate_names_included"], True, "Named record flag")
    assert_eq(len(r1["prompt_hash"]), 64, "SHA-256 hash length")

    # Write an anonymised record
    r2 = logger.log(
        stage="FLAGGED_RESCORING_COMPLETE",
        model="claude-haiku-4-5",
        provider="anthropic",
        prompt="Re-score anonymised candidates...",
        input_artifacts=["artifacts/candidate_scores.json"],
        output_artifact="artifacts/candidate_scores.json",
        candidate_names_included=False,
    )
    assert_eq(r2["candidate_names_included"], False, "Anonymised record flag")

    # Read back
    all_records = logger.read_all()
    assert_eq(len(all_records), 2, "Two records written")
    assert_true(logger.has_anonymised_call(), "Must detect anonymised call")

    stages = logger.get_stages_logged()
    assert_true("FLAGGED_RESCORING_COMPLETE" in stages, "Stage in log")

    print(f"    {len(all_records)} records logged correctly")
    print(f"    Anonymised call detected: {logger.has_anonymised_call()}")
    print(f"    Stages logged: {stages}")


# ---------------------------------------------------------------------------
# T3 — Bias utilities
# ---------------------------------------------------------------------------

@run_test("T3 — Bias: anonymisation and audit parsing")
def test_bias_utils():
    from pipeline.bias import (
        anonymise_candidates,
        get_flagged_criteria,
        requires_rescoring,
        validate_audit_structure,
        rank_candidates,
    )

    # Anonymisation removes name key
    anon = anonymise_candidates(SAMPLE_CANDIDATES)
    assert_eq(len(anon), 3, "All candidates returned")
    for a in anon:
        assert_true("name" not in a, f"Name must be stripped from {a['id']}")
        assert_true("id" in a, "ID must be preserved")
        print(f"    {a['id']}: {a['summary'][:80]}...")

    # Goldman Sachs should be replaced
    c2_anon = next(a for a in anon if a["id"] == "C2")
    assert_true(
        "Goldman Sachs" not in c2_anon["summary"]
        and "goldman sachs" not in c2_anon["summary"].lower(),
        "Goldman Sachs must be stripped"
    )
    print(f"    Employer stripped correctly: 'Goldman Sachs' → '[employer]'")

    # Oxford should be replaced
    assert_true(
        "Oxford" not in c2_anon["summary"],
        "Oxford must be stripped"
    )
    print(f"    Institution stripped correctly: 'Oxford' → '[institution]'")

    # Empty list raises
    try:
        anonymise_candidates([])
        raise AssertionError("Should have raised ValueError for empty list")
    except ValueError as e:
        print(f"    Correctly raised ValueError for empty list: {e}")

    # Flagged criteria extraction
    audit_with_flags = {
        "findings": [
            {"bias_type": "credential bias", "affected_candidates": ["C2"],
             "affected_criteria": ["R4"], "evidence": "...", "severity": "flagged"},
            {"bias_type": "geography bias", "affected_candidates": ["C1"],
             "affected_criteria": ["R3"], "evidence": "...", "severity": "watch"},
        ],
        "flagged_criteria_ids": ["R4"],
        "requires_rescoring": True,
    }
    flagged = get_flagged_criteria(audit_with_flags)
    assert_eq(flagged, ["R4"], "Flagged criteria extracted")
    assert_true(requires_rescoring(audit_with_flags), "Rescoring required")
    print(f"    Flagged criteria: {flagged}")

    # Clean audit — no rescoring
    clean_audit = {
        "findings": [],
        "flagged_criteria_ids": [],
        "requires_rescoring": False,
    }
    assert_true(not requires_rescoring(clean_audit), "Clean audit — no rescoring")
    print(f"    Clean audit correctly returns requires_rescoring=False")

    # Validate structure
    errors = validate_audit_structure(audit_with_flags)
    assert_eq(errors, [], "Valid audit structure has no errors")

    bad_audit = {"findings": [{"bias_type": "x"}]}  # missing required keys
    errors = validate_audit_structure(bad_audit)
    assert_true(len(errors) > 0, "Invalid audit structure must return errors")
    print(f"    Invalid audit detected: {errors[0]}")

    # Ranking
    scored = [
        {"candidate_id": "C1", "candidate_name": "A", "total_weighted_score": 7.2},
        {"candidate_id": "C2", "candidate_name": "B", "total_weighted_score": 8.5},
        {"candidate_id": "C3", "candidate_name": "C", "total_weighted_score": 6.1},
    ]
    ranking = rank_candidates(scored)
    assert_eq(ranking[0]["candidate_id"], "C2", "Top ranked candidate")
    assert_eq(ranking[0]["rank"], 1, "Rank 1 assigned")
    assert_eq(ranking[2]["rank"], 3, "Rank 3 assigned")
    print(f"    Ranking correct: {[(r['rank'], r['candidate_id']) for r in ranking]}")


# ---------------------------------------------------------------------------
# T4 — LLM Stage 1: Rubric generation (live API)
# ---------------------------------------------------------------------------

@run_test("T4 — LLM Stage 1: rubric generation (live API)")
def test_rubric_generation():
    from pipeline.llm import generate_rubric
    from pipeline.logger import LLMCallLogger

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise AssertionError("ANTHROPIC_API_KEY not set — cannot run live API test")

    log_path = Path(TEST_ARTIFACTS_DIR) / "test_llm_calls.jsonl"
    logger = LLMCallLogger(log_path=log_path)

    rubric = generate_rubric(
        job_description=SAMPLE_JOB,
        logger=logger,
        artifacts_dir=TEST_ARTIFACTS_DIR,
    )

    # Must have exactly 6 criteria
    criteria = rubric.get("criteria", [])
    assert_eq(len(criteria), 6, "Rubric must have exactly 6 criteria")

    # Weights must sum to ~1.0
    total_weight = sum(c.get("weight", 0) for c in criteria)
    assert_true(0.98 <= total_weight <= 1.02, f"Weights must sum to 1.0, got {total_weight:.3f}")

    # Each criterion must have required keys
    for i, c in enumerate(criteria):
        assert_keys(c, ["id", "name", "weight", "description", "score_10_means"],
                    f"Criterion {i}")

    print(f"    Rubric generated with {len(criteria)} criteria")
    print(f"    Weight sum: {total_weight:.3f}")
    for c in criteria:
        print(f"    [{c['id']}] {c['name']} — weight: {c['weight']}")

    # Draft file written
    draft_path = Path(TEST_ARTIFACTS_DIR) / "scoring_rubric_draft.json"
    assert_true(draft_path.exists(), "Draft rubric must be written to disk")
    print(f"    Draft saved to: {draft_path}")


# ---------------------------------------------------------------------------
# T5 — LLM Stage 2: Candidate scoring (live API)
# ---------------------------------------------------------------------------

@run_test("T5 — LLM Stage 2: candidate scoring (live API)")
def test_candidate_scoring():
    from pipeline.llm import score_candidates
    from pipeline.logger import LLMCallLogger

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise AssertionError("ANTHROPIC_API_KEY not set — cannot run live API test")

    log_path = Path(TEST_ARTIFACTS_DIR) / "test_llm_calls.jsonl"
    logger = LLMCallLogger(log_path=log_path)

    scores_data = score_candidates(
        candidates=SAMPLE_CANDIDATES,
        rubric=SAMPLE_RUBRIC,
        logger=logger,
        artifacts_dir=TEST_ARTIFACTS_DIR,
    )

    # Required top-level keys
    assert_keys(scores_data, [
        "rubric_reference", "original_scores", "corrected_scores",
        "bias_audit_status", "flagged_criteria", "final_ranking",
        "rescoring_occurred"
    ], "candidate_scores structure")

    # Original scores must exist and never be None
    original = scores_data["original_scores"]
    assert_true(original is not None, "original_scores must not be None")
    assert_eq(len(original), len(SAMPLE_CANDIDATES), "All candidates scored")

    # corrected_scores must be None at this stage
    assert_true(scores_data["corrected_scores"] is None, "corrected_scores must be None initially")

    # Each scored candidate structure
    for scored in original:
        assert_keys(scored, ["candidate_id", "candidate_name",
                             "criterion_scores", "total_weighted_score"], "Scored candidate")
        assert_eq(len(scored["criterion_scores"]), 6, f"6 criteria for {scored['candidate_id']}")
        assert_true(0 <= scored["total_weighted_score"] <= 10,
                    f"Score in range for {scored['candidate_id']}")

    print(f"    {len(original)} candidates scored")
    for s in original:
        print(f"    {s['candidate_id']} — {s['candidate_name']}: {s['total_weighted_score']:.2f}")


# ---------------------------------------------------------------------------
# T6 — LLM Stage 3: Bias audit (live API)
# ---------------------------------------------------------------------------

@run_test("T6 — LLM Stage 3: bias audit (live API)")
def test_bias_audit():
    from pipeline.llm import score_candidates, audit_bias
    from pipeline.logger import LLMCallLogger
    from pipeline.bias import validate_audit_structure

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise AssertionError("ANTHROPIC_API_KEY not set — cannot run live API test")

    log_path = Path(TEST_ARTIFACTS_DIR) / "test_llm_calls.jsonl"
    logger = LLMCallLogger(log_path=log_path)

    # Need scores first
    scores_data = score_candidates(
        candidates=SAMPLE_CANDIDATES,
        rubric=SAMPLE_RUBRIC,
        logger=logger,
        artifacts_dir=TEST_ARTIFACTS_DIR,
    )

    audit_data = audit_bias(
        candidates=SAMPLE_CANDIDATES,
        rubric=SAMPLE_RUBRIC,
        scores_data=scores_data,
        logger=logger,
        artifacts_dir=TEST_ARTIFACTS_DIR,
    )

    # Required keys
    assert_keys(audit_data, ["audit_summary", "findings", "requires_rescoring"], "Audit structure")

    # Validate finding structure
    errors = validate_audit_structure(audit_data)
    assert_eq(errors, [], f"Audit structure validation: {errors}")

    # Each finding must have required keys and valid severity
    valid_severities = {"flagged", "watch", "clear"}
    for i, finding in enumerate(audit_data.get("findings", [])):
        assert_keys(finding, ["bias_type", "affected_candidates", "evidence", "severity"],
                    f"Finding {i}")
        assert_true(finding["severity"] in valid_severities,
                    f"Finding {i} severity must be valid, got '{finding['severity']}'")

    # bias_audit.json written to disk
    audit_path = Path(TEST_ARTIFACTS_DIR) / "bias_audit.json"
    assert_true(audit_path.exists(), "bias_audit.json must be written to disk")

    print(f"    Audit summary: {audit_data.get('audit_summary', '')[:100]}...")
    print(f"    Findings: {len(audit_data.get('findings', []))}")
    print(f"    Requires rescoring: {audit_data.get('requires_rescoring')}")
    for f in audit_data.get("findings", []):
        print(f"    [{f['severity'].upper()}] {f['bias_type']} → {f['affected_candidates']}")


# ---------------------------------------------------------------------------
# T7 — Full integration: pipeline state + all 3 LLM stages in sequence
# ---------------------------------------------------------------------------

@run_test("T7 — Integration: state + rubric + scoring + audit in sequence")
def test_full_integration():
    from pipeline.state import PipelineState, PipelineStage, PipelineOrderError
    from pipeline.llm import generate_rubric, score_candidates, audit_bias
    from pipeline.logger import LLMCallLogger
    from pipeline.bias import requires_rescoring, get_flagged_criteria

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise AssertionError("ANTHROPIC_API_KEY not set — cannot run live API test")

    int_dir = Path(TEST_ARTIFACTS_DIR) / "integration"
    int_dir.mkdir(parents=True, exist_ok=True)

    log_path = int_dir / "llm_calls.jsonl"
    logger = LLMCallLogger(log_path=log_path)
    state = PipelineState(artifacts_dir=str(int_dir))

    # INIT → RUBRIC_GENERATED
    rubric = generate_rubric(SAMPLE_JOB, logger, artifacts_dir=str(int_dir))
    state.advance_to(PipelineStage.RUBRIC_GENERATED)
    print(f"    Stage: {state.stage_label()}")

    # RUBRIC_GENERATED → RUBRIC_APPROVED (simulate approval)
    state.advance_to(PipelineStage.RUBRIC_APPROVED)
    print(f"    Stage: {state.stage_label()} (simulated approval)")

    # RUBRIC_APPROVED → CANDIDATES_SCORED
    scores_data = score_candidates(SAMPLE_CANDIDATES, rubric, logger, artifacts_dir=str(int_dir))
    state.advance_to(PipelineStage.CANDIDATES_SCORED)
    print(f"    Stage: {state.stage_label()}")

    # Verify ranking is blocked before audit
    try:
        state.assert_bias_audit_complete()
        raise AssertionError("Ranking should be blocked before bias audit")
    except PipelineOrderError:
        print(f"    ✅  Ranking correctly blocked — bias audit not yet complete")

    # CANDIDATES_SCORED → BIAS_AUDITED
    audit_data = audit_bias(SAMPLE_CANDIDATES, rubric, scores_data, logger, artifacts_dir=str(int_dir))
    state.advance_to(PipelineStage.BIAS_AUDITED)
    print(f"    Stage: {state.stage_label()}")

    # Now ranking is allowed
    state.assert_bias_audit_complete()
    print(f"    ✅  Ranking unblocked after bias audit")

    # Report audit outcome
    needs_rescore = requires_rescoring(audit_data)
    flagged = get_flagged_criteria(audit_data)
    print(f"    Rescoring required: {needs_rescore}")
    print(f"    Flagged criteria: {flagged}")

    # Verify log has 3 stage records
    records = logger.read_all()
    stages_logged = logger.get_stages_logged()
    print(f"    LLM calls logged: {len(records)}")
    print(f"    Stages: {stages_logged}")
    assert_true(len(records) >= 3, "At least 3 LLM calls must be logged")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'#'*60}")
    print(f"  RECRUITMENT PIPELINE — STAGE TESTS")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}")

    # Clean test artifacts before run
    if Path(TEST_ARTIFACTS_DIR).exists():
        shutil.rmtree(TEST_ARTIFACTS_DIR)
    Path(TEST_ARTIFACTS_DIR).mkdir(exist_ok=True)

    # Run all tests
    test_pipeline_state()
    test_logger()
    test_bias_utils()
    test_rubric_generation()
    test_candidate_scoring()
    test_bias_audit()
    test_full_integration()

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    errors = sum(1 for r in RESULTS if r["status"] == "ERROR")

    for r in RESULTS:
        icon = "✅" if r["status"] == "PASS" else "❌" if r["status"] == "FAIL" else "💥"
        print(f"  {icon}  {r['test']}")
        if r["error"]:
            print(f"       → {r['error']}")

    print(f"\n  Total: {len(RESULTS)} | Passed: {passed} | Failed: {failed} | Errors: {errors}")

    # Clean up test artifacts
    if Path(TEST_ARTIFACTS_DIR).exists():
        shutil.rmtree(TEST_ARTIFACTS_DIR)
        print(f"  Test artifacts cleaned up.")

    sys.exit(0 if (failed + errors) == 0 else 1)


if __name__ == "__main__":
    main()