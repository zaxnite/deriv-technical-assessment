# pipeline/llm.py
"""
All LLM call functions for the recruitment screening pipeline.

Each function represents exactly one stage's LLM interaction:
    - Stage 1: generate_rubric()              -> RUBRIC_GENERATED
    - Stage 2: score_candidates()             -> CANDIDATES_SCORED
    - Stage 3: audit_bias()                   -> BIAS_AUDITED
    - Stage 4: rescore_flagged()              -> FLAGGED_RESCORING_COMPLETE
    - Stage 5: generate_summaries()           -> SUMMARIES_GENERATED
    - Stage 6: generate_interview_questions() -> INTERVIEW_QUESTIONS_GENERATED
    - Stage 7: generate_cohort_analysis()     -> COHORT_ANALYSIS_GENERATED
    - Stage 8: generate_counter_intuitive_pick() -> COUNTER_INTUITIVE_PICK
    - Stage 9: generate_blind_reranking()     -> BLIND_RERANKING_SCORED + BLIND_RERANKING_ANALYSIS

Every function logs its call via LLMCallLogger before returning.
All LLM calls use claude-haiku-4-5 via the Anthropic SDK.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from pipeline.logger import LLMCallLogger
from pipeline.state import PipelineStage, STAGE_LABELS

# ---------------------------------------------------------------------------
# Environment + client setup
# ---------------------------------------------------------------------------

load_dotenv()

ANTHROPIC_MODEL    = "claude-haiku-4-5"
ANTHROPIC_PROVIDER = "anthropic"


def _get_client() -> anthropic.Anthropic:
    """Initialise and return the Anthropic client."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set in environment.")
    return anthropic.Anthropic(api_key=api_key)


def _call_claude(client: anthropic.Anthropic, prompt: str, max_tokens: int = 4096) -> str:
    """
    Make a single-turn call to Claude and return the text response.
    Centralises error handling for all LLM calls in this module.
    """
    try:
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"Anthropic API connection failed: {e}") from e
    except anthropic.RateLimitError as e:
        raise RuntimeError(f"Anthropic rate limit exceeded: {e}") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error {e.status_code}: {e.message}") from e


def _extract_json(text: str) -> any:
    """
    Extract and parse JSON from an LLM response.
    Handles responses where JSON is wrapped in markdown code fences.
    """
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = cleaned.find(start_char)
            end   = cleaned.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start:end + 1])
                except json.JSONDecodeError:
                    continue
        raise ValueError(
            f"Could not extract valid JSON from LLM response: {cleaned[:200]}..."
        )


# ---------------------------------------------------------------------------
# Stage 1 — Rubric Generation
# ---------------------------------------------------------------------------

def generate_rubric(
    job_description: dict,
    logger: LLMCallLogger,
    artifacts_dir: str = "artifacts",
) -> dict:
    """
    Stage 1 LLM call: Generate a 6-criterion scoring rubric from the job description.

    Returns
    -------
    dict with key "criteria" containing a list of 6 criterion objects.
    """
    client = _get_client()

    requirements_text  = "\n".join(f"- {r}" for r in job_description.get("requirements", []))
    nice_to_have_text  = "\n".join(f"- {r}" for r in job_description.get("nice_to_have", []))
    not_required_text  = "\n".join(f"- {r}" for r in job_description.get("explicitly_not_required", []))

    prompt = f"""You are a senior technical recruiter designing a structured evaluation rubric.

Role: {job_description.get('role', 'Software Engineer')}
Company: {job_description.get('company', '')}

REQUIRED qualifications:
{requirements_text}

NICE TO HAVE:
{nice_to_have_text}

EXPLICITLY NOT REQUIRED (do not score on these):
{not_required_text}

Design a scoring rubric with EXACTLY 6 criteria for evaluating candidates for this specific role.

Rules:
1. Each criterion must map directly to the role requirements above — not generic engineering qualities.
2. Weights must sum to exactly 1.0.
3. Do not include criteria based on anything in the "explicitly not required" list.
4. Criteria must be objective and measurable from a resume summary.

Return ONLY a JSON object in this exact format with no other text:
{{
  "role": "{job_description.get('role', '')}",
  "criteria": [
    {{
      "id": "C1",
      "name": "criterion name",
      "weight": 0.20,
      "description": "one sentence describing what this criterion measures",
      "score_10_means": "one sentence describing what a score of 10 looks like"
    }}
  ]
}}

The 6 criteria must cover the most critical requirements for this specific role.
Weights must sum to exactly 1.0."""

    raw_response = _call_claude(client, prompt, max_tokens=2000)

    try:
        rubric = _extract_json(raw_response)
    except ValueError as e:
        raise RuntimeError(f"Stage 1 rubric generation returned invalid JSON: {e}") from e

    criteria = rubric.get("criteria", [])
    if len(criteria) != 6:
        raise ValueError(
            f"Stage 1 rubric must contain exactly 6 criteria, got {len(criteria)}."
        )

    total_weight = sum(c.get("weight", 0) for c in criteria)
    if not (0.98 <= total_weight <= 1.02):
        raise ValueError(
            f"Rubric weights must sum to 1.0, got {total_weight:.3f}."
        )

    os.makedirs(artifacts_dir, exist_ok=True)
    draft_path = Path(artifacts_dir) / "scoring_rubric_draft.json"
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(rubric, f, indent=2)

    logger.log(
        stage=STAGE_LABELS[PipelineStage.RUBRIC_GENERATED],
        model=ANTHROPIC_MODEL,
        provider=ANTHROPIC_PROVIDER,
        prompt=prompt,
        input_artifacts=["job_description.json"],
        output_artifact=str(draft_path),
        candidate_names_included=False,
    )

    return rubric


