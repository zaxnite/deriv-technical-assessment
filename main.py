# main.py
"""
Entry point for the recruitment screening pipeline.

Run with:
    python main.py

The pipeline runs all stages in strict order:
    INIT → RUBRIC_GENERATED → RUBRIC_APPROVED → CANDIDATES_SCORED
    → BIAS_AUDITED → [FLAGGED_RESCORING_COMPLETE] → RANKING_FINALISED
    → SUMMARIES_GENERATED

An interactive terminal checkpoint pauses at RUBRIC_APPROVED.
The rubric rejection loop regenerates the rubric until approved.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from pipeline.state import PipelineState, PipelineStage
from pipeline.logger import LLMCallLogger
from pipeline.stages import (
    stage_init,
    stage_generate_rubric,
    stage_approve_rubric,
    stage_score_candidates,
    stage_audit_bias,
    stage_rescore_flagged,
    stage_finalise_ranking,
    stage_generate_summaries,
    stage_generate_interview_questions,   
    stage_generate_cohort_analysis,       
    RubricRejectedError,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ARTIFACTS_DIR        = "artifacts"
JOB_DESCRIPTION_PATH = "job_description.json"
CANDIDATES_PATH      = "candidates.json"
MAX_RUBRIC_RETRIES   = 3


def print_banner() -> None:
    print(f"\n{'#'*60}")
    print(f"  DERIV — AI RECRUITMENT SCREENING PIPELINE")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}")


def print_complete() -> None:
    print(f"\n{'#'*60}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Artifacts written to: {ARTIFACTS_DIR}/")
    print(f"  Run validation with: python validate.py")
    print(f"{'#'*60}\n")


# ---------------------------------------------------------------------------
# Main pipeline orchestration
# ---------------------------------------------------------------------------

def run_pipeline() -> None:
    """
    Orchestrate all pipeline stages in strict order.

    Raises
    ------
    SystemExit on unrecoverable errors.
    """
    print_banner()

    # Initialise shared dependencies
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    state  = PipelineState(artifacts_dir=ARTIFACTS_DIR)
    logger = LLMCallLogger(
        log_path=Path(ARTIFACTS_DIR) / "llm_calls.jsonl"
    )
    state.llm_calls_path = str(Path(ARTIFACTS_DIR) / "llm_calls.jsonl")

    # ----------------------------------------------------------------
    # STAGE 1: INIT — load inputs
    # ----------------------------------------------------------------
    try:
        job_description, candidates = stage_init(
            state=state,
            job_description_path=JOB_DESCRIPTION_PATH,
            candidates_path=CANDIDATES_PATH,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"\n  ❌  INIT failed: {e}")
        sys.exit(1)

    # ----------------------------------------------------------------
    # STAGE 2 + 3: RUBRIC_GENERATED + RUBRIC_APPROVED
    # Retry loop — operator may reject and regenerate up to MAX_RUBRIC_RETRIES
    # ----------------------------------------------------------------
    approved_rubric = None
    for attempt in range(1, MAX_RUBRIC_RETRIES + 1):
        if attempt > 1:
            print(f"\n  Regenerating rubric (attempt {attempt}/{MAX_RUBRIC_RETRIES})...")
            # Reset state back to INIT for retry
            state.current_stage = PipelineStage.INIT

        try:
            draft_rubric = stage_generate_rubric(
                state=state,
                job_description=job_description,
                logger=logger,
            )
            approved_rubric = stage_approve_rubric(
                state=state,
                rubric=draft_rubric,
            )
            break  # Approved — exit retry loop

        except RubricRejectedError:
            if attempt == MAX_RUBRIC_RETRIES:
                print(f"\n  ❌  Rubric rejected {MAX_RUBRIC_RETRIES} times. Exiting.")
                sys.exit(1)
            # Continue loop to regenerate

        except RuntimeError as e:
            print(f"\n  ❌  Rubric generation failed: {e}")
            sys.exit(1)

    if approved_rubric is None:
        print("\n  ❌  No approved rubric — cannot continue.")
        sys.exit(1)

    # ----------------------------------------------------------------
    # STAGE 4: CANDIDATES_SCORED
    # ----------------------------------------------------------------
    try:
        scores_data = stage_score_candidates(
            state=state,
            candidates=candidates,
            rubric=approved_rubric,
            logger=logger,
        )
    except RuntimeError as e:
        print(f"\n  ❌  Candidate scoring failed: {e}")
        sys.exit(1)

    # ----------------------------------------------------------------
    # STAGE 5: BIAS_AUDITED
    # ----------------------------------------------------------------
    try:
        audit_data = stage_audit_bias(
            state=state,
            candidates=candidates,
            rubric=approved_rubric,
            scores_data=scores_data,
            logger=logger,
        )
    except RuntimeError as e:
        print(f"\n  ❌  Bias audit failed: {e}")
        sys.exit(1)

    # ----------------------------------------------------------------
    # STAGE 6: FLAGGED_RESCORING_COMPLETE (conditional)
    # Only runs if the bias audit found flagged severity findings
    # ----------------------------------------------------------------
    if state.rescoring_required:
        try:
            scores_data = stage_rescore_flagged(
                state=state,
                candidates=candidates,
                rubric=approved_rubric,
                scores_data=scores_data,
                audit_data=audit_data,
                logger=logger,
            )
        except RuntimeError as e:
            print(f"\n  ❌  Re-scoring failed: {e}")
            sys.exit(1)

    # ----------------------------------------------------------------
    # STAGE 7: RANKING_FINALISED
    # Hard-gated by assert_bias_audit_complete()
    # ----------------------------------------------------------------
    try:
        ranking = stage_finalise_ranking(
            state=state,
            scores_data=scores_data,
        )
    except RuntimeError as e:
        print(f"\n  ❌  Ranking failed: {e}")
        sys.exit(1)

    # ----------------------------------------------------------------
    # STAGE 8: SUMMARIES_GENERATED
    # ----------------------------------------------------------------
    try:
        stage_generate_summaries(
            state=state,
            candidates=candidates,
            rubric=approved_rubric,
            scores_data=scores_data,
            job_description=job_description,
            ranking=ranking,
            logger=logger,
        )
    except RuntimeError as e:
        print(f"\n  ❌  Summary generation failed: {e}")
        sys.exit(1)

    # ----------------------------------------------------------------
    # STAGE 9: INTERVIEW QUESTIONS (Task 6 — Should Attempt)
    # ----------------------------------------------------------------
    try:
        from pipeline.stages import stage_generate_interview_questions
        stage_generate_interview_questions(
            state=state,
            candidates=candidates,
            scores_data=scores_data,
            rubric=approved_rubric,
            job_description=job_description,
            ranking=ranking,
            logger=logger,
        )
    except RuntimeError as e:
        print(f"\n  ❌  Interview question generation failed: {e}")
        sys.exit(1)

    # ----------------------------------------------------------------
    # STAGE 10: COHORT ANALYSIS (Task 7 — Should Attempt)
    # ----------------------------------------------------------------
    try:
        from pipeline.stages import stage_generate_cohort_analysis
        stage_generate_cohort_analysis(
            state=state,
            candidates=candidates,
            rubric=approved_rubric,
            job_description=job_description,
            ranking=ranking,
            scores_data=scores_data,
            logger=logger,
        )
    except RuntimeError as e:
        print(f"\n  ❌  Cohort analysis generation failed: {e}")
        sys.exit(1)

    print_complete()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_pipeline()