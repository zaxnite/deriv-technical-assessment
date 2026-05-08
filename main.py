# main.py
"""
Entry point for the recruitment screening pipeline.

Run with:
    python main.py

Each run creates a timestamped session directory:
    artifacts/session_YYYYMMDD_HHMMSS/

artifacts/latest/ always points to the most recent session,
allowing validate.py to check the latest run without knowing the timestamp.
"""

from __future__ import annotations

import sys
import os
import shutil
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
    stage_counter_intuitive_pick,
    stage_blind_reranking,
    RubricRejectedError,
)

BASE_ARTIFACTS_DIR   = "artifacts"
JOB_DESCRIPTION_PATH = "job_description.json"
CANDIDATES_PATH      = "candidates.json"
MAX_RUBRIC_RETRIES   = 3


def create_session_dir() -> str:
    """
    Create a timestamped session directory under artifacts/.

    Returns the path to the new session directory.

    Structure:
        artifacts/
            session_20260508_182611/   <- this run
            session_20260508_183045/   <- previous run
            latest/                    <- always the most recent session
    """
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"session_{timestamp}"
    session_dir = Path(BASE_ARTIFACTS_DIR) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return str(session_dir)


def update_latest_symlink(session_dir: str) -> None:
    """
    Make artifacts/latest/ point to the most recent session.

    On Windows, creates a real directory copy since symlinks require
    elevated permissions. On Unix, creates a proper symlink.
    """
    latest_path = Path(BASE_ARTIFACTS_DIR) / "latest"

    # Remove existing latest
    if latest_path.exists():
        if latest_path.is_symlink():
            latest_path.unlink()
        elif latest_path.is_dir():
            shutil.rmtree(latest_path)

    session_path = Path(session_dir)

    try:
        # Try symlink first (works on Unix and Windows with dev mode)
        latest_path.symlink_to(session_path.resolve(), target_is_directory=True)
        print(f"  ✅  Session symlinked to: {latest_path}")
    except (OSError, NotImplementedError):
        # Windows fallback — copy the directory
        # Will be refreshed at end of run when all artifacts are written
        # Store the session path in a pointer file for validate.py
        pointer_path = Path(BASE_ARTIFACTS_DIR) / "latest_session.txt"
        pointer_path.write_text(str(session_path.resolve()), encoding="utf-8")
        print(f"  ✅  Session pointer written to: {pointer_path}")


def print_banner(session_dir: str) -> None:
    print(f"\n{'#'*60}")
    print(f"  DERIV — AI RECRUITMENT SCREENING PIPELINE")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Session: {session_dir}")
    print(f"{'#'*60}")


def print_complete(session_dir: str) -> None:
    print(f"\n{'#'*60}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Session artifacts: {session_dir}/")
    print(f"  Latest artifacts:  {BASE_ARTIFACTS_DIR}/latest/")
    print(f"  Run validation with: python validate.py")
    print(f"{'#'*60}\n")


def run_pipeline() -> None:
    """Orchestrate all pipeline stages in strict order."""

    # Create session directory for this run
    session_dir = create_session_dir()

    print_banner(session_dir)

    state  = PipelineState(artifacts_dir=session_dir)
    logger = LLMCallLogger(log_path=Path(session_dir) / "llm_calls.jsonl")
    state.llm_calls_path = str(Path(session_dir) / "llm_calls.jsonl")

    # STAGE 1: INIT
    try:
        job_description, candidates = stage_init(
            state=state,
            job_description_path=JOB_DESCRIPTION_PATH,
            candidates_path=CANDIDATES_PATH,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"\n  ❌  INIT failed: {e}")
        sys.exit(1)

    # STAGE 2 + 3: RUBRIC_GENERATED + RUBRIC_APPROVED
    approved_rubric = None
    for attempt in range(1, MAX_RUBRIC_RETRIES + 1):
        if attempt > 1:
            print(f"\n  Regenerating rubric (attempt {attempt}/{MAX_RUBRIC_RETRIES})...")
            state.current_stage = PipelineStage.INIT

        try:
            draft_rubric    = stage_generate_rubric(state, job_description, logger)
            approved_rubric = stage_approve_rubric(state, draft_rubric)
            break
        except RubricRejectedError:
            if attempt == MAX_RUBRIC_RETRIES:
                print(f"\n  ❌  Rubric rejected {MAX_RUBRIC_RETRIES} times. Exiting.")
                sys.exit(1)
        except RuntimeError as e:
            print(f"\n  ❌  Rubric generation failed: {e}")
            sys.exit(1)

    if approved_rubric is None:
        print("\n  ❌  No approved rubric — cannot continue.")
        sys.exit(1)

    # STAGE 4: CANDIDATES_SCORED
    try:
        scores_data = stage_score_candidates(state, candidates, approved_rubric, logger)
    except RuntimeError as e:
        print(f"\n  ❌  Candidate scoring failed: {e}")
        sys.exit(1)

    # STAGE 5: BIAS_AUDITED
    try:
        audit_data = stage_audit_bias(
            state, candidates, approved_rubric, scores_data, logger
        )
    except RuntimeError as e:
        print(f"\n  ❌  Bias audit failed: {e}")
        sys.exit(1)

    # STAGE 6: FLAGGED_RESCORING (conditional)
    if state.rescoring_required:
        try:
            scores_data = stage_rescore_flagged(
                state, candidates, approved_rubric, scores_data, audit_data, logger
            )
        except RuntimeError as e:
            print(f"\n  ❌  Re-scoring failed: {e}")
            sys.exit(1)

    # STAGE 7: RANKING_FINALISED (hard-gated)
    try:
        ranking = stage_finalise_ranking(state, scores_data)
    except RuntimeError as e:
        print(f"\n  ❌  Ranking failed: {e}")
        sys.exit(1)

    # STAGE 8: SUMMARIES_GENERATED
    try:
        stage_generate_summaries(
            state, candidates, approved_rubric,
            scores_data, job_description, ranking, logger
        )
    except RuntimeError as e:
        print(f"\n  ❌  Summary generation failed: {e}")
        sys.exit(1)

    # STAGE 9: INTERVIEW QUESTIONS (Task 6)
    try:
        stage_generate_interview_questions(
            state, candidates, scores_data,
            approved_rubric, job_description, ranking, logger
        )
    except RuntimeError as e:
        print(f"\n  ❌  Interview question generation failed: {e}")
        sys.exit(1)

    # STAGE 10: COHORT ANALYSIS (Task 7)
    try:
        stage_generate_cohort_analysis(
            state, candidates, approved_rubric,
            job_description, ranking, scores_data, logger
        )
    except RuntimeError as e:
        print(f"\n  ❌  Cohort analysis generation failed: {e}")
        sys.exit(1)

    # STAGE 11: COUNTER-INTUITIVE PICK (Stretch 8)
    try:
        stage_counter_intuitive_pick(
            state, candidates, approved_rubric,
            job_description, ranking, scores_data, logger
        )
    except RuntimeError as e:
        print(f"\n  ❌  Counter-intuitive pick failed: {e}")
        sys.exit(1)

    # STAGE 12: BLIND RE-RANKING (Stretch 9)
    try:
        stage_blind_reranking(
            state, candidates, approved_rubric, job_description, ranking, logger
        )
    except RuntimeError as e:
        print(f"\n  ❌  Blind re-ranking failed: {e}")
        sys.exit(1)

    # Update latest pointer after all artifacts are written
    update_latest_symlink(session_dir)

    print_complete(session_dir)


if __name__ == "__main__":
    run_pipeline()