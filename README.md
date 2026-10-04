# Content Moderation and Appeals Workbench

A web app where AI helps review user content against a versioned policy, and
**humans make every final decision**. It supports a moderation queue, appeals
with an independent second review, policy changes with re-evaluation, and a
complete audit trail.

**Live demo:** [https://moderation-workbench.onrender.com/ui/queue]

## What it does
- Accepts posts, comments, and user reports.
- Runs **plain-code checks** first: banned phrases, link spam, repeated text, and repeat offenders.
- Runs an **AI review** that cites the exact policy clause and a quote from the content, separates confirmed evidence from uncertain interpretation, proposes an action, and explains severity and confidence.
- Puts every item in a **moderation queue**. A moderator approves, rejects, or modifies the AI's proposal.
- Lets the author **appeal** a warning or removal. A different person does the second review. The page shows the original decision, the appeal evidence, and the final outcome.
- Supports **new policy versions**. Items still waiting for a moderator are re-reviewed under the new version, and old decisions keep the version they were made under.
- Records every action in an **append-only audit trail**.

## The most important rule
The AI only **proposes**. It never removes content and never rejects an appeal.
Only a human action can move an item to "decided" or "final".

## How the AI is kept safe
- The AI may only cite clauses that exist in the active policy. Invented clauses are dropped.
- A "confirmed" finding must quote text that really appears in the content, or it is downgraded to "uncertain".
- Invalid values (action, severity, confidence) are replaced with safe defaults.
- Code, not the AI, decides when a human is required: low confidence, uncertain findings, removal proposals, or a disagreement between the code checks and the AI all force human review.
- User content is placed inside tags and treated as data, so text like "ignore your rules" does not change the AI's behavior.
- If the AI is unavailable or returns bad output, the app saves a safe "escalate to a human" result and keeps working.

## Tech stack
Python, FastAPI, SQLAlchemy with SQLite, Jinja2 server-rendered pages, Groq for the AI model, pytest.

## Architecture
A request flows through three layers:

    Browser or API client
      -> routes (app/routes: validate input, return responses)
      -> services (app/services: checks, AI review, workflow, decisions, appeals, policy, audit)
      -> database (SQLAlchemy models on SQLite)

Item lifecycle, enforced by one table in `services/workflow.py`:

    submitted -> ai_reviewed -> pending_moderator -> decided -> appealed -> second_review -> final

- Plain-code checks run at submission. The AI review is a separate step that validates the AI's output before saving it.
- Only moderator and second-reviewer routes can move an item to `decided` or `final`.
- Pages (`/ui/...`) call the same route functions as the JSON API (`/docs`), so rules live in one place.
- Each action and its audit entry are saved in a single commit.

## Scope
**Completed**
- Posts, comments, user reports, and moderation history
- Deterministic checks combined with AI review, with cited clauses, confirmed vs uncertain evidence, severity, confidence, and a human-needed flag
- Moderation queue with approve, reject, and modify
- Appeals with an independent second review, showing the original decision, appeal evidence, and final outcome
- Versioned policy, with re-evaluation of items waiting for a moderator
- Append-only audit trail

**Excluded (outside the stated scope)**
- Image or video moderation
- Real social-network integration
- Automatic account bans
- Unrestricted user-generated content

**Left out by choice**
- Authentication and roles
- Pagination

## Deployment
Deployed on Render's free web service from this GitHub repo.

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment variables: `AI_API_KEY`, `AI_MODEL` (set in Render, never committed)
- Health check: `/health`
- The free plan sleeps when idle, so the first load can take up to a minute.
- It has no persistent disk, so the SQLite data resets on redeploy. The seed restores policy v1 and the demo items.

## Project structure
```
app/
  main.py          app setup and routes
  config.py        reads settings from .env
  database.py      database connection and sessions
  models.py        all tables
  seed.py          policy v1 and demo content
  services/        checks, ai_review, workflow, decisions, appeals, policy, audit
  routes/          JSON API (content, queue, appeals, policy) and pages
  templates/       HTML pages
tests/             automated tests
```

## Run it locally
```
python -m venv .venv
.venv\Scripts\activate          (Windows)
pip install -r requirements.txt
copy .env.example .env          then put your own key in .env
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000 for the dashboard, or /docs for the JSON API.

Settings in `.env`: `AI_API_KEY`, `AI_MODEL`, `DATABASE_URL`.

## Run the tests
```
pytest -q
```
The tests use a fake AI, so they need no API key and make no network calls.

## Design decisions
- **Deterministic checks and AI work together.** Code finds clear signals, the AI handles context, and code validates what the AI returns.
- **Every review and decision stores the policy version it used**, so any decision can be explained later even after the policy changes.
- **One workflow rule table** controls which status can move to which. Every status change goes through it.
- **The pages call the same functions as the API**, so the rules cannot be bypassed from the screen.
- **Each action and its audit entry are saved in one commit**, so they succeed or fail together.

## Known limits
- No login. Moderator, author, and reviewer names are typed into forms. A real deployment would need authentication and roles.
- Re-evaluation reviews items one at a time inside one request, so it suits a small queue.
- Items already in second review are not re-evaluated after a policy change.
- SQLite on a free host may reset when the app redeploys. The seed restores the demo data.
- Anyone with the link can trigger AI reviews, which uses the API quota.
- No image or video moderation, automatic bans, or real social network connection.
- The free host sleeps when idle, so the first load can take up to a minute.
