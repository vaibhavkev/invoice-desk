"""Extraction cache table access (SPEC 3.4)."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from ..models import ExtractionCache
from ..util import utcnow_iso


class ExtractionCacheStore:
    def __init__(self, engine):
        self.engine = engine

    def put(self, file_hash: str, model: str, extraction: Dict[str, Any], usage: Dict[str, Any]) -> None:
        with Session(self.engine) as s:
            row = s.exec(select(ExtractionCache).where(ExtractionCache.file_hash == file_hash,
                                                       ExtractionCache.model == model)).first()
            if row is None:
                row = ExtractionCache(file_hash=file_hash, model=model, extraction_json="", created_at="")
            row.extraction_json = json.dumps(extraction)
            row.usage_json = json.dumps(usage or {})
            row.created_at = utcnow_iso()
            s.add(row)
            s.commit()

    def get(self, file_hash: str, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Latest cached extraction for this file; prefers the same model, else any model."""
        with Session(self.engine) as s:
            rows = s.exec(select(ExtractionCache).where(ExtractionCache.file_hash == file_hash)).all()
        if not rows:
            return None
        rows.sort(key=lambda r: (r.model == model, r.created_at), reverse=True)
        r = rows[0]
        return {"model": r.model, "extraction": json.loads(r.extraction_json),
                "usage": json.loads(r.usage_json or "{}"), "created_at": r.created_at}
