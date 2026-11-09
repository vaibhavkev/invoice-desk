"""Configuration: config.yaml at repo root, plus environment overrides, plus backend/.env (SPEC section 1)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import yaml
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
ENV_FILE = BACKEND_DIR / ".env"


def _resolve(p: str, base: Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (base / path).resolve()


@dataclass
class PolicyConfig:
    tolerance_pct: float = 0.02
    tolerance_abs_floor: Dict[str, float] = field(default_factory=dict)
    confidence_floor: float = 0.75
    date_window_days: int = 90
    future_date_grace_days: int = 0
    duplicate_date_window_days: int = 3
    scanned_chars_per_page: int = 50

    def abs_floor(self, currency: Optional[str]) -> float:
        if not currency:
            return 0.0
        return float(self.tolerance_abs_floor.get(currency.upper(), 0.0))


@dataclass
class ExtractionConfig:
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    max_tokens: int = 8000
    cache_fallback: bool = True
    timeout_s: float = 120.0


@dataclass
class Settings:
    policy: PolicyConfig
    extraction: ExtractionConfig
    data_dir: Path
    db_path: Path
    port: int
    frontend_dist: Path
    upload_dir: Path
    today_override: Optional[date] = None

    def today(self) -> date:
        """Business date used by R9. APP_TODAY=YYYY-MM-DD pins it (tests, demo rehearsal)."""
        return self.today_override or date.today()


def load_settings(config_path: Optional[Path] = None) -> Settings:
    load_dotenv(ENV_FILE)  # real environment variables win over the file
    config_path = config_path or Path(os.environ.get("CONFIG_PATH", REPO_ROOT / "config.yaml"))
    raw = {}
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    pol = raw.get("policy", {}) or {}
    ext = raw.get("extraction", {}) or {}

    policy = PolicyConfig(
        tolerance_pct=float(pol.get("tolerance_pct", 0.02)),
        tolerance_abs_floor={k.upper(): float(v) for k, v in (pol.get("tolerance_abs_floor") or {}).items()},
        confidence_floor=float(pol.get("confidence_floor", 0.75)),
        date_window_days=int(pol.get("date_window_days", 90)),
        future_date_grace_days=int(pol.get("future_date_grace_days", 0)),
        duplicate_date_window_days=int(pol.get("duplicate_date_window_days", 3)),
        scanned_chars_per_page=int(pol.get("scanned_chars_per_page", 50)),
    )
    extraction = ExtractionConfig(
        model=os.environ.get("EXTRACTION_MODEL") or ext.get("model", "claude-opus-5-5"),
        effort=os.environ.get("EXTRACTION_EFFORT") or ext.get("effort", "medium"),
        max_tokens=int(ext.get("max_tokens", 8000)),
        cache_fallback=bool(ext.get("cache_fallback", True)),
    )
    db_path = _resolve(os.environ.get("DB_PATH", "./app.db"), BACKEND_DIR)
    today_env = os.environ.get("APP_TODAY")
    return Settings(
        policy=policy,
        extraction=extraction,
        data_dir=_resolve(os.environ.get("DATA_DIR", "../data"), BACKEND_DIR),
        db_path=db_path,
        port=int(os.environ.get("PORT", "8000")),
        frontend_dist=_resolve(os.environ.get("FRONTEND_DIST", "../frontend/dist"), BACKEND_DIR),
        upload_dir=_resolve(os.environ.get("UPLOAD_DIR", "./uploads"), BACKEND_DIR),
        today_override=date.fromisoformat(today_env) if today_env else None,
    )


settings = load_settings()
