# Phase 2.8 — Parent / Guardian Search Filter Fix

## Changes
- Multi-word search is now token-aware. Every search term must match at least one searchable guardian/contact field or a student linked within the current school.
- The search fields remain guardian first name, last name, email, phone, username, linked student first/last name, and admission number.
- School scoping remains applied to the base guardian queryset and linked-student search conditions.
- Relationship and account-status filters are unchanged and continue to combine with search.
- Existing pagination is unchanged; the regression tests cover full-name and single-word searches.

## Verification
- Python syntax compilation passed for the modified view and regression tests.
- ZIP integrity is checked after packaging.
- Django runtime checks/tests could not be executed in this build environment because Django is not installed here. Run `python manage.py test students.tests.ParentGuardianSearchTests` in the project's configured environment.
