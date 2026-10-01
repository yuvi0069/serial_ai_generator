# Serial: an agentic 200-episode story writer with a human in the loop

Give it a one-line premise. It plans a full arc (acts, turning points, characters, dated plot threads, one beat per episode), waits for you to approve the plan, then writes 400-700-word episodes that each end on a hook. Every episode is checked for continuity, repetition and hook strength before you see it. You can approve, edit or reject each one, and feedback like "slow down the romance" or "kill off Theo" changes every episode after it, not just the next one. Stop at episode 12, come back next week, and it resumes exactly where it paused.

- **Backend:** Python, FastAPI, LangGraph, Groq LLMs, Jina embeddings, Qdrant, Supabase Postgres
- **Frontend:** React + Vite. Email/password accounts; each story is a chat in the sidebar you can resume, rename or delete.

| Doc | What's in it |
|---|---|
| [`DECISIONS.md`](DECISIONS.md) | One page: memory at episode 150, where the human steps in, catching inconsistency, what breaks first |
| [`docs/SYSTEM_DESIGN.md`](docs/SYSTEM_DESIGN.md) | Full design, pros/cons with remedies, upgrade path, cost model, how to trace LLM errors |
| [`docs/FOLDER_STRUCTURE.md`](docs/FOLDER_STRUCTURE.md) | Folder tree, request and graph flows, 2-3 lines on every function |

---

## Quick start (about 5 minutes)

You need Python 3.11+, Node 18+, and free accounts on Supabase, Groq, Jina and Qdrant Cloud.

