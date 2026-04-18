"use client";

import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";

interface PaginationProps {
  page: number;
  count: number;
  pageSize?: number;
  onChange: (page: number) => void;
}

const DEFAULT_PAGE_SIZE = 50;

export function Pagination({ page, count, pageSize = DEFAULT_PAGE_SIZE, onChange }: PaginationProps) {
  const totalPages = Math.ceil(count / pageSize);
  if (totalPages <= 1) return null;

  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, count);

  // Build page number list with ellipsis
  const pages: (number | "…")[] = [];
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i);
  } else {
    pages.push(1);
    if (page > 3) pages.push("…");
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) {
      pages.push(i);
    }
    if (page < totalPages - 2) pages.push("…");
    pages.push(totalPages);
  }

  return (
    <div className="pagination-bar">
      <span className="pagination-info">
        {from}–{to} of {count.toLocaleString()}
      </span>
      <div className="pagination-controls">
        <button
          className="pagination-btn"
          disabled={page === 1}
          onClick={() => onChange(1)}
          title="First page"
        >
          <ChevronsLeft size={14} />
        </button>
        <button
          className="pagination-btn"
          disabled={page === 1}
          onClick={() => onChange(page - 1)}
          title="Previous page"
        >
          <ChevronLeft size={14} />
        </button>

        {pages.map((p, i) =>
          p === "…" ? (
            <span key={`ellipsis-${i}`} className="pagination-ellipsis">…</span>
          ) : (
            <button
              key={p}
              className={`pagination-btn pagination-page${p === page ? " pagination-page--active" : ""}`}
              onClick={() => onChange(p as number)}
            >
              {p}
            </button>
          )
        )}

        <button
          className="pagination-btn"
          disabled={page === totalPages}
          onClick={() => onChange(page + 1)}
          title="Next page"
        >
          <ChevronRight size={14} />
        </button>
        <button
          className="pagination-btn"
          disabled={page === totalPages}
          onClick={() => onChange(totalPages)}
          title="Last page"
        >
          <ChevronsRight size={14} />
        </button>
      </div>
    </div>
  );
}
