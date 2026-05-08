# pipeline/logger.py
"""
LLM call logger for the recruitment screening pipeline.

Every LLM call made during the pipeline must be logged here.
Each record is appended as a single JSON line to llm_calls.jsonl.

Schema per record:
{
    "stage": str,                    # Pipeline stage name
    "timestamp": str,                # ISO-8601 UTC timestamp
    "model": str,                    # Model identifier
    "provider": str,                 # "anthropic" | "openai"
    "prompt_hash": str,              # SHA-256 of the full prompt (first 16 chars)
    "input_artifacts": [str],        # List of file paths used as input
    "output_artifact": str,          # File path written as output
    "candidate_names_included": bool # False for anonymised re-scoring calls
}
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LOG_PATH = Path("artifacts") / "llm_calls.jsonl"


# ---------------------------------------------------------------------------
# Core logger
# ---------------------------------------------------------------------------

class LLMCallLogger:
    """
    Appends one JSON record per LLM call to llm_calls.jsonl.

    Usage
    -----
        logger = LLMCallLogger()
        logger.log(
            stage="RUBRIC_GENERATED",
            model="claude-haiku-4-5",
            provider="anthropic",
            prompt="...",
            input_artifacts=["job_description.json"],
            output_artifact="artifacts/scoring_rubric.json",
            candidate_names_included=False,
        )
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self.log_path = Path(log_path) if log_path else DEFAULT_LOG_PATH
        self._ensure_log_file()

    def _ensure_log_file(self) -> None:
        """Create the artifacts directory and log file if they don't exist."""
        try:
            os.makedirs(self.log_path.parent, exist_ok=True)
            # Touch the file if it doesn't exist — don't truncate if it does
            if not self.log_path.exists():
                self.log_path.touch()
        except OSError as e:
            raise RuntimeError(f"Cannot initialise LLM call log at {self.log_path}: {e}") from e

    def log(
        self,
        stage: str,
        model: str,
        provider: str,
        prompt: str,
        input_artifacts: list[str],
        output_artifact: str,
        candidate_names_included: bool,
    ) -> dict:
        """
        Build and append one log record.

        Parameters
        ----------
        stage                    : Pipeline stage name (matches PipelineStage label)
        model                    : Model string e.g. "claude-haiku-4-5"
        provider                 : "anthropic" or "openai"
        prompt                   : Full prompt text — hashed, never stored in plain text
        input_artifacts          : Paths of files consumed by this call
        output_artifact          : Path of file produced by this call
        candidate_names_included : Must be False for anonymised re-scoring calls

        Returns
        -------
        The log record dict (useful for testing / inspection).
        """
        record = {
            "stage":                    stage,
            "timestamp":                datetime.now(timezone.utc).isoformat(),
            "model":                    model,
            "provider":                 provider,
            "prompt_hash":              self._hash_prompt(prompt),
            "input_artifacts":          input_artifacts,
            "output_artifact":          output_artifact,
            "candidate_names_included": candidate_names_included,
        }

        self._append_record(record)
        return record

    def _hash_prompt(self, prompt: str) -> str:
        """
        Return a SHA-256 hex digest of the prompt.
        Stored in full (64 chars) — allows deduplication without
        exposing the raw prompt text in logs.
        """
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def _append_record(self, record: dict) -> None:
        """Append a single JSON record as one line to the log file."""
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            raise RuntimeError(f"Failed to write LLM call log record: {e}") from e

    # ---------------------------------------------------------------------------
    # Read helpers — used by validate.py
    # ---------------------------------------------------------------------------

    def read_all(self) -> list[dict]:
        """
        Read and return all logged records as a list of dicts.
        Returns an empty list if the log file is empty or missing.
        """
        if not self.log_path.exists():
            return []

        records = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"[WARNING] Skipping malformed log line {line_num}: {e}")
        except OSError as e:
            raise RuntimeError(f"Failed to read LLM call log: {e}") from e

        return records

    def get_stages_logged(self) -> list[str]:
        """Return a list of stage names that have been logged (in order)."""
        return [r["stage"] for r in self.read_all()]

    def has_anonymised_call(self) -> bool:
        """Return True if at least one log record has candidate_names_included=False."""
        return any(not r.get("candidate_names_included", True) for r in self.read_all())

    def get_records_for_stage(self, stage: str) -> list[dict]:
        """Return all log records matching a given stage name."""
        return [r for r in self.read_all() if r.get("stage") == stage]

    def count_records(self) -> int:
        """Return total number of logged LLM calls."""
        return len(self.read_all())