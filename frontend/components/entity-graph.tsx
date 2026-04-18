"use client";

/**
 * EntityGraph — pure SVG force-directed graph component.
 *
 * No external library needed.  Uses a simple Fruchterman-Reingold-inspired
 * spring simulation running in useEffect.
 *
 * Props:
 *   nodes   — array of { id, label, type, influence, growth_flag, is_root? }
 *   edges   — array of { source, target, type, strength, co_occurrences }
 *   width / height — canvas size (defaults to 700×500)
 *   onNodeClick — optional callback when a node is clicked
 */

import { useEffect, useRef, useState, useCallback } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

export type GraphNode = {
  id: number;
  label: string;
  type: string;        // PERSON | LOCATION | ORGANIZATION
  influence?: number;  // 0–1
  mentions_7d?: number;
  growth_flag?: boolean;
  is_root?: boolean;
  country?: string;
};

export type GraphEdge = {
  source: number;
  target: number;
  type: string;        // political | military | economic | diplomatic | conflict | unknown
  strength: number;    // 0–1
  co_occurrences?: number;
  last_seen_at?: string;
};

type SimNode = GraphNode & { x: number; y: number; vx: number; vy: number };

// ── Colour maps ───────────────────────────────────────────────────────────────

const NODE_COLORS: Record<string, string> = {
  PERSON:       "#6366f1",  // indigo
  LOCATION:     "#10b981",  // emerald
  ORGANIZATION: "#f59e0b",  // amber
  default:      "#94a3b8",
};

const EDGE_COLORS: Record<string, string> = {
  political:   "#3b82f6",
  military:    "#ef4444",
  economic:    "#10b981",
  diplomatic:  "#8b5cf6",
  conflict:    "#f97316",
  social:      "#06b6d4",
  unknown:     "#64748b",
};

function nodeColor(type: string): string {
  return NODE_COLORS[type] ?? NODE_COLORS.default;
}

function edgeColor(type: string): string {
  return EDGE_COLORS[type] ?? EDGE_COLORS.unknown;
}

// ── Force simulation ──────────────────────────────────────────────────────────

const REPULSION  = 3500;
const ATTRACTION = 0.04;
const DAMPING    = 0.82;
const ITERATIONS = 200;
const CENTER_PULL = 0.015;

function runSimulation(
  nodes: SimNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
): void {
  const n = nodes.length;
  if (n === 0) return;

  const cx = width / 2;
  const cy = height / 2;

  // Build adjacency map: node id → neighbour node indices
  const idToIdx = new Map<number, number>(nodes.map((nd, i) => [nd.id, i]));

  for (let iter = 0; iter < ITERATIONS; iter++) {
    // Repulsion between every pair
    for (let i = 0; i < n - 1; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = nodes[j].x - nodes[i].x;
        const dy = nodes[j].y - nodes[i].y;
        const dist2 = dx * dx + dy * dy + 1;
        const dist  = Math.sqrt(dist2);
        const force = REPULSION / dist2;
        const fx    = (dx / dist) * force;
        const fy    = (dy / dist) * force;
        nodes[i].vx -= fx;
        nodes[i].vy -= fy;
        nodes[j].vx += fx;
        nodes[j].vy += fy;
      }
    }

    // Attraction along edges
    for (const edge of edges) {
      const ai = idToIdx.get(edge.source);
      const bi = idToIdx.get(edge.target);
      if (ai === undefined || bi === undefined) continue;
      const na = nodes[ai];
      const nb = nodes[bi];
      const dx = nb.x - na.x;
      const dy = nb.y - na.y;
      const dist = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const strength = edge.strength ?? 0.1;
      const force = ATTRACTION * dist * (0.5 + strength);
      na.vx += (dx / dist) * force;
      na.vy += (dy / dist) * force;
      nb.vx -= (dx / dist) * force;
      nb.vy -= (dy / dist) * force;
    }

    // Weak pull toward centre
    for (const nd of nodes) {
      if (nd.is_root) continue; // root is pinned later
      nd.vx += (cx - nd.x) * CENTER_PULL;
      nd.vy += (cy - nd.y) * CENTER_PULL;
    }

    // Integrate
    for (const nd of nodes) {
      nd.vx *= DAMPING;
      nd.vy *= DAMPING;
      nd.x  += nd.vx;
      nd.y  += nd.vy;
      // Clamp to canvas
      nd.x = Math.max(32, Math.min(width  - 32, nd.x));
      nd.y = Math.max(24, Math.min(height - 24, nd.y));
    }
  }

  // Pin root node at centre
  const root = nodes.find((nd) => nd.is_root);
  if (root) { root.x = cx; root.y = cy; }
}

