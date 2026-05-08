# pipeline/stages.py
"""
Stage orchestration functions for the recruitment screening pipeline.

Each function corresponds to one pipeline stage and is responsible for:
1. Enforcing stage prerequisites via PipelineState guards
2. Calling the appropriate LLM function from llm.py
3. Writing/updating artifacts to disk
4. Advancing the pipeline state
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Optional

from pipeline.state import PipelineState, PipelineStage
from pipeline.logger import LLMCallLogger
from pipeline import llm
from pipeline.bias import (
    requires_rescoring,
    get_flagged_criteria,
    build_final_scores,
    rank_candidates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: str) -> dict | list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: dict | list) -> None:
    os.makedirs(Path(path).parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _print_stage(label: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  STAGE: {label}")
    print(f"{'─'*60}")


# ---------------------------------------------------------------------------
# Stage: INIT
# ---------------------------------------------------------------------------

def stage_init(
    state: PipelineState,
    job_description_path: str = "job_description.json",
    candidates_path: str = "candidates.json",
) -> tuple[dict, list[dict]]:
    """INIT stage: Load and validate input files."""
    _print_stage("INIT — Loading input files")

    for path in [job_description_path, candidates_path]:
        if not Path(path).exists():
            raise FileNotFoundError(
                f"Required input file not found: {path}"
            )

    job_description = _load_json(job_description_path)
    candidates      = _load_json(candidates_path)

    required_jd_keys = {"role", "requirements"}
    missing_jd = required_jd_keys - set(job_description.keys())
    if missing_jd:
        raise ValueError(f"job_description.json missing required keys: {missing_jd}")
    if not job_description.get("requirements"):
        raise ValueError("job_description.json 'requirements' must not be empty.")

    if not isinstance(candidates, list) or len(candidates) == 0:
        raise ValueError("candidates.json must be a non-empty list.")
    for i, c in enumerate(candidates):
        missing_c = {"id", "name", "summary"} - set(c.keys())
        if missing_c:
            raise ValueError(
                f"candidates.json entry [{i}] missing required keys: {missing_c}"
            )

    print(f"  ✅  Loaded job description: {job_description.get('role', 'Unknown role')}")
    print(f"  ✅  Loaded {len(candidates)} candidates: "
          f"{', '.join(c['id'] for c in candidates)}")

    return job_description, candidates


# ---------------------------------------------------------------------------
# Stage: RUBRIC_GENERATED
# ---------------------------------------------------------------------------

def stage_generate_rubric(
    state: PipelineState,
    job_description: dict,
    logger: LLMCallLogger,
) -> dict:
    """RUBRIC_GENERATED stage: Generate scoring rubric via Stage 1 LLM call."""
    _print_stage("RUBRIC_GENERATED — Generating scoring rubric")
    state.require_stage(PipelineStage.INIT)

    rubric = llm.generate_rubric(
        job_description=job_description,
        logger=logger,
        artifacts_dir=state.artifacts_dir,
    )

    state.advance_to(PipelineStage.RUBRIC_GENERATED)
    print(f"  ✅  Rubric generated with {len(rubric['criteria'])} criteria")
    for c in rubric["criteria"]:
        print(f"       [{c['id']}] {c['name']} — weight: {c['weight']}")

    return rubric


# ---------------------------------------------------------------------------
# Stage: RUBRIC_APPROVED
# ---------------------------------------------------------------------------

def stage_approve_rubric(
    state: PipelineState,
    rubric: dict,
) -> dict:
    """RUBRIC_APPROVED stage: Interactive terminal checkpoint."""
    _print_stage("RUBRIC_APPROVED — Interactive rubric checkpoint")
    state.require_stage(PipelineStage.RUBRIC_GENERATED)

    approved_rubric = _run_rubric_checkpoint(rubric)

    rubric_path = str(Path(state.artifacts_dir) / "scoring_rubric.json")
    _save_json(rubric_path, approved_rubric)
    state.rubric_path = rubric_path

    state.advance_to(PipelineStage.RUBRIC_APPROVED)
    print(f"  ✅  Approved rubric saved to: {rubric_path}")

    return approved_rubric


def _run_rubric_checkpoint(rubric: dict) -> dict:
    """Interactive terminal rubric review loop."""
    current_rubric = rubric

    while True:
        _display_rubric(current_rubric)

        print("\n  OPTIONS:")
        print("    [A] Approve rubric and proceed to scoring")
        print("    [E] Edit criterion name, description, or weight")
        print("    [R] Reject and regenerate rubric")
        print()

        choice = input("  Your choice [A/E/R]: ").strip().upper()

        if choice == "A":
            print("\n  ✅  Rubric approved.")
            return current_rubric
        elif choice == "E":
            current_rubric = _edit_rubric_interactive(current_rubric)
        elif choice == "R":
            print("\n  ⚠️   Rubric rejected. Returning to regeneration...")
            raise RubricRejectedError("Operator rejected the rubric.")
        else:
            print("  Invalid choice. Enter A, E, or R.")


def _display_rubric(rubric: dict) -> None:
    print(f"\n  {'═'*56}")
    print(f"  DRAFT SCORING RUBRIC — {rubric.get('role', 'Role')}")
    print(f"  {'═'*56}")
    total_weight = 0
    for c in rubric.get("criteria", []):
        w = c.get("weight", 0)
        total_weight += w
        print(f"\n  [{c['id']}] {c['name']}")
        print(f"       Weight    : {w:.2f} ({w*100:.0f}%)")
        print(f"       Measures  : {c.get('description', '')}")
        print(f"       Score 10  : {c.get('score_10_means', '')}")
    print(f"\n  Total weight: {total_weight:.2f}")
    print(f"  {'═'*56}")


def _edit_rubric_interactive(rubric: dict) -> dict:
    """Allow operator to edit specific criteria fields interactively."""
    criteria = rubric.get("criteria", [])

    print("\n  Select criterion to edit:")
    for i, c in enumerate(criteria):
        print(f"    [{i+1}] {c['id']} — {c['name']} (weight: {c['weight']})")

    try:
        idx = int(input("\n  Criterion number: ").strip()) - 1
        if not (0 <= idx < len(criteria)):
            print("  Invalid selection.")
            return rubric
    except ValueError:
        print("  Invalid input — enter a number.")
        return rubric

    selected = criteria[idx]
    print(f"\n  Editing: [{selected['id']}] {selected['name']}")
    print("  Fields: [1] name  [2] description  [3] score_10_means  [4] weight")

    field_choice = input("  Field to edit [1-4]: ").strip()
    field_map    = {"1": "name", "2": "description", "3": "score_10_means", "4": "weight"}
    field        = field_map.get(field_choice)

    if not field:
        print("  Invalid field choice.")
        return rubric

    current_val = selected.get(field, "")
    print(f"  Current value: {current_val}")
    new_val = input(f"  New value: ").strip()

    if not new_val:
        print("  No change made.")
        return rubric

    if field == "weight":
        try:
            new_val = float(new_val)
        except ValueError:
            print("  Weight must be a number (e.g. 0.20).")
            return rubric

    updated_rubric = copy.deepcopy(rubric)
    updated_rubric["criteria"][idx][field] = new_val

    total = sum(c.get("weight", 0) for c in updated_rubric["criteria"])
    if not (0.95 <= total <= 1.05):
        print(f"  ⚠️   Warning: weights now sum to {total:.3f} (should be 1.0).")

    print(f"  ✅  Updated [{selected['id']}].{field} = {new_val}")
    return updated_rubric


class RubricRejectedError(Exception):
    """Raised when the operator rejects the rubric at the checkpoint."""
    pass


# ---------------------------------------------------------------------------
# Stage: CANDIDATES_SCORED
# ---------------------------------------------------------------------------

def stage_score_candidates(
    state: PipelineState,
    candidates: list[dict],
    rubric: dict,
    logger: LLMCallLogger,
) -> dict:
    """CANDIDATES_SCORED stage: Score all candidates via Stage 2 LLM call."""
    _print_stage("CANDIDATES_SCORED — Scoring candidates against rubric")
    state.require_stage(PipelineStage.RUBRIC_APPROVED)

    scores_data = llm.score_candidates(
        candidates=candidates,
        rubric=rubric,
        logger=logger,
        artifacts_dir=state.artifacts_dir,
    )

    state.scores_path = str(Path(state.artifacts_dir) / "candidate_scores.json")
    state.advance_to(PipelineStage.CANDIDATES_SCORED)

    print(f"  ✅  {len(scores_data['original_scores'])} candidates scored")
    for s in scores_data["original_scores"]:
        print(f"       {s['candidate_id']} — {s['candidate_name']}: "
              f"{s['total_weighted_score']:.2f}/10")

    return scores_data


# ---------------------------------------------------------------------------
# Stage: BIAS_AUDITED
# ---------------------------------------------------------------------------

def stage_audit_bias(
    state: PipelineState,
    candidates: list[dict],
    rubric: dict,
    scores_data: dict,
    logger: LLMCallLogger,
) -> dict:
    """BIAS_AUDITED stage: Audit scores for bias via Stage 3 LLM call."""
    _print_stage("BIAS_AUDITED — Running mandatory bias audit")
    state.require_stage(PipelineStage.CANDIDATES_SCORED)

    audit_data = llm.audit_bias(
        candidates=candidates,
        rubric=rubric,
        scores_data=scores_data,
        logger=logger,
        artifacts_dir=state.artifacts_dir,
    )

    needs_rescore    = requires_rescoring(audit_data)
    flagged_criteria = get_flagged_criteria(audit_data)

    state.bias_flags_found  = needs_rescore
    state.rescoring_required = needs_rescore
    state.bias_audit_path   = str(Path(state.artifacts_dir) / "bias_audit.json")

    scores_path = Path(state.artifacts_dir) / "candidate_scores.json"
    scores_data["bias_audit_status"] = "COMPLETE"
    scores_data["flagged_criteria"]  = flagged_criteria
    _save_json(str(scores_path), scores_data)

    state.advance_to(PipelineStage.BIAS_AUDITED)

    findings      = audit_data.get("findings", [])
    flagged_count = sum(1 for f in findings if f.get("severity") == "flagged")
    watch_count   = sum(1 for f in findings if f.get("severity") == "watch")
    clear_count   = sum(1 for f in findings if f.get("severity") == "clear")

    print(f"  ✅  Bias audit complete — {len(findings)} finding(s)")
    print(f"       Summary: {audit_data.get('audit_summary', '')[:100]}...")
    print(f"       Flagged: {flagged_count}  |  Watch: {watch_count}  |  Clear: {clear_count}")

    if needs_rescore:
        print(f"  ⚠️   Re-scoring required for criteria: {flagged_criteria}")
    else:
        print(f"  ✅  No re-scoring required — proceeding to ranking")

    return audit_data


# ---------------------------------------------------------------------------
# Stage: FLAGGED_RESCORING_COMPLETE
# ---------------------------------------------------------------------------

def stage_rescore_flagged(
    state: PipelineState,
    candidates: list[dict],
    rubric: dict,
    scores_data: dict,
    audit_data: dict,
    logger: LLMCallLogger,
) -> dict:
    """FLAGGED_RESCORING stage: Re-score flagged criteria with anonymised data."""
    _print_stage("FLAGGED_RESCORING — Anonymised re-scoring of flagged criteria")
    state.require_stage(PipelineStage.BIAS_AUDITED)

    flagged_criteria_ids = get_flagged_criteria(audit_data)

    if not flagged_criteria_ids:
        print("  ℹ️   No flagged criteria — skipping re-scoring stage.")
        state.advance_to(PipelineStage.FLAGGED_RESCORING_COMPLETE)
        return scores_data

    print(f"  ⚠️   Re-scoring criteria (anonymised): {flagged_criteria_ids}")
    print(f"       Candidate names stripped in Python before prompt construction")

    corrected_scores = llm.rescore_flagged(
        candidates=candidates,
        rubric=rubric,
        scores_data=scores_data,
        flagged_criteria_ids=flagged_criteria_ids,
        logger=logger,
        artifacts_dir=state.artifacts_dir,
    )

    scores_data["corrected_scores"]  = corrected_scores
    scores_data["rescoring_occurred"] = True

    scores_path = str(Path(state.artifacts_dir) / "candidate_scores.json")
    _save_json(scores_path, scores_data)

    state.advance_to(PipelineStage.FLAGGED_RESCORING_COMPLETE)

    print(f"  ✅  Re-scoring complete")
    print(f"       Original scores preserved in 'original_scores'")
    print(f"       Corrected scores saved in 'corrected_scores'")

    original_map = {
        s["candidate_id"]: s["total_weighted_score"]
        for s in scores_data["original_scores"]
    }
    for corrected in corrected_scores:
        cid   = corrected["candidate_id"]
        orig  = original_map.get(cid, 0)
        corr  = corrected["total_weighted_score"]
        delta = corr - orig
        sign  = "+" if delta >= 0 else ""
        print(f"       {cid}: {orig:.2f} → {corr:.2f} ({sign}{delta:.2f})")

    return scores_data


# ---------------------------------------------------------------------------
# Stage: RANKING_FINALISED
# ---------------------------------------------------------------------------

def stage_finalise_ranking(
    state: PipelineState,
    scores_data: dict,
) -> list[dict]:
    """
    RANKING_FINALISED stage: Produce the final ranked candidate list.
    Hard-gated by assert_bias_audit_complete().
    """
    _print_stage("RANKING_FINALISED — Producing final candidate ranking")

    # HARD GATE — ranking cannot proceed without bias audit
    state.assert_bias_audit_complete()

    final_scores = build_final_scores(
        scores_data=scores_data,
        corrected_scores=scores_data.get("corrected_scores"),
    )

    ranking = rank_candidates(final_scores)

    scores_data["final_ranking"] = ranking
    scores_path = str(Path(state.artifacts_dir) / "candidate_scores.json")
    _save_json(scores_path, scores_data)

    state.advance_to(PipelineStage.RANKING_FINALISED)

    score_source = "corrected" if scores_data.get("rescoring_occurred") else "original"
    print(f"  ✅  Final ranking produced (using {score_source} scores)")
    print()
    for r in ranking:
        print(f"       #{r['rank']}  {r['candidate_id']} — {r['candidate_name']}: "
              f"{r['total_weighted_score']:.2f}/10")

    return ranking


# ---------------------------------------------------------------------------
# Stage: SUMMARIES_GENERATED
# ---------------------------------------------------------------------------

def stage_generate_summaries(
    state: PipelineState,
    candidates: list[dict],
    rubric: dict,
    scores_data: dict,
    job_description: dict,
    ranking: list[dict],
    logger: LLMCallLogger,
) -> str:
    """SUMMARIES_GENERATED stage: Generate hiring committee summaries for top 3."""
    _print_stage("SUMMARIES_GENERATED — Generating hiring committee summaries")
    state.require_stage(PipelineStage.RANKING_FINALISED)

    final_scores = build_final_scores(
        scores_data=scores_data,
        corrected_scores=scores_data.get("corrected_scores"),
    )

    summaries_md = llm.generate_summaries(
        top_candidates=final_scores,
        all_candidates=candidates,
        rubric=rubric,
        job_description=job_description,
        final_ranking=ranking,
        logger=logger,
        artifacts_dir=state.artifacts_dir,
    )

    summaries_path = str(Path(state.artifacts_dir) / "hiring_summaries.md")
    state.hiring_summaries_path = summaries_path
    state.advance_to(PipelineStage.SUMMARIES_GENERATED)

    print(f"  ✅  Hiring summaries saved to: {summaries_path}")
    print(f"       Top 3 candidates covered with strengths, gaps, and interview focus areas")

    return summaries_md


# ---------------------------------------------------------------------------
# Stage 6 — Interview Questions
# ---------------------------------------------------------------------------

def stage_generate_interview_questions(
    state: PipelineState,
    candidates: list[dict],
    scores_data: dict,
    rubric: dict,
    job_description: dict,
    ranking: list[dict],
    logger: LLMCallLogger,
) -> str:
    """Stage 6: Generate 5 structured interview questions for the #1 candidate."""
    _print_stage("INTERVIEW_QUESTIONS — Generating questions for #1 candidate")
    state.require_stage(PipelineStage.SUMMARIES_GENERATED)

    top_rank    = ranking[0]
    top_cand_id = top_rank["candidate_id"]

    score_list = (
        scores_data.get("corrected_scores")
        or scores_data.get("original_scores", [])
    )
    top_scored = next(
        (s for s in score_list if s["candidate_id"] == top_cand_id), {}
    )
    top_full = next(
        (c for c in candidates if c["id"] == top_cand_id), {}
    )

    result = llm.generate_interview_questions(
        top_candidate=top_scored,
        candidate_full=top_full,
        rubric=rubric,
        job_description=job_description,
        logger=logger,
        artifacts_dir=state.artifacts_dir,
    )

    print(f"  ✅  5 interview questions generated for #1: "
          f"{top_rank.get('candidate_name', top_cand_id)}")
    print(f"       Appended to: {state.hiring_summaries_path}")

    return result


