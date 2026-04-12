"use client";

import { useState, useCallback } from "react";
import {
  GitBranch, Plus, Trash2, ArrowRight, Circle,
} from "lucide-react";
import type { ReasoningChain, ReasoningNode, ReasoningNodeType, ReasoningEdge } from "@/lib/types";

/* ── Persistence ───────────────────────────────────────────── */
function storageKey(caseId: number) { return `rc_${caseId}`; }
function loadChains(caseId: number): ReasoningChain[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(storageKey(caseId)) || "[]"); } catch { return []; }
}
function saveChains(caseId: number, data: ReasoningChain[]) { localStorage.setItem(storageKey(caseId), JSON.stringify(data)); }
function uid() { return `n_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`; }

const NODE_COLORS: Record<ReasoningNodeType, string> = {
  event: "#2563eb", entity: "#7c3aed", narrative: "#d97706",
  hypothesis: "#059669", conclusion: "#dc2626",
};

type Props = {
  caseId: number;
  onEvolution?: (type: string, title: string, detail?: string) => void;
};

/* ── Chain Graph (SVG) ─────────────────────────────────────── */
function ChainGraph({ chain }: { chain: ReasoningChain }) {
  const nodes = chain.nodes;
  const edges = chain.edges;
  if (nodes.length === 0) return <div className="empty-state">Add nodes to build the chain</div>;

  const colW = 160, rowH = 60, padX = 20, padY = 20;
  /* Simple left→right layout: group by depth via topological ordering */
  const depths: Record<string, number> = {};
  const roots = new Set(nodes.map((n) => n.id));
  edges.forEach((e) => roots.delete(e.to));
  const queue = [...roots];
  queue.forEach((id) => { depths[id] = 0; });
  // BFS
  const visited = new Set<string>();
  while (queue.length) {
    const cur = queue.shift()!;
    if (visited.has(cur)) continue;
    visited.add(cur);
    edges.filter((e) => e.from === cur).forEach((e) => {
      depths[e.to] = Math.max(depths[e.to] ?? 0, (depths[cur] ?? 0) + 1);
      queue.push(e.to);
    });
  }
  // assign unvisited nodes
  nodes.forEach((n) => { if (!(n.id in depths)) depths[n.id] = 0; });

  const maxDepth = Math.max(0, ...Object.values(depths));
  const cols: Record<number, string[]> = {};
  nodes.forEach((n) => {
    const d = depths[n.id] ?? 0;
    if (!cols[d]) cols[d] = [];
    cols[d].push(n.id);
  });

  const pos: Record<string, { x: number; y: number }> = {};
  for (let d = 0; d <= maxDepth; d++) {
    (cols[d] ?? []).forEach((id, i) => {
      pos[id] = { x: padX + d * colW, y: padY + i * rowH };
    });
  }

  const svgW = padX * 2 + (maxDepth + 1) * colW;
  const maxRows = Math.max(1, ...Object.values(cols).map((c) => c.length));
  const svgH = padY * 2 + maxRows * rowH;

  return (
    <svg width="100%" viewBox={`0 0 ${svgW} ${svgH}`} className="reasoning-chain-svg">
      <defs>
        <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill="#94a3b8" />
        </marker>
      </defs>
      {/* edges */}
      {edges.map((e, i) => {
        const from = pos[e.from]; const to = pos[e.to];
        if (!from || !to) return null;
        return (
          <g key={i}>
            <line x1={from.x + 70} y1={from.y + 16} x2={to.x - 4} y2={to.y + 16}
              stroke="#94a3b8" strokeWidth="1.5" markerEnd="url(#arrowhead)" />
            <text x={(from.x + 70 + to.x) / 2} y={(from.y + to.y) / 2 + 10}
              fontSize="9" fill="#94a3b8" textAnchor="middle">{e.relation}</text>
          </g>
        );
      })}
      {/* nodes */}
      {nodes.map((n) => {
        const p = pos[n.id];
        if (!p) return null;
        const color = NODE_COLORS[n.type];
        return (
          <g key={n.id}>
            <rect x={p.x} y={p.y} width={140} height={32} rx={6}
              fill={color + "18"} stroke={color} strokeWidth="1.5" />
            <circle cx={p.x + 12} cy={p.y + 16} r={5} fill={color} />
            <text x={p.x + 22} y={p.y + 20} fontSize="10" fill="#0f172a" fontWeight="500">
              {n.label.length > 16 ? n.label.slice(0, 15) + "…" : n.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ── Main Component ────────────────────────────────────────── */
export function ReasoningChainPanel({ caseId, onEvolution }: Props) {
  const [chains, setChains] = useState<ReasoningChain[]>(() => loadChains(caseId));
  const [selectedChainId, setSelectedChainId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");

  /* node form */
  const [nodeLabel, setNodeLabel] = useState("");
  const [nodeType, setNodeType] = useState<ReasoningNodeType>("event");
  const [nodeDetail, setNodeDetail] = useState("");
  /* edge form */
  const [edgeFrom, setEdgeFrom] = useState("");
  const [edgeTo, setEdgeTo] = useState("");
  const [edgeRelation, setEdgeRelation] = useState("leads_to");
  /* conclusion */
  const [conclusionText, setConclusionText] = useState("");

  const persist = useCallback((list: ReasoningChain[]) => {
    setChains(list);
    saveChains(caseId, list);
  }, [caseId]);

  const selectedChain = chains.find((c) => c.id === selectedChainId) ?? null;

  const createChain = () => {
    if (!newTitle.trim()) return;
    const now = new Date().toISOString();
    const c: ReasoningChain = { id: uid(), case_id: caseId, title: newTitle, nodes: [], edges: [], created_at: now, updated_at: now };
    persist([c, ...chains]);
    setSelectedChainId(c.id);
    setNewTitle("");
    setShowCreate(false);
    onEvolution?.("chain_created", `Reasoning chain: ${c.title}`);
  };

  const addNode = () => {
    if (!selectedChainId || !nodeLabel.trim()) return;
    const n: ReasoningNode = { id: uid(), type: nodeType, label: nodeLabel, detail: nodeDetail || undefined };
    persist(chains.map((c) => {
      if (c.id !== selectedChainId) return c;
      return { ...c, nodes: [...c.nodes, n], updated_at: new Date().toISOString() };
    }));
    setNodeLabel(""); setNodeDetail("");
  };

  const addEdge = () => {
    if (!selectedChainId || !edgeFrom || !edgeTo || edgeFrom === edgeTo) return;
    const e: ReasoningEdge = { from: edgeFrom, to: edgeTo, relation: edgeRelation };
    persist(chains.map((c) => {
      if (c.id !== selectedChainId) return c;
      return { ...c, edges: [...c.edges, e], updated_at: new Date().toISOString() };
    }));
    setEdgeFrom(""); setEdgeTo("");
  };

  const setConclusion = () => {
    if (!selectedChainId) return;
    persist(chains.map((c) => {
      if (c.id !== selectedChainId) return c;
      return { ...c, conclusion: conclusionText, updated_at: new Date().toISOString() };
    }));
  };

  const removeNode = (nodeId: string) => {
    if (!selectedChainId) return;
    persist(chains.map((c) => {
      if (c.id !== selectedChainId) return c;
      return {
        ...c,
        nodes: c.nodes.filter((n) => n.id !== nodeId),
        edges: c.edges.filter((e) => e.from !== nodeId && e.to !== nodeId),
        updated_at: new Date().toISOString(),
      };
    }));
  };

  const deleteChain = (id: string) => {
    persist(chains.filter((c) => c.id !== id));
    if (selectedChainId === id) setSelectedChainId(null);
  };

  return (
    <div className="reasoning-panel">
      <div className="reasoning-header">
        <GitBranch size={16} />
        <h4>Reasoning Chains</h4>
        <span className="badge badge-purple">{chains.length}</span>
        <button className="action-btn action-btn-sm" onClick={() => setShowCreate(!showCreate)}>
          <Plus size={12} /> New
        </button>
      </div>

      {showCreate && (
        <div className="reasoning-create-form">
          <input className="filter-input" placeholder="Chain title" value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)} />
          <div style={{ display: "flex", gap: 6 }}>
            <button className="action-btn action-btn-primary action-btn-sm" onClick={createChain}>Create</button>
            <button className="action-btn action-btn-sm" onClick={() => setShowCreate(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Chain selector */}
      <div className="reasoning-chain-list">
        {chains.map((c) => (
          <button key={c.id}
            className={`reasoning-chain-chip ${selectedChainId === c.id ? "reasoning-chain-chip--active" : ""}`}
            onClick={() => setSelectedChainId(c.id)}>
            <GitBranch size={12} /> {c.title}
            <span className="badge badge-gray" style={{ fontSize: "0.6rem" }}>{c.nodes.length}n</span>
            <button className="evidence-remove" onClick={(e) => { e.stopPropagation(); deleteChain(c.id); }} title="Delete">
              <Trash2 size={10} />
            </button>
          </button>
        ))}
      </div>

      {selectedChain && (
        <div className="reasoning-chain-detail">
          {/* Graph */}
          <div className="reasoning-graph-container">
            <ChainGraph chain={selectedChain} />
          </div>

          {/* Conclusion */}
          {selectedChain.conclusion && (
            <div className="reasoning-conclusion">
              <strong>Conclusion:</strong> {selectedChain.conclusion}
            </div>
          )}

          {/* Add node */}
          <div className="reasoning-form-row">
            <select className="filter-select" value={nodeType}
              onChange={(e) => setNodeType(e.target.value as ReasoningNodeType)}>
              <option value="event">Event</option>
              <option value="entity">Entity</option>
              <option value="narrative">Narrative</option>
              <option value="hypothesis">Hypothesis</option>
              <option value="conclusion">Conclusion</option>
            </select>
            <input className="filter-input" placeholder="Node label" value={nodeLabel}
              onChange={(e) => setNodeLabel(e.target.value)} style={{ flex: 1 }} />
            <button className="action-btn action-btn-sm action-btn-primary" onClick={addNode}>
              <Plus size={11} /> Node
            </button>
          </div>

          {/* Add edge */}
          {selectedChain.nodes.length >= 2 && (
            <div className="reasoning-form-row">
              <select className="filter-select" value={edgeFrom} onChange={(e) => setEdgeFrom(e.target.value)}>
                <option value="">From…</option>
                {selectedChain.nodes.map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
              </select>
              <ArrowRight size={14} style={{ flexShrink: 0, color: "#94a3b8" }} />
              <select className="filter-select" value={edgeTo} onChange={(e) => setEdgeTo(e.target.value)}>
                <option value="">To…</option>
                {selectedChain.nodes.map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
              </select>
              <select className="filter-select" value={edgeRelation} onChange={(e) => setEdgeRelation(e.target.value)}>
                <option value="leads_to">leads to</option>
                <option value="supports">supports</option>
                <option value="contradicts">contradicts</option>
                <option value="involves">involves</option>
              </select>
              <button className="action-btn action-btn-sm action-btn-primary" onClick={addEdge}>
                <Plus size={11} /> Edge
              </button>
            </div>
          )}

          {/* Set conclusion */}
          <div className="reasoning-form-row">
            <input className="filter-input" placeholder="Chain conclusion…" value={conclusionText}
              onChange={(e) => setConclusionText(e.target.value)} style={{ flex: 1 }} />
            <button className="action-btn action-btn-sm" onClick={setConclusion}>Set Conclusion</button>
          </div>

          {/* Node list for removal */}
          <div className="reasoning-node-list">
            {selectedChain.nodes.map((n) => (
              <div key={n.id} className="reasoning-node-chip">
                <Circle size={8} fill={NODE_COLORS[n.type]} stroke="none" />
                <span>{n.label}</span>
                <span className="badge badge-gray" style={{ fontSize: "0.6rem" }}>{n.type}</span>
                <button className="evidence-remove" onClick={() => removeNode(n.id)}><Trash2 size={10} /></button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
