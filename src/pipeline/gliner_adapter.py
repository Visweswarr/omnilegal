"""GLiNER adapter with an isolated-venv subprocess fallback."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from src.config import GLINER_MODEL, OMNILEGAL_DIR
from src.services.model_cache import gliner_status, isolated_gliner_python


def predict_entities_isolated(
    text: str,
    labels: list[str],
    *,
    threshold: float = 0.5,
    timeout: int = 25,
) -> list[dict[str, Any]]:
    python_exe = isolated_gliner_python()
    worker = OMNILEGAL_DIR / "scripts" / "gliner_worker.py"
    if not python_exe.exists() or not worker.exists():
        return []

    env = os.environ.copy()
    env.setdefault("GLINER_MODEL", GLINER_MODEL)
    payload = json.dumps({"text": text, "labels": labels, "threshold": threshold})
    try:
        proc = subprocess.run(
            [str(python_exe), str(worker)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            return []
        result = json.loads(proc.stdout or "{}")
        return list(result.get("entities") or [])
    except Exception as exc:
        print(f"Warning: isolated GLiNER adapter failed: {exc}")
        return []


def adapter_available() -> bool:
    return bool(gliner_status().get("ok"))
