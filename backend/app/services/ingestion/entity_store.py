import json
import logging
import os
from typing import Dict, List, Set, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class EntityInfo:
    name: str
    label: str
    count: int
    aliases: List[str]
    is_promoted: bool = False

class EntityStore:
    def __init__(self, kb_id: str, storage_dir: str = "data/entity_stores"):
        self.kb_id = kb_id
        self.storage_dir = storage_dir
        self.file_path = os.path.join(storage_dir, f"entity_store_{kb_id}.json")
        self.entities: Dict[str, EntityInfo] = {}  # Key: entity text
        
        # Ensure directory exists
        os.makedirs(storage_dir, exist_ok=True)
        self.load()

    def load(self):
        """Load entities from JSON file."""
        if not os.path.exists(self.file_path):
            return

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for key, val in data.items():
                    self.entities[key] = EntityInfo(**val)
            logger.info(f"Loaded {len(self.entities)} entities for KB {self.kb_id}")
        except Exception as e:
            logger.error(f"Error loading entity store for KB {self.kb_id}: {e}")

    def save(self):
        """Save entities to JSON file."""
        try:
            data = {k: asdict(v) for k, v in self.entities.items()}
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"Saved entity store for KB {self.kb_id}")
        except Exception as e:
            logger.error(f"Error saving entity store for KB {self.kb_id}: {e}")

    def add_candidates(self, candidates: List[dict]):
        """
        Add candidate entities.
        candidates: List of dicts with keys 'text', 'label'
        """
        updated = False
        for c in candidates:
            text = c['text'].strip()
            label = c['label']
            
            if not text:
                continue

            if text in self.entities:
                self.entities[text].count += 1
                updated = True
            else:
                self.entities[text] = EntityInfo(
                    name=text,
                    label=label,
                    count=1,
                    aliases=[],
                    is_promoted=False
                )
                updated = True
        
        if updated:
            self.save()

    def promote_entities(self, min_freq: int = 3, min_len: int = 2, allowed_labels: Optional[List[str]] = None):
        """
        Promote entities that meet criteria to be used in PhraseMatcher.
        """
        promoted_count = 0
        for text, info in self.entities.items():
            if info.is_promoted:
                continue
                
            # Criteria 1: Frequency
            if info.count < min_freq:
                continue
            
            # Criteria 2: Length
            if len(text) < min_len:
                continue
            
            # Criteria 3: Label Whitelist
            if allowed_labels and info.label not in allowed_labels:
                continue
                
            # Promote
            info.is_promoted = True
            promoted_count += 1
            
        if promoted_count > 0:
            logger.info(f"Promoted {promoted_count} new entities for KB {self.kb_id}")
            self.save()

    def get_patterns(self) -> List[dict]:
        """
        Return patterns for spaCy PhraseMatcher.
        Only returns promoted entities.
        """
        patterns = []
        for text, info in self.entities.items():
            if info.is_promoted:
                # PhraseMatcher pattern format: {"label": "ORG", "pattern": "Google"}
                patterns.append({"label": info.label, "pattern": text})
                # Add aliases if needed
                for alias in info.aliases:
                     patterns.append({"label": info.label, "pattern": alias})
        return patterns
