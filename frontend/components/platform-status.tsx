"use client";

import { useEffect, useState } from "react";

type StatusResponse = {
  status: string;
  dependencies?: Record<string, string>;
};

const apiBasePath = process.env.NEXT_PUBLIC_API_BASE_PATH ?? "/api/v1";

export function PlatformStatus() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadStatus() {
      try {
        const response = await fetch(`${apiBasePath}/system/health/ready/`, {
          cache: "no-store"
        });
        const payload = (await response.json()) as StatusResponse;

        if (!cancelled) {
          setStatus(payload);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError("Backend readiness is not reachable through Nginx yet.");
        }
      }
    }

    void loadStatus();
    const timer = window.setInterval(() => {
      void loadStatus();
    }, 30000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const overall = error ? "error" : status?.status ?? "degraded";
  const dependencies = status?.dependencies ?? {};

  return (
    <section className="status-panel">
      <div className="status-header">
        <h2>Platform status</h2>
        <span className={`status-pill ${overall}`}>{overall}</span>
      </div>

      <p className="status-text">
        {error ??
          "This panel reads the real backend readiness endpoint through the shared Nginx entrypoint."}
      </p>

      <div className="dependency-list">
        {Object.keys(dependencies).length > 0 ? (
          Object.entries(dependencies).map(([name, value]) => (
            <div className="dependency-item" key={name}>
              <span className="dependency-name">{name}</span>
              <span className="dependency-value">{value}</span>
            </div>
          ))
        ) : (
          <div className="dependency-item">
            <span className="dependency-name">backend</span>
            <span className="dependency-value">pending</span>
          </div>
        )}
      </div>
    </section>
  );
}

