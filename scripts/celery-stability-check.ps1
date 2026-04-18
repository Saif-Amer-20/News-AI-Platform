#!/usr/bin/env pwsh
# ── Celery Stability Observation Script ──────────────────────────────────
# Run periodically during 24-48h observation window (started 2026-04-18).
# No changes — monitoring only.

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "`n═══════════════════════════════════════════════════════════"
Write-Host "  CELERY STABILITY CHECK — $timestamp"
Write-Host "═══════════════════════════════════════════════════════════"

# ── 1. Worker CPU & Memory ───────────────────────────────────────────────
Write-Host "`n[1] WORKER CPU & MEMORY"
Write-Host "─────────────────────────────────────────────────────"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>&1 |
    Select-String "worker|beat|NAME"

# ── 2. Queue Length ──────────────────────────────────────────────────────
Write-Host "`n[2] CELERY QUEUE DEPTH"
Write-Host "─────────────────────────────────────────────────────"
$qlen = docker exec newsintel-redis-1 redis-cli -n 1 LLEN celery
Write-Host "  Queue length: $qlen"
if ([int]$qlen -gt 50) {
    Write-Host "  ⚠ WARNING: Queue backlog detected (>50 tasks)" -ForegroundColor Yellow
}

# ── 3. Task Durations (PERF logs, last 2 hours) ─────────────────────────
Write-Host "`n[3] TASK DURATIONS (last 2h, from [PERF] logs)"
Write-Host "─────────────────────────────────────────────────────"
$perfLogs = docker logs --since 2h newsintel-worker-1 2>&1 | Select-String "\[PERF\]"
if ($perfLogs) {
    $perfLogs | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "  (no PERF entries in last 2h — tasks may not have fired yet)"
}

# ── 4. Lock Skips (overlap detection) ───────────────────────────────────
Write-Host "`n[4] TASK OVERLAP DETECTION (lock skips, last 2h)"
Write-Host "─────────────────────────────────────────────────────"
$skips = docker logs --since 2h newsintel-worker-1 2>&1 | Select-String "skipped.*previous run still active"
if ($skips) {
    Write-Host "  ⚠ Overlapping tasks detected:" -ForegroundColor Yellow
    $skips | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "  ✓ No task overlaps detected"
}

# ── 5. Intelligence Freshness ───────────────────────────────────────────
Write-Host "`n[5] INTELLIGENCE OUTPUT FRESHNESS"
Write-Host "─────────────────────────────────────────────────────"

# Dashboard summary (checks entity scores + signals exist)
try {
    $dash = Invoke-WebRequest -Uri "http://localhost:8088/api/v1/entity-intelligence/dashboard/" -UseBasicParsing -TimeoutSec 10
    $dd = $dash.Content | ConvertFrom-Json
    $kpi = $dd.kpis
    Write-Host "  Dashboard:        HTTP $($dash.StatusCode) | entities=$($kpi.entities) relationships=$($kpi.relationships) signals=$($kpi.signals) scored=$($kpi.scored_entities)"
} catch {
    Write-Host "  Dashboard:        ✗ FAILED — $($_.Exception.Message)" -ForegroundColor Red
}

# Graph endpoint
try {
    $graph = Invoke-WebRequest -Uri "http://localhost:8088/api/v1/entity-intelligence/graph/" -UseBasicParsing -TimeoutSec 10
    $gd = $graph.Content | ConvertFrom-Json
    Write-Host "  Graph:            HTTP $($graph.StatusCode) | nodes=$($gd.nodes.Count) edges=$($gd.edges.Count)"
} catch {
    Write-Host "  Graph:            ✗ FAILED — $($_.Exception.Message)" -ForegroundColor Red
}

# Signals endpoint
try {
    $sig = Invoke-WebRequest -Uri "http://localhost:8088/api/v1/entity-intelligence/signals/" -UseBasicParsing -TimeoutSec 10
    $sd = $sig.Content | ConvertFrom-Json
    Write-Host "  Signals:          HTTP $($sig.StatusCode) | count=$($sd.Count)"
} catch {
    Write-Host "  Signals:          ✗ FAILED — $($_.Exception.Message)" -ForegroundColor Red
}

# Strongest relationships
try {
    $str = Invoke-WebRequest -Uri "http://localhost:8088/api/v1/entity-intelligence/strongest/" -UseBasicParsing -TimeoutSec 10
    $strd = $str.Content | ConvertFrom-Json
    Write-Host "  Strongest:        HTTP $($str.StatusCode) | count=$($strd.Count)"
} catch {
    Write-Host "  Strongest:        ✗ FAILED — $($_.Exception.Message)" -ForegroundColor Red
}

# ── 6. Recent Errors ────────────────────────────────────────────────────
Write-Host "`n[6] RECENT ERRORS (last 2h)"
Write-Host "─────────────────────────────────────────────────────"
$errors = docker logs --since 2h newsintel-worker-1 2>&1 | Select-String "ERROR|Traceback|FAILED"
if ($errors) {
    Write-Host "  ⚠ Errors found:" -ForegroundColor Yellow
    $errors | Select-Object -First 20 | ForEach-Object { Write-Host "  $_" }
    if ($errors.Count -gt 20) {
        Write-Host "  ... and $($errors.Count - 20) more"
    }
} else {
    Write-Host "  ✓ No errors in worker logs"
}

# ── Summary ─────────────────────────────────────────────────────────────
Write-Host "`n═══════════════════════════════════════════════════════════"
Write-Host "  CHECK COMPLETE — $timestamp"
Write-Host "═══════════════════════════════════════════════════════════`n"