# ---------------------------------------------------------------------------
# Stage 7 — Cohort Analysis
# ---------------------------------------------------------------------------

def stage_generate_cohort_analysis(
    state: PipelineState,
    candidates: list[dict],
    rubric: dict,
    job_description: dict,
    ranking: list[dict],
    scores_data: dict,
    logger: LLMCallLogger,
) -> str:
    """Stage 7: Generate cohort analysis paragraph."""
    _print_stage("COHORT_ANALYSIS — Generating cohort summary")
    state.require_stage(PipelineStage.SUMMARIES_GENERATED)

    result = llm.generate_cohort_analysis(
        candidates=candidates,
        rubric=rubric,
        job_description=job_description,
        final_ranking=ranking,
        scores_data=scores_data,
        logger=logger,
        artifacts_dir=state.artifacts_dir,
    )

    print(f"  ✅  Cohort analysis appended to: {state.hiring_summaries_path}")

    return result


# ---------------------------------------------------------------------------
# Stretch 8 — Counter-Intuitive Pick
# ---------------------------------------------------------------------------

def stage_counter_intuitive_pick(
    state: PipelineState,
    candidates: list[dict],
    rubric: dict,
    job_description: dict,
    ranking: list[dict],
    scores_data: dict,
    logger: LLMCallLogger,
) -> str:
    """Stretch 8: Devil's advocate case for the lowest-ranked candidate."""
    _print_stage("COUNTER_INTUITIVE_PICK — Devil's advocate for lowest-ranked candidate")
    state.require_stage(PipelineStage.SUMMARIES_GENERATED)

    result = llm.generate_counter_intuitive_pick(
        candidates=candidates,
        rubric=rubric,
        job_description=job_description,
        final_ranking=ranking,
        scores_data=scores_data,
        logger=logger,
        artifacts_dir=state.artifacts_dir,
    )

    lowest = ranking[-1]
    print(f"  ✅  Counter-intuitive case written for "
          f"#{lowest['rank']}: {lowest.get('candidate_name', lowest['candidate_id'])}")
    print(f"       Appended to: {state.hiring_summaries_path}")

    return result


# ---------------------------------------------------------------------------
# Stretch 9 — Blind Re-Ranking
# ---------------------------------------------------------------------------

def stage_blind_reranking(
    state: PipelineState,
    candidates: list[dict],
    rubric: dict,
    job_description: dict,
    ranking: list[dict],
    logger: LLMCallLogger,
) -> str:
    """Stretch 9: Anonymised re-scoring and comparison to original ranking."""
    _print_stage("BLIND_RERANKING — Anonymised re-scoring and comparison")
    state.require_stage(PipelineStage.SUMMARIES_GENERATED)

    result = llm.generate_blind_reranking(
        candidates=candidates,
        rubric=rubric,
        job_description=job_description,
        original_ranking=ranking,
        logger=logger,
        artifacts_dir=state.artifacts_dir,
    )

    print(f"  ✅  Blind re-ranking analysis appended to: {state.hiring_summaries_path}")

    return result