# pipeline/bias.py
"""
Bias audit utilities for the recruitment screening pipeline.

Responsibilities:
1. Parse bias audit findings and determine if re-scoring is required
2. Identify which criteria are flagged for re-scoring
3. Anonymise candidate data in Python before any re-scoring prompt is built
   — names and demographic signals are stripped here, not inside the LLM

Anonymisation rules:
- Remove candidate name entirely
- Strip university/institution names
- Strip employer brand names (FAANG, Goldman Sachs, etc.)
- Strip geographic signals (city, country references)
- Strip degree type references
- Preserve all technical skill mentions
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Employer and institution brand signals to strip
# ---------------------------------------------------------------------------

PRESTIGE_EMPLOYERS = [
    "google", "meta", "facebook", "amazon", "apple", "microsoft", "netflix",
    "goldman sachs", "barclays", "jpmorgan", "morgan stanley", "blackrock",
    "mckinsey", "bcg", "bain", "deloitte", "accenture",
    "razorpay", "stripe", "coinbase",
]

INSTITUTION_SIGNALS = [
    "oxford", "cambridge", "harvard", "mit", "stanford", "yale", "princeton",
    "imperial", "lse", "iit", "ntu", "nus",
]

GEOGRAPHY_SIGNALS = [
    "lagos", "london", "new york", "san francisco", "bangalore", "beijing",
    "shanghai", "singapore", "dubai", "nairobi", "moscow", "paris",
    "nigeria", "uk", "us", "usa", "india", "china", "russia", "ukraine",
    "apac", "europe", "africa",
]

DEGREE_SIGNALS = [
    r"\b(phd|ph\.d|mba|m\.b\.a|b\.sc|bsc|msc|m\.sc|bachelor|master|degree"
    r"|undergraduate|graduate|honours|honor)\b"
]


# ---------------------------------------------------------------------------
# Core anonymisation
# ---------------------------------------------------------------------------

def anonymise_candidates(candidates: list[dict]) -> list[dict]:
    """
    Strip names and demographic signals from candidate records in Python.

    This function must be called BEFORE constructing any re-scoring prompt.
    The returned list preserves candidate IDs so scores can be matched back.

    Parameters
    ----------
    candidates : list of raw candidate dicts with keys: id, name, summary

    Returns
    -------
    list of anonymised dicts with keys: id, summary (name is removed)

    Raises
    ------
    ValueError  if candidates list is empty or malformed
    """
    if not candidates:
        raise ValueError("Cannot anonymise an empty candidate list.")

    anonymised = []
    for i, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ValueError(f"Candidate at index {i} is not a dict: {type(candidate)}")

        cand_id = candidate.get("id")
        if not cand_id:
            raise ValueError(f"Candidate at index {i} is missing required 'id' field.")

        summary = candidate.get("summary", "")
        if not summary:
            # Non-fatal — log and continue with empty summary
            print(f"[WARNING] Candidate {cand_id} has no summary — anonymising as empty.")

        cleaned_summary = _strip_signals(summary)

        anonymised.append({
            "id": cand_id,
            "summary": cleaned_summary,
            # Explicitly no 'name' key — enforces anonymisation
        })

    return anonymised


def _strip_signals(text: str) -> str:
    """
    Remove demographic and prestige signals from a text string.

    Applies in order:
    1. Employer brand names
    2. Institution names
    3. Geographic references
    4. Degree type mentions
    5. Leftover multiple spaces

    Parameters
    ----------
    text : raw summary string

    Returns
    -------
    Cleaned string with signals replaced by neutral placeholders.
    """
    if not text:
        return text

    result = text

    # 1. Replace prestige employer names with neutral placeholder
    for employer in PRESTIGE_EMPLOYERS:
        pattern = re.compile(re.escape(employer), re.IGNORECASE)
        result = pattern.sub("[employer]", result)

    # 2. Replace institution names
    for institution in INSTITUTION_SIGNALS:
        pattern = re.compile(re.escape(institution), re.IGNORECASE)
        result = pattern.sub("[institution]", result)

    # 3. Replace geographic signals
    for geo in GEOGRAPHY_SIGNALS:
        pattern = re.compile(r"\b" + re.escape(geo) + r"\b", re.IGNORECASE)
        result = pattern.sub("[location]", result)

    # 4. Replace degree type mentions
    for degree_pattern in DEGREE_SIGNALS:
        result = re.sub(degree_pattern, "[degree]", result, flags=re.IGNORECASE)

    # 5. Clean up multiple spaces left by replacements
    result = re.sub(r" {2,}", " ", result).strip()

    return result


# ---------------------------------------------------------------------------
# Audit result parsing
# ---------------------------------------------------------------------------

def get_flagged_criteria(audit_data: dict) -> list[str]:
    """
    Extract the list of criterion IDs that require re-scoring.

    Uses the top-level 'flagged_criteria_ids' field if present.
    Falls back to scanning findings for severity='flagged' and
    collecting their affected_criteria lists.

    Parameters
    ----------
    audit_data : parsed bias_audit.json dict

    Returns
    -------
    Deduplicated list of criterion ID strings (may be empty).

    Raises
    ------
    ValueError if audit_data is not a dict
    """
    if not isinstance(audit_data, dict):
        raise ValueError(f"audit_data must be a dict, got {type(audit_data)}")

    # Prefer the explicit top-level field the LLM was asked to return
    if "flagged_criteria_ids" in audit_data:
        ids = audit_data["flagged_criteria_ids"]
        if isinstance(ids, list):
            return list(dict.fromkeys(ids))  # deduplicate, preserve order

    # Fallback: scan findings manually
    flagged_ids: list[str] = []
    for finding in audit_data.get("findings", []):
        if finding.get("severity") == "flagged":
            criteria = finding.get("affected_criteria", [])
            if isinstance(criteria, list):
                flagged_ids.extend(criteria)

    return list(dict.fromkeys(flagged_ids))


def requires_rescoring(audit_data: dict) -> bool:
    """
    Return True if the audit produced any 'flagged' severity findings.

    Checks both the explicit 'requires_rescoring' field and scans
    findings as a fallback.

    Parameters
    ----------
    audit_data : parsed bias_audit.json dict

    Returns
    -------
    bool
    """
    if not isinstance(audit_data, dict):
        return False

    # Trust the explicit field if present
    if "requires_rescoring" in audit_data:
        return bool(audit_data["requires_rescoring"])

    # Fallback: check finding severities
    return any(
        f.get("severity") == "flagged"
        for f in audit_data.get("findings", [])
    )


def validate_audit_structure(audit_data: dict) -> list[str]:
    """
    Validate that a bias audit result has the required structure.

    Used by validate.py to check the artifact on disk.

    Parameters
    ----------
    audit_data : parsed bias_audit.json dict

    Returns
    -------
    List of error strings — empty list means valid.
    """
    errors: list[str] = []

    if not isinstance(audit_data, dict):
        errors.append("bias_audit.json root must be a JSON object.")
        return errors

    if "findings" not in audit_data:
        errors.append("bias_audit.json is missing required 'findings' key.")

    findings = audit_data.get("findings", [])
    if not isinstance(findings, list):
        errors.append("'findings' must be a list.")
        return errors

    valid_severities = {"flagged", "watch", "clear"}
    for i, finding in enumerate(findings):
        for required_key in ("bias_type", "affected_candidates", "evidence", "severity"):
            if required_key not in finding:
                errors.append(
                    f"Finding [{i}] is missing required key '{required_key}'."
                )
        severity = finding.get("severity", "")
        if severity not in valid_severities:
            errors.append(
                f"Finding [{i}] has invalid severity '{severity}'. "
                f"Must be one of: {valid_severities}."
            )

    return errors


# ---------------------------------------------------------------------------
# Scoring helpers used by stages.py
# ---------------------------------------------------------------------------

def build_final_scores(
    scores_data: dict,
    corrected_scores: Optional[list[dict]],
) -> list[dict]:
    """
    Return the score list to use for final ranking.

    If corrected scores exist, use them.
    Otherwise fall back to original Stage 2 scores.

    Parameters
    ----------
    scores_data      : full candidate_scores.json dict
    corrected_scores : list from rescore_flagged(), or None

    Returns
    -------
    List of scored_candidate dicts with total_weighted_score.
    """
    if corrected_scores:
        return corrected_scores
    return scores_data.get("original_scores", [])


def rank_candidates(scored_candidates: list[dict]) -> list[dict]:
    """
    Sort candidates by total_weighted_score descending and assign ranks.

    Parameters
    ----------
    scored_candidates : list of scored_candidate dicts

    Returns
    -------
    List of ranking dicts:
    [{"rank": 1, "candidate_id": "C4", "total_weighted_score": 8.5}, ...]

    Raises
    ------
    ValueError if scored_candidates is empty
    """
    if not scored_candidates:
        raise ValueError("Cannot rank an empty candidate list.")

    sorted_candidates = sorted(
        scored_candidates,
        key=lambda c: c.get("total_weighted_score", 0),
        reverse=True,
    )

    return [
        {
            "rank": i + 1,
            "candidate_id": c["candidate_id"],
            "candidate_name": c.get("candidate_name", ""),
            "total_weighted_score": round(c.get("total_weighted_score", 0), 4),
        }
        for i, c in enumerate(sorted_candidates)
    ]