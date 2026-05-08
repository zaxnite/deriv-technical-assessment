# pipeline/llm.py
"""
All LLM call functions for the recruitment screening pipeline.

Each function represents exactly one stage's LLM interaction:
    - Stage 1: generate_rubric()       -> RUBRIC_GENERATED
    - Stage 2: score_candidates()      -> CANDIDATES_SCORED
    - Stage 3: audit_bias()            -> BIAS_AUDITED
    - Stage 4: rescore_flagged()       -> FLAGGED_RESCORING_COMPLETE
    - Stage 5: generate_summaries()    -> SUMMARIES_GENERATED

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

ANTHROPIC_MODEL = "claude-haiku-4-5"
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
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find the first { or [ and parse from there
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = cleaned.find(start_char)
            end = cleaned.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start:end + 1])
                except json.JSONDecodeError:
                    continue
        raise ValueError(f"Could not extract valid JSON from LLM response: {cleaned[:200]}...")


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

    The rubric is grounded in the specific requirements of the role.
    It is saved as a DRAFT — the approved version is written by stages.py
    after the interactive checkpoint.

    Returns
    -------
    dict with key "criteria" containing a list of 6 criterion objects.
    """
    client = _get_client()

    requirements_text = "\n".join(f"- {r}" for r in job_description.get("requirements", []))
    nice_to_have_text = "\n".join(f"- {r}" for r in job_description.get("nice_to_have", []))
    not_required_text = "\n".join(f"- {r}" for r in job_description.get("explicitly_not_required", []))

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

    # Validate structure
    criteria = rubric.get("criteria", [])
    if len(criteria) != 6:
        raise ValueError(
            f"Stage 1 rubric must contain exactly 6 criteria, got {len(criteria)}."
        )

    # Validate weights sum to ~1.0
    total_weight = sum(c.get("weight", 0) for c in criteria)
    if not (0.98 <= total_weight <= 1.02):
        raise ValueError(
            f"Rubric weights must sum to 1.0, got {total_weight:.3f}. "
            "Regenerate the rubric."
        )

    # Save draft rubric
    os.makedirs(artifacts_dir, exist_ok=True)
    draft_path = Path(artifacts_dir) / "scoring_rubric_draft.json"
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(rubric, f, indent=2)

    # Log the call
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

    Each candidate receives a score per criterion (0-10), a weighted total,
    and a one-sentence rationale per criterion.

    Original scores are stored under the key "original_scores" and must
    never be overwritten.

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

    # Build the full candidate_scores.json structure
    output = {
        "rubric_reference": str(Path(artifacts_dir) / "scoring_rubric.json"),
        "scoring_stage": "CANDIDATES_SCORED",
        "original_scores": scored,           # NEVER overwrite this key
        "corrected_scores": None,            # Populated by rescore_flagged() if needed
        "bias_audit_status": "PENDING",      # Updated by audit_bias()
        "flagged_criteria": [],              # Populated by bias.py if needed
        "final_ranking": [],                 # Populated by stages.py finalise_ranking()
        "rescoring_occurred": False,
    }

    # Save to disk
    os.makedirs(artifacts_dir, exist_ok=True)
    scores_path = Path(artifacts_dir) / "candidate_scores.json"
    with open(scores_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    # Log the call
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
    Stage 3 LLM call: Audit the Stage 2 scores for potential bias.

    The audit prompt includes candidate names, summaries, the approved rubric,
    and the Stage 2 scoring results. The LLM looks for patterns suggesting
    name-based, credential, geography, or prestige bias.

    Each finding uses severity: "flagged" | "watch" | "clear".

    Returns
    -------
    Bias audit dict saved to bias_audit.json.
    """
    client = _get_client()

    # Build rubric summary for the prompt
    criteria_text = "\n".join(
        f"- [{c['id']}] {c['name']} (weight: {c['weight']})"
        for c in rubric["criteria"]
    )

    # Build candidate+score summary for the prompt
    candidate_score_lines = []
    for scored in scores_data.get("original_scores", []):
        cand_id = scored["candidate_id"]
        cand_name = scored["candidate_name"]
        # Find original summary
        summary = next(
            (c["summary"] for c in candidates if c["id"] == cand_id),
            "No summary available"
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
1. Name-based or nationality-based scoring patterns (e.g. names suggesting certain ethnicities scoring differently)
2. Credential bias — degree institution prestige, employer brand (FAANG, Goldman Sachs, etc.) influencing scores beyond actual skill evidence
3. Experience context bias — startup vs corporate background, geographic bias (e.g. Lagos vs London)
4. Gender-correlated scoring patterns
5. Any criterion where scores appear to correlate with demographic signals rather than stated job requirements

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

Be thorough. If you find no bias at all, still return the structure with an empty findings list and requires_rescoring: false."""

    raw_response = _call_claude(client, prompt, max_tokens=3000)

    try:
        audit_data = _extract_json(raw_response)
    except ValueError as e:
        raise RuntimeError(f"Stage 3 bias audit returned invalid JSON: {e}") from e

    # Validate findings structure
    findings = audit_data.get("findings", [])
    for i, finding in enumerate(findings):
        required_keys = {"bias_type", "affected_candidates", "evidence", "severity"}
        missing = required_keys - set(finding.keys())
        if missing:
            raise ValueError(f"Bias audit finding {i} is missing required keys: {missing}")

        severity = finding.get("severity", "")
        if severity not in {"flagged", "watch", "clear"}:
            raise ValueError(
                f"Bias audit finding {i} has invalid severity '{severity}'. "
                "Must be 'flagged', 'watch', or 'clear'."
            )

    # Save to disk
    os.makedirs(artifacts_dir, exist_ok=True)
    audit_path = Path(artifacts_dir) / "bias_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=2)

    # Log the call
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
# Stage 4 — De-Biased Re-Scoring (only if flagged findings exist)
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
    the prompt is constructed — this is enforced here, not inside the LLM.

    Only the flagged criteria are re-scored. All other criterion scores
    remain unchanged from Stage 2.

    Returns
    -------
    List of corrected scored_candidates (same structure as original_scores).
    """
    from pipeline.bias import anonymise_candidates  # local import to avoid circular

    client = _get_client()

    # Strip names and demographic signals in code before building prompt
    anonymised = anonymise_candidates(candidates)

    # Build anonymised candidate text
    candidates_text = "\n\n".join(
        f"Candidate ID: {a['id']}\nSummary: {a['summary']}"
        for a in anonymised
    )

    # Only include flagged criteria in the re-scoring prompt
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

    # Merge corrected scores with original scores
    # Only replace flagged criteria — preserve all other original scores
    original_scores = scores_data.get("original_scores", [])
    corrected_scores = []

    for original in original_scores:
        cand_id = original["candidate_id"]

        # Find this candidate's re-scored criteria
        rescore_entry = next(
            (r for r in rescored if r["candidate_id"] == cand_id), None
        )

        # Deep copy original criterion scores
        updated_criteria = [dict(cs) for cs in original["criterion_scores"]]

        if rescore_entry:
            rescored_map = {
                rc["criterion_id"]: rc
                for rc in rescore_entry.get("rescored_criteria", [])
            }
            # Replace only flagged criteria
            for cs in updated_criteria:
                if cs["criterion_id"] in rescored_map:
                    new_score = rescored_map[cs["criterion_id"]]
                    cs["score"] = new_score["score"]
                    cs["rationale"] = new_score["rationale"]
                    cs["rescored"] = True  # Mark as corrected

        # Recalculate weighted total using corrected scores
        weight_map = {c["id"]: c["weight"] for c in rubric["criteria"]}
        new_total = sum(
            cs["score"] * weight_map.get(cs["criterion_id"], 0)
            for cs in updated_criteria
        )

        corrected_scores.append({
            "candidate_id": cand_id,
            "candidate_name": original["candidate_name"],
            "criterion_scores": updated_criteria,
            "total_weighted_score": round(new_total, 4),
        })

    # Log the call — candidate_names_included MUST be False
    scores_path = Path(artifacts_dir) / "candidate_scores.json"
    audit_path = Path(artifacts_dir) / "bias_audit.json"

    logger.log(
        stage=STAGE_LABELS[PipelineStage.FLAGGED_RESCORING_COMPLETE],
        model=ANTHROPIC_MODEL,
        provider=ANTHROPIC_PROVIDER,
        prompt=prompt,
        input_artifacts=[
            str(scores_path),
            str(audit_path),
        ],
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
    Stage 5 LLM call: Generate hiring committee summaries for top 3 candidates
    plus a cohort analysis paragraph.

    Returns
    -------
    Markdown string saved to hiring_summaries.md.
    """
    client = _get_client()

    # Build context for top 3
    top3_context = []
    for rank_entry in final_ranking[:3]:
        cand_id = rank_entry["candidate_id"]
        candidate = next((c for c in all_candidates if c["id"] == cand_id), {})
        scores = next(
            (s for s in top_candidates if s["candidate_id"] == cand_id), {}
        )
        top3_context.append({
            "rank": rank_entry["rank"],
            "id": cand_id,
            "name": candidate.get("name", "Unknown"),
            "summary": candidate.get("summary", ""),
            "total_score": rank_entry["total_weighted_score"],
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

    requirements_text = "\n".join(f"- {r}" for r in job_description.get("requirements", []))

    # Full cohort for cohort analysis
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
   - ## [Rank] — [Name]
   - **Overall Score**: X.XX / 10
   - **Hire Confidence**: [Strong Yes | Yes | Maybe | No]
   - **Confidence Justification**: one sentence
   - **Strengths**: bullet points mapped to specific job requirements
   - **Gaps**: bullet points with criticality assessment (Critical / Moderate / Minor)
   - **Recommended Interview Focus**: exactly 3 specific technical areas to probe (not generic questions)

2. A ## Cohort Analysis section (one paragraph) covering:
   - Overall talent level of the pool
   - Common skill gaps across candidates
   - Recommendation: proceed with this pool or expand the search

Return the complete Markdown document. Do not include JSON. Use clean Markdown formatting."""

    raw_response = _call_claude(client, prompt, max_tokens=4096)

    # Save to disk
    os.makedirs(artifacts_dir, exist_ok=True)
    summaries_path = Path(artifacts_dir) / "hiring_summaries.md"
    with open(summaries_path, "w", encoding="utf-8") as f:
        f.write(raw_response)

    # Log the call
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
# Stage 6 — Structured Interview Questions (top-ranked candidate)
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

    Questions must be:
    - Both behavioural and technical
    - Specific to this candidate's claimed strengths and identified gaps
    - Not generic (no "Explain WebSockets" style questions)

    Output is appended to hiring_summaries.md.

    Returns
    -------
    Markdown string of the 5 interview questions.
    """
    client = _get_client()

    cand_id   = top_candidate["candidate_id"]
    cand_name = top_candidate.get("candidate_name", cand_id)
    summary   = candidate_full.get("summary", "")
    score     = top_candidate.get("total_weighted_score", 0)

    # Build criterion scores for context
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
4. Do NOT ask generic questions like "Explain WebSockets", "What is Kafka", or "Describe PostgreSQL".
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

    # Append to hiring_summaries.md
    os.makedirs(artifacts_dir, exist_ok=True)
    summaries_path = Path(artifacts_dir) / "hiring_summaries.md"
    with open(summaries_path, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n")
        f.write(raw_response)

    # Log the call
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
# Stage 7 — Cohort Analysis (separate explicit LLM call)
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
    Stage 7 LLM call: Generate a cohort analysis paragraph covering:
    - Overall talent level of the candidate pool
    - Common skill gaps across all candidates
    - Recommendation: proceed with current pool or expand the search

    Output is appended to hiring_summaries.md.

    Returns
    -------
    Markdown string of the cohort analysis.
    """
    client = _get_client()

    # Use corrected scores if available
    score_list = scores_data.get("corrected_scores") or scores_data.get("original_scores", [])
    score_map  = {s["candidate_id"]: s for s in score_list}

    # Build full candidate context with scores
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
    requirements_text   = "\n".join(f"- {r}" for r in job_description.get("requirements", []))

    prompt = f"""You are writing a cohort analysis for the hiring committee.

ROLE: {job_description.get('role', '')} at {job_description.get('company', '')}

JOB REQUIREMENTS:
{requirements_text}

ALL CANDIDATES (ranked):
{all_candidates_text}

Write a cohort analysis as a single focused paragraph covering exactly:
1. Overall talent level of this candidate pool
2. The most common skill gaps that appear across multiple candidates
3. A clear recommendation: proceed with interviewing the current pool, OR expand the search — with specific reasoning

The paragraph must be concrete and evidence-based — reference actual candidate scores and patterns.
Do not be vague. Name specific gaps. Give a direct recommendation with justification.

Return clean Markdown:

## Cohort Analysis

<one focused paragraph>

Return only the Markdown. No preamble."""

    raw_response = _call_claude(client, prompt, max_tokens=1000)

    # Append to hiring_summaries.md
    os.makedirs(artifacts_dir, exist_ok=True)
    summaries_path = Path(artifacts_dir) / "hiring_summaries.md"
    with open(summaries_path, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n")
        f.write(raw_response)

    # Log the call
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