import asyncio
import os
from src.rag.retriever import search_documents
from src.rag.generator import generate

async def test_query():
    query = "What does the UN Charter say about the use of force?"
    print(f"Query: {query}")
    print("Retrieving documents...")
    docs = search_documents(query)
    print(f"Retrieved {len(docs)} documents.")
    for i, d in enumerate(docs):
        print(f"Doc {i+1}: {d.get('metadata', {}).get('source_name', 'Unknown')}")
    
    print("\nGenerating answer...")
    async for chunk in generate(query, docs, "LONG"):
        print(chunk, end="", flush=True)
    print("\n\nDone.")

if __name__ == "__main__":
    asyncio.run(test_query())
