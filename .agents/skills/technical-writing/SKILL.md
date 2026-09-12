---
name: technical-writing
description: Turn validated DDALANGOO engineering work into concise external-facing technical narratives for AI/software engineers and hiring managers. Prioritize problem-solving reasoning, system judgment, trade-offs, and verification over internal work logs.
version: 1.0.0
---

# Technical Writing

Write for an external technical reader who does not know DDALANGOO but may evaluate Jiwoo for an AI Agent Engineer role.

## Core Principle
Never write a chronological work log. Write a problem-solving argument.

Prefer:
HOOK -> PROBLEM -> EXPECTED FLOW -> FAILURE TRACE -> FIRST DIVERGENCE -> ROOT CAUSE -> DESIGN DECISION -> IMPLEMENTATION -> VALIDATION -> LIMITATION -> LESSON

Lead with the most interesting failure, contradiction, design decision, or result.

## Highlight
Prioritize:
- non-obvious failure mechanisms
- architecture/system judgment
- LLM vs deterministic-code boundaries
- state/routing/lifecycle reasoning
- first-divergence debugging
- reliability/safety design
- evaluation/regression methodology
- rejected alternatives and trade-offs
- measurable before/after evidence
- reusable engineering lessons

Compress/remove trivial fixes, repetitive implementation details, issue-management chatter, chronological logs, file/function names with no insight, and code that proves no meaningful decision.

Show competence through evidence, never praise.

## Evidence Gate
Use only Lead diagnosis, Coder evidence, Verifier results, Linear, actual code/diffs/tests.
Final narrative requires CODE PASS + BEHAVIOR PASS.
Missing evidence -> STATUS: NEEDS EVIDENCE.
Prefer concrete reproduction cases, before/after flows, test evidence, and measured impact over adjectives.

## External Reader Filter
Before keeping a detail ask:
1. Why would an outsider care?
2. What engineering ability does this prove?
3. What context is necessary?
4. What can be deleted?

Every technical detail should answer at least one:
WHY did it matter?
HOW did the system behave?
WHY was this design chosen?
WHAT evidence proves it?

Code supports the story; it is not the story.

## Trade-offs
When meaningful show: considered option -> why insufficient -> chosen design -> new trade-off.
Always state remaining limitations honestly.

## Presentation
Use strong title/opening, one main idea per section, short paragraphs, informative headings, clear definitions, and diagrams/tables when clearer than prose.
Suggest failure trace, before/after flow, architecture boundary, or compact evidence table when useful.

## Output
- Publish: YES / COMBINE / INTERNAL
- Reader hook
- Core engineering signal
- Narrative outline
- Evidence to show
- Details to cut
- Suggested diagram/table
- Trade-off worth explaining
- Remaining limitation
- Title candidates
- Portfolio/blog placement

All Jiwoo-facing writing must be Korean.

Goal: let the reader conclude from evidence that Jiwoo has traced real agent failures, designed system boundaries, and improved reliability through verifiable engineering.