# ---------------------------------------------------------------------------
# Stage 2 — Candidate Scoring
# ---------------------------------------------------------------------------

def score_candidates(
    candidates: list[dict],
    rubric: dict,
    logger: LLMCallLogger,
    artifacts_dir: str = "artifacts",
) -> dict:
    """
    Stage 2 LLM call: Score all candidates against the approved rubric.

    Returns
    -------
    Full candidate_scores dict ready to be saved to candidate_scores.json.
    """
    client = _get_client()

    criteria_text = "\n".join(
        f"- [{c['id']}] {c['name']} (weight: {c['weight']}): {c['description']} "
        f"Score of 10 means: {c['score_10_means']}"
        for c in rubric["criteria"]
    )

    candidates_text = "\n\n".join(
        f"Candidate ID: {c['id']}\nName: {c['name']}\nSummary: {c['summary']}"
        for c in candidates
    )

    criteria_ids = [c["id"] for c in rubric["criteria"]]

    prompt = f"""You are evaluating candidates for the role: {rubric.get('role', 'Software Engineer')}

SCORING RUBRIC:
{criteria_text}

CANDIDATES:
{candidates_text}

Score every candidate against every criterion.

Rules:
1. Use only information present in the candidate summary.
2. Score each criterion 0-10 based solely on the criterion description.
3. Do not infer skills not mentioned. Do not penalise for things in "explicitly not required".
4. Be consistent — the same evidence should produce the same score across candidates.
5. Provide a one-sentence rationale for each criterion score.

Return ONLY a JSON object in this exact format with no other text:
{{
  "scored_candidates": [
    {{
      "candidate_id": "C1",
      "candidate_name": "Full Name",
      "criterion_scores": [
        {{
          "criterion_id": "C1",
          "criterion_name": "name",
          "score": 8,
          "rationale": "one sentence rationale"
        }}
      ],
      "total_weighted_score": 7.45
    }}
  ]
}}

Score ALL {len(candidates)} candidates. Include all {len(criteria_ids)} criteria for each candidate.
Calculate total_weighted_score as the sum of (score * weight) for each criterion."""

    raw_response = _call_claude(client, prompt, max_tokens=4096)

    try:
        scores_data = _extract_json(raw_response)
    except ValueError as e:
        raise RuntimeError(f"Stage 2 candidate scoring returned invalid JSON: {e}") from e

    scored = scores_data.get("scored_candidates", [])
    if len(scored) != len(candidates):
        raise ValueError(
            f"Expected scores for {len(candidates)} candidates, got {len(scored)}."
        )

    output = {
        "rubric_reference":  str(Path(artifacts_dir) / "scoring_rubric.json"),
        "scoring_stage":     "CANDIDATES_SCORED",
        "original_scores":   scored,
        "corrected_scores":  None,
        "bias_audit_status": "PENDING",
        "flagged_criteria":  [],
        "final_ranking":     [],
        "rescoring_occurred": False,
    }

    os.makedirs(artifacts_dir, exist_ok=True)
    scores_path = Path(artifacts_dir) / "candidate_scores.json"
    with open(scores_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    logger.log(
        stage=STAGE_LABELS[PipelineStage.CANDIDATES_SCORED],
        model=ANTHROPIC_MODEL,
        provider=ANTHROPIC_PROVIDER,
        prompt=prompt,
        input_artifacts=[
            "candidates.json",
            str(Path(artifacts_dir) / "scoring_rubric.json"),
        ],
        output_artifact=str(scores_path),
        candidate_names_included=True,
    )

    return output


# ---------------------------------------------------------------------------
# Stage 3 — Bias Audit
# ---------------------------------------------------------------------------

def audit_bias(
    candidates: list[dict],
    rubric: dict,
    scores_data: dict,
    logger: LLMCallLogger,
    artifacts_dir: str = "artifacts",
) -> dict:
    """
    Stage 3 LLM call: Audit Stage 2 scores for potential bias.

    Returns
    -------
    Bias audit dict saved to bias_audit.json.
    """
    client = _get_client()

    criteria_text = "\n".join(
        f"- [{c['id']}] {c['name']} (weight: {c['weight']})"
        for c in rubric["criteria"]
    )

    candidate_score_lines = []
    for scored in scores_data.get("original_scores", []):
        cand_id   = scored["candidate_id"]
        cand_name = scored["candidate_name"]
        summary   = next(
            (c["summary"] for c in candidates if c["id"] == cand_id),
            "No summary available",
        )
        scores_line = ", ".join(
            f"{cs['criterion_name']}: {cs['score']}"
            for cs in scored["criterion_scores"]
        )
        total = scored.get("total_weighted_score", 0)
        candidate_score_lines.append(
            f"ID: {cand_id} | Name: {cand_name}\n"
            f"Summary: {summary}\n"
            f"Scores: {scores_line}\n"
            f"Total: {total}"
        )

    candidates_scores_text = "\n\n".join(candidate_score_lines)

    prompt = f"""You are an independent bias auditor reviewing AI-generated candidate scores.

ROLE BEING HIRED FOR: {rubric.get('role', '')}

SCORING RUBRIC CRITERIA:
{criteria_text}

CANDIDATE SCORES (including names and backgrounds):
{candidates_scores_text}

Conduct a thorough bias audit. Look specifically for:
1. Name-based or nationality-based scoring patterns
2. Credential bias — degree institution prestige, employer brand (FAANG, Goldman Sachs, etc.)
3. Experience context bias — startup vs corporate background, geographic bias
4. Gender-correlated scoring patterns
5. Any criterion where scores correlate with demographic signals rather than job requirements

For each issue found, classify severity:
- "flagged": clear evidence of bias that requires re-scoring
- "watch": possible bias pattern worth noting but not conclusive
- "clear": area examined, no bias found

Return ONLY a JSON object in this exact format with no other text:
{{
  "audit_summary": "2-3 sentence overall assessment",
  "findings": [
    {{
      "bias_type": "string describing the type of bias",
      "affected_candidates": ["C1", "C2"],
      "affected_criteria": ["criterion_id"],
      "evidence": "specific evidence from the scores that supports this finding",
      "severity": "flagged | watch | clear"
    }}
  ],
  "flagged_criteria_ids": ["list of criterion IDs that must be re-scored"],
  "requires_rescoring": true
}}

Be thorough. If you find no bias, still return the structure with empty findings and requires_rescoring: false."""

    raw_response = _call_claude(client, prompt, max_tokens=3000)

    try:
        audit_data = _extract_json(raw_response)
    except ValueError as e:
        raise RuntimeError(f"Stage 3 bias audit returned invalid JSON: {e}") from e

    findings = audit_data.get("findings", [])
    for i, finding in enumerate(findings):
        required_keys = {"bias_type", "affected_candidates", "evidence", "severity"}
        missing = required_keys - set(finding.keys())
        if missing:
            raise ValueError(f"Bias audit finding {i} missing required keys: {missing}")
        severity = finding.get("severity", "")
        if severity not in {"flagged", "watch", "clear"}:
            raise ValueError(
                f"Bias audit finding {i} has invalid severity '{severity}'."
            )

    os.makedirs(artifacts_dir, exist_ok=True)
    audit_path = Path(artifacts_dir) / "bias_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=2)

    logger.log(
        stage=STAGE_LABELS[PipelineStage.BIAS_AUDITED],
        model=ANTHROPIC_MODEL,
        provider=ANTHROPIC_PROVIDER,
        prompt=prompt,
        input_artifacts=[
            "candidates.json",
            str(Path(artifacts_dir) / "scoring_rubric.json"),
            str(Path(artifacts_dir) / "candidate_scores.json"),
        ],
        output_artifact=str(audit_path),
        candidate_names_included=True,
    )

    return audit_data


# ---------------------------------------------------------------------------
# Stage 4 — De-Biased Re-Scoring
# ---------------------------------------------------------------------------

def rescore_flagged(
    candidates: list[dict],
    rubric: dict,
    scores_data: dict,
    flagged_criteria_ids: list[str],
    logger: LLMCallLogger,
    artifacts_dir: str = "artifacts",
) -> list[dict]:
    """
    Stage 4 LLM call: Re-score only flagged criteria using anonymised candidate data.

    Candidate names and demographic signals are stripped in Python BEFORE
    the prompt is constructed.

    Returns
    -------
    List of corrected scored_candidates.
    """
    from pipeline.bias import anonymise_candidates

    client = _get_client()

    anonymised     = anonymise_candidates(candidates)
    candidates_text = "\n\n".join(
        f"Candidate ID: {a['id']}\nSummary: {a['summary']}"
        for a in anonymised
    )

    flagged_criteria = [
        c for c in rubric["criteria"] if c["id"] in flagged_criteria_ids
    ]
    criteria_text = "\n".join(
        f"- [{c['id']}] {c['name']} (weight: {c['weight']}): {c['description']} "
        f"Score of 10 means: {c['score_10_means']}"
        for c in flagged_criteria
    )

    prompt = f"""You are re-scoring candidates on specific criteria where bias was detected.

IMPORTANT: Candidate names and demographic information have been removed.
Score ONLY based on the technical skills and experience described.

ROLE: {rubric.get('role', 'Software Engineer')}

CRITERIA TO RE-SCORE (these specific criteria only):
{criteria_text}

ANONYMISED CANDIDATES:
{candidates_text}

Score each candidate on ONLY the listed criteria.
Use only evidence from the summary. Do not infer. Do not penalise for missing information.

Return ONLY a JSON object in this exact format with no other text:
{{
  "rescored_candidates": [
    {{
      "candidate_id": "C1",
      "rescored_criteria": [
        {{
          "criterion_id": "C1",
          "criterion_name": "name",
          "score": 8,
          "rationale": "one sentence rationale based only on skills described"
        }}
      ]
    }}
  ]
}}

Include ALL {len(candidates)} candidates. Include ALL {len(flagged_criteria)} flagged criteria for each."""

    raw_response = _call_claude(client, prompt, max_tokens=3000)

    try:
        rescore_data = _extract_json(raw_response)
    except ValueError as e:
        raise RuntimeError(f"Stage 4 re-scoring returned invalid JSON: {e}") from e

    rescored = rescore_data.get("rescored_candidates", [])
    if len(rescored) != len(candidates):
        raise ValueError(
            f"Re-scoring expected {len(candidates)} candidates, got {len(rescored)}."
        )

    original_scores  = scores_data.get("original_scores", [])
    corrected_scores = []

    for original in original_scores:
        cand_id = original["candidate_id"]

        rescore_entry = next(
            (r for r in rescored if r["candidate_id"] == cand_id), None
        )

        updated_criteria = [dict(cs) for cs in original["criterion_scores"]]

        if rescore_entry:
            rescored_map = {
                rc["criterion_id"]: rc
                for rc in rescore_entry.get("rescored_criteria", [])
            }
            for cs in updated_criteria:
                if cs["criterion_id"] in rescored_map:
                    new_score = rescored_map[cs["criterion_id"]]
                    cs["score"]    = new_score["score"]
                    cs["rationale"] = new_score["rationale"]
                    cs["rescored"] = True

        weight_map = {c["id"]: c["weight"] for c in rubric["criteria"]}
        new_total  = sum(
            cs["score"] * weight_map.get(cs["criterion_id"], 0)
            for cs in updated_criteria
        )

        # Track whether any criterion actually changed for this candidate
        original_criteria_map = {
            cs["criterion_id"]: cs["score"]
            for cs in original["criterion_scores"]
        }
        any_changed = any(
            cs.get("rescored") and
            cs["score"] != original_criteria_map.get(cs["criterion_id"])
            for cs in updated_criteria
        )

        corrected_scores.append({
            "candidate_id":         cand_id,
            "candidate_name":       original["candidate_name"],
            "criterion_scores":     updated_criteria,
            # Preserve exact original total if nothing actually changed
            # prevents float drift on non-affected candidates
            "total_weighted_score": round(new_total, 4) if any_changed
                                    else original["total_weighted_score"],
        })

    scores_path = Path(artifacts_dir) / "candidate_scores.json"
    audit_path  = Path(artifacts_dir) / "bias_audit.json"

    logger.log(
        stage=STAGE_LABELS[PipelineStage.FLAGGED_RESCORING_COMPLETE],
        model=ANTHROPIC_MODEL,
        provider=ANTHROPIC_PROVIDER,
        prompt=prompt,
        input_artifacts=[str(scores_path), str(audit_path)],
        output_artifact=str(scores_path),
        candidate_names_included=False,  # CRITICAL — anonymised call
    )

    return corrected_scores


# ---------------------------------------------------------------------------
# Stage 5 — Hiring Committee Summaries
# ---------------------------------------------------------------------------

def generate_summaries(
    top_candidates: list[dict],
    all_candidates: list[dict],
    rubric: dict,
    job_description: dict,
    final_ranking: list[dict],
    logger: LLMCallLogger,
    artifacts_dir: str = "artifacts",
) -> str:
    """
    Stage 5 LLM call: Generate hiring committee summaries for top 3 candidates.

    Returns
    -------
    Markdown string saved to hiring_summaries.md.
    """
    client = _get_client()

    top3_context = []
    for rank_entry in final_ranking[:3]:
        cand_id   = rank_entry["candidate_id"]
        candidate = next((c for c in all_candidates if c["id"] == cand_id), {})
        scores    = next(
            (s for s in top_candidates if s["candidate_id"] == cand_id), {}
        )
        top3_context.append({
            "rank":            rank_entry["rank"],
            "id":              cand_id,
            "name":            candidate.get("name", "Unknown"),
            "summary":         candidate.get("summary", ""),
            "total_score":     rank_entry["total_weighted_score"],
            "criterion_scores": scores.get("criterion_scores", []),
        })

    candidates_context_text = "\n\n".join(
        f"RANK #{c['rank']} — {c['name']} (ID: {c['id']}, Score: {c['total_score']:.2f})\n"
        f"Resume Summary: {c['summary']}\n"
        f"Criterion Scores: " + ", ".join(
            f"{cs['criterion_name']}: {cs['score']}/10"
            for cs in c["criterion_scores"]
        )
        for c in top3_context
    )

    requirements_text = "\n".join(
        f"- {r}" for r in job_description.get("requirements", [])
    )

    all_scores_text = "\n".join(
        f"Rank {r['rank']}: {r['candidate_id']} — Score {r['total_weighted_score']:.2f}"
        for r in final_ranking
    )

    prompt = f"""You are preparing hiring committee briefing documents for the role:
{job_description.get('role', 'Software Engineer')} at {job_description.get('company', '')}

JOB REQUIREMENTS:
{requirements_text}

TOP 3 CANDIDATES:
{candidates_context_text}

FULL RANKING (all candidates):
{all_scores_text}

Produce the following in clean Markdown:

1. For each of the top 3 candidates, a structured summary with these exact sections:
   - ## Rank [N] — [Name]
   - **Overall Score**: X.XX / 10
   - **Hire Confidence**: [Strong Yes | Yes | Maybe | No]
   - **Confidence Justification**: one sentence
   - **Strengths**: bullet points mapped to specific job requirements
   - **Gaps**: bullet points with criticality assessment (Critical / Moderate / Minor)
   - **Recommended Interview Focus**: exactly 3 specific technical areas to probe

Return the complete Markdown document. Do not include JSON. Use clean Markdown formatting."""

    raw_response = _call_claude(client, prompt, max_tokens=4096)

    os.makedirs(artifacts_dir, exist_ok=True)
    summaries_path = Path(artifacts_dir) / "hiring_summaries.md"
    with open(summaries_path, "w", encoding="utf-8") as f:
        f.write(raw_response)

    logger.log(
        stage=STAGE_LABELS[PipelineStage.SUMMARIES_GENERATED],
        model=ANTHROPIC_MODEL,
        provider=ANTHROPIC_PROVIDER,
        prompt=prompt,
        input_artifacts=[
            str(Path(artifacts_dir) / "candidate_scores.json"),
            str(Path(artifacts_dir) / "bias_audit.json"),
            "job_description.json",
        ],
        output_artifact=str(summaries_path),
        candidate_names_included=True,
    )

    return raw_response


# ---------------------------------------------------------------------------
# Stage 6 — Structured Interview Questions
# ---------------------------------------------------------------------------

def generate_interview_questions(
    top_candidate: dict,
    candidate_full: dict,
    rubric: dict,
    job_description: dict,
    logger: LLMCallLogger,
    artifacts_dir: str = "artifacts",
) -> str:
    """
    Stage 6 LLM call: Generate 5 structured interview questions for the
    #1 ranked candidate.

    Questions are behavioural and technical, specific to this candidate.
    Output is appended to hiring_summaries.md.
    """
    client = _get_client()

    cand_id   = top_candidate["candidate_id"]
    cand_name = top_candidate.get("candidate_name", cand_id)
    summary   = candidate_full.get("summary", "")
    score     = top_candidate.get("total_weighted_score", 0)

    criterion_context = "\n".join(
        f"  - {cs['criterion_name']}: {cs['score']}/10 — {cs['rationale']}"
        for cs in top_candidate.get("criterion_scores", [])
    )

    requirements_text = "\n".join(
        f"- {r}" for r in job_description.get("requirements", [])
    )

    prompt = f"""You are preparing a structured technical interview for the top-ranked candidate.

ROLE: {job_description.get('role', '')} at {job_description.get('company', '')}

CANDIDATE: {cand_name} (Score: {score:.2f}/10)
RESUME SUMMARY: {summary}

CRITERION SCORES:
{criterion_context}

JOB REQUIREMENTS:
{requirements_text}

Generate exactly 5 interview questions for this specific candidate.

Rules:
1. Mix of behavioural (2) and technical (3) questions.
2. Each question must validate a claimed strength OR probe an identified gap — state which.
3. Questions must be specific to THIS candidate's background — not generic.
4. Do NOT ask generic questions like "Explain WebSockets", "What is Kafka", "Describe PostgreSQL".
5. Each question should require a detailed, evidence-based answer — not a yes/no.

Return clean Markdown in this exact format:

## Structured Interview Questions — {cand_name}

**Question 1 [Behavioural — validates: <strength/gap name>]**
<specific question text>

**Question 2 [Technical — probes: <strength/gap name>]**
<specific question text>

**Question 3 [Technical — probes: <strength/gap name>]**
<specific question text>

**Question 4 [Behavioural — validates: <strength/gap name>]**
<specific question text>

**Question 5 [Technical — probes: <strength/gap name>]**
<specific question text>

Return only the Markdown. No preamble."""

    raw_response = _call_claude(client, prompt, max_tokens=2000)

    os.makedirs(artifacts_dir, exist_ok=True)
    summaries_path = Path(artifacts_dir) / "hiring_summaries.md"
    with open(summaries_path, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n")
        f.write(raw_response)

    logger.log(
        stage="INTERVIEW_QUESTIONS_GENERATED",
        model=ANTHROPIC_MODEL,
        provider=ANTHROPIC_PROVIDER,
        prompt=prompt,
        input_artifacts=[
            str(Path(artifacts_dir) / "candidate_scores.json"),
            "job_description.json",
        ],
        output_artifact=str(summaries_path),
        candidate_names_included=True,
    )

    return raw_response


# ---------------------------------------------------------------------------
# Stage 7 — Cohort Analysis
# ---------------------------------------------------------------------------

def generate_cohort_analysis(
    candidates: list[dict],
    rubric: dict,
    job_description: dict,
    final_ranking: list[dict],
    scores_data: dict,
    logger: LLMCallLogger,
    artifacts_dir: str = "artifacts",
) -> str:
    """
    Stage 7 LLM call: Generate a cohort analysis paragraph.

    Covers overall talent level, common skill gaps, and hiring recommendation.
    Output is appended to hiring_summaries.md.
    """
    client = _get_client()

    score_list = scores_data.get("corrected_scores") or scores_data.get("original_scores", [])
    score_map  = {s["candidate_id"]: s for s in score_list}

    candidate_lines = []
    for rank_entry in final_ranking:
        cid      = rank_entry["candidate_id"]
        name     = rank_entry.get("candidate_name", cid)
        total    = rank_entry["total_weighted_score"]
        summary  = next((c["summary"] for c in candidates if c["id"] == cid), "")
        scores   = score_map.get(cid, {})
        criteria = "\n    ".join(
            f"{cs['criterion_name']}: {cs['score']}/10"
            for cs in scores.get("criterion_scores", [])
        )
        candidate_lines.append(
            f"Rank #{rank_entry['rank']} — {name} (Total: {total:.2f}/10)\n"
            f"  Summary: {summary}\n"
            f"  Criteria:\n    {criteria}"
        )

    all_candidates_text = "\n\n".join(candidate_lines)
    requirements_text   = "\n".join(
        f"- {r}" for r in job_description.get("requirements", [])
    )

    prompt = f"""You are writing a cohort analysis for the hiring committee.

ROLE: {job_description.get('role', '')} at {job_description.get('company', '')}

JOB REQUIREMENTS:
{requirements_text}

ALL CANDIDATES (ranked):
{all_candidates_text}

Write a cohort analysis as a single focused paragraph covering exactly:
1. Overall talent level of this candidate pool
2. The most common skill gaps that appear across multiple candidates
3. A clear recommendation: proceed with the current pool or expand the search — with specific reasoning

Be concrete and evidence-based. Reference actual candidate scores and patterns.
Name specific gaps. Give a direct recommendation with justification.

Return clean Markdown:

## Cohort Analysis

<one focused paragraph>

Return only the Markdown. No preamble."""

    raw_response = _call_claude(client, prompt, max_tokens=1000)

    os.makedirs(artifacts_dir, exist_ok=True)
    summaries_path = Path(artifacts_dir) / "hiring_summaries.md"
    with open(summaries_path, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n")
        f.write(raw_response)

    logger.log(
        stage="COHORT_ANALYSIS_GENERATED",
        model=ANTHROPIC_MODEL,
        provider=ANTHROPIC_PROVIDER,
        prompt=prompt,
        input_artifacts=[
            str(Path(artifacts_dir) / "candidate_scores.json"),
            "candidates.json",
            "job_description.json",
        ],
        output_artifact=str(summaries_path),
        candidate_names_included=True,
    )

    return raw_response


# ---------------------------------------------------------------------------
# Stretch 8 — Counter-Intuitive Pick
# ---------------------------------------------------------------------------

def generate_counter_intuitive_pick(
    candidates: list[dict],
    rubric: dict,
    job_description: dict,
    final_ranking: list[dict],
    scores_data: dict,
    logger: LLMCallLogger,
    artifacts_dir: str = "artifacts",
) -> str:
    """
    Stretch 8: Argue the case for the lowest-ranked candidate.

    Explains what specific scenario, company need, or team context would
    make the lowest-ranked candidate the best choice.

    This is a devil's advocate exercise — it must NOT reverse the ranking.
    Output is appended to hiring_summaries.md.
    """
    client = _get_client()

    lowest_rank  = final_ranking[-1]
    lowest_id    = lowest_rank["candidate_id"]
    lowest_name  = lowest_rank.get("candidate_name", lowest_id)
    lowest_score = lowest_rank["total_weighted_score"]
    lowest_full  = next((c for c in candidates if c["id"] == lowest_id), {})

    ranking_text = "\n".join(
        f"  #{r['rank']} {r['candidate_id']} — {r.get('candidate_name', '')}: "
        f"{r['total_weighted_score']:.2f}/10"
        for r in final_ranking
    )

    prompt = f"""You are playing devil's advocate for a hiring committee.

ROLE: {job_description.get('role', '')} at {job_description.get('company', '')}

FINAL RANKING (do not change this):
{ranking_text}

LOWEST-RANKED CANDIDATE: {lowest_name} (Rank #{lowest_rank['rank']}, Score: {lowest_score:.2f}/10)
THEIR BACKGROUND: {lowest_full.get('summary', '')}

Your task: Construct the strongest possible argument for WHY this lowest-ranked candidate
could be the BEST choice — but only under specific circumstances.

Requirements:
1. Identify a concrete scenario, company need, or team gap that would make this candidate ideal
2. Reference specific skills or traits from their background that become valuable in that scenario
3. Be specific — not "they bring diversity of thought" but an actual technical or strategic reason
4. Explicitly state this does NOT change the final ranking — it is a devil's advocate exercise
5. Keep it to 2-3 focused paragraphs

Return clean Markdown:

## Counter-Intuitive Pick — Devil's Advocate Case for {lowest_name}

> *Note: This is a structured devil's advocate exercise. The final ranking above stands.*

<2-3 paragraph argument>

Return only the Markdown. No preamble."""

    raw_response = _call_claude(client, prompt, max_tokens=1000)

    os.makedirs(artifacts_dir, exist_ok=True)
    summaries_path = Path(artifacts_dir) / "hiring_summaries.md"
    with open(summaries_path, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n")
        f.write(raw_response)

    logger.log(
        stage="COUNTER_INTUITIVE_PICK",
        model=ANTHROPIC_MODEL,
        provider=ANTHROPIC_PROVIDER,
        prompt=prompt,
        input_artifacts=[
            str(Path(artifacts_dir) / "candidate_scores.json"),
            "candidates.json",
        ],
        output_artifact=str(summaries_path),
        candidate_names_included=True,
    )

    return raw_response


# ---------------------------------------------------------------------------
# Stretch 9 — Blind Re-Ranking
# ---------------------------------------------------------------------------

def generate_blind_reranking(
    candidates: list[dict],
    rubric: dict,
    job_description: dict,
    original_ranking: list[dict],
    logger: LLMCallLogger,
    artifacts_dir: str = "artifacts",
) -> str:
    """
    Stretch 9: Strip all names and demographic signals, re-run Stage 2
    scoring on anonymised data, compare blind ranking to original.

    Both LLM calls use candidate_names_included=False.
    Output is appended to hiring_summaries.md.
    """
    from pipeline.bias import anonymise_candidates

    client = _get_client()

    # Strip names and demographic signals in Python before prompt
    anonymised      = anonymise_candidates(candidates)
    candidates_text = "\n\n".join(
        f"Candidate ID: {a['id']}\nSummary: {a['summary']}"
        for a in anonymised
    )

    criteria_text = "\n".join(
        f"- [{c['id']}] {c['name']} (weight: {c['weight']}): {c['description']} "
        f"Score of 10 means: {c['score_10_means']}"
        for c in rubric["criteria"]
    )

    scoring_prompt = f"""You are scoring candidates for: {job_description.get('role', '')}

All candidate names and demographic signals have been removed.
Score ONLY on technical skills and experience described.

RUBRIC:
{criteria_text}

ANONYMISED CANDIDATES:
{candidates_text}

Score every candidate on every criterion. Use only evidence in the summary.

Return ONLY a JSON object:
{{
  "scored_candidates": [
    {{
      "candidate_id": "C1",
      "criterion_scores": [
        {{
          "criterion_id": "C1",
          "score": 8,
          "rationale": "one sentence"
        }}
      ],
      "total_weighted_score": 7.45
    }}
  ]
}}

Include ALL {len(candidates)} candidates and ALL {len(rubric['criteria'])} criteria."""

    raw_response = _call_claude(client, scoring_prompt, max_tokens=4096)

    try:
        blind_scores = _extract_json(raw_response)
    except ValueError as e:
        raise RuntimeError(f"Blind re-ranking scoring returned invalid JSON: {e}") from e

    scored = blind_scores.get("scored_candidates", [])
    blind_ranking = sorted(
        scored,
        key=lambda c: c.get("total_weighted_score", 0),
        reverse=True,
    )

    scores_path = Path(artifacts_dir) / "candidate_scores.json"

    # Log scoring call — anonymised
    logger.log(
        stage="BLIND_RERANKING_SCORED",
        model=ANTHROPIC_MODEL,
        provider=ANTHROPIC_PROVIDER,
        prompt=scoring_prompt,
        input_artifacts=[
            "candidates.json",
            str(Path(artifacts_dir) / "scoring_rubric.json"),
        ],
        output_artifact=str(scores_path),
        candidate_names_included=False,
    )

    # Build position change data
    original_order = [r["candidate_id"] for r in original_ranking]
    blind_order    = [r["candidate_id"] for r in blind_ranking]

    position_changes = []
    for cid in original_order:
        orig_pos  = original_order.index(cid) + 1
        blind_pos = blind_order.index(cid) + 1 if cid in blind_order else None
        if blind_pos and orig_pos != blind_pos:
            direction = "▲ up" if blind_pos < orig_pos else "▼ down"
            position_changes.append(
                f"- **{cid}**: #{orig_pos} → #{blind_pos} "
                f"({direction} {abs(orig_pos - blind_pos)} "
                f"position{'s' if abs(orig_pos - blind_pos) > 1 else ''})"
            )

    changes_text = (
        "\n".join(position_changes)
        if position_changes
        else "- No position changes detected."
    )

    original_ranking_text = "\n".join(
        f"  #{r['rank']} {r['candidate_id']} — "
        f"{r.get('candidate_name', '')}: {r['total_weighted_score']:.2f}/10"
        for r in original_ranking
    )

    blind_ranking_text = "\n".join(
        f"  #{i+1} {r['candidate_id']}: {r.get('total_weighted_score', 0):.2f}/10"
        for i, r in enumerate(blind_ranking)
    )

    analysis_prompt = f"""You are analysing the difference between a named and blind candidate ranking.

ORIGINAL RANKING (with names and full context):
{original_ranking_text}

BLIND RANKING (anonymised — names and demographics stripped):
{blind_ranking_text}

POSITION CHANGES:
{changes_text}

Write a Markdown analysis covering:
1. Which candidates moved and by how much
2. For each position change — is it likely due to:
   (a) bias in original scoring
   (b) legitimate context that anonymisation removed
   (c) scoring inconsistency
3. Overall conclusion: does the blind ranking suggest the original scoring was fair,
   partially biased, or significantly biased?

Be specific. Reference candidate IDs and score differences.

Return clean Markdown:

## Blind Re-Ranking Analysis

### Ranking Comparison

| Candidate | Original Rank | Blind Rank | Change |
|-----------|--------------|------------|--------|
<fill in table rows>

### Position Change Analysis

<specific analysis per changed candidate>

### Conclusion

<overall fairness assessment — 2-3 sentences>

Return only the Markdown. No preamble."""

    analysis_response = _call_claude(client, analysis_prompt, max_tokens=1500)

    # Log analysis call — still anonymised
    logger.log(
        stage="BLIND_RERANKING_ANALYSIS",
        model=ANTHROPIC_MODEL,
        provider=ANTHROPIC_PROVIDER,
        prompt=analysis_prompt,
        input_artifacts=[str(scores_path)],
        output_artifact=str(Path(artifacts_dir) / "hiring_summaries.md"),
        candidate_names_included=False,
    )

    os.makedirs(artifacts_dir, exist_ok=True)
    summaries_path = Path(artifacts_dir) / "hiring_summaries.md"
    with open(summaries_path, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n")
        f.write(analysis_response)

    return analysis_response