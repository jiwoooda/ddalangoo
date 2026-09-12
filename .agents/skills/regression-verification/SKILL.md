---
name: regression-verification
description: Verify agent-system fixes with both code-level and behavior-level evidence. Use after an implementation change to confirm the original failure is fixed, nearby behavior has not regressed, and the change scope is correct.
version: 1.0.0
---

# Regression Verification

Do not trust an implementation claim by itself. Verify the actual diff and behavior.

## 1. Reconstruct the goal
- What was the original failure?
- What was the expected behavior?
- What root cause was claimed?
- What was actually changed?

## 2. CODE REVIEW gate
Inspect the actual commit/diff.

Check:
- only expected files/hunks changed
- the change addresses the first divergence or root cause
- no unrelated redesign or scope creep
- state, routing, lifecycle, payment, and safety boundaries remain valid
- tests assert meaningful behavior, not just implementation details
- hotspot files or boundaries were handled safely

Verdict:
  CODE PASS / CODE FAIL / CODE BLOCKED

## 3. BEHAVIOR gate
Only proceed if code review is acceptable.

Verify:
- the original failure reproduction
- the expected behavior
- the relevant Living Regression Test
- multi-turn behavior when relevant
- stale state, rerouting, no-progress, and lifecycle edge cases
- nearby behavior that could regress from the change

Verdict:
  BEHAVIOR PASS / BEHAVIOR FAIL / BEHAVIOR BLOCKED

## Rules
- Independently assess the failure before trusting the coder rationale.
- Do not accept passing unit tests alone as behavioral proof.
- Do not use real production side effects or real browser/payment actions for evaluation.
- If the original failure cannot be reproduced, explain why and what evidence supports the verification.
- A resolution is not complete until both code and behavior gates are satisfied.

Goal: prove the system behaves correctly, not just that the code looks plausible.
