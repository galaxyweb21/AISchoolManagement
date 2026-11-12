# Phase 2.7 — Student Management Polish

## Changes

- Added the missing `unregistered_faces` context value used by the Students page summary.
- Fixed live face-status filtering to use explicit row data instead of searching badge text. Previously, “Not Registered” also contained the word “Registered” and could be classified incorrectly.
- Fixed active/inactive live filtering to use explicit status data, avoiding text-label ambiguity.
- Clarified the live filter count as the number shown on the current page; server-side filters and pagination remain in place.
- Updated the Quick View status badge styling for inactive students.
- Improved Manage Guardian modal submission with inline validation/network feedback and an AJAX save path. Errors stay in the modal; successful saves refresh the current student profile so the newly linked guardian appears without redirecting to the student edit page.
- Added JSON error responses for AJAX guardian submissions while preserving the standard form-post fallback.

## Compatibility

- No database model or migration changes.
- Existing student create/edit routes and fee/invoice lifecycle were not changed.
- Guardian creation/linking remains scoped to the logged-in user's school and authorized staff roles.

## Verification performed

- Python bytecode compilation for the `students` app passed.
- ZIP integrity and targeted source assertions passed.
- A full `manage.py check` could not be run in this environment because Django is not installed in the execution environment. Run it inside the project's configured virtual environment before deployment.
