# Enterprise Fee Lifecycle Fix

The finance lifecycle is now idempotent at the **student + academic term** level.

## Rules

1. `FeeStructure` is the published price definition.
2. `StudentFee` is the student's frozen term calculation.
3. `StudentFee` is unique per student and academic term.
4. Clicking **Prepare** again does not rebuild an existing PREPARED, APPROVED, or INVOICED fee.
5. Clicking **Approve** again is a no-op and cannot create another debit.
6. APPROVED and INVOICED fees are never silently rebuilt by student registration or background automation.
7. A student registered after the class/term billing cycle has already reached APPROVED/INVOICED automatically inherits the approved lifecycle for that term.
8. New-student add-ons remain term-enrollment driven.
9. Official invoices are the authoritative billed amount. Provisional `FEE-<studentfee>` ledger rows are removed when an invoice is created.
10. Existing duplicate provisional ledger rows can be cleaned with:

```text
python manage.py repair_fee_lifecycle --dry-run
python manage.py repair_fee_lifecycle
```

Use `--school <UUID>` to limit repair to one school.

## Recommended enterprise workflow

**Fee Structure → Prepare Student Fees → Review → Approve → Generate/Confirm Invoice → Record Payments**

Preparation is a snapshot operation, not a recurring charge operation. Any change after approval should be represented by a controlled adjustment/credit/debit or a new fee revision, never by rebuilding the original approved record.
