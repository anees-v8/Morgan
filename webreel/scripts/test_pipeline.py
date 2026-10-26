import sys
import argparse
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Ensure utf-8 stdout on Windows console
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from webreel.engine.pipeline import run_pipeline

async def main():
    parser = argparse.ArgumentParser(description="WebReel Video Pipeline Test Runner")
    parser.add_argument("--url", default="https://stripe.com", help="Target website URL")
    args = parser.parse_args()

    print("\n=======================================================")
    print(f"[START] WebReel Autonomous Pipeline Starting: {args.url}")
    print("=======================================================\n")


    def log_progress(pct: int, msg: str):
        print(f"[{pct:3d}%] {msg}")

    try:
        result = await run_pipeline(
            url=args.url,
            progress_callback=log_progress
        )
        print("\n=======================================================")
        print("✅ Pipeline Succeeded!")
        print(f"Video Output: {result.get('video_path')}")
        print(f"Scenes Visited: {result.get('scenes_count')}")
        print(f"Render Time: {result.get('duration_seconds')}s")
        print("=======================================================\n")
    except Exception as e:
        print(f"\n❌ Pipeline Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
