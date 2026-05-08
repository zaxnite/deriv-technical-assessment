# Deriv AI Recruitment Screening Pipeline

A production-grade, multi-stage AI pipeline that evaluates candidate resumes
against a job description, scores them on structured criteria, audits for bias,
applies de-biasing logic, and produces hiring committee-ready outputs.

---

## Architecture

INIT -> RUBRIC_GENERATED -> RUBRIC_APPROVED -> CANDIDATES_SCORED
     -> BIAS_AUDITED -> [FLAGGED_RESCORING_COMPLETE] -> RANKING_FINALISED
     -> SUMMARIES_GENERATED -> INTERVIEW_QUESTIONS -> COHORT_ANALYSIS
     -> COUNTER_INTUITIVE_PICK -> BLIND_RERANKING

Each stage is enforced in code. Rankings cannot be produced before the bias
audit completes — attempting to do so raises a PipelineOrderError.

---

## Project Structure

deriv-technical-assessment/
├── main.py                     # Pipeline entry point
├── validate.py                 # Artifact validation command
├── job_description.json        # Input: role specification
├── candidates.json             # Input: candidate pool
├── requirements.txt            # Python dependencies
├── pipeline/
│   ├── __init__.py
│   ├── state.py                # Stage ordering + PipelineState
│   ├── stages.py               # One function per pipeline stage
│   ├── llm.py                  # All LLM call functions (1 per stage)
│   ├── bias.py                 # Anonymisation + audit parsing
│   └── logger.py               # llm_calls.jsonl writer
└── artifacts/
    ├── latest/                 # Symlink to most recent session (Unix)
    ├── latest_session.txt      # Session pointer (Windows fallback)
    └── session_YYYYMMDD_HHMMSS/
        ├── scoring_rubric.json
        ├── candidate_scores.json
        ├── bias_audit.json
        ├── hiring_summaries.md
        ├── llm_calls.jsonl
        └── pipeline_state.json

---

## Setup

### Prerequisites

- Python 3.13+
- Git

### Installation

```bash
git clone <your-repo-url>
cd deriv-technical-assessment
python -m venv venv

# Windows
venv\Scripts\activate

# Unix/macOS
source venv/bin/activate

pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root:

```env
ANTHROPIC_API_KEY=your_anthropic_api_key
OPENAI_API_KEY=your_openai_api_key
PINECONE_API_KEY=your_pinecone_api_key
LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
LANGFUSE_SECRET_KEY=your_langfuse_secret_key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

Only `ANTHROPIC_API_KEY` is required to run the pipeline.
All LLM calls use `claude-haiku-4-5`.

---

## Input Files

The pipeline reads two JSON files from the working directory:

### `job_description.json`

```json
{
  "role": "string",
  "company": "string",
  "location": "string",
  "requirements": ["string"],
  "nice_to_have": ["string"],
  "explicitly_not_required": ["string"]
}
```

### `candidates.json`

```json
[
  {
    "id": "string",
    "name": "string",
    "summary": "string"
  }
]
```

The evaluator may replace these files with equivalent fixtures using the
same schema. The pipeline makes no assumptions about candidate names, IDs,
ordering, or text content.

---

## Run Command

```bash
python main.py
```

The pipeline will:

