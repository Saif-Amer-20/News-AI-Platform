"use client";

import { X, Filter, Save, BookmarkCheck, History, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { api, apiPost } from "@/lib/api";

/* ── Types ─────────────────────────────────────────────────── */
export type FilterDef = {
  key: string;
  label: string;
  type: "select" | "text" | "bool";
  options?: { value: string; label: string }[];
  placeholder?: string;
};

type SavedView = { id: number; name: string; search_type: string; query_params: Record<string, string> };

type RecentContext = { id: string; label: string; params: Record<string, string>; ts: number };

/* ── session storage helpers ──────────────────────────────── */
function getRecentContexts(searchType: string): RecentContext[] {
  try {
    const raw = sessionStorage.getItem(`recent-ctx:${searchType}`);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function pushRecentContext(searchType: string, label: string, params: Record<string, string>) {
  const list = getRecentContexts(searchType);
  const id = JSON.stringify(params);
  const filtered = list.filter((c) => c.id !== id);
  filtered.unshift({ id, label, params, ts: Date.now() });
  try {
    sessionStorage.setItem(`recent-ctx:${searchType}`, JSON.stringify(filtered.slice(0, 8)));
  } catch { /* quota */ }
}

function removeRecentContext(searchType: string, id: string) {
  const list = getRecentContexts(searchType).filter((c) => c.id !== id);
  try {
    sessionStorage.setItem(`recent-ctx:${searchType}`, JSON.stringify(list));
  } catch { /* quota */ }
}

/* ── FilterBar ─────────────────────────────────────────────── */
export function FilterBar({
  filters,
  values,
  onChange,
  searchType,
}: {
  filters: FilterDef[];
  values: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  searchType?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [showSave, setShowSave] = useState(false);
  const [viewName, setViewName] = useState("");
  const [savedViews, setSavedViews] = useState<SavedView[]>([]);
  const [recentContexts, setRecentContexts] = useState<RecentContext[]>([]);

  // Sync filters to URL
  useEffect(() => {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(values)) {
      if (v) params.set(k, v);
    }
    const qs = params.toString();
    const target = qs ? `${pathname}?${qs}` : pathname;
    router.replace(target, { scroll: false });
  }, [values, pathname, router]);

  // Load from URL on mount
  useEffect(() => {
    const fromUrl: Record<string, string> = {};
    let changed = false;
    for (const f of filters) {
      const v = searchParams.get(f.key);
      if (v) { fromUrl[f.key] = v; changed = true; }
    }
    if (changed) onChange({ ...values, ...fromUrl });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load saved views
  useEffect(() => {
    if (!searchType) return;
    api<{ results: SavedView[] }>(`/saved-views/?search_type=${searchType}`)
      .then((d) => setSavedViews(d.results ?? []))
      .catch(() => {});
  }, [searchType]);

  // Load recent contexts from session
  useEffect(() => {
    if (!searchType) return;
    setRecentContexts(getRecentContexts(searchType));
  }, [searchType]);

  // Record active filter snapshot to recent contexts on meaningful filter changes
  useEffect(() => {
    if (!searchType) return;
    const active = Object.entries(values).filter(([, v]) => v);
    if (active.length === 0) return;
    const label = active.map(([k, v]) => `${k}=${v}`).join(", ");
    pushRecentContext(searchType, label, values);
    setRecentContexts(getRecentContexts(searchType));
  }, [values, searchType]);

  const activeCount = Object.values(values).filter(Boolean).length;

  const handleClear = () => {
    const empty: Record<string, string> = {};
    for (const f of filters) empty[f.key] = "";
    onChange(empty);
  };

  const handleSaveView = async () => {
    if (!viewName.trim() || !searchType) return;
    const params: Record<string, string> = {};
    for (const [k, v] of Object.entries(values)) { if (v) params[k] = v; }
    try {
      await apiPost("/saved-views/", {
        name: viewName.trim(),
        search_type: searchType,
        query_params: params,
        is_global: false,
      });
      setShowSave(false);
      setViewName("");
      // Refresh saved views
      const d = await api<{ results: SavedView[] }>(`/saved-views/?search_type=${searchType}`);
      setSavedViews(d.results ?? []);
    } catch { /* empty */ }
  };

  const applySaved = useCallback((v: SavedView) => {
    const next: Record<string, string> = {};
    for (const f of filters) next[f.key] = v.query_params[f.key] ?? "";
    onChange(next);
  }, [filters, onChange]);

  return (
    <div className="filter-bar">
      <div className="filter-bar-row">
        <Filter size={15} className="filter-bar-icon" />
        {filters.map((f) => (
          <FilterControl key={f.key} def={f} value={values[f.key] ?? ""} onChange={(v) => onChange({ ...values, [f.key]: v })} />
        ))}
        {activeCount > 0 && (
          <button className="filter-clear-btn" onClick={handleClear}>
            <X size={13} /> Clear ({activeCount})
          </button>
        )}
        {searchType && (
          <button className="filter-save-btn" onClick={() => setShowSave(!showSave)} title="Save current view">
            <Save size={14} />
          </button>
        )}
      </div>

      {showSave && (
        <div className="filter-save-row">
          <input className="filter-input" placeholder="View name…" value={viewName} onChange={(e) => setViewName(e.target.value)} />
          <button className="action-btn action-btn-primary" onClick={handleSaveView} disabled={!viewName.trim()}>Save View</button>
          <button className="action-btn" onClick={() => setShowSave(false)}>Cancel</button>
        </div>
      )}

      {savedViews.length > 0 && (
        <div className="filter-saved-views">
          <BookmarkCheck size={13} />
          {savedViews.map((v) => {
            const cnt = Object.values(v.query_params).filter(Boolean).length;
            return (
              <button key={v.id} className="saved-view-chip" onClick={() => applySaved(v)} title={Object.entries(v.query_params).filter(([,val]) => val).map(([k,val]) => `${k}: ${val}`).join(", ")}>
                {v.name}
                {cnt > 0 && <span className="saved-view-count">{cnt}</span>}
              </button>
            );
          })}
        </div>
      )}

      {recentContexts.length > 1 && (
        <div className="filter-recent-bar">
          <History size={13} />
          <span className="filter-recent-label">Recent:</span>
          {recentContexts.slice(1, 5).map((c) => (
            <span key={c.id} className="recent-ctx-chip">
              <button className="recent-ctx-btn" onClick={() => onChange(c.params)} title={c.label}>
                {c.label.length > 30 ? c.label.slice(0, 30) + "…" : c.label}
              </button>
              {searchType && (
                <button className="recent-ctx-remove" onClick={() => { removeRecentContext(searchType, c.id); setRecentContexts(getRecentContexts(searchType)); }}><X size={10} /></button>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Individual filter control ─────────────────────────────── */
function FilterControl({ def, value, onChange }: { def: FilterDef; value: string; onChange: (v: string) => void }) {
  if (def.type === "select") {
    return (
      <select className="filter-select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{def.label}</option>
        {def.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  }
  if (def.type === "bool") {
    return (
      <select className="filter-select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{def.label}</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  }
  return (
    <input
      className="filter-input"
      placeholder={def.placeholder ?? def.label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/* ── Active filters summary ────────────────────────────────── */
export function ActiveFiltersSummary({ values, onClear }: { values: Record<string, string>; onClear: (key: string) => void }) {
  const active = Object.entries(values).filter(([, v]) => v);
  if (active.length === 0) return null;
  return (
    <div className="active-filters">
      {active.map(([k, v]) => (
        <span key={k} className="active-filter-chip">
          {k}: <strong>{v}</strong>
          <button onClick={() => onClear(k)}><X size={11} /></button>
        </span>
      ))}
    </div>
  );
}
