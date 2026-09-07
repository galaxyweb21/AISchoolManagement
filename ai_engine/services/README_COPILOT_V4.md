# Copilot V4 — Full School Database Intelligence

The Copilot now uses `FullSchoolDatabaseIntelligence` before the legacy deterministic engines.

## Rule

School database facts must come from Django ORM. Groq is not the source of truth for:
- counts
- balances
- statuses
- lists
- attendance
- leave
- payroll record counts
- academic record counts
- library counts
- transport/finance record counts
- school identity and active academic context

## Processing order

1. FullSchoolDatabaseIntelligence
2. Existing SchoolDatabaseIntelligence
3. Existing SchoolDataQueryEngine
4. Verified school-data safety guard
5. Ghana education / research / general AI pipeline

## Safety

If a school-data question is not covered by a verified query, the safety guard prevents an invented database answer. The Copilot must not expose raw Django model dumps, internal AI models, credentials, passwords, biometric data or private identifiers.

## V4 coverage

The registry covers the current student, staff/HR, academics, assessments, attendance, finance, library, school, communication, transport, payroll, leave and promotion models present in this release. Domain-specific handlers provide stronger answers for staff availability, staff leave, student counts/lists, finance summaries, attendance, library summaries and academic summaries.
