# pipeline/stages.py
"""
Stage orchestration functions for the recruitment screening pipeline.

Each function corresponds to one pipeline stage and is responsible for:
1. Enforcing stage prerequisites via PipelineState guards
2. Calling the appropriate LLM function from llm.py
3. Writing/updating artifacts to disk
4. Advancing the pipeline state

Stage functions must be called in order from main.py.
They do not call each other — main.py is the orchestrator.
"""

from __future__ import annotations

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
    """Load and parse a JSON file from disk."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: dict | list) -> None:
    """Save data as formatted JSON to disk."""
    os.makedirs(Path(path).parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _print_stage(label: str) -> None:
    """Print a consistent stage banner to terminal."""
    print(f"\n{'─'*60}")
    print(f"  STAGE: {label}")
    print(f"{'─'*60}")


# ---------------------------------------------------------------------------
# Stage: INIT — load input files
# ---------------------------------------------------------------------------

def stage_init(
    state: PipelineState,
    job_description_path: str = "job_description.json",
    candidates_path: str = "candidates.json",
) -> tuple[dict, list[dict]]:
    """
    INIT stage: Load and validate input files from disk.

    Parameters
    ----------
    state                : Pipeline state object
    job_description_path : Path to job_description.json
    candidates_path      : Path to candidates.json

    Returns
    -------
    Tuple of (job_description dict, candidates list)

    Raises
    ------
    FileNotFoundError if either input file is missing
    ValueError        if input files fail schema validation
    """
    _print_stage("INIT — Loading input files")

    # Validate input files exist
    for path in [job_description_path, candidates_path]:
        if not Path(path).exists():
            raise FileNotFoundError(
                f"Required input file not found: {path}\n"
                f"Ensure both job_description.json and candidates.json are in "
                f"the working directory."
            )

    job_description = _load_json(job_description_path)
    candidates = _load_json(candidates_path)

    # Validate job_description schema
    required_jd_keys = {"role", "requirements"}
    missing_jd = required_jd_keys - set(job_description.keys())
    if missing_jd:
        raise ValueError(
            f"job_description.json is missing required keys: {missing_jd}"
        )
    if not job_description.get("requirements"):
        raise ValueError("job_description.json 'requirements' must not be empty.")

    # Validate candidates schema
    if not isinstance(candidates, list) or len(candidates) == 0:
        raise ValueError("candidates.json must be a non-empty list.")
    for i, c in enumerate(candidates):
        missing_c = {"id", "name", "summary"} - set(c.keys())
        if missing_c:
            raise ValueError(
                f"candidates.json entry [{i}] is missing required keys: {missing_c}"
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
    """
    RUBRIC_GENERATED stage: Call Stage 1 LLM to generate a scoring rubric.

    Saves draft to artifacts/scoring_rubric_draft.json.
    The approved rubric is saved in stage_approve_rubric().

    Returns
    -------
    Draft rubric dict with 6 criteria.
    """
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
# Stage: RUBRIC_APPROVED — interactive terminal checkpoint
# ---------------------------------------------------------------------------

def stage_approve_rubric(
    state: PipelineState,
    rubric: dict,
) -> dict:
    """
    RUBRIC_APPROVED stage: Interactive terminal checkpoint for rubric review.

    The operator may:
        [A] Approve the rubric unchanged
        [E] Edit criterion names, descriptions, or weights
        [R] Reject and signal regeneration needed

    The APPROVED rubric (not the draft) is saved to scoring_rubric.json
    and used for all candidate scoring.

    Returns
    -------
    Approved rubric dict (may differ from draft if edited).

    Raises
    ------
    SystemExit if operator rejects the rubric (caller must regenerate).
    """
    _print_stage("RUBRIC_APPROVED — Interactive rubric checkpoint")
    state.require_stage(PipelineStage.RUBRIC_GENERATED)

    approved_rubric = _run_rubric_checkpoint(rubric)

    # Save the APPROVED rubric — this is the one used for scoring
    rubric_path = str(Path(state.artifacts_dir) / "scoring_rubric.json")
    _save_json(rubric_path, approved_rubric)
    state.rubric_path = rubric_path

    state.advance_to(PipelineStage.RUBRIC_APPROVED)
    print(f"  ✅  Approved rubric saved to: {rubric_path}")

    return approved_rubric


def _run_rubric_checkpoint(rubric: dict) -> dict:
    """
    Run the interactive terminal rubric review loop.

    Loops until the operator approves or rejects the rubric.
    On edit, validates the updated rubric before accepting.

    Returns
    -------
    Final approved rubric dict.
    """
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
    """Print the rubric to terminal in a readable format."""
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
    """
    Allow operator to edit specific criteria fields interactively.

    Shows all criteria with indices, lets operator pick one and
    edit name, description, weight, or score_10_means.

    Returns
    -------
    Updated rubric dict (validated before returning).
    """
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

    field_map = {
        "1": "name",
        "2": "description",
        "3": "score_10_means",
        "4": "weight",
    }

    field = field_map.get(field_choice)
    if not field:
        print("  Invalid field choice.")
        return rubric

    current_val = selected.get(field, "")
    print(f"  Current value: {current_val}")
    new_val = input(f"  New value: ").strip()

    if not new_val:
        print("  No change made.")
        return rubric

    # Convert weight to float
    if field == "weight":
        try:
            new_val = float(new_val)
        except ValueError:
            print("  Weight must be a number (e.g. 0.20).")
            return rubric

    # Apply edit
    import copy
    updated_rubric = copy.deepcopy(rubric)
    updated_rubric["criteria"][idx][field] = new_val

    # Validate weights still sum to ~1.0 after edit
    total = sum(c.get("weight", 0) for c in updated_rubric["criteria"])
    if not (0.95 <= total <= 1.05):
        print(f"  ⚠️   Warning: weights now sum to {total:.3f} (should be 1.0).")
        print("  Edit saved anyway — fix weights before approving.")

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
    """
    CANDIDATES_SCORED stage: Call Stage 2 LLM to score all candidates.

    Saves candidate_scores.json with original_scores populated.
    corrected_scores remains None until after the bias audit.

    Returns
    -------
    Full candidate_scores dict.
    """
    _print_stage("CANDIDATES_SCORED — Scoring candidates against rubric")
    state.require_stage(PipelineStage.RUBRIC_APPROVED)

    scores_data = llm.score_candidates(
        candidates=candidates,
        rubric=rubric,
        logger=logger,
        artifacts_dir=state.artifacts_dir,
    )

    scores_path = str(Path(state.artifacts_dir) / "candidate_scores.json")
    state.scores_path = scores_path
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
    """
    BIAS_AUDITED stage: Call Stage 3 LLM to audit scores for bias.

    This stage MUST complete before any ranking can be produced.
    The state.assert_bias_audit_complete() guard in stage_finalise_ranking()
    enforces this at runtime.

    Saves bias_audit.json and updates candidate_scores.json with audit status.

    Returns
    -------
    Audit result dict.
    """
    _print_stage("BIAS_AUDITED — Running mandatory bias audit")
    state.require_stage(PipelineStage.CANDIDATES_SCORED)

    audit_data = llm.audit_bias(
        candidates=candidates,
        rubric=rubric,
        scores_data=scores_data,
        logger=logger,
        artifacts_dir=state.artifacts_dir,
    )

    # Determine if re-scoring is required
    needs_rescore = requires_rescoring(audit_data)
    flagged_criteria = get_flagged_criteria(audit_data)

    # Update pipeline state
    state.bias_flags_found = needs_rescore
    state.rescoring_required = needs_rescore
    state.bias_audit_path = str(Path(state.artifacts_dir) / "bias_audit.json")

    # Update candidate_scores.json with audit results
    scores_path = Path(state.artifacts_dir) / "candidate_scores.json"
    scores_data["bias_audit_status"] = "COMPLETE"
    scores_data["flagged_criteria"] = flagged_criteria
    _save_json(str(scores_path), scores_data)

    state.advance_to(PipelineStage.BIAS_AUDITED)

    # Print audit findings
    findings = audit_data.get("findings", [])
    print(f"  ✅  Bias audit complete — {len(findings)} finding(s)")
    print(f"       Summary: {audit_data.get('audit_summary', '')[:100]}...")

    flagged_count = sum(1 for f in findings if f.get("severity") == "flagged")
    watch_count = sum(1 for f in findings if f.get("severity") == "watch")
    clear_count = sum(1 for f in findings if f.get("severity") == "clear")

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
    """
    FLAGGED_RESCORING_COMPLETE stage: Re-score only flagged criteria
    using anonymised candidate data.

    Skipped entirely if no flagged findings exist.
    Original scores are preserved — corrected scores are added separately.

    Returns
    -------
    Updated scores_data dict with corrected_scores populated.
    """
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

    # Add corrected scores to scores_data — original_scores is NEVER modified
    scores_data["corrected_scores"] = corrected_scores
    scores_data["rescoring_occurred"] = True

    # Persist updated candidate_scores.json
    scores_path = str(Path(state.artifacts_dir) / "candidate_scores.json")
    _save_json(scores_path, scores_data)

    state.advance_to(PipelineStage.FLAGGED_RESCORING_COMPLETE)

    print(f"  ✅  Re-scoring complete")
    print(f"       Original scores preserved in 'original_scores'")
    print(f"       Corrected scores saved in 'corrected_scores'")

    # Show score deltas
    original_map = {
        s["candidate_id"]: s["total_weighted_score"]
        for s in scores_data["original_scores"]
    }
    for corrected in corrected_scores:
        cid = corrected["candidate_id"]
        orig = original_map.get(cid, 0)
        corr = corrected["total_weighted_score"]
        delta = corr - orig
        sign = "+" if delta >= 0 else ""
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

    HARD REQUIREMENT: assert_bias_audit_complete() is called here.
    If the bias audit has not completed, this function raises
    PipelineOrderError and ranking cannot proceed.

    Uses corrected scores if re-scoring occurred, otherwise original scores.

    Returns
    -------
    Final ranking list sorted by score descending.
    """
    _print_stage("RANKING_FINALISED — Producing final candidate ranking")

    # HARD GATE — ranking cannot proceed without bias audit
    state.assert_bias_audit_complete()

    # Select the right score set
    final_scores = build_final_scores(
        scores_data=scores_data,
        corrected_scores=scores_data.get("corrected_scores"),
    )

    ranking = rank_candidates(final_scores)

    # Persist ranking into candidate_scores.json
    scores_data["final_ranking"] = ranking
    scores_path = str(Path(state.artifacts_dir) / "candidate_scores.json")
    _save_json(scores_path, scores_data)

    state.advance_to(PipelineStage.RANKING_FINALISED)

    # Print final ranking
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
    """
    SUMMARIES_GENERATED stage: Generate hiring committee summaries
    for top 3 candidates plus a cohort analysis paragraph.

    Saves output to artifacts/hiring_summaries.md.

    Returns
    -------
    Markdown string of the summaries.
    """
    _print_stage("SUMMARIES_GENERATED — Generating hiring committee summaries")
    state.require_stage(PipelineStage.RANKING_FINALISED)

    # Use corrected scores if available, else original
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
    """
    Stage 6: Generate 5 structured interview questions for the #1 ranked candidate.

    Questions are specific — behavioural and technical — validating strengths
    and probing gaps identified during scoring.

    Appends output to hiring_summaries.md.
    """
    _print_stage("INTERVIEW_QUESTIONS — Generating questions for #1 candidate")
    state.require_stage(PipelineStage.SUMMARIES_GENERATED)

    # Get top-ranked candidate
    top_rank    = ranking[0]
    top_cand_id = top_rank["candidate_id"]

    # Get their full score entry
    score_list  = (
        scores_data.get("corrected_scores")
        or scores_data.get("original_scores", [])
    )
    top_scored  = next(
        (s for s in score_list if s["candidate_id"] == top_cand_id), {}
    )

    # Get their original candidate record
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

    print(f"  ✅  5 interview questions generated for #{1}: {top_rank.get('candidate_name', top_cand_id)}")
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
    """
    Stage 7: Generate a cohort analysis paragraph covering overall talent level,
    common skill gaps, and a hiring recommendation.

    Appends output to hiring_summaries.md as a separate section.
    """
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