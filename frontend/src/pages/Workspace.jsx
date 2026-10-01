import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import Sidebar from "../components/Sidebar.jsx";
import StorySpine from "../components/StorySpine.jsx";
import MessageList from "../components/MessageList.jsx";
import PlanReview from "../components/PlanReview.jsx";
import EpisodeReview from "../components/EpisodeReview.jsx";
import ContinueGate from "../components/ContinueGate.jsx";
import Composer from "../components/Composer.jsx";
import MemoryPanel from "../components/MemoryPanel.jsx";
import NewStory from "../components/NewStory.jsx";
import { statusLabel } from "../components/status.js";

export default function Workspace() {
  const { storyId } = useParams();
  const navigate = useNavigate();
  const [stories, setStories] = useState([]);
  const [st, setSt] = useState(null);
  const [messages, setMessages] = useState([]);
  const [plan, setPlan] = useState(null);
  const [panel, setPanel] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [error, setError] = useState("");
  const [editingTitle, setEditingTitle] = useState(false);
  const sig = useRef("");
  const bottom = useRef(null);

  const loadStories = useCallback(() => api.stories().then(setStories).catch((e) => setError(e.message)), []);
  useEffect(() => { loadStories(); }, [loadStories]);

  const refresh = useCallback(async () => {
    if (!storyId) return;
    try {
      const s = await api.state(storyId);
      setSt(s);
      const next = `${s.story.status}|${s.running}|${s.pending?.type}|${s.pending?.episode}|${s.episodes.length}|${s.story.title}`;
      if (next !== sig.current) {
        sig.current = next;
        const [msgs] = await Promise.all([api.messages(storyId), loadStories()]);
        setMessages(msgs);
        api.plan(storyId).then(setPlan).catch(() => setPlan(null));
      }
    } catch (e) {
      setError(e.message);
    }
  }, [storyId, loadStories]);

  useEffect(() => {
    sig.current = "";
    setSt(null); setMessages([]); setPlan(null); setError("");
    refresh();
  }, [storyId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!storyId) return;
    const busy = st?.running || st?.story.status === "planning";
    const t = setInterval(refresh, busy ? 1500 : 6000);
    return () => clearInterval(t);
  }, [storyId, st?.running, st?.story.status, refresh]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages.length, st?.pending?.type]);

  const act = async (body) => {
    setError("");
    try {
      await api.act(storyId, body);
      setSt((s) => (s ? { ...s, running: true, pending: null } : s));
      setTimeout(refresh, 400);
    } catch (e) { setError(e.message); }
  };

  const create = async (premise, target) => {
    const s = await api.createStory(premise, target);
    await loadStories();
    navigate(`/s/${s.id}`);
  };

  const rename = async (id, title) => {
    await api.rename(id, title);
    await loadStories();
    if (id === storyId) refresh();
  };

  const remove = async (id) => {
    await api.remove(id);
    await loadStories();
    if (id === storyId) navigate("/");
  };

  const pending = st?.pending;
  const story = st?.story;

  return (
    <div className={`desk ${panel ? "with-panel" : ""}`}>
      <Sidebar stories={stories} activeId={storyId} open={navOpen} onClose={() => setNavOpen(false)}
        onNew={() => { navigate("/"); setNavOpen(false); }} onOpen={(id) => { navigate(`/s/${id}`); setNavOpen(false); }}
        onRename={rename} onDelete={remove} />
      <main className="page">
        {!storyId ? (
          <>
            <button className="btn ghost nav-toggle" onClick={() => setNavOpen(true)}>Stories</button>
            <NewStory onCreate={create} />
          </>
        ) : !story ? (
          <div className="loading">Loading the story</div>
        ) : (
          <>
            <header className="story-head">
              <button className="btn ghost nav-toggle" onClick={() => setNavOpen(true)}>Stories</button>
              <div className="story-title-wrap">
                {editingTitle ? (
                  <input className="title-input" autoFocus defaultValue={story.title} maxLength={200}
                    onBlur={(e) => { setEditingTitle(false); if (e.target.value.trim() && e.target.value !== story.title) rename(story.id, e.target.value.trim()); }}
                    onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setEditingTitle(false); }} />
                ) : (
                  <h1 className="story-title" onDoubleClick={() => setEditingTitle(true)} title="Double-click to rename">{story.title}</h1>
                )}
                <p className="story-status">
                  <span className={`dot s-${story.status}`} aria-hidden="true" />
                  {st.running ? (st.activity || "Working") : statusLabel(story)}
                  <span className="spend">${story.total_cost_usd.toFixed(3)} spent</span>
                </p>
              </div>
              <div className="head-actions">
                <button className="btn ghost" onClick={() => setEditingTitle(true)}>Rename</button>
                <button className="btn ghost" onClick={async () => {
                  const md = await api.exportMd(storyId);
                  const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
                  Object.assign(document.createElement("a"), { href: url, download: `${story.title}.md` }).click();
                }}>Export</button>
                <button className={`btn ${panel ? "primary" : "ghost"}`} onClick={() => setPanel(!panel)}>Story bible</button>
              </div>
            </header>
            <StorySpine total={story.target_episodes} episodes={st.episodes} current={story.current_episode}
              acts={plan?.plan?.acts || []} pendingEp={pending?.type === "episode_review" ? pending.episode : null} />

            <section className="stream" aria-live="polite">
              <MessageList messages={messages} storyId={storyId} plan={plan} onChanged={refresh}
                canEdit={!st.running} />
              {story.status === "error" && !st.running && (
                <div className="notice error-notice">
                  <p>The run stopped: {story.last_error}</p>
                  <p className="hint">Nothing is lost. Retry picks up from the last saved step.</p>
                  <button className="btn primary" onClick={async () => { await api.retry(storyId); refresh(); }}>Retry</button>
                </div>
              )}
              {st.running && <div className="working"><span className="pulse" />{st.activity || "Working"}</div>}
              {!st.running && pending?.type === "plan_review" && plan && <PlanReview data={plan} onAct={act} />}
              {!st.running && pending?.type === "episode_review" && <EpisodeReview p={pending} onAct={act} />}
              {!st.running && pending?.type === "continue" && <ContinueGate p={pending} onAct={act} />}
              <div ref={bottom} />
            </section>
            {error && <p className="error floating" role="alert" onClick={() => setError("")}>{error}</p>}
            <Composer pending={pending} running={st.running} onAct={act} />
          </>
        )}
      </main>
      {panel && storyId && <MemoryPanel storyId={storyId} onClose={() => setPanel(false)} version={st?.episodes.length} />}
    </div>
  );
}