### 1. Database (Supabase)
Create a project, then open **Connect** and copy the **Session pooler** connection string. It uses port **5432**. Don't use the transaction pooler on port 6543: LangGraph's checkpointer needs session semantics. Tables are created automatically on first start (Alembic migrations run at startup; see [Database migrations](#database-migrations)).

### 2. Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # then fill in DATABASE_URL, GROQ_API_KEY, JINA_API_KEY, QDRANT_URL, QDRANT_API_KEY, JWT_SECRET
uvicorn app.main:app --reload
```
Check `http://localhost:8000/health`. Interactive API docs are at `http://localhost:8000/docs`.

To generate a `JWT_SECRET`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

### 3. Frontend
```bash
cd frontend
npm install
cp .env.example .env    # VITE_API_URL=http://localhost:8000
npm run dev
```
Open `http://localhost:5173`, create an account, and enter a premise.

### Try it without any keys
Offline mode swaps in a deterministic fake LLM, hash embeddings, an in-memory vector store and SQLite, so the whole pipeline runs locally.
```bash
cd backend
OFFLINE_MODE=true DATABASE_URL=sqlite:///./test_offline.db python -m pytest -q tests      # end-to-end API test
OFFLINE_MODE=true DATABASE_URL=sqlite:///./local.db uvicorn app.main:app --reload         # clickable UI, fake prose
```

### Database migrations
The app's schema is versioned with Alembic in `backend/alembic/versions/`, and startup runs `alembic upgrade head` for you. LangGraph's checkpoint tables are managed by LangGraph itself and are excluded. After changing `app/models.py`:
```bash
cd backend
alembic revision --autogenerate -m "describe the change"   # review the generated file in alembic/versions/
alembic upgrade head                                       # or just restart the server
alembic check                                              # confirms the DB matches the models
```

---

## Using it

1. **Plan review.** Read the arc and edit any beat inline (or the raw JSON). Approve it, or type what should change and the planner revises it.
2. **Continue gate.** Choose how many episodes to write. Optionally tick "skip my review when the critic passes"; flagged episodes still stop for you.
3. **Episode review.** You see the draft with the critic's hook and beat scores and issues. Approve, edit, or reject it with a note. Anything in the feedback box becomes a standing rule for future episodes and rewrites upcoming beats.
4. **Rewrite an old episode.** Every episode card has "Rewrite this episode". Saving rebuilds that episode's memory (facts, character states, threads) and lists any later episodes that now contradict it.
5. **Story bible** (header button). Shows characters, threads, your standing rules (which you can retire), summaries, and a **Trace** tab with every step, retry, token and dollar, plus the projected cost and time for the rest of the run.
6. **Export.** Downloads Markdown with the full arc plan, every beat, your interventions, and all episodes.

The strip under the title is the **story spine**: one tick per episode, colored by approved, auto-approved, edited or under review, with act boundaries marked.

---

## Producing the deliverable headlessly

This writes the 200-episode arc plan plus 15 episodes, with scripted human interventions, straight to Markdown:
```bash
cd backend
python -m scripts.demo_run \
  --premise "A delivery rider realizes every address on today's route belongs to someone who died in the same building." \
  --target 200 --episodes 15 \
  --intervene 5:"Slow down the romance between the rider and the dispatcher" \
  --reject 8:"Too much exposition; show it through a delivery instead" \
  --intervene 11:"Kill off the building manager within the next two episodes" \
  --out demo_output.md
```
- `--intervene EP:"text"` approves that episode with carry-forward feedback.
- `--reject EP:"note"` rejects it and has it rewritten.

The export records each intervention and which beats it changed.

---

## Cost and time

Default models: writing on `openai/gpt-oss-120b`, checking and memory on `openai/gpt-oss-20b`. Token counts below were measured on these models, reasoning tokens included.

| | Estimate |
|---|---|
| Tokens per episode | ~16k in / ~3.2k out: write, ~1.5 critiques, ~0.5 revisions, extraction, amortized summaries ([breakdown](docs/SYSTEM_DESIGN.md#10-cost-and-time)) |
| Cost per episode | **~$0.004** at $0.15 / $0.75 per M tokens (120b) and $0.10 / $0.50 (20b), from the price table in `services/llm.py`; check Groq's current pricing |
| 200 episodes | **~$0.80-1.00** including ~$0.02 for planning; **$0 on Groq's free tier** |
| Machine time | ~10-15 s per episode unthrottled, so ~35-50 min for 200 |
| Time on the free tier | **~4.5-5 h for 200.** Each model allows 8k tokens/min, and gpt-oss-20b needs ~10.6k per episode, so ~1.3 min per episode. 1k requests/day per model allows ~370 episodes/day. Groq may also apply a daily token cap. |
| Real bottleneck | Free-tier tokens per minute, then human review time |

These are pre-run estimates. The actual per-story numbers are measured from the logs and shown in Story bible → Trace. The time projection there includes time spent waiting on rate limits.

**Built-in bounds** (all in `.env`):

| Setting | Default | Effect |
|---|---|---|
| `MAX_REVISIONS` | 2 | Rewrite attempts before an episode is escalated to you |
| `MAX_EPISODE_COST_USD` | 0.05 | Spend per episode before it is escalated to you (~12x the typical episode, so `MAX_REVISIONS` usually stops first) |
| `MAX_STORY_COST_USD` | 5 | Story total that pauses the run at the next gate; you can override it |
| `LLM_MAX_ATTEMPTS` | 6 | Attempts per LLM call, waiting as long as Groq's rate-limit message asks |
| `MAX_RATE_LIMIT_WAIT_S` | 90 | A longer wait (a daily quota) stops the run with a "Retry after N min" message instead of blocking |

On the free tier the dollar caps act as token budgets, because the cost is estimated, not billed.

**Ways to cut cost and time** (on the free tier, every token saved is also time saved):
- **Stop forced revisions.** Measured drafts run 748-757 words against a 700 cap. That fails the word-count check and triggers a rewrite (~6k tokens on 120b, ~35% of episode cost). Ask the writer for 500-600 words, or widen the check's slack.
- **Skip the LLM critic in auto-approve batches when the deterministic checks are clean**, and spot-check 1 in 5. Critiques are ~80% of gpt-oss-20b's tokens, so this alone cuts free-tier time to ~1.1 min per episode.
- **Move the writer to `openai/gpt-oss-20b`.** This cuts cost ~30%, with some loss in prose quality.
- **Cache the static prompt prefix** (series bible + directives) where the provider supports prompt caching.
- **Use tighter retrieval caps** (top 5 instead of 8) and **batch extraction** for auto-approved runs.

---

## Deploying

- **Backend** runs on Render, Railway or Fly.io.
  - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
  - Copy every `.env` variable into the host's settings.
  - Set `CORS_ORIGINS` to your frontend URL.
  - Run **one instance**: the job runner is in-process, and the design doc explains how to move to a queue.
- **Frontend** runs on Vercel or Netlify.
  - Build command: `npm run build`; output directory: `dist`.
  - Set `VITE_API_URL` to the backend URL.
  - Add a rewrite from `/*` to `/index.html` so `/s/:id` links work.
- **Spending cap:** set one in the Groq console for any public deployment.

---

## Security notes

- Never commit `backend/.env`; it is in `.gitignore`.
- **Rotate any API key that has been shared in chat, email or a commit.**
- Passwords are bcrypt-hashed and sessions are JWTs. Every story endpoint checks ownership, and someone else's story returns 404.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `prepared statement ... already exists` or checkpointer errors | You're on the 6543 pooler. Switch to the Session pooler URI (port 5432). |
| Story shows "Stopped by an error" | Open Story bible → Trace for the failing step (errors are in red), fix the cause (often a rate limit or a model id), then press **Retry**. It resumes from the last checkpoint. |
| `model_not_found` (404) from Groq | Groq retired that model id. List the ones your key can use (`GET https://api.groq.com/openai/v1/models`), set the `*_MODEL` variables in `.env`, restart, then press **Retry**. |
| 429s from Groq | Free-tier limit. Write smaller batches, move the critic and extractor to 8B, or wait for the daily reset. |
| "Can't reach the server" in the UI | The backend isn't running, or `VITE_API_URL` / `CORS_ORIGINS` don't match. |
