"""Headless demo producing the deliverable: full arc plan + N episodes with scripted HITL
interventions, exported to Markdown. Uses the same graph as the web app.

  python -m scripts.demo_run --premise "A delivery rider realizes..." --episodes 15 \
      --intervene 5:"Slow down the romance between the leads" --intervene 9:"Kill off the landlord"

At each --intervene episode the script pauses for review and APPROVES WITH FEEDBACK, which is compiled
into a directive + rewritten beats; later episodes can be checked against it in the export."""
import argparse
import sys
import time

from langgraph.types import Command

from app.auth import hash_password
from app.db import session_scope
from app.graph.checkpointer import get_graph
from app.main import app  # noqa: F401  (ensures models are registered)
from app.migrate import upgrade_db
from app.models import Story, User
from app.memory import store
from app.services import runner, vector_store


def pending(sid):
    return runner.pending_interrupt(sid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--premise", required=True)
    ap.add_argument("--episodes", type=int, default=15)
    ap.add_argument("--target", type=int, default=200)
    ap.add_argument("--email", default="demo@example.com")
    ap.add_argument("--intervene", action="append", default=[], help='EP:"feedback" (approve + carry-forward)')
    ap.add_argument("--reject", action="append", default=[], help='EP:"note" (reject + rewrite)')
    ap.add_argument("--out", default="demo_output.md")
    a = ap.parse_args()
    fb = {int(x.split(":", 1)[0]): x.split(":", 1)[1].strip('"') for x in a.intervene}
    rj = {int(x.split(":", 1)[0]): x.split(":", 1)[1].strip('"') for x in a.reject}

    upgrade_db()
    vector_store.ensure_collection()
    with session_scope() as s:
        user = s.query(User).filter_by(email=a.email).first() or User(email=a.email, password_hash=hash_password("demo-pass-123"))
        s.add(user)
        s.flush()
        story = Story(user_id=user.id, premise=a.premise, target_episodes=a.target, title=a.premise[:60])
        s.add(story)
        s.flush()
        sid = str(story.id)
        store.add_message(s, sid, "user", "text", a.premise)
    g, cfg = get_graph(), runner.config_for(sid)
    t0 = time.time()
    print(f"story {sid}: planning {a.target} episodes...")
    g.invoke({"story_id": sid, "target_episodes": a.target, "current_episode": 1}, cfg)
    g.invoke(Command(resume={"action": "approve"}), cfg)
    rejected: set[int] = set()
    marks = sorted(set(fb) | set(rj))
    while True:
        p = pending(sid)
        if p is None:
            break
        if p["type"] == "continue":
            n = p["next_episode"]
            if n > a.episodes:
                break
            if n in marks:  # intervention episode: write it alone and stop for review
                g.invoke(Command(resume={"action": "continue", "count": 1, "auto_approve": False}), cfg)
            else:
                stop = min([e for e in marks if e > n] + [a.episodes + 1])
                print(f"-> writing eps {n}-{stop - 1} with auto-approve (critic failures still escalate)")
                g.invoke(Command(resume={"action": "continue", "count": stop - n, "auto_approve": True}), cfg)
        elif p["type"] == "episode_review":
            n = p["episode"]
            if n in rj and n not in rejected:
                rejected.add(n)
                print(f"   ep {n}: REJECT + note: {rj[n]}")
                g.invoke(Command(resume={"action": "reject", "feedback": rj[n]}), cfg)
            elif n in fb:
                print(f"   ep {n}: APPROVE + carry-forward feedback: {fb[n]}")
                g.invoke(Command(resume={"action": "approve", "feedback": fb.pop(n)}), cfg)
            else:
                print(f"   ep {n}: review ({p['reason']}) -> approve")
                g.invoke(Command(resume={"action": "approve"}), cfg)
    print(f"done in {time.time() - t0:.0f}s")
    from fastapi.testclient import TestClient
    from app.auth import create_token
    with session_scope() as s:
        uid = store.get_story(s, sid).user_id
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {create_token(uid)}"}
        open(a.out, "w").write(c.get(f"/stories/{sid}/export", headers=h).text)
        logs = c.get(f"/stories/{sid}/logs", headers=h).json()
    print(f"wrote {a.out}; total ${logs['total_cost_usd']}, projection: {logs['projection']}")

if __name__ == "__main__":
    sys.exit(main())
