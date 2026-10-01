"""End-to-end offline test: plan -> approve -> write with auto-approve -> human review with feedback
-> reject -> resume -> retro edit. Run: OFFLINE_MODE=true DATABASE_URL=sqlite:///./test.db python -m pytest -q"""
import os
import time

os.environ.setdefault("OFFLINE_MODE", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_offline.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def wait(c, sid, h, want=None, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = c.get(f"/stories/{sid}/state", headers=h).json()
        if not st["running"] and (want is None or (st["pending"] or {}).get("type") == want or st["story"]["status"] == want):
            return st
        time.sleep(0.1)
    raise AssertionError(f"timeout waiting for {want}: {st}")


def test_full_flow():
    if os.path.exists("test_offline.db"):
        os.remove("test_offline.db")
    with TestClient(app) as c:
        tok = c.post("/auth/register", json={"email": "a@b.co", "password": "password123"}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        sid = c.post("/stories", json={"premise": "A delivery rider delivers to the dead.", "target_episodes": 30},
                     headers=h).json()["id"]
        wait(c, sid, h, "plan_review")
        plan = c.get(f"/stories/{sid}/plan", headers=h).json()["plan"]
        assert len(plan["beats"]) == 30
        c.post(f"/stories/{sid}/act", json={"action": "approve"}, headers=h)
        wait(c, sid, h, "continue")
        c.post(f"/stories/{sid}/act", json={"action": "continue", "count": 3, "auto_approve": True}, headers=h)
        st = wait(c, sid, h, "continue")
        assert st["story"]["current_episode"] == 4
        # manual review with carry-forward feedback
        c.post(f"/stories/{sid}/act", json={"action": "continue", "count": 1}, headers=h)
        st = wait(c, sid, h, "episode_review")
        c.post(f"/stories/{sid}/act", json={"action": "approve", "feedback": "slow down the romance"}, headers=h)
        wait(c, sid, h, "continue")
        mem = c.get(f"/stories/{sid}/memory", headers=h).json()
        assert mem["directives"], "feedback must persist as a directive"
        # reject path
        c.post(f"/stories/{sid}/act", json={"action": "continue", "count": 1}, headers=h)
        wait(c, sid, h, "episode_review")
        c.post(f"/stories/{sid}/act", json={"action": "reject", "feedback": "make it scarier"}, headers=h)
        wait(c, sid, h, "episode_review")
        c.post(f"/stories/{sid}/act", json={"action": "approve"}, headers=h)
        st = wait(c, sid, h, "continue")
        assert st["story"]["current_episode"] == 6
        # retro edit + rename + export + logs
        c.put(f"/stories/{sid}/episodes/2", json={"content": "Maya never went back to the building. " * 30}, headers=h)
        wait(c, sid, h, "continue")
        assert c.patch(f"/stories/{sid}", json={"title": "Renamed"}, headers=h).json()["title"] == "Renamed"
        assert "Episode 5" in c.get(f"/stories/{sid}/export", headers=h).text
        logs = c.get(f"/stories/{sid}/logs", headers=h).json()
        assert logs["total_cost_usd"] > 0 and logs["projection"]["avg_cost_per_episode"] > 0
        msgs = c.get(f"/stories/{sid}/messages", headers=h).json()
        assert any(m["kind"] == "ripple" for m in msgs)
