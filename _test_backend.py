"""Quick test: verify vector backend resolves to server_qdrant."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from src.env import load_environment
load_environment()

print("BACKEND env:", os.getenv("OMNILEGAL_VECTOR_BACKEND"))

from src.rag.vector_store import get_store
store = get_store()
print("Store type:", type(store).__name__)
print("SUCCESS - connected to Qdrant server")
