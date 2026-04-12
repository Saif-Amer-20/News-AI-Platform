from __future__ import annotations

import os
import socket
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def wait_for(host: str, port: int, name: str, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"[wait-for] {name} is available on {host}:{port}")
                return
        except OSError:
            print(f"[wait-for] waiting for {name} on {host}:{port}")
            time.sleep(2)
    raise TimeoutError(f"Timed out waiting for {name} on {host}:{port}")


def wait_for_http(url: str, name: str, deadline: float) -> None:
    request = Request(url, method="GET")
    while time.monotonic() < deadline:
        try:
            with urlopen(request, timeout=3) as response:
                if 200 <= response.status < 500:
                    print(f"[wait-for] {name} is available at {url}")
                    return
        except Exception:
            print(f"[wait-for] waiting for {name} at {url}")
            time.sleep(2)
    raise TimeoutError(f"Timed out waiting for {name} at {url}")


def parse_host_port(url: str, default_host: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or default_host
    port = parsed.port or default_port
    return host, port


def main() -> int:
    timeout = int(os.getenv("DEPENDENCY_WAIT_TIMEOUT", "120"))
    deadline = time.monotonic() + timeout

    postgres_host = os.getenv("POSTGRES_HOST", "postgres")
    postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    opensearch_url = os.getenv("OPENSEARCH_URL", "http://opensearch:9200")
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    minio_endpoint = os.getenv("MINIO_ENDPOINT", "http://minio:9000")

    neo4j_host, neo4j_port = parse_host_port(neo4j_uri, "neo4j", 7687)

    try:
        wait_for(postgres_host, postgres_port, "postgres", deadline)
        wait_for(redis_host, redis_port, "redis", deadline)
        wait_for_http(
            f"{opensearch_url.rstrip('/')}/_cluster/health?wait_for_status=yellow&timeout=2s",
            "opensearch",
            deadline,
        )
        wait_for(neo4j_host, neo4j_port, "neo4j", deadline)
        wait_for_http(
            f"{minio_endpoint.rstrip('/')}/minio/health/live",
            "minio",
            deadline,
        )
    except TimeoutError as exc:
        print(f"[wait-for] {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
