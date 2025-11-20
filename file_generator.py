"""File generation and build plan utilities."""
import io
import json
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple
from zipfile import ZipFile, ZIP_DEFLATED

from api_client import call_greenpt_chat
from config import BUILD_PLAN_PROMPT, FILE_GENERATION_PROMPT
from project_manager import ensure_safe_path


def _plan_contains_dockerfile(plan: List[dict]) -> bool:
    """Return True if the plan already has a Dockerfile entry."""
    for spec in plan:
        path_value = spec.get("path")
        if not path_value:
            continue
        if Path(path_value).name.lower() == "dockerfile":
            return True
    return False


def _collect_stack_hints(plan: List[dict]) -> dict:
    """Infer stack hints (python/node/manifests) from the build plan."""
    python_tokens = {
        ".py",
        "fastapi",
        "flask",
        "django",
        "streamlit",
        "requirements.txt",
        "pyproject.toml",
        "poetry.lock",
        "pipfile",
        "pipfile.lock",
    }
    node_tokens = {
        "package.json",
        "vite.config",
        "next.config",
        ".tsx",
        ".jsx",
        "pnpm-lock.yaml",
        "yarn.lock",
        "package-lock.json",
    }

    hints = {
        "has_python": False,
        "has_node": False,
        "has_frontend": False,
        "python_manifests": [],
        "node_manifests": [],
    }

    for spec in plan:
        path_value = (spec.get("path") or "").lower()
        detail_blob = " ".join(
            filter(
                None,
                [
                    path_value,
                    (spec.get("description") or "").lower(),
                    (spec.get("instructions") or "").lower(),
                ],
            )
        )
        if any(token in detail_blob for token in python_tokens):
            hints["has_python"] = True
        if any(token in detail_blob for token in node_tokens):
            hints["has_node"] = True

        file_name = Path(path_value).name.lower()
        if file_name in {
            "requirements.txt",
            "pyproject.toml",
            "poetry.lock",
            "pipfile",
            "pipfile.lock",
        }:
            hints["python_manifests"].append(spec.get("path") or file_name)
            hints["has_python"] = True
        if file_name in {
            "package.json",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
        }:
            hints["node_manifests"].append(spec.get("path") or file_name)
            hints["has_node"] = True

        if any(token in path_value for token in ("frontend/", "client/", "web/", "ui/")):
            hints["has_frontend"] = True

    return hints


def _summarize_plan(plan: List[dict], max_items: int = 8) -> List[str]:
    """Return a short list of file summaries for the instructions block."""
    summaries: List[str] = []
    for spec in plan[:max_items]:
        path_value = spec.get("path") or "(unnamed file)"
        description = (spec.get("description") or "").strip()
        if description:
            summaries.append(f"{path_value} – {description}")
        else:
            summaries.append(path_value)
    if len(plan) > max_items:
        summaries.append("…")
    return summaries


def _dockerfile_instruction_text(plan: List[dict]) -> str:
    """Build the instruction text for the Dockerfile specification."""
    hints = _collect_stack_hints(plan)
    instructions: List[str] = [
        "Create a production-ready Dockerfile that containers the generated application.",
        "General rules:",
        "- Always start with an official base image, pin the major version, and avoid placeholder text.",
        "- Use `/app` as the working directory and copy dependency manifests before the rest to improve build caching.",
        "- Install only what the project needs and clean up build caches.",
        "- Expose the runtime port mentioned in the blueprint (default to 8080 if not specified).",
        "- Finish with a CMD or ENTRYPOINT that starts the main service discussed in the blueprint.",
    ]

    if hints["python_manifests"]:
        manifest_list = ", ".join(hints["python_manifests"])
        instructions.append(
            f"- Use `python:3.11-slim` for Python services and `pip install --no-cache-dir -r {manifest_list}` to install dependencies."
        )
    elif hints["has_python"]:
        instructions.append(
            "- If the backend is Python, install dependencies from requirements.txt/pyproject and run the ASGI/WSGI server via uvicorn or gunicorn."
        )

    if hints["node_manifests"]:
        manifest_list = ", ".join(hints["node_manifests"])
        instructions.append(
            f"- Use a Node.js 18 builder stage to run `npm install` (or pnpm/yarn) against {manifest_list} and build frontend assets before copying them into the runtime image."
        )
    elif hints["has_node"] or hints["has_frontend"]:
        instructions.append(
            "- If a frontend exists, add a `node:18-alpine` build stage that compiles the UI (npm/yarn build) and copy the output into the server image or serve via a lightweight web server."
        )

    if hints["has_python"] and hints["has_node"]:
        instructions.append(
            "- When both backend and frontend layers exist, keep the backend runtime lean (python:3.11-slim) and copy in the pre-built frontend assets or serve them via the backend static directory."
        )

    summaries = _summarize_plan(plan)
    if summaries:
        instructions.append("Key files to consider:")
        for line in summaries:
            instructions.append(f"  - {line}")

    return "\n".join(instructions)


