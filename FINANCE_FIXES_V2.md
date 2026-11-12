# Finance Fixes V2

- Class add-on Create/Edit now has a robust Add item handler; injected modal markup is supported.
- All large tables receive a 25-row paginator. Existing server-side paginated tables remain server paginated.
- Invoice generation accepts an empty class selection as "all school classes" and uses approved/prepared StudentFee records as the source of truth. Missing StudentFee records are prepared when possible.
- Approval immediately attempts invoice creation; repeating approval repairs a missing invoice without duplicating charges.
- Payment modal redesigned and uses the actual finance API URL, explicit form submission, invoice selection, balance calculation, full-payment shortcut, and CSRF protection.
- Bulk statement export now creates an outer ZIP with one ZIP per class. PDFs include student name + admission/student ID + invoice number.
- No new migrations are required by these changes.
