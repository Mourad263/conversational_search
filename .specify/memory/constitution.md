<!--
Sync Impact Report
- Version change: [TEMPLATE] → 1.0.0 (initial ratification)
- Modified principles: n/a (template placeholders replaced with 6 new principles)
- Added sections: Core Principles (I–VI), Quality & Evaluation Standards, Scope Boundaries, Governance
- Removed sections: none (template placeholder examples removed)
- Deferred/TODO placeholders: RATIFICATION_DATE set to today (2026-09-06) as this is the initial
  ratification; adjust if an earlier project kickoff date should be recorded instead.
- Note: This constitution intentionally excludes implementation architecture (no stack, service,
  or component decisions) per project scope instructions.
-->

# Project 6 — Conversational Search Constitution

## Core Principles

### I. Conversation Over Query
The system MUST treat search as a multi-turn dialogue, not a single-shot lookup. Every user
turn MUST be interpretable in the context of prior turns within the same session (e.g., a
follow-up like "cheaper ones" or "بس لون أحمر" must resolve against the active filter/result
state, not be treated as a fresh, context-free query). Session context (accumulated filters,
last result set, last intent) MUST be explicitly tracked and MUST be inspectable/loggable for
debugging and evaluation — implicit, unrecoverable state is not acceptable.

**Rationale**: Multi-turn filter refinement is a stated core capability of this project; if
context isn't a first-class, inspectable concept, refinement quality cannot be measured or
improved.

### II. Bilingual Parity (English & Arabic)
Arabic is a first-class input language, not a fallback or best-effort mode. Any capability
claimed for English input (intent understanding, filter extraction, refinement, result
relevance) MUST be evaluated and demonstrated for Arabic input as well, including mixed
English/Arabic and transliterated queries where reasonably encountered. Known gaps between
the two languages MUST be documented rather than silently accepted. Right-to-left text and
Arabic-specific tokenization/normalization concerns (diacritics, elongation, digit forms)
MUST be accounted for in evaluation, not just in passing manual tests.

**Rationale**: A conversational search system that quietly degrades for Arabic fails a
stated project requirement, not just a "nice to have."

### III. Baseline-Relative Evaluation (NON-NEGOTIABLE)
No claim of improvement, quality, or relevance is valid without a documented comparison
against the traditional keyword-search baseline on the same queries/tasks. Every evaluation
MUST report both systems side by side using the same test set and the same metrics. Cherry-
picked or anecdotal comparisons ("it felt better") are not sufficient evidence for design or
release decisions — only recorded, repeatable comparisons are.

**Rationale**: The project's explicit purpose includes proving (or disproving) value over
keyword search; without a rigorous baseline comparison, that purpose cannot be fulfilled.

### IV. Transparent, Debuggable Behavior
The system's search and refinement decisions MUST be explainable after the fact: for any
result set returned, it MUST be possible to trace which interpreted intent, filters, and
conversation state produced it. Silent, unexplainable behavior changes (e.g., a filter
appearing or disappearing with no traceable cause) are treated as defects. This applies
equally to English and Arabic sessions.

**Rationale**: As a prototype meant to be evaluated and iterated on, undebuggable behavior
blocks both quality improvement and honest comparison against the baseline.

### V. Honest Prototype Scoping
This is an explicitly a prototype: functionality MUST be truthfully represented as
prototype-grade, not production-grade, in any documentation, demo, or evaluation report.
Known limitations (language coverage gaps, unhandled query types, performance limits) MUST
be documented rather than hidden or hand-waved. Scope MUST stay within natural-language
product search, multi-turn refinement, English/Arabic input, and baseline comparison — new
capabilities outside this scope require a deliberate decision, not incidental scope creep.

**Rationale**: Overclaiming prototype maturity, or silently expanding scope, undermines the
credibility of any comparison or conclusion drawn from the project.

### VI. Data & Query Privacy by Default
User queries (including free-text natural-language input in either language) MUST be
treated as potentially sensitive. Logged conversation/session data used for debugging or
evaluation MUST be handled with the minimum retention and access needed for that purpose,
and MUST NOT be repurposed (e.g., for unrelated analytics) without a deliberate decision.

**Rationale**: Conversational input is more revealing than keyword queries (it can carry
more context about the user's intent and situation), so it warrants deliberate handling
even at prototype stage.

## Quality & Evaluation Standards

- Every change that affects search behavior (intent parsing, filter extraction, ranking,
  refinement logic) MUST be checked against a shared evaluation set covering English and
  Arabic queries, single-turn and multi-turn cases, before being considered done.
- Relevance and refinement quality MUST be judged using consistent, predefined criteria
  (e.g., precision of returned items against stated intent, correct filter carry-over across
  turns) agreed upon before evaluation, not invented after seeing results.
- Regressions in either language, or in baseline-comparison metrics, MUST be treated as
  defects, not acceptable trade-offs, unless explicitly justified and recorded.
- Failure modes (unrecognized intent, ambiguous filter, no results) MUST degrade gracefully
  and MUST be distinguishable from success in logs/evaluation — silent failure is not
  acceptable.

## Scope Boundaries

- This constitution governs project-wide principles and quality bars. It does NOT prescribe
  system architecture, technology choices, or component design — those are determined in
  later planning artifacts and MUST remain consistent with these principles, not the reverse.
- Any implementation decision that conflicts with a Core Principle (e.g., an architecture
  that cannot support multi-turn context, or that only supports English) MUST be flagged and
  resolved before proceeding, not deferred silently.

## Governance

This constitution supersedes ad hoc practice for Project 6. All specifications, plans, and
task breakdowns MUST be checked for consistency with these principles before being finalized.

**Amendment procedure**: Amendments are made by editing this file, incrementing the version
per the policy below, and recording a Sync Impact Report as an HTML comment at the top of the
file summarizing what changed and why.

**Versioning policy** (semantic versioning applied to governance):
- MAJOR: Removal or backward-incompatible redefinition of a principle.
- MINOR: Addition of a new principle or materially expanded guidance.
- PATCH: Clarifications, wording fixes, non-semantic refinements.

**Compliance review**: Every spec, plan, and evaluation report produced for this project
MUST include or reference an explicit check against these principles (in particular
Principles II, III, and IV) before being marked complete. Deviations MUST be documented with
rationale, not silently absorbed.

**Version**: 1.0.0 | **Ratified**: 2026-09-06 | **Last Amended**: 2026-09-06
