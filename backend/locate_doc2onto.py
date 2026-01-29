import sys
import os

# Add backend to path as doc2onto.py does
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.append(app_dir)

try:
    import doc2onto
    print(f"doc2onto file: {doc2onto.__file__}")
except ImportError as e:
    print(f"ImportError: {e}")
    # Try looking in subdirs
    if os.path.exists(os.path.join(app_dir, "app", "doc2onto_backup")):
        print(f"Found doc2onto_backup at {os.path.join(app_dir, 'app', 'doc2onto_backup')}")
