"""Debug: inspect opinions field from CourtListener search."""
import sys, types, json, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "src.services" not in sys.modules:
    stub = types.ModuleType("src.services")
    stub.__path__ = [str(Path(__file__).resolve().parent.parent / "src" / "services")]
    stub.__package__ = "src.services"
    sys.modules["src.services"] = stub

import io
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.config import COURTLISTENER_TOKEN

url = "https://www.courtlistener.com/api/rest/v4/search/?q=international+law&type=o&stat_Precedential=on"
headers = {
    "User-Agent": "OmniLegalResearchAssistant/1.0",
    "Accept": "application/json",
    "Authorization": f"Token {COURTLISTENER_TOKEN}",
}
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read().decode())

r = data["results"][0]
opinions = r.get("opinions", [])
print(f"opinions type: {type(opinions)}", flush=True)
print(f"opinions count: {len(opinions) if isinstance(opinions, list) else 'N/A'}", flush=True)
if opinions and isinstance(opinions, list):
    op = opinions[0]
    print(f"opinion keys: {list(op.keys()) if isinstance(op, dict) else type(op)}", flush=True)
    if isinstance(op, dict):
        for k, v in op.items():
            if isinstance(v, str):
                print(f"  {k} ({len(v)} chars): {v[:200]}...", flush=True)
            else:
                print(f"  {k}: {v}", flush=True)

# Also check other fields that might have text
for field in ["posture", "procedural_history", "syllabus"]:
    val = r.get(field, "")
    if val:
        print(f"\n{field} ({len(str(val))} chars): {str(val)[:200]}", flush=True)

# Try fetching the actual opinion detail
abs_url = r.get("absolute_url", "")
cluster_id = r.get("cluster_id", "")
if cluster_id:
    detail_url = f"https://www.courtlistener.com/api/rest/v4/clusters/{cluster_id}/"
    print(f"\nFetching cluster detail: {detail_url}", flush=True)
    req2 = urllib.request.Request(detail_url, headers=headers)
    with urllib.request.urlopen(req2, timeout=30) as resp2:
        detail = json.loads(resp2.read().decode())
    print(f"Cluster keys: {list(detail.keys())}", flush=True)
    sub_opinions = detail.get("sub_opinions", [])
    print(f"sub_opinions: {sub_opinions[:3] if sub_opinions else 'none'}", flush=True)
