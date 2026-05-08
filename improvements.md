# What I Would Add With More Time

Given more time, here are the improvements I would make to the pipeline.
I've grouped them roughly by priority, starting with correctness and robustness,
then moving into testing, observability, and features.

---

## 1. Code Review and Cleanup

With more time I would do a proper pass through the codebase to remove redundancies.
Working under a time limit means some things get written quickly and not revisited,
and there are parts of the code I would tighten up given a second look.

---

## 2. Langfuse Integration

The `.env` file already has Langfuse keys wired in but the integration was not completed
in time. I would add Langfuse tracing across all LLM calls so every stage has a full
trace with inputs, outputs, latency, and token counts visible in the Langfuse dashboard.
This would give much better visibility into where the pipeline is slow, which prompts are
expensive, and how outputs change between runs on different input files.

---

## 3. Token Optimisation with tiktoken

I would add `tiktoken` to count tokens in each prompt before the API call is made.
Right now `max_tokens` values are set conservatively by hand. With tiktoken I could
measure actual prompt sizes, set tighter output budgets, and flag prompts that are
approaching context limits before they cause a truncated or failed response. It would
also give accurate cost estimates per run without needing to wait for the SDK's usage
response.

---

## 4. LLM Call Robustness

**Retry logic with exponential backoff**
Right now `_call_claude()` raises immediately on `RateLimitError` and `APIConnectionError`.
With 11 API calls per run, one transient network hiccup kills the entire pipeline.
I'd wrap the function with a simple retry decorator (3 attempts, 2s / 4s / 8s backoff)
so short-lived rate limits don't force a full restart.

**Recompute weighted scores in Python after Stage 2**
The scoring prompt asks the LLM to calculate `total_weighted_score` itself.
If the model gets the arithmetic wrong, the error goes straight into `original_scores` unchecked.
The re-scoring stage already recomputes totals in Python, so I would apply that same logic
right after parsing Stage 2 results and treat the model's total as advisory only.

**Add a system prompt to all structured JSON calls**
All LLM calls currently go out as single-turn user messages with no system prompt.
A short system prompt along the lines of "Return only valid JSON with no preamble or markdown fences"
would cut down on `_extract_json` parse failures without any other changes.

**Stronger `_extract_json` fallback**
The current brace/bracket scan uses `str.rfind()` which picks the wrong closing brace
if the model happens to return two JSON objects in one response.
Replacing the fallback with `json.JSONDecoder().raw_decode()` would parse the first valid
JSON object and stop cleanly.

---

## 5. Correctness and Spec Hardening

**Auto-normalise rubric weights on edit**
The interactive rubric editor warns when weights drift from 1.0 but still saves the rubric.
I would either block the save or auto-normalise weights proportionally so the pipeline
can never proceed with a rubric that sums to something other than 1.0.

**Per-criterion assertion in re-scoring**
`rescore_flagged()` checks that the right number of candidates came back,
but it does not verify that every flagged criterion was actually re-scored for every candidate.
A per-candidate, per-criterion check would catch silent LLM omissions before they affect the ranking.

**Stricter schema validation on input files**
`stage_init()` checks for required keys but does not validate types or empty values.
Adding `pydantic` models for `job_description.json` and `candidates.json` would surface
malformed inputs immediately, before any LLM call is made.

---

## 4. Unit Tests

The pure functions in `bias.py` and `state.py` are untested. I would add a `tests/` directory
covering at minimum:

- `test_anonymise_candidates`: verify that names, employers, institutions, and geography are all stripped
- `test_strip_signals`: parametrised cases for each signal category
- `test_pipeline_order_enforcement`: assert that calling `stage_finalise_ranking` before `BIAS_AUDITED` raises `PipelineOrderError`
- `test_rank_candidates`: verify sort order and rank assignment
- `test_requires_rescoring`: both the explicit field and the findings fallback path
- `test_extract_json`: fenced JSON, plain JSON, and malformed input cases

---

## 6. Observability and Debugging

**Structured run report**
At the end of each run I would write a `run_report.json` that captures stage durations,
token counts per call, bias findings count, whether re-scoring occurred, and the final ranking.
That makes it easy to compare behaviour across different input files.

**Token usage in the log**
The Anthropic SDK already returns `usage.input_tokens` and `usage.output_tokens` per call.
Adding those to each `llm_calls.jsonl` record would make cost tracking and prompt optimisation
much easier over time.

**Resume from last completed stage**
A failure at Stage 7 currently means re-running all 11 LLM calls from scratch.
Since `pipeline_state.json` already persists the current stage, I would extend `main.py`
to detect an existing state file and offer to pick up from where the pipeline left off.

---

## 7. Pipeline Features

**Configurable top-N for summaries**
The hiring summaries are hardcoded to the top 3 candidates. For larger pools this should
be a CLI argument or environment variable so the pipeline generalises without code changes.

**Parallel candidate scoring for large pools**
Stage 2 currently scores all candidates in a single LLM call. For pools of 20 or more candidates
this creates real context window pressure and risks truncation. Batching into groups of 5
and running them in parallel async calls would be more reliable at scale.

**Use Anthropic's tool use API for structured output**
Instead of prompting for JSON and then parsing it, I would use tool use to define the expected
schema as a tool definition. The model is constrained to return valid structured output,
which would remove the need for `_extract_json` entirely.

**Per-criterion scoring diff in the output**
The pipeline prints score deltas to the terminal but `candidate_scores.json` does not store
a before/after diff per criterion. Adding a `scoring_changes` key would make the audit trail
much clearer for anyone reviewing the output after the fact.