def ensure_dockerfile_entry(plan: List[dict]) -> List[dict]:
    """Ensure the build plan contains a Dockerfile specification."""
    if _plan_contains_dockerfile(plan):
        return plan

    docker_spec = {
        "path": "Dockerfile",
        "type": "infrastructure",
        "description": "Container configuration to run the generated project end-to-end.",
        "instructions": _dockerfile_instruction_text(plan),
    }
    plan.append(docker_spec)
    return plan


def extract_json_array(raw_text: str) -> List[dict]:
    """Extract a JSON array from raw text, handling markdown fences."""
    cleaned = (raw_text or "").strip()
    if not cleaned:
        raise ValueError("GreenPT returned an empty response.")

    if cleaned.startswith("```"):
        fence_lines = cleaned.splitlines()
        if fence_lines:
            first_line = fence_lines[0].strip("`").strip()
            if first_line.lower() == "json":
                fence_lines = fence_lines[1:]
        if fence_lines and fence_lines[-1].strip().startswith("```"):
            fence_lines = fence_lines[:-1]
        cleaned = "\n".join(fence_lines).strip()
        if not cleaned:
            raise ValueError("GreenPT returned an empty fenced code block.")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1 and start < end:
            snippet = cleaned[start : end + 1]
            snippet = snippet.strip()
            if snippet:
                return json.loads(snippet)
        raise


def generate_build_plan(
    blueprint: str,
    tone: Optional[str],
    model: str,
    max_retries: int = 1,
) -> List[dict]:
    """Generate a build plan from a blueprint."""
    base_prompt = BUILD_PLAN_PROMPT.format(blueprint=blueprint)
    last_error: Optional[Exception] = None
    last_raw: Optional[str] = None

    for attempt in range(max_retries + 1):
        prompt = (
            base_prompt
            if attempt == 0
            else f"{base_prompt}\n\nReminder: Return a JSON array only. No prose."
        )
        plan_text = call_greenpt_chat(prompt, tone, model)
        try:
            plan = extract_json_array(plan_text)
        except (json.JSONDecodeError, ValueError) as parse_err:
            last_error = parse_err
            last_raw = plan_text
            continue
        if not isinstance(plan, list) or not plan:
            last_error = ValueError("Build plan response was empty.")
            last_raw = plan_text
            continue
        return ensure_dockerfile_entry(plan)

    error_message = (
        f"Could not parse build plan JSON after {max_retries + 1} attempt(s): {last_error}"
    )
    if last_raw is not None:
        error_message = f"{error_message}\nRaw response:\n{last_raw}"
    raise ValueError(error_message)


def generate_file_content(
    file_spec: dict,
    blueprint: str,
    tone: Optional[str],
    model: str,
) -> str:
    """Generate file content from a file specification."""
    prompt = FILE_GENERATION_PROMPT.format(
        path=file_spec.get("path", "file.txt"),
        file_type=file_spec.get("type", "config"),
        description=file_spec.get("description", ""),
        instructions=file_spec.get("instructions", ""),
        blueprint=blueprint,
    )
    return call_greenpt_chat(prompt, tone, model, max_tokens=4000, timeout=120, max_retries=1)


def write_files_from_plan(
    plan: List[dict],
    base_dir: Path,
    blueprint: str,
    tone: Optional[str],
    model: str,
    progress_callback: Optional[
        Callable[[int, int, dict], None]
    ] = None,
) -> List[Path]:
    """Write files from a build plan."""
    created_files: List[Path] = []
    total = len(plan)
    for idx, spec in enumerate(plan, start=1):
        rel_path = Path(spec.get("path", "output.txt"))
        target_path = ensure_safe_path(base_dir, rel_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = generate_file_content(spec, blueprint, tone, model)
        target_path.write_text(content, encoding="utf-8")
        created_files.append(target_path)
        if progress_callback:
            progress_callback(idx, total, spec)
    return created_files


def package_directory(directory: Path) -> Tuple[str, bytes]:
    """Package a directory into a zip file."""
    buffer = io.BytesIO()
    zip_name = f"{directory.name}.zip"
    with ZipFile(buffer, "w", ZIP_DEFLATED) as zipf:
        for path in directory.rglob("*"):
            if path.is_file():
                zipf.write(path, path.relative_to(directory))
    buffer.seek(0)
    return zip_name, buffer.read()


def build_blueprint_prompt(
    user_prompt: str,
    sections: Sequence[Tuple[str, str]],
    detail_instruction: str,
) -> str:
    """Build a blueprint prompt from user input and sections."""
    section_text = "\n".join(
        f"- {title}: {description}" for title, description in sections
    )
    return (
        f"### Project Brief\n{user_prompt.strip()}\n\n"
        "### Required Deliverables (use this order)\n"
        f"{section_text}\n\n"
        "### Output Requirements\n"
        f"{detail_instruction}\n"
        "- Use `## <section name>` headings matching each deliverable title.\n"
        "- Specify primary frameworks, libraries, services, and hosting choices.\n"
        "- Surface security, testing, automation, and scalability considerations.\n"
        "- End each section with `Assumptions:` followed by concise bullets.\n"
    )
