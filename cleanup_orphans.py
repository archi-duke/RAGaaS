import shutil
from pathlib import Path

# Orphans detected from previous scan
orphans = [
    'dc5f474e-4add-4c29-aee5-d7cdc06e79a4', 
    '132884d5-d3cd-4380-ab4c-fc13f24389e6', 
    'a592a040-0416-4b5c-b710-08509084ced3', 
    '298f7c64-5032-4f9e-930a-1e774c434759', 
    '35ba3578-99e7-4e31-925f-9d44633b8ff7', 
    '2ab48569-f0a2-4fee-ad4e-b1b1bc267d1d', 
    'c04702af-7799-473c-89b8-04a81e41bd0c', 
    'd64df05b-776e-43a3-980c-042002a67f43', 
    '634c298b-4341-48b4-8413-cec74ad91a3f', 
    'e8c4ff2b-c3c0-4818-83cc-e0ca9a6375b3'
]

base_dir = Path("backend/doc2onto_out")

print(f"Cleaning up {len(orphans)} orphan directories...")

count = 0
for orphan_id in orphans:
    target = base_dir / orphan_id
    if target.exists() and target.is_dir():
        try:
            shutil.rmtree(target)
            print(f" - Deleted: {orphan_id}")
            count += 1
        except Exception as e:
            print(f" - Failed to delete {orphan_id}: {e}")
    else:
        print(f" - Skipped (Not found): {orphan_id}")

print(f"\nCleanup complete. Removed {count} directories.")
