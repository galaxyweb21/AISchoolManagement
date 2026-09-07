# EduAI School Management — Render Demo/UAT Release

This repository is a controlled demonstration and user-acceptance-testing release of the EduAI School Management platform.

## Included modules

- School and academic setup
- Role-based accounts and permissions
- Student and parent management
- Staff, teachers, departments and leave
- Classes, subjects and teacher assignments
- Attendance
- Ghana terminal results (Class Work 30% + Examination 70%)
- Report cards, ranking and comments
- Fees, invoices, payments and student financial ledger
- Payroll and payslips
- Library
- Communication and notifications
- AI configuration and optional Groq-powered features

## Demo deployment design

The Render Blueprint creates:

1. A Docker-based Django web service.
2. A managed Render PostgreSQL database.
3. Automatic migrations during container startup.
4. Static-file collection during startup.
5. Automatic fictional demo-school seeding after the first successful deployment.

Face recognition is intentionally optional in the lightweight Render demo image. Manual attendance remains available. The full native face-recognition dependency set is preserved in `requirements.full-face.txt` for a dedicated/local environment.

## Demo accounts

The seed command creates fictional accounts such as:

- `demo_admin`
- `demo_bursar`
- `demo_registrar`
- `demo_hod`
- `demo_secretary`
- `demo_librarian`
- `demo_teacher1` through `demo_teacher5`
- `demo_parent1` through `demo_parent3`
- `demo_student01` onward

Default demo password:

`Demo@2026!`

Change the password supplied to the seed command if you create a different demo environment.

## Local setup

Create a virtual environment, install `requirements.txt`, configure a local MySQL database, then run:

```bash
python manage.py migrate
python manage.py seed_permissions
python manage.py seed_roles
python manage.py seed_demo_school --reset
python manage.py verify_demo_school
python manage.py runserver
```

## Render deployment

Push this repository to a new GitHub repository with the root-level `render.yaml` and `Dockerfile` intact. In Render choose **New → Blueprint**, connect the repository, review the proposed web service and Postgres database, and deploy the Blueprint.

The Blueprint uses Render's Docker runtime and provisions PostgreSQL through `fromDatabase`. Render's free Postgres is intended for testing and expires after 30 days, so this release is for demo/UAT rather than permanent production data.

After the first successful deploy, open the service URL and log in with one of the demo accounts above.

See `RENDER_DOCKER_DEPLOYMENT.md` and `DEMO_TEST_PLAN.md` for the full test sequence.
