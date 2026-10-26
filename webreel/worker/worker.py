import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from webreel.engine.pipeline import run_pipeline

async def worker_loop():
    print("🚀 WebReel Container Worker started. Waiting for pipeline jobs...")
    while True:
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(worker_loop())