1. Load `job_description.json` and `candidates.json`
2. Generate a 6-criterion scoring rubric via LLM
3. Pause for interactive rubric approval — you may approve, edit, or reject
4. Score all candidates against the approved rubric
5. Run a mandatory bias audit (ranking is blocked until this completes)
6. Re-score flagged criteria using anonymised candidate data (if required)
7. Produce the final ranked list using corrected scores
8. Generate hiring committee summaries for the top 3 candidates
9. Generate 5 structured interview questions for the #1 candidate
10. Generate a cohort analysis paragraph
11. Write a counter-intuitive pick (devil's advocate for lowest-ranked)
12. Run blind re-ranking comparison

Each run creates a timestamped session directory:

    artifacts/session_20260508_183729/
    artifacts/latest/  <- always points to the most recent session

### Interactive Rubric Checkpoint

At stage 3, the pipeline pauses and displays the generated rubric:

    OPTIONS:
      [A] Approve rubric and proceed to scoring
      [E] Edit criterion name, description, or weight
      [R] Reject and regenerate rubric

- A — approve and continue
- E — edit a specific criterion field interactively
- R — reject and regenerate (up to 3 attempts)

---

## Validation Command

```bash
python validate.py
```

Validates all 13 requirements:

1.  All required artifact files exist
2.  All JSON files are valid
3.  Rubric contains exactly 6 criteria with correct fields
4.  Rubric weights sum to 1.0
5.  Approved rubric was used for candidate scoring
6.  All candidates were scored on all 6 criteria
7.  original_scores and corrected_scores both preserved
8.  bias_audit.json has valid structure and severity values
9.  Bias audit completed before ranking was produced
10. Flagged criteria re-scored using anonymised data
11. llm_calls.jsonl contains all required stage records
12. Interview questions and cohort analysis are present
13. Session directory structure is correct

Exit codes: 0 = all checks passed, 1 = one or more failures.

---

## Output Artifacts

All artifacts are written to `artifacts/latest/`:

| File                  | Description                                                        |
|-----------------------|--------------------------------------------------------------------|
| scoring_rubric.json   | Approved 6-criterion rubric used for scoring                       |
| candidate_scores.json | Original scores, corrected scores, final ranking                   |
| bias_audit.json       | Bias findings with severity: flagged / watch / clear               |
| hiring_summaries.md   | Top 3 summaries, interview questions, cohort analysis,             |
|                       | counter-intuitive pick, blind re-ranking                           |
| llm_calls.jsonl       | One JSON record per LLM call with prompt hash + anonymisation flag |
| pipeline_state.json   | Current pipeline stage for inspection/debugging                    |

### candidate_scores.json structure

```json
{
  "rubric_reference": "path/to/scoring_rubric.json",
  "original_scores": ["..."],
  "corrected_scores": ["..."],
  "bias_audit_status": "COMPLETE",
  "flagged_criteria": ["C1", "C3"],
  "final_ranking": ["..."],
  "rescoring_occurred": true
}
```

- `original_scores` — set once at Stage 2, never overwritten
- `corrected_scores` — only populated if flagged re-scoring occurred
- `final_ranking` — uses corrected scores when available

### llm_calls.jsonl structure

```json
{
  "stage": "FLAGGED_RESCORING_COMPLETE",
  "timestamp": "2026-05-08T18:37:51+00:00",
  "model": "claude-haiku-4-5",
  "provider": "anthropic",
  "prompt_hash": "sha256-hex",
  "input_artifacts": ["artifacts/.../candidate_scores.json"],
  "output_artifact": "artifacts/.../candidate_scores.json",
  "candidate_names_included": false
}
```

`candidate_names_included` is `false` for all anonymised re-scoring and
blind re-ranking calls.

---

## Pipeline Stage Enforcement

Stage ordering is enforced by `pipeline/state.py`.
Skipping a stage raises `PipelineOrderError`.
Producing a ranking before the bias audit raises `PipelineOrderError`.

```python
# Raises PipelineOrderError if bias audit has not completed
state.assert_bias_audit_complete()
```

---

## Bias Audit and De-Biasing

The bias audit (Stage 3) checks for:

- Name-based or nationality-based scoring patterns
- Credential bias (degree institution, employer prestige)
- Experience context bias (startup vs corporate, geography)
- Gender-correlated scoring patterns

Findings use severity levels:

- `flagged` — requires anonymised re-scoring
- `watch` — noted but not acted on
- `clear` — area examined, no bias found

If any `flagged` findings exist, only the affected criteria are re-scored.
Candidate names and demographic signals are stripped in Python
(`pipeline/bias.py`) before the re-scoring prompt is constructed.

---

## Model

All LLM calls use `claude-haiku-4-5` via the Anthropic API.
Each stage makes exactly one LLM call, logged separately in `llm_calls.jsonl`.

---

## Clean Checkout Execution

```bash
# Delete artifacts
rmdir /s /q artifacts     # Windows
rm -rf artifacts           # Unix

# Run pipeline from scratch
python main.py

# Validate
python validate.py
```

The pipeline regenerates all artifacts from the input files on every run.
No static precomputed outputs are used.