from django.test import TestCase

# Create your tests here.

# Enterprise finance lifecycle regression tests are intentionally kept small
# here because the project already contains extensive integration tests.
# The critical invariants are:
#   1. one StudentFee per student/term;
#   2. invoice totals come from StudentFeeItem rows;
#   3. confirmed payments reduce invoice balance;
#   4. new-student-only add-ons depend on term enrollment, not the profile flag.
