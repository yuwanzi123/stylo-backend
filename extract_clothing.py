from visual_pipeline import run_pipeline

VIDEO_PATH = "uploads/20260611_163958.mp4"

results = run_pipeline(VIDEO_PATH)

print(f"\n=== {len(results)} items extracted ===")
for path in results:
    print(f"  {path}")
