from __future__ import annotations

from typing import Callable

import redis
import requests
from django.conf import settings
from django.db import connections
from django.http import JsonResponse
from neo4j import GraphDatabase


def health_live(request):
    return JsonResponse(
        {
            "status": "ok",
            "service": "backend",
            "environment": settings.PLATFORM_ENV,
        }
    )


def _check_database() -> None:
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()


def _check_redis() -> None:
    client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)
    client.ping()


def _check_opensearch() -> None:
    response = requests.get(
        f"{settings.OPENSEARCH_URL}/_cluster/health",
        params={"wait_for_status": "yellow", "timeout": "2s"},
        timeout=3,
    )
    response.raise_for_status()


def _check_neo4j() -> None:
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    try:
        driver.verify_connectivity()
    finally:
        driver.close()


def _check_minio() -> None:
    response = requests.get(
        f"{settings.MINIO_ENDPOINT}/minio/health/live",
        timeout=3,
    )
    response.raise_for_status()


def health_ready(request):
    checks: list[tuple[str, Callable[[], None]]] = [
        ("postgres", _check_database),
        ("redis", _check_redis),
        ("opensearch", _check_opensearch),
        ("neo4j", _check_neo4j),
        ("minio", _check_minio),
    ]

    results: dict[str, str] = {}
    failed = False

    for name, check in checks:
        try:
            check()
            results[name] = "ok"
        except Exception:
            results[name] = "error"
            failed = True

    status_code = 503 if failed else 200
    return JsonResponse(
        {
            "status": "degraded" if failed else "ok",
            "service": "backend",
            "dependencies": results,
        },
        status=status_code,
    )

