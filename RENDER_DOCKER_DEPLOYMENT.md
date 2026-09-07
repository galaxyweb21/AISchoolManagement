# Render Docker Deployment — EduAI Demo/UAT

## 1. Create the GitHub repository

Create a **new empty GitHub repository**. Do not upload `.env`, `db.sqlite3`, `.git`, `media/`, or `staticfiles/`.

From this release directory:

```bash
git init
git branch -M main
git add .
git commit -m "Initial EduAI school management demo"
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git push -u origin main
```

## 2. Deploy with Render Blueprint

In Render:

1. Open **New → Blueprint**.
2. Connect the new GitHub repository.
3. Select branch `main`.
4. Render reads the root `render.yaml`.
5. Confirm the proposed resources:
   - `eduai-school-demo` web service
   - `eduai-school-demo-db` PostgreSQL database
6. Apply the Blueprint.

The web service uses the root `Dockerfile`.

## 3. What happens automatically

The Docker container:

1. Installs the lightweight Render dependencies.
2. Starts Django through Gunicorn.
3. Runs migrations before Gunicorn.
4. Runs `collectstatic`.
5. Exposes `/healthz/` for Render's health check.
6. After the first successful deployment, Render runs:

```bash
python manage.py seed_demo_school --reset --students 18
```

This creates the fictional `EduAI Demonstration School` dataset.

## 4. Environment variables

The Blueprint creates the important variables automatically. You only need to enter `GROQ_API_KEY` if you want to test the AI features.

Do not put API keys, passwords, or database URLs into GitHub.

## 5. First login

Default password:

`Demo@2026!`

Example usernames:

- `demo_admin` — school administration
- `demo_bursar` — finance
- `demo_registrar` — student/registry workflows
- `demo_hod` — academic/HOD workflows
- `demo_teacher1` — teacher workflows
- `demo_parent1` — parent portal
- `demo_student01` — student portal

## 6. Verify the deployment

Open:

```text
https://YOUR-RENDER-SERVICE.onrender.com/healthz/
```

Expected response:

```json
{"status": "ok"}
```

Then open the normal service URL and test the workflows in `DEMO_TEST_PLAN.md`.

## 7. Important Free-tier limitation

Render Free web services can spin down after inactivity. Free Render Postgres databases currently expire after 30 days. This is acceptable for controlled testing but not for a real school production deployment.
