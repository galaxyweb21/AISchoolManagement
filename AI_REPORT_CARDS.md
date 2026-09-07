# AI Report-Card Generator

Batch-generates a draft report card comment for every student in a term,
so a teacher reviews and edits instead of writing 30+ comments from
scratch — without ever letting the AI have the last word on a document a
parent receives.

## Design choices that matter here

- **A human always signs off.** Generation produces a *draft*. A teacher
  can edit any part of the narrative, regenerate it, or finalize it. Once
  finalized, it's locked — no batch re-run, edit, or regenerate can touch
  it until an admin explicitly un-finalizes it.
- **Edits survive re-runs.** If a teacher has already rewritten a
  student's comment, re-running the batch (e.g. because other students'
  grades came in late) preserves that edit instead of silently
  overwriting it with a fresh AI draft. Verified directly: edited a
  narrative, re-ran the batch, confirmed the edit was untouched.
- **Finalized cards are completely skipped**, not just narrative-protected
  — a re-run doesn't recompute their grades/attendance either. Verified:
  finalized one student's card, re-ran the batch, confirmed
  `students_skipped_finalized` counted it and nothing about that row
  changed.
- **One ReportCard row per (student, term), not per batch run** — unlike
  the timetabler/risk-engine, which keep every run as history. A report
  card is a single evolving document (draft → edited → finalized), so a
  batch run updates the existing row in place rather than creating a new
  one each time.

## What's in a report card

- Subject-by-subject average, computed from `Grade` records linked (via
  `Assessment.academic_term`, added by this feature) to the specific term
  — not just "all grades ever entered."
- Attendance rate for the term.
- An AI-written 3-4 sentence narrative covering the whole term across all
  subjects (not one paragraph per subject) — acknowledges real strengths,
  names what needs attention, and gives one concrete suggestion.

## Running it

`/ai-engine/report-cards/` — same pattern as the timetabler and risk
dashboard: an admin triggers a batch, it runs as a Celery task (inline
fallback if no worker's reachable), and the dashboard lists every
student's card with draft/finalized status. A teacher opens one card to
edit the narrative, regenerate it, or finalize it.

## `Assessment.academic_term`

Added a nullable FK from `Assessment` to `AcademicTerm` so report cards
know which term an assessment counts toward. Existing/legacy assessments
without it set still work — the report-card engine falls back to matching
by `created_at` date range against the term's start/end dates.

## Not done yet / natural next steps

- No PDF export — report cards are viewed/edited in-browser only. Given
  the `pdf` tooling pattern already established elsewhere in this
  project's ecosystem, generating a printable PDF per student (or a
  batch ZIP) is the natural next step for something parents actually take
  home.
- No parent-facing view — currently admin/teacher only.
- Regenerating a single card's narrative costs one Groq call each time;
  fine at the "review one flagged student" scale, but a "regenerate all
  drafts" bulk action would need the same rate-limiting care as the batch
  job already has.
