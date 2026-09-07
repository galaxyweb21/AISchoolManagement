# EduAI School Management — School Demo & UAT Plan

This is a controlled demonstration/UAT plan for the fictional **EduAI Demonstration School**. It is not a production-data import.

## 1. Create the demo environment

Run after migrations:

```bash
python manage.py migrate
python manage.py seed_permissions
python manage.py seed_roles
python manage.py seed_demo_school
python manage.py verify_demo_school
```

To rebuild only the fictional demo school:

```bash
python manage.py seed_demo_school --reset
python manage.py verify_demo_school
```

To use your own temporary demo password:

```bash
python manage.py seed_demo_school --password "YourTemporaryDemoPassword"
```

The seeder only uses the `eduai-demo` school and synthetic records. Do not load real student or parent data into this environment.

## 2. Demo accounts

The seeder creates role-focused accounts including:

- `demo_admin` — School Admin
- `demo_bursar` — Bursar / Finance
- `demo_registrar` — Registrar
- `demo_hod` — HOD
- `demo_secretary` — Secretary
- `demo_teacher1` through `demo_teacher5` — Teachers
- `demo_parent1` through `demo_parent3` — Parents
- `demo_student01` onward — Students
- `demo_librarian` — School Admin account for library demonstration

The command prints the password used when it finishes. Change temporary demo credentials before any external pilot.

## 3. Demonstration storyline

### A. School administration
1. Log in as `demo_admin`.
2. Show the role-based dashboard.
3. Show active students, attendance, finance KPIs and recent activity.
4. Open school/academic settings.
5. Show GES grade levels and the active academic year/term.

### B. Admissions and students
1. Switch to `demo_registrar`.
2. Open the student list.
3. Demonstrate admission numbers, class assignment and parent relationships.
4. Open a student profile.
5. Show the student's academic, attendance and financial information.

### C. Teacher workflow
1. Log in as `demo_teacher1`.
2. Show assigned class/subject scope.
3. Open attendance and demonstrate the existing attendance records.
4. Open Assessment & Results Centre.
5. Show CA and examination assessments.
6. Open a terminal result and demonstrate the Ghana 30/70 result model.
7. Explain that official marks are stored independently of AI narrative assistance.

### D. Results and report cards
1. Log in as `demo_hod` or `demo_admin`.
2. Open report-card management.
3. Show overall average, grade, remark, position and attendance.
4. Open a report-card detail page.
5. Export/print the report card to PDF and Word.
6. Demonstrate teacher/headteacher comments.
7. Explain finalization as the point at which the academic snapshot becomes locked.

### E. Finance
1. Log in as `demo_bursar`.
2. Open billing/finance dashboard.
3. Show fee structures for Basic 4, Basic 5 and JHS 1.
4. Open a student's invoice.
5. Demonstrate a partially paid invoice.
6. Demonstrate a fully paid invoice.
7. Verify receipt number, payment method, ledger and balance due.
8. Show the student's financial statement.

### F. Staff, leave and payroll
1. Log in as `demo_admin`.
2. Open staff/HR.
3. Show staff grades and salary structures.
4. Open leave configuration and grade-based entitlement.
5. Open the pending demo leave request.
6. Open payroll and show the September 2026 payroll period.
7. Open a demo payslip.

### G. Library
1. Open the library dashboard.
2. Show book categories and inventory.
3. Open a book.
4. Show the active borrowing record for a demo student.
5. Demonstrate return/lost workflows only with synthetic data.

### H. Communication
1. Open announcements.
2. Show the published welcome announcement.
3. Open notification records for demo parents.
4. Demonstrate notification preferences without sending real email/SMS.

### I. AI School Copilot
Use an account whose role is authorized for the information being requested.

Suggested questions:

- How many active students do we have?
- What is our current attendance situation?
- Which students have weaker academic performance?
- Give me an overview of school performance.
- What is our current outstanding fee position?
- Which staff members have leave requests?

For the demo, clearly state that AI is an assistant. It must not be presented as the authority for official student marks or financial transactions.

## 4. UAT acceptance checks

| Test | Expected result |
|---|---|
| Login by role | Correct dashboard and access scope |
| Tenant isolation | A school user cannot see another school's records |
| Student creation | Student receives admission number and correct class/parent relationship |
| Attendance | Present/Absent/Late records save and appear in dashboards |
| CA score | Saved against the correct student/assessment |
| Examination score | Saved against the correct student/assessment |
| Terminal result | Final score respects 30/70 scale |
| Report card | Uses authoritative saved results |
| Report card export | PDF/Word opens and contains the correct student |
| Fee structure | Correct class/term pricing appears |
| Invoice | Invoice total equals its line items |
| Partial payment | Balance decreases correctly |
| Full payment | Invoice changes to PAID and balance becomes zero |
| Receipt | Unique receipt is generated |
| Financial ledger | Invoice debit and confirmed payment credit reconcile |
| Leave request | Request follows configured workflow |
| Payroll | Salary structure, payroll run and payslip are linked |
| Library | Borrowing affects availability and is visible in history |
| Communication | Announcement/notification is scoped to the school |
| AI | AI responses respect role/data scope |
| Mobile UI | Main workflows remain usable on a phone-sized viewport |
| Health endpoint | `/healthz/` returns `status: ok` |

## 5. Issues to record during school testing

For every issue capture:

- user role
- exact URL/page
- action taken
- expected result
- actual result
- screenshot
- browser/device
- date/time
- severity: Blocker / Critical / Major / Minor / Cosmetic

Do not use real student names, Ghana Card numbers, phone numbers, payment references or parent credentials in screenshots sent for bug reports.

## 6. Demo exit criteria

The demo should be promoted to a limited school pilot only after:

- no Blocker/Critical UAT issues remain;
- authentication and tenant isolation have been tested;
- finance reconciliation has been verified;
- terminal results and report-card exports have been verified;
- parent and student portal flows have been tested;
- AI permissions have been verified;
- production media storage has been configured;
- production secrets are stored only in the hosting environment;
- backups and restore procedures have been tested.
