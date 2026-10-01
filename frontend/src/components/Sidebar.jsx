import { useState } from "react";
import { useAuth } from "../context/AuthContext.jsx";
import { statusLabel, written } from "./status.js";

// Story list = chat history. Rename inline, delete with confirmation, resume by clicking.
export default function Sidebar({ stories, activeId, open, onClose, onNew, onOpen, onRename, onDelete }) {
  const { user, logout } = useAuth();
  const [editing, setEditing] = useState(null);
  const [confirm, setConfirm] = useState(null);

  return (
    <>
      {open && <div className="scrim" onClick={onClose} />}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand">Serial</div>
        <button className="btn new" onClick={onNew}>New story</button>
        <nav className="story-list" aria-label="Your stories">
          {stories.length === 0 && <p className="empty">Your stories will appear here.</p>}
          {stories.map((s) => (
            <div key={s.id} className={`story-item ${s.id === activeId ? "active" : ""}`}>
              {editing === s.id ? (
                <input className="rename" autoFocus defaultValue={s.title} maxLength={200}
                  onBlur={(e) => { const v = e.target.value.trim(); setEditing(null); if (v && v !== s.title) onRename(s.id, v); }}
                  onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setEditing(null); }} />
              ) : (
                <button className="story-open" onClick={() => onOpen(s.id)}>
                  <span className="story-name">{s.title}</span>
                  <span className="story-sub">{written(s)}/{s.target_episodes} written. {statusLabel(s)}</span>
                </button>
              )}
              <div className="item-actions">
                {confirm === s.id ? (
                  <>
                    <button className="mini danger" onClick={() => { setConfirm(null); onDelete(s.id); }}>Delete</button>
                    <button className="mini" onClick={() => setConfirm(null)}>Keep</button>
                  </>
                ) : (
                  <>
                    <button className="mini" aria-label={`Rename ${s.title}`} onClick={() => setEditing(s.id)}>Rename</button>
                    <button className="mini" aria-label={`Delete ${s.title}`} onClick={() => setConfirm(s.id)}>Delete</button>
                  </>
                )}
              </div>
            </div>
          ))}
        </nav>
        <div className="account">
          <span title={user?.email}>{user?.email}</span>
          <button className="mini" onClick={logout}>Sign out</button>
        </div>
      </aside>
    </>
  );
}
