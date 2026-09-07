# AI School Copilot — Verified Database Intelligence

This release changes the Copilot's school-data architecture so that factual
questions are answered from the authenticated school's Django database before
any external AI provider is considered.

## Rules

1. School data is tenant-scoped to `request.user.school`.
2. Database counts, lists, balances, statuses and dates are calculated by ORM.
3. The LLM is not allowed to invent database facts.
4. If a question clearly requests school data but no verified query exists,
   the Copilot returns a safe "could not verify" response instead of guessing.
5. Sensitive fields and internal security records are never exposed.
6. Existing conversation history, delete, reopen and stale-conversation recovery
   remain unchanged.

## Current verified coverage

- School identity
- Active/inactive students and student lists
- Active/inactive staff, teachers, non-teaching staff, positions, availability
  and current approved/taken leave
- Classes and subjects
- Departments, staff grades and leave types
- Academic years and terms
- Fees/invoices, payment records and verified financial totals
- Today's student attendance
- Assessment/grade/terminal-result record totals and average recorded score
- Library books and categories
- School announcements

The existing `SchoolDataQueryEngine` remains in the pipeline for its richer,
previously implemented fee/attendance/student-specific answers. The new
`SchoolDatabaseIntelligence` layer runs first and supplies broader verified
coverage.

## Why this is safer

A temporary Groq DNS/network failure cannot turn a database question into an
"AI service error" or a hallucinated answer. The Copilot either returns a
verified database result or explicitly refuses to guess.
