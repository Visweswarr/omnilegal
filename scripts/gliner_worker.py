"""JSON stdin/stdout worker for isolated GLiNER inference."""
from __future__ import annotations

import json
import os
import sys


def main() -> None:
    request = json.loads(sys.stdin.read() or "{}")
    text = str(request.get("text") or "")[:2048]
    labels = list(request.get("labels") or [])
    threshold = float(request.get("threshold", 0.5))
    model_name = os.getenv("GLINER_MODEL", "urchade/gliner_multi-v2.1")

    from gliner import GLiNER

    model = GLiNER.from_pretrained(model_name)
    entities = model.predict_entities(text, labels, threshold=threshold)
    print(json.dumps({"entities": entities}, ensure_ascii=False))


if __name__ == "__main__":
    main()
