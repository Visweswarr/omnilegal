import asyncio
from sniffio import current_async_library

async def test():
    lib = current_async_library()
    print(f"Detected async library: {lib!r}")

asyncio.run(test())
