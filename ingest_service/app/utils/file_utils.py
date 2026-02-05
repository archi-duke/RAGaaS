import os
import unicodedata
from typing import Optional

async def read_text_file(file_path: str) -> Optional[str]:
    """
    Reads a file (TXT or PDF) and handles Mac OS Hangul NFD normalization issues.
    """
    if not os.path.exists(file_path):
        # 1. Try resolving relative to SHARED_STORAGE_PATH if it looks like a shared path
        from app.core.config import settings
        if "/data/uploads/" in file_path:
            relative_part = file_path.split("/data/uploads/")[-1]
            new_path = os.path.join(settings.SHARED_STORAGE_PATH, relative_part)
            if os.path.exists(new_path):
                file_path = new_path
        
        # 2. Try normalizing to NFC/NFD
        if not os.path.exists(file_path):
            nfc_path = unicodedata.normalize('NFC', file_path)
            if os.path.exists(nfc_path):
                file_path = nfc_path
            else:
                nfd_path = unicodedata.normalize('NFD', file_path)
                if os.path.exists(nfd_path):
                    file_path = nfd_path
    
    # 3. Fuzzy match by UUID prefix if still not found
    if not os.path.exists(file_path):
        from app.core.config import settings
        directory = os.path.dirname(file_path)
        # If directory doesn't exist, try relative to shared storage
        if not os.path.exists(directory) and "/data/uploads/" in directory:
             rel_dir = directory.split("/data/uploads/")[-1]
             directory = os.path.join(settings.SHARED_STORAGE_PATH, rel_dir)

        filename = os.path.basename(file_path)
        if os.path.exists(directory):
            uuid_part = filename.split('_')[0]
            for f in os.listdir(directory):
                if f.startswith(uuid_part):
                    file_path = os.path.join(directory, f)
                    break

    if not os.path.exists(file_path):
        return None

    text = ""
    try:
        if file_path.lower().endswith('.pdf'):
            from pypdf import PdfReader
            import io
            with open(file_path, "rb") as f:
                pdf = PdfReader(io.BytesIO(f.read()))
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        return text
    except Exception as e:
        print(f"[file_utils] Error reading file {file_path}: {e}")
        return None
