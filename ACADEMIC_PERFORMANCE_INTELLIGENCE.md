# Academic Performance Intelligence

## What changed

The AI School Copilot now has an expanded deterministic academic analytics path in `ai_engine/services/full_school_database_intelligence.py`.

It is integrated through the existing `academic_summary()` handler and existing Copilot domain planner. No new database tables or migrations are required.

## Data source and calculation rules

- Uses `assessments.TerminalResult` as the authoritative terminal/report-card result source.
- Includes only records scoped to the authenticated school, the authorized student queryset (when supplied), active students, `status=COMPLETE`, and a non-null `final_score`.
- Uses the project's existing 40/100 pass threshold.
- Draft, incomplete, missing, and null-score results are excluded; they are not counted as failures.
- Uses the selected academic term. Current-term requests require an active term; previous-term requests require an active term to establish the comparison period.
- Subject and class filters are resolved against real school records before being applied.

## Supported analysis

- Overall average, pass rate, failure rate, completed result count, and distinct student count.
- Subject averages and strongest/weakest subject identification.
- Class averages and class comparison.
- Students with completed subject results below 40%, including an optional minimum failed-subject count (for example, three or more).
- Whole-cohort term-to-term average comparison.
- Individual student average declines where a student has completed results in both compared terms.

## Copilot examples

- What is the school's overall academic performance this term?
- Which subject has the lowest average?
- Which subject performed best this term?
- Which class performed best this term?
- Compare class performance this term.
- Show students below 40%.
- Which students failed three or more subjects?
- Compare this term with last term.
- Show students whose scores declined.

## Security and compatibility

The existing central `academics` and `students` AI capability checks remain in force. School and authorized-student filtering are applied before aggregation and listing. The new analytics are additive and leave the existing student merit-ranking handler and legacy assessment-record summary available.

## Validation

Python syntax compilation and isolated Copilot intent-planner smoke checks were run. Full Django test execution could not be run in the build environment because Django is not installed there and package installation is unavailable. Run the project test suite in the configured development environment after installing `requirements.txt`.
