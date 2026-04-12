"use client";

import { useEffect, useState } from "react";
import { X, FolderOpen, Plus, Check } from "lucide-react";
import { api, apiPost } from "@/lib/api";

type AttachType = "event" | "alert" | "entity" | "article";

type Props = {
  objectType: AttachType;
  objectId: number;
  objectTitle: string;
  onClose: () => void;
  onSuccess?: () => void;
};

type CaseOption = { id: number; title: string; status: string; priority: string };

export function AttachToCaseModal({ objectType, objectId, objectTitle, onClose, onSuccess }: Props) {
  const [cases, setCases] = useState<CaseOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<"attach" | "create">("attach");
  const [selectedCase, setSelectedCase] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [search, setSearch] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create-case fields
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newPriority, setNewPriority] = useState("medium");

  useEffect(() => {
    api<{ results: CaseOption[] }>("/cases/?ordering=-updated_at&page_size=50")
      .then((d) => setCases(d.results ?? []))
      .catch(() => setCases([]))
      .finally(() => setLoading(false));
  }, []);

  const filtered = cases.filter((c) =>
    c.title.toLowerCase().includes(search.toLowerCase())
  );

  const handleAttach = async (caseId: number) => {
    setSubmitting(true);
    setError(null);
    try {
      const endpoint = getAttachEndpoint(objectType, objectId, caseId);
      const body = getAttachBody(objectType, objectId, caseId, notes);
      await apiPost(endpoint, body);
      setDone(true);
      setTimeout(() => { onSuccess?.(); onClose(); }, 800);
    } catch {
      setError("Failed to attach. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreate = async () => {
    if (!newTitle.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await apiPost<{ id: number }>("/cases/", {
        title: newTitle,
        description: newDesc,
        priority: newPriority,
      });
      await handleAttach(created.id);
    } catch {
      setError("Failed to create case.");
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="modal-overlay" onClick={onClose} />
      <div className="modal">
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <FolderOpen size={18} />
            <span className="modal-title">{mode === "attach" ? "Attach to Case" : "Create New Case"}</span>
          </div>
          <button className="close-btn" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="modal-context">
          <span className="badge badge-blue">{objectType}</span>
          <span style={{ fontSize: "0.88rem", fontWeight: 500 }}>{objectTitle}</span>
        </div>

        {done ? (
          <div className="modal-body" style={{ textAlign: "center", padding: "2rem" }}>
            <Check size={32} color="#16a34a" />
            <p style={{ marginTop: 8, color: "#16a34a", fontWeight: 600 }}>Attached successfully</p>
          </div>
        ) : (
          <>
            <div className="modal-tabs">
              <button
                className={`modal-tab ${mode === "attach" ? "modal-tab--active" : ""}`}
                onClick={() => setMode("attach")}
              >
                Existing Case
              </button>
              <button
                className={`modal-tab ${mode === "create" ? "modal-tab--active" : ""}`}
                onClick={() => setMode("create")}
              >
                <Plus size={14} /> New Case
              </button>
            </div>

            <div className="modal-body">
              {error && <div className="modal-error">{error}</div>}

              {mode === "attach" ? (
                <>
                  <input
                    className="filter-input"
                    style={{ width: "100%", marginBottom: "0.75rem" }}
                    placeholder="Search cases…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                  {loading ? (
                    <div className="loading-state" style={{ padding: "1.5rem" }}>
                      <div className="loading-spinner" /> Loading cases…
                    </div>
                  ) : filtered.length === 0 ? (
                    <div className="empty-state" style={{ padding: "1.5rem" }}>No cases found</div>
                  ) : (
                    <div className="case-list-modal">
                      {filtered.map((c) => (
                        <div
                          key={c.id}
                          className={`case-option ${selectedCase === c.id ? "case-option--selected" : ""}`}
                          onClick={() => setSelectedCase(c.id)}
                        >
                          <span className="case-option-title">{c.title}</span>
                          <div style={{ display: "flex", gap: 4 }}>
                            <span className={`badge ${c.status === "open" ? "badge-blue" : "badge-gray"}`}>{c.status}</span>
                            <span className={`badge ${c.priority === "critical" ? "badge-red" : c.priority === "high" ? "badge-amber" : "badge-gray"}`}>{c.priority}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  <textarea
                    className="filter-input"
                    style={{ width: "100%", marginTop: "0.75rem", resize: "vertical" }}
                    placeholder="Optional note…"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    rows={2}
                  />
                  <div className="modal-footer">
                    <button className="action-btn" onClick={onClose}>Cancel</button>
                    <button
                      className="action-btn action-btn-primary"
                      disabled={!selectedCase || submitting}
                      onClick={() => selectedCase && handleAttach(selectedCase)}
                    >
                      {submitting ? "Attaching…" : "Attach"}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <input
                    className="filter-input"
                    style={{ width: "100%", marginBottom: 8 }}
                    placeholder="Case title"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                  />
                  <textarea
                    className="filter-input"
                    style={{ width: "100%", marginBottom: 8, resize: "vertical" }}
                    placeholder="Description"
                    value={newDesc}
                    onChange={(e) => setNewDesc(e.target.value)}
                    rows={3}
                  />
                  <select
                    className="filter-select"
                    style={{ marginBottom: 8 }}
                    value={newPriority}
                    onChange={(e) => setNewPriority(e.target.value)}
                  >
                    <option value="low">Low Priority</option>
                    <option value="medium">Medium Priority</option>
                    <option value="high">High Priority</option>
                    <option value="critical">Critical Priority</option>
                  </select>
                  <textarea
                    className="filter-input"
                    style={{ width: "100%", marginTop: 4, resize: "vertical" }}
                    placeholder="Optional note…"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    rows={2}
                  />
                  <div className="modal-footer">
                    <button className="action-btn" onClick={onClose}>Cancel</button>
                    <button
                      className="action-btn action-btn-primary"
                      disabled={!newTitle.trim() || submitting}
                      onClick={handleCreate}
                    >
                      {submitting ? "Creating…" : "Create & Attach"}
                    </button>
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}

/* ── Helpers to route attach calls to the right endpoint ───── */
function getAttachEndpoint(type: AttachType, objectId: number, caseId: number): string {
  switch (type) {
    case "event": return `/events/${objectId}/attach-case/`;
    case "alert": return `/alerts/${objectId}/attach-case/`;
    case "entity": return `/entities/${objectId}/attach-case/`;
    case "article": return `/cases/${caseId}/add-article/`;
  }
}

function getAttachBody(type: AttachType, objectId: number, caseId: number, notes: string): Record<string, unknown> {
  switch (type) {
    case "event": return { case_id: caseId, notes };
    case "alert": return { case_id: caseId };
    case "entity": return { case_id: caseId, notes };
    case "article": return { article_id: objectId, notes };
  }
}
