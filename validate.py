# validate.py
"""
Validation command for the recruitment screening pipeline.

Run with:
    python validate.py

Resolves artifact location in this order:
    1. artifacts/latest/          (symlink on Unix)
    2. artifacts/latest_session.txt (pointer file on Windows)
    3. artifacts/                 (flat fallback for backward compatibility)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Resolve artifacts directory
# ---------------------------------------------------------------------------

BASE_ARTIFACTS_DIR = Path("artifacts")


def resolve_artifacts_dir() -> Path:
    """
    Find the most recent session's artifact directory.

    Checks in order:
    1. artifacts/latest/ symlink or directory
    2. artifacts/latest_session.txt pointer file (Windows fallback)
    3. artifacts/ flat directory (backward compatibility)

    Returns
    -------
    Path to the resolved artifacts directory.
    """
    # Option 1: latest/ symlink or real directory
    latest_path = BASE_ARTIFACTS_DIR / "latest"
    if latest_path.exists():
        resolved = latest_path.resolve()
        print(f"  📁  Artifacts directory: {resolved}")
        return resolved

    # Option 2: Windows pointer file
    pointer_path = BASE_ARTIFACTS_DIR / "latest_session.txt"
    if pointer_path.exists():
        session_path = Path(pointer_path.read_text(encoding="utf-8").strip())
        if session_path.exists():
            print(f"  📁  Artifacts directory (from pointer): {session_path}")
            return session_path

    # Option 3: flat fallback
    if BASE_ARTIFACTS_DIR.exists():
        print(f"  📁  Artifacts directory (flat fallback): {BASE_ARTIFACTS_DIR}")
        return BASE_ARTIFACTS_DIR

    # Nothing found
    print(f"  ❌  No artifacts directory found. Run 'python main.py' first.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration — resolved at runtime
# ---------------------------------------------------------------------------

ARTIFACTS_DIR = resolve_artifacts_dir()

REQUIRED_FILES = {
    "job_description.json":  Path("job_description.json"),
    "candidates.json":       Path("candidates.json"),
    "scoring_rubric.json":   ARTIFACTS_DIR / "scoring_rubric.json",
    "candidate_scores.json": ARTIFACTS_DIR / "candidate_scores.json",
    "bias_audit.json":       ARTIFACTS_DIR / "bias_audit.json",
    "hiring_summaries.md":   ARTIFACTS_DIR / "hiring_summaries.md",
    "llm_calls.jsonl":       ARTIFACTS_DIR / "llm_calls.jsonl",
}

REQUIRED_LLM_STAGES = [
    "RUBRIC_GENERATED",
    "CANDIDATES_SCORED",
    "BIAS_AUDITED",
    "SUMMARIES_GENERATED",
    "INTERVIEW_QUESTIONS_GENERATED",
    "COHORT_ANALYSIS_GENERATED",
]


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

class ValidationResult:
    def __init__(self):
        self.passed:   list[str] = []
        self.failed:   list[str] = []
        self.warnings: list[str] = []

    def ok(self, msg: str) -> None:
        self.passed.append(msg)
        print(f"  ✅  {msg}")

    def fail(self, msg: str) -> None:
        self.failed.append(msg)
        print(f"  ❌  {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  ⚠️   {msg}")

    def summary(self) -> bool:
        print(f"\n{'═'*60}")
        print(f"  VALIDATION SUMMARY")
        print(f"{'═'*60}")
        print(f"  Passed  : {len(self.passed)}")
        print(f"  Failed  : {len(self.failed)}")
        print(f"  Warnings: {len(self.warnings)}")

        if self.failed:
            print(f"\n  FAILURES:")
            for f in self.failed:
                print(f"    ✗  {f}")

        if self.warnings:
            print(f"\n  WARNINGS:")
            for w in self.warnings:
                print(f"    ⚠  {w}")

        if not self.failed:
            print(f"\n  ✅  ALL CHECKS PASSED")
        else:
            print(f"\n  ❌  {len(self.failed)} CHECK(S) FAILED")

        return len(self.failed) == 0


# ---------------------------------------------------------------------------
# Helper: safe JSON load
# ---------------------------------------------------------------------------

def load_json_safe(path: Path, result: ValidationResult) -> dict | list | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        result.fail(f"{path.name} is not valid JSON: {e}")
        return None
    except OSError as e:
        result.fail(f"Cannot read {path.name}: {e}")
        return None


def load_jsonl_safe(path: Path, result: ValidationResult) -> list[dict]:
    records = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    result.fail(f"llm_calls.jsonl line {i} is invalid JSON: {e}")
    except OSError as e:
        result.fail(f"Cannot read llm_calls.jsonl: {e}")
    return records


# ---------------------------------------------------------------------------
# Check 1: Required files exist
# ---------------------------------------------------------------------------

def check_files_exist(result: ValidationResult) -> bool:
    print(f"\n{'─'*60}")
    print(f"  CHECK 1 — Required artifact files exist")
    print(f"{'─'*60}")

    all_present = True
    for name, path in REQUIRED_FILES.items():
        if path.exists():
            result.ok(f"Found: {path}")
        else:
            result.fail(f"Missing required file: {path}")
            all_present = False

    return all_present


# ---------------------------------------------------------------------------
# Check 2: JSON files are valid
# ---------------------------------------------------------------------------

def check_json_validity(result: ValidationResult) -> dict:
    print(f"\n{'─'*60}")
    print(f"  CHECK 2 — JSON files are valid")
    print(f"{'─'*60}")

    loaded = {}
    json_files = {
        "job_description": Path("job_description.json"),
        "candidates":      Path("candidates.json"),
        "rubric":          ARTIFACTS_DIR / "scoring_rubric.json",
        "scores":          ARTIFACTS_DIR / "candidate_scores.json",
        "audit":           ARTIFACTS_DIR / "bias_audit.json",
    }

    for key, path in json_files.items():
        if not path.exists():
            result.warn(f"Skipping JSON validation for missing file: {path}")
            continue
        data = load_json_safe(path, result)
        if data is not None:
            loaded[key] = data
            result.ok(f"Valid JSON: {path.name}")

    return loaded


# ---------------------------------------------------------------------------
# Check 3: Rubric has exactly 6 criteria
# ---------------------------------------------------------------------------

def check_rubric_criteria(rubric: dict, result: ValidationResult) -> None:
    print(f"\n{'─'*60}")
    print(f"  CHECK 3 — Rubric contains exactly 6 criteria")
    print(f"{'─'*60}")

    criteria = rubric.get("criteria", [])
    count    = len(criteria)

    if count == 6:
        result.ok(f"Rubric has exactly 6 criteria")
    else:
        result.fail(f"Rubric has {count} criteria — must be exactly 6")

    required_fields = {"id", "name", "weight", "description", "score_10_means"}
    for i, c in enumerate(criteria):
        missing = required_fields - set(c.keys())
        if missing:
            result.fail(f"Criterion [{i}] missing fields: {missing}")
        else:
            result.ok(f"Criterion [{c.get('id', i)}] has all required fields")

    total_weight = sum(c.get("weight", 0) for c in criteria)
    if 0.98 <= total_weight <= 1.02:
        result.ok(f"Rubric weights sum to {total_weight:.3f} (within tolerance)")
    else:
        result.fail(f"Rubric weights sum to {total_weight:.3f} — must be ~1.0")


# ---------------------------------------------------------------------------
# Check 4: Approved rubric was used for scoring
# ---------------------------------------------------------------------------

def check_rubric_used_for_scoring(
    rubric: dict,
    scores: dict,
    result: ValidationResult,
) -> None:
    print(f"\n{'─'*60}")
    print(f"  CHECK 4 — Approved rubric was used for candidate scoring")
    print(f"{'─'*60}")

    ref = scores.get("rubric_reference", "")
    if ref:
        result.ok(f"candidate_scores.json references rubric: {ref}")
    else:
        result.fail("candidate_scores.json missing 'rubric_reference' field")

    rubric_criterion_ids = {c["id"] for c in rubric.get("criteria", [])}
    original_scores      = scores.get("original_scores", [])

    if not original_scores:
        result.fail("No original_scores found — cannot verify rubric usage")
        return

    for scored in original_scores:
        scored_criterion_ids = {
            cs["criterion_id"] for cs in scored.get("criterion_scores", [])
        }
        extra   = scored_criterion_ids - rubric_criterion_ids
        missing = rubric_criterion_ids - scored_criterion_ids

        if missing:
            result.fail(
                f"Candidate {scored['candidate_id']} missing criteria "
                f"from approved rubric: {missing}"
            )
        elif extra:
            result.fail(
                f"Candidate {scored['candidate_id']} scored on criteria "
                f"not in approved rubric: {extra}"
            )
        else:
            result.ok(
                f"Candidate {scored['candidate_id']} scored on all approved rubric criteria"
            )


# ---------------------------------------------------------------------------
# Check 5: All candidates were scored
# ---------------------------------------------------------------------------

def check_all_candidates_scored(
    candidates: list,
    scores: dict,
    result: ValidationResult,
) -> None:
    print(f"\n{'─'*60}")
    print(f"  CHECK 5 — All candidates from candidates.json were scored")
    print(f"{'─'*60}")

    candidate_ids = {c["id"] for c in candidates}
    scored_ids    = {s["candidate_id"] for s in scores.get("original_scores", [])}

    missing = candidate_ids - scored_ids
    extra   = scored_ids - candidate_ids

    if not missing and not extra:
        result.ok(f"All {len(candidate_ids)} candidates were scored")
    if missing:
        result.fail(f"Candidates not scored: {missing}")
    if extra:
        result.warn(f"Scores found for unknown candidate IDs: {extra}")

    for scored in scores.get("original_scores", []):
        n_criteria = len(scored.get("criterion_scores", []))
        cid = scored["candidate_id"]
        if n_criteria == 6:
            result.ok(f"{cid}: 6 criteria scored")
        else:
            result.fail(f"{cid}: {n_criteria} criteria scored — expected 6")


# ---------------------------------------------------------------------------
# Check 6: Original and corrected scores preserved
# ---------------------------------------------------------------------------

def check_score_preservation(scores: dict, result: ValidationResult) -> None:
    print(f"\n{'─'*60}")
    print(f"  CHECK 6 — Original and corrected scores preserved")
    print(f"{'─'*60}")

    original = scores.get("original_scores")
    if original is not None and len(original) > 0:
        result.ok(f"original_scores present with {len(original)} entries")
    else:
        result.fail("original_scores is missing or empty")

    rescoring_occurred = scores.get("rescoring_occurred", False)

    if rescoring_occurred:
        corrected = scores.get("corrected_scores")
        if corrected is not None and len(corrected) > 0:
            result.ok(f"corrected_scores present with {len(corrected)} entries")
        else:
            result.fail("rescoring_occurred=True but corrected_scores is missing or empty")

        if original and corrected:
            orig_ids      = {s["candidate_id"] for s in original}
            corrected_ids = {s["candidate_id"] for s in corrected}
            if orig_ids == corrected_ids:
                result.ok("Both score sets cover the same candidate IDs")
            else:
                result.fail(
                    f"Candidate ID mismatch: Original={orig_ids} | Corrected={corrected_ids}"
                )

            orig_map = {s["candidate_id"]: s["total_weighted_score"] for s in original}
            corr_map = {s["candidate_id"]: s["total_weighted_score"] for s in corrected}
            changed  = [
                cid for cid in orig_map
                if abs(orig_map[cid] - corr_map.get(cid, orig_map[cid])) > 0.001
            ]
            if changed:
                result.ok(f"Score changes detected for: {changed}")
            else:
                result.warn("rescoring_occurred=True but no score values changed")
    else:
        corrected = scores.get("corrected_scores")
        if corrected is None:
            result.ok("No re-scoring required — corrected_scores correctly None")
        else:
            result.warn("corrected_scores is set but rescoring_occurred=False")


# ---------------------------------------------------------------------------
# Check 7: Bias audit structure
# ---------------------------------------------------------------------------

def check_bias_audit(audit: dict, result: ValidationResult) -> None:
    print(f"\n{'─'*60}")
    print(f"  CHECK 7 — bias_audit.json structure is valid")
    print(f"{'─'*60}")

    try:
        from pipeline.bias import validate_audit_structure
        errors = validate_audit_structure(audit)
        if not errors:
            result.ok("bias_audit.json has valid structure")
        else:
            for e in errors:
                result.fail(e)
    except ImportError:
        if "findings" not in audit:
            result.fail("bias_audit.json missing 'findings' key")
        else:
            result.ok("bias_audit.json has 'findings' key")

    findings = audit.get("findings", [])
    result.ok(f"bias_audit.json has {len(findings)} finding(s)")

    valid_severities = {"flagged", "watch", "clear"}
    for i, f in enumerate(findings):
        sev = f.get("severity", "")
        if sev in valid_severities:
            result.ok(f"Finding [{i}] severity '{sev}' is valid")
        else:
            result.fail(f"Finding [{i}] has invalid severity '{sev}'")


# ---------------------------------------------------------------------------
# Check 8: Bias audit before ranking
# ---------------------------------------------------------------------------

def check_audit_before_ranking(
    llm_records: list[dict],
    scores: dict,
    result: ValidationResult,
) -> None:
    print(f"\n{'─'*60}")
    print(f"  CHECK 8 — Bias audit completed before ranking was produced")
    print(f"{'─'*60}")

    stages_in_order = [r.get("stage") for r in llm_records]

    if "BIAS_AUDITED" not in stages_in_order:
        result.fail("BIAS_AUDITED stage not found in llm_calls.jsonl")
        return
    result.ok("BIAS_AUDITED stage present in llm_calls.jsonl")

    bias_idx      = stages_in_order.index("BIAS_AUDITED")
    summaries_idx = (
        stages_in_order.index("SUMMARIES_GENERATED")
        if "SUMMARIES_GENERATED" in stages_in_order else None
    )

    if summaries_idx is not None:
        if bias_idx < summaries_idx:
            result.ok(
                f"BIAS_AUDITED (call #{bias_idx+1}) precedes "
                f"SUMMARIES_GENERATED (call #{summaries_idx+1})"
            )
        else:
            result.fail("SUMMARIES_GENERATED appears before BIAS_AUDITED — ordering violated")

    audit_status  = scores.get("bias_audit_status", "")
    final_ranking = scores.get("final_ranking", [])

    if final_ranking and audit_status != "COMPLETE":
        result.fail(
            f"final_ranking populated but bias_audit_status='{audit_status}'"
        )
    elif final_ranking and audit_status == "COMPLETE":
        result.ok("final_ranking present and bias_audit_status=COMPLETE")
    elif not final_ranking:
        result.warn("final_ranking is empty — pipeline may not have completed fully")


# ---------------------------------------------------------------------------
# Check 9: Anonymised re-scoring
# ---------------------------------------------------------------------------

def check_anonymised_rescoring(
    scores: dict,
    llm_records: list[dict],
    result: ValidationResult,
) -> None:
    print(f"\n{'─'*60}")
    print(f"  CHECK 9 — Flagged criteria re-scored with anonymised data")
    print(f"{'─'*60}")

    rescoring_occurred = scores.get("rescoring_occurred", False)
    flagged_criteria   = scores.get("flagged_criteria", [])

    if not rescoring_occurred:
        if not flagged_criteria:
            result.ok("No flagged criteria — anonymised re-scoring not required")
        else:
            result.warn(
                f"Flagged criteria exist {flagged_criteria} but rescoring_occurred=False"
            )
        return

    rescore_records = [
        r for r in llm_records if r.get("stage") == "FLAGGED_RESCORING_COMPLETE"
    ]

    if not rescore_records:
        result.fail(
            "rescoring_occurred=True but no FLAGGED_RESCORING_COMPLETE record in log"
        )
        return

    result.ok(f"Found {len(rescore_records)} FLAGGED_RESCORING_COMPLETE log record(s)")

    for i, rec in enumerate(rescore_records):
        if not rec.get("candidate_names_included", True):
            result.ok(f"Rescore call [{i}] has candidate_names_included=False (anonymised)")
        else:
            result.fail(f"Rescore call [{i}] has candidate_names_included=True — must be False")

    if flagged_criteria:
        result.ok(f"Flagged criteria recorded: {flagged_criteria}")
    else:
        result.warn("rescoring_occurred=True but flagged_criteria list is empty")


# ---------------------------------------------------------------------------
# Check 10: LLM call log completeness
# ---------------------------------------------------------------------------

def check_llm_call_log(
    llm_records: list[dict],
    result: ValidationResult,
) -> None:
    print(f"\n{'─'*60}")
    print(f"  CHECK 10 — llm_calls.jsonl has all required stage records")
    print(f"{'─'*60}")

    if not llm_records:
        result.fail("llm_calls.jsonl is empty — no LLM calls logged")
        return

    result.ok(f"llm_calls.jsonl has {len(llm_records)} record(s)")

    stages_logged = [r.get("stage") for r in llm_records]

    for required_stage in REQUIRED_LLM_STAGES:
        if required_stage in stages_logged:
            result.ok(f"Stage '{required_stage}' is logged")
        else:
            result.fail(f"Required stage '{required_stage}' not found in llm_calls.jsonl")

    required_record_fields = {
        "stage", "timestamp", "model", "provider",
        "prompt_hash", "input_artifacts", "output_artifact",
        "candidate_names_included",
    }
    for i, rec in enumerate(llm_records):
        missing = required_record_fields - set(rec.keys())
        if missing:
            result.fail(f"llm_calls.jsonl record [{i}] missing fields: {missing}")
        else:
            result.ok(f"Record [{i}] ({rec.get('stage', '?')}) has all required fields")


# ---------------------------------------------------------------------------
# Check 11: hiring_summaries.md content
# ---------------------------------------------------------------------------

def check_hiring_summaries(result: ValidationResult) -> None:
    print(f"\n{'─'*60}")
    print(f"  CHECK 11 — hiring_summaries.md is non-empty")
    print(f"{'─'*60}")

    path = ARTIFACTS_DIR / "hiring_summaries.md"
    if not path.exists():
        result.fail("hiring_summaries.md does not exist")
        return

    content       = path.read_text(encoding="utf-8").strip()
    content_lower = content.lower()

    if not content:
        result.fail("hiring_summaries.md exists but is empty")
        return

    result.ok(f"hiring_summaries.md is non-empty ({len(content)} chars)")

    rank_patterns = [
        ["## rank 1", "## #1", "## rank #1", "rank 1 —", "rank 1-"],
        ["## rank 2", "## #2", "## rank #2", "rank 2 —", "rank 2-"],
        ["## rank 3", "## #3", "## rank #3", "rank 3 —", "rank 3-"],
    ]

    for rank_num, patterns in enumerate(rank_patterns, start=1):
        if any(p in content_lower for p in patterns):
            result.ok(f"Rank {rank_num} candidate section found")
        else:
            result.warn(f"Rank {rank_num} section not clearly identified")

    if "cohort analysis" in content_lower:
        result.ok("Cohort Analysis section found")
    else:
        result.warn("Cohort Analysis section not found")


# ---------------------------------------------------------------------------
# Check 12: Interview questions and cohort analysis logged
# ---------------------------------------------------------------------------

def check_interview_and_cohort(
    llm_records: list[dict],
    result: ValidationResult,
) -> None:
    print(f"\n{'─'*60}")
    print(f"  CHECK 12 — Interview questions and cohort analysis generated")
    print(f"{'─'*60}")

    stages_logged = [r.get("stage") for r in llm_records]

    if "INTERVIEW_QUESTIONS_GENERATED" in stages_logged:
        result.ok("INTERVIEW_QUESTIONS_GENERATED stage logged")
        iq_records = [
            r for r in llm_records
            if r.get("stage") == "INTERVIEW_QUESTIONS_GENERATED"
        ]
        for i, rec in enumerate(iq_records):
            if rec.get("candidate_names_included") is True:
                result.ok(f"Interview questions call [{i}] correctly includes candidate names")
            else:
                result.warn(
                    f"Interview questions call [{i}] has "
                    f"candidate_names_included={rec.get('candidate_names_included')}"
                )
    else:
        result.fail("INTERVIEW_QUESTIONS_GENERATED not found in llm_calls.jsonl")

    if "COHORT_ANALYSIS_GENERATED" in stages_logged:
        result.ok("COHORT_ANALYSIS_GENERATED stage logged")
    else:
        result.fail("COHORT_ANALYSIS_GENERATED not found in llm_calls.jsonl")

    # Check stretch stages are logged
    if "COUNTER_INTUITIVE_PICK" in stages_logged:
        result.ok("COUNTER_INTUITIVE_PICK (Stretch 8) stage logged")
    else:
        result.warn("COUNTER_INTUITIVE_PICK not found — Stretch 8 may not have run")

    blind_stages = [s for s in stages_logged if s.startswith("BLIND_RERANKING")]
    if blind_stages:
        result.ok(f"Blind re-ranking stages logged: {blind_stages}")
        anon_blind = [
            r for r in llm_records
            if r.get("stage", "").startswith("BLIND_RERANKING")
            and not r.get("candidate_names_included", True)
        ]
        if len(anon_blind) == len(blind_stages):
            result.ok("All blind re-ranking calls correctly anonymised")
        else:
            result.fail(
                f"Some blind re-ranking calls have candidate_names_included=True — "
                f"must be False"
            )
    else:
        result.warn("BLIND_RERANKING stages not found — Stretch 9 may not have run")

    # Verify sections in hiring_summaries.md
    summaries_path = ARTIFACTS_DIR / "hiring_summaries.md"
    if summaries_path.exists():
        content_lower = summaries_path.read_text(encoding="utf-8").lower()
        if any(p in content_lower for p in ["interview question", "structured interview", "behavioural"]):
            result.ok("Interview questions section found in hiring_summaries.md")
        else:
            result.warn("Interview questions section not detected in hiring_summaries.md")

        if "counter-intuitive" in content_lower or "devil's advocate" in content_lower:
            result.ok("Counter-intuitive pick section found in hiring_summaries.md")
        else:
            result.warn("Counter-intuitive pick section not detected in hiring_summaries.md")

        if "blind re-ranking" in content_lower or "blind reranking" in content_lower:
            result.ok("Blind re-ranking section found in hiring_summaries.md")
        else:
            result.warn("Blind re-ranking section not detected in hiring_summaries.md")


# ---------------------------------------------------------------------------
# Check 13: Session directory structure
# ---------------------------------------------------------------------------

def check_session_structure(result: ValidationResult) -> None:
    print(f"\n{'─'*60}")
    print(f"  CHECK 13 — Session directory structure")
    print(f"{'─'*60}")

    sessions = sorted(BASE_ARTIFACTS_DIR.glob("session_*"), reverse=True)
    if sessions:
        result.ok(f"Found {len(sessions)} session(s) in {BASE_ARTIFACTS_DIR}/")
        result.ok(f"Most recent session: {sessions[0].name}")
    else:
        result.warn(
            f"No session_* directories found in {BASE_ARTIFACTS_DIR}/ — "
            f"may be using flat artifact layout"
        )

    latest_path = BASE_ARTIFACTS_DIR / "latest"
    pointer_path = BASE_ARTIFACTS_DIR / "latest_session.txt"

    if latest_path.exists():
        result.ok(f"artifacts/latest/ exists → {latest_path.resolve()}")
    elif pointer_path.exists():
        result.ok(f"artifacts/latest_session.txt exists (Windows pointer)")
    else:
        result.warn(
            "Neither artifacts/latest/ nor artifacts/latest_session.txt found — "
            "validate.py fell back to flat artifacts/ directory"
        )


# ---------------------------------------------------------------------------
# Main validation runner
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\n{'#'*60}")
    print(f"  RECRUITMENT PIPELINE — VALIDATION")
    print(f"{'#'*60}")

    result = ValidationResult()

    files_ok = check_files_exist(result)
    if not files_ok:
        print("\n  ⚠️   Some required files are missing.")
        print("  Run 'python main.py' first to generate all artifacts.\n")

    loaded     = check_json_validity(result)
    rubric     = loaded.get("rubric")
    scores     = loaded.get("scores")
    audit      = loaded.get("audit")
    candidates = loaded.get("candidates", [])

    if rubric:
        check_rubric_criteria(rubric, result)
    else:
        result.fail("Cannot check rubric — scoring_rubric.json not loaded")

    if rubric and scores:
        check_rubric_used_for_scoring(rubric, scores, result)
    else:
        result.warn("Skipping rubric-scoring consistency check")

    if candidates and scores:
        check_all_candidates_scored(candidates, scores, result)
    else:
        result.warn("Skipping candidate coverage check")

    if scores:
        check_score_preservation(scores, result)
    else:
        result.fail("Cannot check score preservation — candidate_scores.json not loaded")

    if audit:
        check_bias_audit(audit, result)
    else:
        result.fail("Cannot check bias audit — bias_audit.json not loaded")

    llm_records = load_jsonl_safe(ARTIFACTS_DIR / "llm_calls.jsonl", result)

    if scores and llm_records is not None:
        check_audit_before_ranking(llm_records, scores, result)
    else:
        result.warn("Skipping audit-before-ranking check")

    if scores and llm_records is not None:
        check_anonymised_rescoring(scores, llm_records, result)
    else:
        result.warn("Skipping anonymised re-scoring check")

    if llm_records is not None:
        check_llm_call_log(llm_records, result)
    else:
        result.fail("Cannot check LLM call log")

    check_hiring_summaries(result)

    if llm_records is not None:
        check_interview_and_cohort(llm_records, result)
    else:
        result.warn("Skipping interview/cohort check")

    check_session_structure(result)

    all_passed = result.summary()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()