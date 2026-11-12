# Predictive Academic Risk & Early Intervention Intelligence

## Overview

This upgrade adds a deterministic academic early-warning path to the existing AI School Copilot. It is separate from the existing holistic/dropout risk engine, which also considers attendance and overdue fees. The academic screen uses completed terminal academic results only.

## What it identifies

- Critical: current average below 40%, or at least three subjects below 40%.
- High: current average below 50%, at least two subjects below 40%, or a like-for-like term average decline of at least 10 percentage points.
- Watch: current average below 60%, or a like-for-like term average decline of at least 5 percentage points.
- On track: no current rule-based warning condition.

The band is an explainable early-warning category, not a validated prediction or probability of future failure. Staff should verify marks and speak with the student before deciding on interventions.

## Fair trend comparison

Term-to-term changes are calculated only for subjects with completed results in both periods. Students without matching subjects in both periods do not receive a decline value. If the active term has no completed results yet, general early-warning questions use the most recent term with completed results; explicit current-term questions still require the active term's records.

## Recommended actions

The Copilot suggests teacher-led review, targeted remediation, monitoring, and follow-up. It does not automatically message guardians, alter grades, or create interventions without a separate authorized workflow.

## Data integrity and access

- Source: `assessments.TerminalResult`.
- Requires `status=COMPLETE` and non-null `final_score`.
- Scoped to the authenticated school and the authorized student queryset supplied by the Copilot.
- Draft and missing results are excluded rather than treated as zero or failure.
- Uses the existing `academics` and `students` capability checks.
- No new database tables or migrations are introduced.

## Example Copilot questions

- Which students are at academic risk this term?
- Show students who are struggling academically.
- Prepare an early intervention list.
- Which students are falling behind?
- Which students are failing in multiple subjects?
- Show students whose grades declined.
- What support should we provide to students at risk?

## Validation

Python syntax compilation and isolated intent-routing / risk-band smoke checks are included in the delivery validation. Full Django tests should be run in the configured development environment because Django is not installed in the build environment used for this package.
