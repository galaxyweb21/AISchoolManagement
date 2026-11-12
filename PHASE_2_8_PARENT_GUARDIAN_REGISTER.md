# Phase 2.8 — Parent / Guardian Register

## Included

- Added a dedicated Parents / Guardians register under Student & Academics navigation.
- Added school-scoped guardian listing with search across guardian name, email, phone, username, linked student name, and admission number.
- Added linked / unlinked and active / inactive filters.
- Added summary counts for all guardians, guardians linked to students, unlinked guardian accounts, and active accounts.
- Added a responsive register table showing guardian contact details and linked students, with direct links to student profiles.
- Added View Details, Add Guardian, and Edit Guardian Bootstrap modals.
- Added AJAX form submissions with inline validation and server-error feedback.
- New guardian creation generates a unique username and temporary password. The password is returned only to the authorized staff member creating the account and is shown in the modal once, with a reminder to share it securely.
- All register queries and create/update operations are scoped to the logged-in user's school; only authorized staff roles can access the register or mutate guardian accounts.

## Compatibility

- No model changes or database migrations.
- Existing student create/edit and Manage Guardian workflows are unchanged.
- Finance, fee preparation, invoices, payments, and receipts are untouched.

## Verification performed

- `python -m py_compile students/views.py students/urls.py` passed.
- Static assertions for route names and required template elements passed.
- ZIP integrity test passed.
- Full Django checks and browser interaction tests were not run in this environment because Django is not installed here. Run `python manage.py check` and test the modal flows in the configured local virtual environment before deployment.
