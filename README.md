# News Intelligence Platform

A full-stack OSINT news intelligence platform built for monitoring, analyzing, and tracking global news in real time. Designed as a single-server deployment using Docker Compose.

## Overview

The platform ingests news from multiple sources (RSS, GDELT, GNews, web scraping), processes and deduplicates articles through a multi-stage pipeline, and presents them through an interactive web dashboard with search, mapping, timeline, entity tracking, and case management capabilities.

Key features:

- **Multi-source ingestion** — RSS feeds, GDELT, GNews API, Scrapy crawlers
- **NLP pipeline** — Entity extraction, event detection, topic matching, narrative analysis, story clustering
- **Full-text search** — OpenSearch-backed search with faceted filtering
- **Knowledge graph** — Neo4j graph for entity/event relationships
- **AI summaries** — LLM-powered article summaries with geopolitical predictions (Groq API)
- **Arabic translation** — Automatic translation of articles and summaries to Arabic
- **Alerting system** — Rule-based alerts with evaluation engine
- **Case management** — Track investigations by attaching articles and entities
- **Interactive map** — Geographic visualization of news events
- **Timeline view** — Temporal event tracking
- **Observability** — Prometheus metrics, Grafana dashboards, Loki log aggregation

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.1, Django REST Framework 3.15, Celery 5.4 |
| Frontend | Next.js 14, React 18, Tailwind CSS 4 |
| Database | PostgreSQL 16 |
| Search | OpenSearch 2.13 |
| Graph DB | Neo4j 5 |
| Object Storage | MinIO |
| Cache / Broker | Redis 7.2 |
| Reverse Proxy | Nginx 1.27 |
| Monitoring | Prometheus, Grafana, Loki |
| Crawlers | Scrapy |
| Containerization | Docker Compose (15 services) |

## Project Structure

```
├── backend/            # Django application
│   ├── accounts/       # User management & RBAC
│   ├── alerts/         # Alert rules & evaluation
│   ├── cases/          # Case/investigation management
│   ├── config/         # Django settings, URLs, WSGI/ASGI
│   ├── core/           # Shared utilities, admin customization
│   ├── ops/            # Operational monitoring & DLQ
│   ├── services/       # Business logic layer
│   │   ├── connectors/       # Source connectors (RSS, GDELT, etc.)
│   │   ├── integrations/     # External service adapters
│   │   └── orchestration/    # Pipeline orchestration services
│   ├── sources/        # Articles, sources, events, entities
│   └── topics/         # Topic definitions & matching
├── crawlers/           # Scrapy-based web crawlers
├── frontend/           # Next.js web application
│   ├── app/            # Pages (articles, events, map, search, etc.)
│   ├── components/     # Reusable UI components
│   └── lib/            # API client, types
├── infra/              # Infrastructure configs
│   ├── grafana/        # Dashboard provisioning
│   ├── loki/           # Log aggregation config
│   ├── nginx/          # Reverse proxy config
│   └── prometheus/     # Metrics & alert rules
├── docker-compose.yml
└── Makefile
```

## Getting Started

### Prerequisites

- Docker & Docker Compose v2
- 8 GB RAM minimum (OpenSearch + Neo4j are memory-heavy)

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/Saif-Amer-20/News-AI-Platform.git
   cd News-AI-Platform
   ```

2. Copy the example environment file and fill in your values:
   ```bash
   cp .env.example .env
   ```

   At minimum, update the passwords and add your API keys:
   - `DJANGO_SECRET_KEY` — a strong random string
   - `POSTGRES_PASSWORD`, `NEO4J_PASSWORD`, `MINIO_ROOT_PASSWORD` — service passwords
   - `GROQ_API_KEY` — for AI-powered summaries (free tier available at groq.com)
   - `GNEWS_KEY` — for GNews source (optional)

3. Build and start all services:
   ```bash
   docker compose up -d --build
   ```

4. Run initial migrations and seed data:
   ```bash
   docker compose exec backend python manage.py migrate
   docker compose exec backend python manage.py seed_sources
   docker compose exec backend python manage.py bootstrap_rbac
   ```

5. Open the platform at [http://localhost:8088](http://localhost:8088)

### Admin Panel

Access the Django admin at [http://localhost:8088/ops/](http://localhost:8088/ops/) to manage sources, view pipeline status, and configure alerts.

## Architecture

The platform follows a three-layer architecture:

1. **Ingestion layer** — Connectors fetch raw content from external sources, adapters normalize it, and Celery workers process items through the pipeline.
2. **Processing layer** — Orchestration services handle deduplication, entity extraction, event detection, topic matching, story clustering, and indexing into OpenSearch/Neo4j.
3. **Presentation layer** — REST API serves the Next.js frontend through Nginx reverse proxy.

All services communicate through Redis (Celery broker) and share PostgreSQL as the primary data store.

## License

This project is proprietary. All rights reserved.

