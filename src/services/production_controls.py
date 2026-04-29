"""Local production controls: PII redaction, rate limiting, and JSONL traces."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from typing import Any

from src.config import OMNILEGAL_DIR, OMNILEGAL_LOG_RETENTION_DAYS

_REQUESTS: dict[str, deque[float]] = defaultdict(deque)
_LOG_DIR = OMNILEGAL_DIR / "data" / "logs"
_TRACE_PATH = _LOG_DIR / "chainlit_traces.jsonl"


def check_rate_limit(key: str, *, max_requests: int = 20, window_seconds: int = 3600) -> tuple[bool, str]:
    now = time.time()
    bucket = _REQUESTS[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= max_requests:
        return False, f"Rate limit exceeded: {max_requests} requests per {window_seconds // 60} minutes."
    bucket.append(now)
    return True, ""


_presidio_engines: tuple | None = None
_presidio_lock = threading.Lock()


def _get_presidio_engines():
    """Lazy-init singleton for Presidio engines (thread-safe, avoids 10s+ reload each call)."""
    global _presidio_engines
    if _presidio_engines is not None:
        return _presidio_engines
    with _presidio_lock:
        if _presidio_engines is None:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine
            _presidio_engines = (AnalyzerEngine(), AnonymizerEngine())
    return _presidio_engines


def redact_pii(text: str) -> str:
    if not text:
        return text
    if os.getenv("OMNILEGAL_ENABLE_PRESIDIO_REDACTION", "0").lower() not in {"1", "true", "yes"}:
        return _regex_redact(text)
    try:
        analyzer, anonymizer = _get_presidio_engines()
        results = analyzer.analyze(text=text, language="en")
        return anonymizer.anonymize(text=text, analyzer_results=results).text
    except Exception:
        return _regex_redact(text)


def _regex_redact(text: str) -> str:
    redacted = re.sub(r"\b[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[EMAIL]", text)
    redacted = re.sub(r"\b(?:\+?\d[\d -]{8,}\d)\b", "[PHONE_OR_ID]", redacted)
    return redacted


def cleanup_old_logs(retention_days: int = OMNILEGAL_LOG_RETENTION_DAYS) -> None:
    if not _LOG_DIR.exists():
        return
    cutoff = time.time() - retention_days * 86400
    for path in _LOG_DIR.glob("*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def write_trace(event: str, payload: dict[str, Any]) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_old_logs()
    clean_payload = {
        key: redact_pii(value) if isinstance(value, str) else value
        for key, value in payload.items()
    }
    record = {"ts": time.time(), "event": event, "payload": clean_payload}
    with _TRACE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
