"use client";

import { useState, useCallback, useMemo } from "react";
import {
  StickyNote, Plus, Tag, Link2, Calendar, Trash2, Filter,
} from "lucide-react";
import type { StructuredNote } from "@/lib/types";
import { NOTE_TYPE_BADGE } from "@/lib/types";

/* ── Persistence ───────────────────────────────────────────── */
function storageKey(caseId: number) { return `snotes_${caseId}`; }
function loadNotes(caseId: number): StructuredNote[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(storageKey(caseId)) || "[]"); } catch { return []; }
}
function saveNotes(caseId: number, d: StructuredNote[]) { localStorage.setItem(storageKey(caseId), JSON.stringify(d)); }
function uid() { return `sn_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`; }

type Props = {
  caseId: number;
  availableEvents: { id: number; title: string }[];
  availableEntities: { id: number; name: string }[];
  onEvolution?: (type: string, title: string, detail?: string) => void;
};

const NOTE_TYPES = ["observation", "assessment", "action_item", "question"] as const;

export function StructuredNotesPanel({ caseId, availableEvents, availableEntities, onEvolution }: Props) {
  const [notes, setNotes] = useState<StructuredNote[]>(() => loadNotes(caseId));
  const [showCreate, setShowCreate] = useState(false);
  const [filterType, setFilterType] = useState<string>("");
  const [filterTag, setFilterTag] = useState<string>("");

  const [form, setForm] = useState({
    text: "", note_type: "observation" as StructuredNote["note_type"],
    tags: "", timeline_date: "",
    linked_events: [] as number[],
    linked_entities: [] as number[],
  });

  const persist = useCallback((list: StructuredNote[]) => {
    setNotes(list);
    saveNotes(caseId, list);
  }, [caseId]);

  /* All tags for filter dropdown */
  const allTags = useMemo(() => {
    const s = new Set<string>();
    notes.forEach((n) => n.tags.forEach((t) => s.add(t)));
    return [...s].sort();
  }, [notes]);

  const filtered = useMemo(() => {
    let list = notes;
    if (filterType) list = list.filter((n) => n.note_type === filterType);
    if (filterTag) list = list.filter((n) => n.tags.includes(filterTag));
    return list;
  }, [notes, filterType, filterTag]);

  const createNote = () => {
    if (!form.text.trim()) return;
    const now = new Date().toISOString();
    const note: StructuredNote = {
      id: uid(), case_id: caseId, text: form.text, note_type: form.note_type,
      tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
      linked_events: form.linked_events,
      linked_entities: form.linked_entities,
      timeline_date: form.timeline_date || undefined,
      created_at: now, updated_at: now,
    };
    persist([note, ...notes]);
    onEvolution?.("note_added", `Note (${form.note_type}): ${form.text.slice(0, 60)}`);
    setForm({ text: "", note_type: "observation", tags: "", timeline_date: "", linked_events: [], linked_entities: [] });
    setShowCreate(false);
  };

  const deleteNote = (id: string) => {
    persist(notes.filter((n) => n.id !== id));
  };

  const toggleLinkedEvent = (eid: number) => {
    setForm((f) => ({
      ...f,
      linked_events: f.linked_events.includes(eid)
        ? f.linked_events.filter((x) => x !== eid)
        : [...f.linked_events, eid],
    }));
  };

  const toggleLinkedEntity = (eid: number) => {
    setForm((f) => ({
      ...f,
      linked_entities: f.linked_entities.includes(eid)
        ? f.linked_entities.filter((x) => x !== eid)
        : [...f.linked_entities, eid],
    }));
  };

  return (
    <div className="structured-notes-panel">
      <div className="structured-notes-header">
        <StickyNote size={16} />
        <h4>Structured Notes</h4>
        <span className="badge badge-blue">{notes.length}</span>
        <button className="action-btn action-btn-sm" onClick={() => setShowCreate(!showCreate)}>
          <Plus size={12} /> New
        </button>
      </div>

      {/* Filters */}
      <div className="structured-notes-filters">
        <Filter size={12} />
        <select className="filter-select" value={filterType} onChange={(e) => setFilterType(e.target.value)}>
          <option value="">All types</option>
          {NOTE_TYPES.map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
        </select>
        <select className="filter-select" value={filterTag} onChange={(e) => setFilterTag(e.target.value)}>
          <option value="">All tags</option>
          {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {showCreate && (
        <div className="structured-note-create-form">
          <textarea className="filter-input" placeholder="Note text…" rows={3} value={form.text}
            onChange={(e) => setForm((f) => ({ ...f, text: e.target.value }))} style={{ width: "100%", resize: "vertical" }} />

          <div className="structured-note-form-row">
            <select className="filter-select" value={form.note_type}
              onChange={(e) => setForm((f) => ({ ...f, note_type: e.target.value as StructuredNote["note_type"] }))}>
              {NOTE_TYPES.map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
            </select>
            <div style={{ position: "relative", flex: 1 }}>
              <Tag size={12} style={{ position: "absolute", left: 8, top: 8, color: "#94a3b8" }} />
              <input className="filter-input" placeholder="Tags (comma-separated)" value={form.tags}
                onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
                style={{ paddingLeft: 28, width: "100%" }} />
            </div>
            <div style={{ position: "relative" }}>
              <Calendar size={12} style={{ position: "absolute", left: 8, top: 8, color: "#94a3b8" }} />
              <input type="date" className="filter-input" value={form.timeline_date}
                onChange={(e) => setForm((f) => ({ ...f, timeline_date: e.target.value }))}
                style={{ paddingLeft: 28 }} />
            </div>
          </div>

          {/* Link events */}
          {availableEvents.length > 0 && (
            <div className="structured-note-links">
              <span className="structured-note-links-label"><Link2 size={11} /> Events:</span>
              <div className="structured-note-link-chips">
                {availableEvents.slice(0, 10).map((ev) => (
                  <button key={ev.id}
                    className={`structured-note-link-chip ${form.linked_events.includes(ev.id) ? "structured-note-link-chip--active" : ""}`}
                    onClick={() => toggleLinkedEvent(ev.id)}>
                    {ev.title.slice(0, 30)}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Link entities */}
          {availableEntities.length > 0 && (
            <div className="structured-note-links">
              <span className="structured-note-links-label"><Link2 size={11} /> Entities:</span>
              <div className="structured-note-link-chips">
                {availableEntities.slice(0, 10).map((en) => (
                  <button key={en.id}
                    className={`structured-note-link-chip ${form.linked_entities.includes(en.id) ? "structured-note-link-chip--active" : ""}`}
                    onClick={() => toggleLinkedEntity(en.id)}>
                    {en.name.slice(0, 25)}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <button className="action-btn action-btn-primary action-btn-sm" onClick={createNote}>Create Note</button>
            <button className="action-btn action-btn-sm" onClick={() => setShowCreate(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Notes list */}
      <div className="structured-notes-list">
        {filtered.length === 0 && <div className="empty-state">No notes yet</div>}
        {filtered.map((note) => (
          <div key={note.id} className="structured-note-card">
            <div className="structured-note-card-header">
              <span className={`badge ${NOTE_TYPE_BADGE[note.note_type] ?? "badge-gray"}`}>
                {note.note_type.replace("_", " ")}
              </span>
              {note.timeline_date && (
                <span className="structured-note-date"><Calendar size={11} /> {note.timeline_date}</span>
              )}
              <span className="structured-note-ts">{new Date(note.created_at).toLocaleString()}</span>
              <button className="evidence-remove" onClick={() => deleteNote(note.id)}><Trash2 size={11} /></button>
            </div>
            <p className="structured-note-text">{note.text}</p>
            {note.tags.length > 0 && (
              <div className="structured-note-tags">
                {note.tags.map((t) => (
                  <span key={t} className="structured-note-tag"><Tag size={9} /> {t}</span>
                ))}
              </div>
            )}
            {(note.linked_events.length > 0 || note.linked_entities.length > 0) && (
              <div className="structured-note-linked">
                {note.linked_events.map((eid) => {
                  const ev = availableEvents.find((e) => e.id === eid);
                  return ev ? (
                    <a key={eid} href={`/events?highlight=${eid}`} className="structured-note-link-ref">
                      <Link2 size={10} /> {ev.title.slice(0, 30)}
                    </a>
                  ) : null;
                })}
                {note.linked_entities.map((eid) => {
                  const en = availableEntities.find((e) => e.id === eid);
                  return en ? (
                    <a key={eid} href={`/entities?highlight=${eid}`} className="structured-note-link-ref">
                      <Link2 size={10} /> {en.name.slice(0, 25)}
                    </a>
                  ) : null;
                })}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
