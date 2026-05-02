"""App versioning and auto-update detection."""
import hashlib
import os
import glob
from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter(prefix="/api", tags=["version"])

# Base version
MAJOR = 2
MINOR = 1

# Cache for computed values
_cached_hash = None
_cached_patch = None
_cached_at = None


def _compute_code_hash():
    """Hash all Python files in backend to detect real code changes."""
    hasher = hashlib.sha256()
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    py_files = sorted(glob.glob(os.path.join(backend_dir, "**/*.py"), recursive=True))
    for fpath in py_files:
        try:
            with open(fpath, "rb") as f:
                hasher.update(f.read())
        except Exception:
            pass
    return hasher.hexdigest()[:16]


def _compute_patch_from_hash(code_hash: str) -> int:
    """Derive a stable patch number from the code hash."""
    return int(code_hash[:8], 16) % 10000


def get_version_info():
    """Get current version info, cached for performance."""
    global _cached_hash, _cached_patch, _cached_at
    now = datetime.now(timezone.utc)
    # Recompute every 30 seconds max
    if _cached_at and (now - _cached_at).total_seconds() < 30:
        return _cached_hash, _cached_patch
    _cached_hash = _compute_code_hash()
    _cached_patch = _compute_patch_from_hash(_cached_hash)
    _cached_at = now
    return _cached_hash, _cached_patch


@router.get("/app-version")
async def app_version():
    code_hash, patch = get_version_info()
    return {
        "version": f"{MAJOR}.{MINOR}.{patch}",
        "major": MAJOR,
        "minor": MINOR,
        "patch": patch,
        "hash": code_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
