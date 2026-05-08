# pipeline/state.py
"""
Pipeline state management and stage ordering enforcement.

This module defines the canonical stage order for the recruitment screening
pipeline and provides guard utilities that prevent out-of-order execution.
Attempting to advance to a stage before its prerequisites are met will raise
a PipelineOrderError — this is the primary enforcement mechanism that ensures
rankings cannot be produced before the bias audit completes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

class PipelineStage(IntEnum):
    """
    Ordered pipeline stages. Integer values enforce sequential progression.
    A higher value = further along the pipeline.
    Comparing stages with < / >= works naturally via IntEnum.
    """
    INIT                       = 0
    RUBRIC_GENERATED           = 1
    RUBRIC_APPROVED            = 2
    CANDIDATES_SCORED          = 3
    BIAS_AUDITED               = 4
    FLAGGED_RESCORING_COMPLETE = 5
    RANKING_FINALISED          = 6
    SUMMARIES_GENERATED        = 7


# Human-readable labels used in logs and terminal output
STAGE_LABELS: dict[PipelineStage, str] = {
    PipelineStage.INIT:                       "INIT",
    PipelineStage.RUBRIC_GENERATED:           "RUBRIC_GENERATED",
    PipelineStage.RUBRIC_APPROVED:            "RUBRIC_APPROVED",
    PipelineStage.CANDIDATES_SCORED:          "CANDIDATES_SCORED",
    PipelineStage.BIAS_AUDITED:               "BIAS_AUDITED",
    PipelineStage.FLAGGED_RESCORING_COMPLETE: "FLAGGED_RESCORING_COMPLETE",
    PipelineStage.RANKING_FINALISED:          "RANKING_FINALISED",
    PipelineStage.SUMMARIES_GENERATED:        "SUMMARIES_GENERATED",
}


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class PipelineOrderError(RuntimeError):
    """
    Raised when a stage is attempted before its required predecessor
    has completed. This is a hard enforcement error — not a warning.
    """
    def __init__(self, attempted: PipelineStage, required: PipelineStage, current: PipelineStage) -> None:
        self.attempted = attempted
        self.required  = required
        self.current   = current
        super().__init__(
            f"Cannot enter stage '{STAGE_LABELS[attempted]}'. "
            f"Required stage '{STAGE_LABELS[required]}' has not completed. "
            f"Current stage is '{STAGE_LABELS[current]}'."
        )


class PipelineStateError(RuntimeError):
    """Raised for general state consistency violations."""
    pass


# ---------------------------------------------------------------------------
# State dataclass
# ---------------------------------------------------------------------------

@dataclass
class PipelineState:
    """
    Tracks the current stage of the pipeline and all key artifact paths.

    This object is the single source of truth for pipeline progress.
    It is persisted to pipeline_state.json after every stage transition
    so the pipeline can be inspected or resumed.

    Fields
    ------
    current_stage       : The stage the pipeline has most recently completed.
    started_at          : ISO-8601 timestamp of pipeline initialisation.
    artifacts_dir       : Directory where all output artifacts are written.
    rubric_path         : Path to scoring_rubric.json once approved.
    scores_path         : Path to candidate_scores.json.
    bias_audit_path     : Path to bias_audit.json.
    hiring_summaries_path: Path to hiring_summaries.md.
    llm_calls_path      : Path to llm_calls.jsonl.
    bias_flags_found    : True if the audit produced any 'flagged' findings.
    rescoring_required  : True if flagged findings were found (same as above,
                          kept separate for explicitness in output artifacts).
    """
    current_stage:          PipelineStage = PipelineStage.INIT
    started_at:             str           = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    artifacts_dir:          str           = "artifacts"

    # Artifact paths — populated as each stage completes
    rubric_path:            Optional[str] = None
    scores_path:            Optional[str] = None
    bias_audit_path:        Optional[str] = None
    hiring_summaries_path:  Optional[str] = None
    llm_calls_path:         Optional[str] = None

    # Bias audit outcomes — set by the BIAS_AUDITED stage
    bias_flags_found:       bool          = False
    rescoring_required:     bool          = False

    # ---------------------------------------------------------------------------
    # Stage advancement
    # ---------------------------------------------------------------------------

    def advance_to(self, stage: PipelineStage) -> None:
        """
        Advance the pipeline to the given stage.

        Rules
        -----
        - Stages must be entered in strict sequential order.
        - Re-entering the current stage is a no-op (idempotent).
        - Skipping a stage raises PipelineOrderError.
        """
        if stage == self.current_stage:
            # Already at this stage — idempotent, do nothing
            return

        expected_next = PipelineStage(self.current_stage + 1)

        # Special case: FLAGGED_RESCORING_COMPLETE may be skipped
        # when no flagged findings exist. In that case the pipeline
        # jumps directly from BIAS_AUDITED → RANKING_FINALISED.
        if (
            self.current_stage == PipelineStage.BIAS_AUDITED
            and stage == PipelineStage.RANKING_FINALISED
            and not self.rescoring_required
        ):
            self.current_stage = stage
            self._persist()
            return

        if stage != expected_next:
            raise PipelineOrderError(
                attempted=stage,
                required=expected_next,
                current=self.current_stage,
            )

        self.current_stage = stage
        self._persist()

    # ---------------------------------------------------------------------------
    # Stage guards — call these at the top of any stage function
    # ---------------------------------------------------------------------------

    def require_stage(self, minimum: PipelineStage, context: str = "") -> None:
        """
        Assert that the pipeline has reached at least `minimum` stage.

        Usage
        -----
            state.require_stage(PipelineStage.BIAS_AUDITED, context="finalise_ranking")

        Raises
        ------
        PipelineOrderError if the current stage is below the minimum.
        """
        if self.current_stage < minimum:
            raise PipelineOrderError(
                attempted=minimum,
                required=minimum,
                current=self.current_stage,
            )

    def assert_bias_audit_complete(self) -> None:
        """
        Hard guard specifically for ranking. Called before any ranking
        logic executes. Ensures the bias audit cannot be bypassed.
        """
        if self.current_stage < PipelineStage.BIAS_AUDITED:
            raise PipelineOrderError(
                attempted=PipelineStage.RANKING_FINALISED,
                required=PipelineStage.BIAS_AUDITED,
                current=self.current_stage,
            )

    # ---------------------------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------------------------

    def _persist(self) -> None:
        """Write current state to pipeline_state.json inside artifacts_dir."""
        try:
            os.makedirs(self.artifacts_dir, exist_ok=True)
            state_path = Path(self.artifacts_dir) / "pipeline_state.json"
            payload = asdict(self)
            # Convert PipelineStage enum to its label string for readability
            payload["current_stage"] = STAGE_LABELS[self.current_stage]
            payload["current_stage_int"] = int(self.current_stage)
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except OSError as e:
            # Non-fatal — log but don't crash the pipeline
            print(f"[WARNING] Could not persist pipeline state: {e}")

    @classmethod
    def load(cls, artifacts_dir: str = "artifacts") -> "PipelineState":
        """
        Load a previously persisted pipeline state from disk.
        Returns a fresh INIT state if no state file exists.
        """
        state_path = Path(artifacts_dir) / "pipeline_state.json"
        if not state_path.exists():
            return cls(artifacts_dir=artifacts_dir)

        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Restore the integer stage from the persisted int field
            stage_int = data.get("current_stage_int", 0)
            state = cls(
                current_stage         = PipelineStage(stage_int),
                started_at            = data.get("started_at", datetime.now(timezone.utc).isoformat()),
                artifacts_dir         = data.get("artifacts_dir", artifacts_dir),
                rubric_path           = data.get("rubric_path"),
                scores_path           = data.get("scores_path"),
                bias_audit_path       = data.get("bias_audit_path"),
                hiring_summaries_path = data.get("hiring_summaries_path"),
                llm_calls_path        = data.get("llm_calls_path"),
                bias_flags_found      = data.get("bias_flags_found", False),
                rescoring_required    = data.get("rescoring_required", False),
            )
            return state
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise PipelineStateError(f"Failed to load pipeline state from {state_path}: {e}") from e

    # ---------------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------------

    def stage_label(self) -> str:
        """Return the human-readable label for the current stage."""
        return STAGE_LABELS[self.current_stage]

    def __str__(self) -> str:
        return (
            f"PipelineState(stage={self.stage_label()}, "
            f"bias_flags={self.bias_flags_found}, "
            f"rescoring_required={self.rescoring_required})"
        )