// ── Component ─────────────────────────────────────────────────────────────────

interface EntityGraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width?: number;
  height?: number;
  onNodeClick?: (node: GraphNode) => void;
}

export function EntityGraph({
  nodes,
  edges,
  width = 700,
  height = 500,
  onNodeClick,
}: EntityGraphProps) {
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [tooltip, setTooltip] = useState<{ node: SimNode; x: number; y: number } | null>(null);
  const [dragging, setDragging] = useState<{ id: number; offsetX: number; offsetY: number } | null>(null);
  const [didDrag, setDidDrag] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(width);

  // (Re)run simulation whenever nodes/edges change
  useEffect(() => {
    if (nodes.length === 0) { setSimNodes([]); return; }

    const simW = containerWidth || width;
    const cx = simW / 2;
    const cy = height / 2;

    // Scatter randomly around centre, pull root to centre immediately
    const sim: SimNode[] = nodes.map((nd, i) => {
      const angle = (2 * Math.PI * i) / nodes.length;
      const radius = 60 + Math.random() * 120;
      return {
        ...nd,
        x: nd.is_root ? cx : cx + Math.cos(angle) * radius,
        y: nd.is_root ? cy : cy + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
      };
    });

    runSimulation(sim, edges, simW, height);
    setSimNodes(sim);
  }, [nodes, edges, containerWidth, height]);

  // Measure container width for responsive SVG
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    ro.observe(el);
    setContainerWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  // ── Drag support ─────────────────────────────────────────────────────────

  const onMouseDown = useCallback((e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const nd = simNodes.find((n) => n.id === id);
    if (!nd) return;
    setDidDrag(false);
    setDragging({ id, offsetX: e.clientX - rect.left - nd.x, offsetY: e.clientY - rect.top - nd.y });
  }, [simNodes]);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging) return;
    setDidDrag(true);
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const x = e.clientX - rect.left - dragging.offsetX;
    const y = e.clientY - rect.top  - dragging.offsetY;
    setSimNodes((prev) =>
      prev.map((nd) =>
        nd.id === dragging.id ? { ...nd, x, y, vx: 0, vy: 0 } : nd
      )
    );
  }, [dragging]);

  const onMouseUp = useCallback(() => { setDragging(null); }, []);

  // ── Look-up helpers ───────────────────────────────────────────────────────

  const nodeMap = new Map<number, SimNode>(simNodes.map((nd) => [nd.id, nd]));

  const nodeRadius = (nd: SimNode): number =>
    nd.is_root ? 18
    : 9 + Math.round((nd.influence ?? 0) * 9);

  if (nodes.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: "2rem", color: "#64748b", fontSize: "0.85rem" }}>
        No relationship data yet. Run the entity relationship scoring task first.
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ position: "relative", userSelect: "none", width: "100%" }}>
      {/* Legend */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 8, fontSize: "0.72rem", color: "#94a3b8" }}>
        {Object.entries(NODE_COLORS).filter(([k]) => k !== "default").map(([type, color]) => (
          <span key={type} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%", background: color }} />
            {type}
          </span>
        ))}
        <span style={{ marginLeft: 8 }}>─</span>
        {Object.entries(EDGE_COLORS).filter(([k]) => k !== "default").map(([type, color]) => (
          <span key={type} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ display: "inline-block", width: 20, height: 3, background: color, borderRadius: 2 }} />
            {type}
          </span>
        ))}
      </div>

      <svg
        ref={svgRef}
        width={containerWidth}
        height={height}
        viewBox={`0 0 ${containerWidth} ${height}`}
        style={{ borderRadius: 8, cursor: dragging ? "grabbing" : "default", display: "block", width: "100%" }}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
      >
        {/* Edges */}
        <g>
          {edges.map((edge, i) => {
            const a = nodeMap.get(edge.source);
            const b = nodeMap.get(edge.target);
            if (!a || !b) return null;
            const color  = edgeColor(edge.type);
            const stroke = Math.max(0.5, edge.strength * 4);
            return (
              <line
                key={i}
                x1={a.x} y1={a.y}
                x2={b.x} y2={b.y}
                stroke={color}
                strokeWidth={stroke}
                strokeOpacity={0.55}
              />
            );
          })}
        </g>

        {/* Nodes */}
        <g>
          {simNodes.map((nd) => {
            const r     = nodeRadius(nd);
            const color = nodeColor(nd.type);
            return (
              <g
                key={nd.id}
                transform={`translate(${nd.x},${nd.y})`}
                style={{ cursor: "pointer" }}
                onMouseDown={(e) => onMouseDown(e, nd.id)}
                onDoubleClick={() => onNodeClick?.(nd)}
                onMouseEnter={(e) => {
                  const svg = svgRef.current;
                  if (!svg) return;
                  const rect = svg.getBoundingClientRect();
                  setTooltip({ node: nd, x: nd.x + 14, y: nd.y - 10 });
                }}
                onMouseLeave={() => !dragging && setTooltip(null)}
              >
                {/* Growth ring */}
                {nd.growth_flag && (
                  <circle r={r + 5} fill="none" stroke="#fbbf24" strokeWidth={2} strokeDasharray="4 2" />
                )}
                {/* Root ring */}
                {nd.is_root && (
                  <circle r={r + 4} fill="none" stroke={color} strokeWidth={2} opacity={0.6} />
                )}
                <circle r={r} fill={color} fillOpacity={0.9} />
                <text
                  textAnchor="middle"
                  dy={r + 12}
                  fontSize={11}
                  fill="#334155"
                  style={{ pointerEvents: "none" }}
                >
                  {nd.label.length > 18 ? nd.label.slice(0, 16) + "…" : nd.label}
                </text>
              </g>
            );
          })}
        </g>

        {/* Tooltip */}
        {tooltip && (
          <g transform={`translate(${Math.min(tooltip.x, width - 150)},${Math.max(tooltip.y - 10, 0)})`} style={{ pointerEvents: "none" }}>
            <rect
              x={0} y={0}
              width={148} height={nd_tooltip_height(tooltip.node)}
              rx={6} ry={6}
              fill="#fff"
              stroke="#e2e8f0"
              strokeWidth={1}
            />
            <text x={8} y={16} fontSize={11} fill="#0f172a" fontWeight={600}>{tooltip.node.label}</text>
            <text x={8} y={30} fontSize={10} fill="#64748b">{tooltip.node.type} {tooltip.node.country ? `· ${tooltip.node.country}` : ""}</text>
            {(tooltip.node.mentions_7d ?? 0) > 0 && (
              <text x={8} y={44} fontSize={10} fill="#94a3b8">Mentions (7d): {tooltip.node.mentions_7d}</text>
            )}
            {tooltip.node.growth_flag && (
              <text x={8} y={58} fontSize={10} fill="#f59e0b">⚡ Growing fast</text>
            )}
          </g>
        )}
      </svg>

      <p style={{ fontSize: "0.72rem", color: "#94a3b8", marginTop: 6 }}>
        Drag nodes to rearrange · Double-click to open entity detail
      </p>
    </div>
  );
}

function nd_tooltip_height(nd: SimNode): number {
  let h = 38;
  if ((nd.mentions_7d ?? 0) > 0) h += 14;
  if (nd.growth_flag) h += 14;
  return h;
}
