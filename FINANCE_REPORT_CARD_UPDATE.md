# Finance + Report Card Update

## Payment receipt
After a successful payment, the receipt now opens in a new browser tab/window. The original page refreshes after the receipt is opened.

## Report-card workflow
AI is an assistant, not the release authority. `Generate / Refresh Results` and `Generate All + Class ZIPs` generate/update report cards. `Finalize & Release All` remains an explicit administrator action for locking/publishing eligible cards and running release notifications.

## Bulk report cards
`Generate All + Class ZIPs` regenerates all active-term report cards, then downloads one outer ZIP containing one ZIP per class. Each class ZIP contains one PDF per student, named with student name, admission/ID and class.

Example:
School - First Term 2026 - Report Cards.zip
  JHS 1.zip
    Ama Mensah - STU001 - JHS 1 - Report Card.pdf
    Kofi Owusu - STU002 - JHS 1 - Report Card.pdf
  JHS 2.zip
    ...

## Pagination
The base template includes the global table paginator with 25 rows per page for tables that render more than 25 rows. Existing server-side paginated tables remain compatible.
