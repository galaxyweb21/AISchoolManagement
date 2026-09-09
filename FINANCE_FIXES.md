# Finance fixes included

- Fee Structure create/edit/delete now refreshes from the server after a successful save/delete so pagination/order never becomes stale.
- Fee Structure Add Item works from dynamically loaded modal forms using delegated event handling.
- Fee Add-on/Class Add-on Add Item works reliably for dynamically loaded create and edit forms.
- Fee Preparation now supports both **Prepare Selected Class** and **Prepare All Classes** for a selected term.
- Finance list/table pagination defaults to 25 records per page (25/50/100 controls).
- Recent Fee Preparations and Billing/Accounts Receivable tables are server-paginated.
- Student Financial Account transaction history is server-paginated.
- Student fee approval now immediately creates the official invoice, idempotently.
- Automatically approved fees also attempt immediate official invoice creation.
- Bulk approval also creates/repairs invoices immediately.
- Invoice generation was hardened to repair/create invoices from the authoritative approved StudentFee lifecycle and supports all classes when no class filter is supplied.
- Bulk Fee Statements are organized into class-specific ZIP files inside one master ZIP. PDF names include student full name, admission/student ID, and invoice number.
- Payment modal was rewritten to use form-scoped event handling and an explicit initializer, fixing dynamically injected invoice selection, balance calculation, full-payment calculation, allocation preview, and payment submission.

## Validation

- Python compilation checks passed for the project finance/core code.
- JavaScript syntax checks passed for all finance templates.
- `manage.py check` could not be executed in the build environment because Django is not installed there; no application code was changed to require new packages or migrations.

No model changes were made, so no new migration is required for these fixes.
