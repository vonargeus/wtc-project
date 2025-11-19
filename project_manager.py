"""Project management utilities for chat history and project state."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import streamlit as st

from config import INITIAL_ASSISTANT_GREETING, PROJECT_LOGS_ROOT


def sanitize_project_slug(name: str) -> str:
    """Convert a project name to a safe slug."""
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.lower())
    slug = slug.strip("-_") or "greenpt-project"
    return slug[:60]


def ensure_safe_path(base_dir: Path, relative_path: Path) -> Path:
    """Ensure a path stays within the base directory to prevent directory traversal."""
    base_resolved = base_dir.resolve()
    target_path = (base_dir / relative_path).resolve()
    if base_resolved == target_path or base_resolved in target_path.parents:
        return target_path
    raise ValueError(
        f"Cannot write `{relative_path}` outside of `{base_dir}`. Check build plan inputs."
    )


def initial_chat_history() -> List[dict]:
    """Create initial chat history with greeting."""
    return [
        {
            "role": "assistant",
            "content": INITIAL_ASSISTANT_GREETING,
        }
    ]


def save_project_log(project_slug: str, history: List[dict]) -> Path:
    """Save project chat history to a JSON file."""
    PROJECT_LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = PROJECT_LOGS_ROOT / f"{project_slug}.json"
    payload = {
        "project": project_slug,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "history": history,
    }
    log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return log_path


def get_or_create_project_state(slug: str) -> dict:
    """Get or create a project state in session state."""
    projects = st.session_state.setdefault("projects", {})
    if slug not in projects:
        projects[slug] = {
            "history": initial_chat_history(),
            "last_blueprint": None,
            "last_build": None,
        }
    return projects[slug]

