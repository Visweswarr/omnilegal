"""Quick test: list Qdrant collections and their point counts."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from src.env import load_environment
load_environment()

from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333", timeout=10)
collections = client.get_collections().collections
print(f"Found {len(collections)} collections:\n")
for col in sorted(collections, key=lambda c: c.name):
    info = client.get_collection(col.name)
    print(f"  {col.name}: {info.points_count} points")
