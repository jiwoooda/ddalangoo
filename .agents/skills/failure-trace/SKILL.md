---
name: failure-trace
description: Diagnose agent-system failures by reconstructing expected flow, tracing the actual execution path, and identifying the first divergence before proposing a fix.
version: 1.0.0
---

# Failure Trace

Use for behavioral failures, regressions, stuck loops, wrong routing, lost state, incorrect tool behavior, or mismatched responses.

## Method

1. State the expected behavior.
2. Reconstruct the actual path.
3. Trace in order:
   - user input
   - LLM raw output
   - parser / postprocess
   - router / handoff
   - state / schema / lifecycle
   - tool or deterministic logic
   - downstream node
   - final response
4. Identify the FIRST DIVERGENCE from expected behavior.
5. Separate:
   - FACT
   - HYPOTHESIS
   - UNKNOWN
6. Explain how the first divergence propagated into the final failure.
7. Propose the smallest fix that addresses the root cause.
8. Define how to verify the fix and what nearby regressions to test.

## Rules

- Do not assume the prompt is the root cause.
- Do not fix the final symptom if an earlier boundary caused it.
- Prefer evidence from traces, code paths, state snapshots, tests, and diffs.
- Distinguish interpretation failures from orchestration, state, schema, lifecycle, and deterministic-code failures.
- If evidence contradicts the current hypothesis, stop and revise the diagnosis.

Goal: find where the system first became wrong, not merely where the user noticed it.
