import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import asyncio
from webreel.engine.pipeline import run_pipeline

async def main():
    print("=== STARTING CAMPUSWEB INTERACTIVE V3 ===", flush=True)
    try:
        res = await run_pipeline("https://campusweb.co.in", job_id="campusweb_interactive_v3")
        print("=== PIPELINE COMPLETED SUCCESSFULLY ===", flush=True)
        print("Video Path:", res.get("video_path"), flush=True)
        print("Duration:", res.get("duration_seconds"), "s", flush=True)
        for s in res.get("scenes", []):
            print(f"  Scene: {s.get('scene_id')} -> {s.get('scene_type')} (CTA: {s.get('cta_coordinates')})", flush=True)
    except Exception as e:
        print("ERROR IN PIPELINE:", e, flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
