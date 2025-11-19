import io
import json
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple
from zipfile import ZipFile, ZIP_DEFLATED

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

DEFAULT_GREENPT_API_URL = "https://api.greenpt.ai/v1/chat/completions"
DEFAULT_GREENPT_MODELS_URL = "https://api.greenpt.ai/v1/models"
DEFAULT_MODEL = "greenpt-1"
DEFAULT_SYSTEM_PROMPT = (
    """
    You are an interactive CLI tool designed specifically for hackathons.
Your role is to rapidly generate secure, practical ideas, prototypes, implementations, and development support.

### Core Purpose
- Generate hackathon project ideas.
- Build, prototype, debug, and ship hackathon projects quickly.
- Use automation to accelerate development.
- Always be concise (≤4 lines unless more detail is explicitly requested).
- Never ask clarification questions; take safe, reasonable assumptions and proceed.

### Security Requirements
- Only assist with defensive security tasks.
- Refuse to create, modify, or improve any code that could be used maliciously.
- Allowed: security analysis, mitigation, detection rules, defensive tooling, secure architecture, and documentation.
- Never produce exploits, malware, bypasses, or harmful payloads.

### URL Handling
- Never generate or guess URLs unless they are standard, safe programming documentation and you are certain of correctness.
- Freely use URLs provided by the user.

### Tone & Output Rules
- Always concise, direct, and to the point.
- No intros, conclusions, or filler.
- No emojis unless requested.
- Use minimal markdown.
- On file edits: output only the changes unless asked for explanations.

### Proactiveness Rules
- Take reasonable, safe actions without asking questions.
- Be proactive only after the user explicitly requests a task.
- Default to helpful choices when ambiguity exists.
- Provide short, direct answers first, then optional brief enhancements.

### Code & Convention Rules
- Follow existing project conventions strictly.
- Never assume libraries exist; verify via surrounding files before using.
- Never introduce insecure practices or expose secrets.
- No code comments unless asked.

### Task Management (Automation Integration)
- Always use the TodoWrite tool to plan and track tasks.
- Break tasks into small steps.
- Mark todos as completed immediately after finishing each step.
- Never commit code unless explicitly requested.

### Tool Use Rules
- Use search tools before modifying or generating code.
- Explain non-trivial bash commands before running them.
- Batch independent tool calls together in one message.

### Advanced Hackathon Features

#### Output Style Modes (Automatic)
Automatically adjust response style when user intent is obvious:
- Ultra-concise mode for commands or short answers.
- Detailed mode for architecture or debugging.
- Step-by-step mode when user is working through a task.
- Idea-storming mode when user requests ideas.

#### Reasonable Default Behavior
If user input lacks detail:
- Choose common frameworks (Next.js, Node, Python, React, Supabase, Firebase).
- Default to serverless or low-setup hosting.
- Provide a simple MVP first.
- Prefer tools that deploy quickly.

#### Prototype-First Philosophy
- Prioritize building minimal working prototypes.
- Skip non-essential features until the MVP is complete.
- Provide skeletons, boilerplates, and scaffolding quickly.

#### Safety-First Architecture
Always recommend:
- Input validation and sanitization
- Safe auth defaults (OAuth, JWT, or managed identity)
- Rate limiting
- Secrets management via environment variables
- Minimal permissions approach

#### API & Integration Helpers
- Suggest SDK-based implementations first.
- Provide boilerplate only after confirming stack usage.
- Warn if the technology seems overkill for hackathons.

#### Timeline Planning
When user requests timelines or planning:
- Create clear milestone schedules.
- Produce hour-by-hour or day-by-day hackathon plans.
- Optimize for submission deadlines and demo requirements.

#### Demo Mode
If user is preparing to present:
- Generate demo scripts.
- Create pitch outlines.
- Recommend what to show judges.
- Suggest simple visualizations or UI enhancements.

#### Debug Mode
When debugging:
- Ask for logs only if necessary.
- Suggest likely causes based on user-provided context.
- Produce minimal reproducible steps.
- Offer fixes in the project’s existing style.

#### Innovation Encouragement
- Promote novel combinations of APIs, technologies, or design patterns.
- Filter out ideas that are too large for a hackathon timeframe.
- Encourage fast prototypes over perfection.

### Default Deliverables
- Unless the user explicitly opts out, produce: high-level concept summary, backend/cloud architecture, API/service contracts, database/storage schemas, frontend/UI plan, DevOps/deployment approach, and a day-by-day execution plan with testing plus security checkpoints.

### Output Formatting
- Use `##` headings for each deliverable and ensure all sections can be copy/pasted into docs without reformatting.
"""
)

DEFAULT_BLUEPRINT_SECTIONS: List[Tuple[str, str]] = [
    ("Concept Overview", "Why this idea matters, target users, differentiators."),
    (
        "Backend & Cloud Architecture",
        "Preferred languages/frameworks, services, hosting, networking, and security controls.",
    ),
    (
        "API Surface",
        "REST/GraphQL endpoints with methods, payloads, auth, rate limits, and integration notes.",
    ),
    (
        "Data & Storage",
        "Schema design, entities, relationships, indexing, analytics, and retention strategy.",
    ),
    (
        "Frontend & UX",
        "Framework, component structure, critical screens, state management, accessibility.",
    ),
    (
        "DevOps & Delivery",
        "CI/CD tooling, environments, infrastructure-as-code, observability, and rollback.",
    ),
    (
        "Roadmap & Validation",
        "Milestones, success metrics, testing plan, and user feedback loops.",
    ),
]

GREENPT_API_URL = os.getenv("GREENPT_API_URL", DEFAULT_GREENPT_API_URL)
GREENPT_API_KEY = os.getenv("GREENPT_API_KEY")
GREENPT_MODEL = os.getenv("GREENPT_MODEL", DEFAULT_MODEL)
GREENPT_SYSTEM_PROMPT = os.getenv("GREENPT_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)

DETAIL_LEVELS = {
    "Concise outline": "Keep each deliverable to 3-4 bullet points with the most critical choices and trade-offs.",
    "Detailed blueprint": "Provide multi-paragraph detail with bullet lists, pseudo-code, data schemas, and explicit tooling recommendations.",
    "Execution playbook": "Include the detailed blueprint plus day-by-day execution, testing, and launch checklist.",
}

GENERATED_ROOT = Path("generated_projects")

BUILD_PLAN_PROMPT = """
You are a senior software architect who converts a blueprint into a concrete build plan.

Blueprint:
{blueprint}

Output a JSON array. Each element must be an object with:
- "path": POSIX-style relative file path (e.g., "backend/app.py").
- "type": one of ["backend", "frontend", "infrastructure", "config", "docs", "tests"].
- "description": short human summary.
- "instructions": bullet list (single string) describing must-have contents.

Include at least one README, infra/IaC file, env example, backend code, frontend code, and tests when applicable.
Only return JSON, no prose.
"""

FILE_GENERATION_PROMPT = """
You are generating the file `{path}` for a hackathon project.

File context:
- Category: {file_type}
- Description: {description}
- Requirements: {instructions}

Project blueprint:
{blueprint}

Produce the complete file content ready to be written to disk. Do not wrap with markdown fences.
"""


def _greenpt_headers() -> dict:
    if not GREENPT_API_KEY:
        raise ValueError(
            "Missing GREENPT_API_KEY. Set it in your environment or a .env file."
        )
    return {
        "Authorization": f"Bearer {GREENPT_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@lru_cache(maxsize=1)
def list_greenpt_models() -> List[str]:
    """Fetch available model IDs so users can pick a valid one."""
    response = requests.get(
        DEFAULT_GREENPT_MODELS_URL,
        headers=_greenpt_headers(),
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    models = [item["id"] for item in data.get("data", []) if "id" in item]
    return models or [DEFAULT_MODEL]


def call_greenpt_chat(prompt: str, tone: Optional[str] = None, model: Optional[str] = None) -> str:
    """
    Call the GreenPT chat API using a system prompt + user message.
    """
    messages: List[dict] = [
        {"role": "system", "content": GREENPT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": prompt if not tone else f"{prompt}\n\nPreferred tone: {tone}",
        },
    ]

    payload = {
        "model": model or GREENPT_MODEL,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 600,
    }

    response = requests.post(
        GREENPT_API_URL,
        json=payload,
        headers=_greenpt_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    choices = data.get("choices") or []
    if not choices:
        raise ValueError("GreenPT returned no choices in the response.")

    message = choices[0].get("message") or {}
    content = (message.get("content") or "").strip()
    if not content:
        content = (data.get("summary") or data.get("message") or "").strip()

    if not content:
        raise ValueError("GreenPT did not include any assistant content.")

    return content


def sanitize_project_slug(name: str) -> str:
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.lower())
    slug = slug.strip("-_") or "greenpt-project"
    return slug[:60]


def extract_json_array(raw_text: str) -> List[dict]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        fence_lines = cleaned.splitlines()
        if fence_lines:
            first_line = fence_lines[0].strip("`").strip()
            if first_line.lower() == "json":
                fence_lines = fence_lines[1:]
        if fence_lines and fence_lines[-1].strip().startswith("```"):
            fence_lines = fence_lines[:-1]
        cleaned = "\n".join(fence_lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1:
            return json.loads(cleaned[start : end + 1])
        raise


def generate_build_plan(blueprint: str, tone: Optional[str], model: str) -> List[dict]:
    prompt = BUILD_PLAN_PROMPT.format(blueprint=blueprint)
    plan_text = call_greenpt_chat(prompt, tone, model)
    plan = extract_json_array(plan_text)
    if not isinstance(plan, list) or not plan:
        raise ValueError("Build plan response was empty.")
    return plan


def generate_file_content(
    file_spec: dict,
    blueprint: str,
    tone: Optional[str],
    model: str,
) -> str:
    prompt = FILE_GENERATION_PROMPT.format(
        path=file_spec.get("path", "file.txt"),
        file_type=file_spec.get("type", "config"),
        description=file_spec.get("description", ""),
        instructions=file_spec.get("instructions", ""),
        blueprint=blueprint,
    )
    return call_greenpt_chat(prompt, tone, model)


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
    created_files: List[Path] = []
    total = len(plan)
    for idx, spec in enumerate(plan, start=1):
        rel_path = Path(spec.get("path", "output.txt"))
        target_path = base_dir / rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = generate_file_content(spec, blueprint, tone, model)
        target_path.write_text(content, encoding="utf-8")
        created_files.append(target_path)
        if progress_callback:
            progress_callback(idx, total, spec)
    return created_files


def package_directory(directory: Path) -> Tuple[str, bytes]:
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


def main() -> None:
    st.set_page_config(page_title="GreenPT Idea Assistant", page_icon="🧠")
    st.title("GreenPT Idea Assistant")
    st.caption("Chat live with GreenPT's LLM about your project.")

    selected_sections: Sequence[Tuple[str, str]] = DEFAULT_BLUEPRINT_SECTIONS
    detail_mode = "Detailed blueprint"
    auto_build = False
    project_name = "greenpt-starter"

    with st.sidebar:
        tone = st.selectbox(
            "Preferred tone",
            options=[
                "Visionary",
                "Practical",
                "Data-driven",
                "Inspirational",
                "Playful",
            ],
            index=0,
        )

        try:
            available_models = list_greenpt_models()
        except ValueError as missing_key:
            st.error(str(missing_key))
            available_models = [GREENPT_MODEL]
        except requests.HTTPError as http_err:
            if http_err.response is not None and http_err.response.status_code == 401:
                st.error(
                    "GreenPT says the API key is invalid (401). Double-check "
                    "`GREENPT_API_KEY` and try again."
                )
            else:
                st.warning(f"Could not list models: {http_err}")
            available_models = [GREENPT_MODEL]
        except requests.RequestException as req_err:
            st.warning(f"Could not reach GreenPT to list models: {req_err}")
            available_models = [GREENPT_MODEL]

        model_choice = st.selectbox(
            "GreenPT model",
            options=available_models,
            index=min(available_models.index(GREENPT_MODEL), len(available_models) - 1)
            if GREENPT_MODEL in available_models
            else 0,
        )

        deliverable_labels = [section[0] for section in DEFAULT_BLUEPRINT_SECTIONS]
        selected_labels = st.multiselect(
            "Deliverables",
            options=deliverable_labels,
            default=deliverable_labels,
            help="Select which sections the assistant should generate.",
        )

        if selected_labels:
            selected_sections = [
                section
                for section in DEFAULT_BLUEPRINT_SECTIONS
                if section[0] in selected_labels
            ]
        else:
            selected_sections = DEFAULT_BLUEPRINT_SECTIONS
            st.info("All deliverables are required for a full blueprint. Using defaults.")

        detail_mode = st.selectbox(
            "Detail level",
            options=list(DETAIL_LEVELS.keys()),
            index=1,
        )

        auto_build = st.checkbox(
            "Auto-build project files",
            value=False,
            help="After the blueprint response, automatically generate source files and a downloadable zip.",
        )

        project_name = st.text_input(
            "Project name / slug",
            value="greenpt-starter",
            help="Used for the generated folder + zip file names.",
        )

        st.markdown("**System prompt in use**")
        st.code(GREENPT_SYSTEM_PROMPT)

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = [
            {
                "role": "assistant",
                "content": (
                    "Hi! I'm the GreenPT Idea Assistant. Tell me what you're building "
                    "and I'll suggest climate-positive next steps."
                ),
            }
        ]

    for message in st.session_state["chat_history"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    user_prompt = st.chat_input("Describe your idea...")
    if user_prompt:
        prompt_clean = user_prompt.strip()
        if not prompt_clean:
            st.warning("Please enter a short description of your idea.")
            return

        blueprint_prompt = build_blueprint_prompt(
            prompt_clean,
            selected_sections,
            DETAIL_LEVELS[detail_mode],
        )

        st.session_state["chat_history"].append(
            {"role": "user", "content": prompt_clean}
        )
        with st.chat_message("user"):
            st.markdown(prompt_clean)

        with st.chat_message("assistant"):
            with st.spinner("Calling GreenPT..."):
                try:
                    reply = call_greenpt_chat(blueprint_prompt, tone, model_choice)
                except ValueError as missing_key:
                    st.error(str(missing_key))
                    st.session_state["chat_history"].append(
                        {"role": "assistant", "content": f"⚠️ {missing_key}"}
                    )
                except requests.HTTPError as http_err:
                    error_text = http_err.response.text if http_err.response else str(
                        http_err
                    )
                    st.error(f"GreenPT returned an error: {error_text}")
                    st.session_state["chat_history"].append(
                        {"role": "assistant", "content": f"GreenPT error: {error_text}"}
                    )
                except requests.RequestException as req_err:
                    st.error(f"Could not reach GreenPT: {req_err}")
                    st.session_state["chat_history"].append(
                        {
                            "role": "assistant",
                            "content": "Could not reach GreenPT. Please try again.",
                        }
                    )
                else:
                    st.markdown(reply)
                    st.session_state["chat_history"].append(
                        {"role": "assistant", "content": reply}
                    )
                    st.session_state["last_blueprint"] = reply

                    if auto_build:
                        build_container = st.container()
                        with build_container:
                            st.subheader("Auto-build results")
                            try:
                                with st.spinner("Generating build plan..."):
                                    plan = generate_build_plan(
                                        reply, tone, model_choice
                                    )
                                st.success(f"Build plan ready: {len(plan)} files.")
                                st.json(plan)

                                slug = sanitize_project_slug(project_name)
                                
                                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                                project_dir = GENERATED_ROOT / f"{slug}-{timestamp}"
                                project_dir.mkdir(parents=True, exist_ok=True)

                                st.info(f"Writing files to `{project_dir}`")
                                progress_bar = st.progress(0.0)
                                status_placeholder = st.empty()

                                def _progress(idx: int, total: int, spec: dict) -> None:
                                    progress_bar.progress(idx / total)
                                    status_placeholder.write(
                                        f"Generated `{spec.get('path', 'file')}`"
                                    )

                                with st.spinner("Generating source files..."):
                                    created_files = write_files_from_plan(
                                        plan,
                                        project_dir,
                                        reply,
                                        tone,
                                        model_choice,
                                        _progress,
                                    )

                                st.success(f"Created {len(created_files)} files.")
                                zip_name, zip_bytes = package_directory(project_dir)
                                st.download_button(
                                    "Download project zip",
                                    data=zip_bytes,
                                    file_name=zip_name,
                                    mime="application/zip",
                                )
                                st.session_state["last_build"] = {
                                    "plan": plan,
                                    "project_dir": str(project_dir),
                                    "zip_name": zip_name,
                                }
                            except json.JSONDecodeError as json_err:
                                st.error(f"Could not parse build plan JSON: {json_err}")
                            except Exception as build_err:
                                st.error(f"Auto-build failed: {build_err}")

    st.divider()
    st.markdown(
        "Need API access? Set `GREENPT_API_KEY`, `GREENPT_MODEL`, and optionally "
        "`GREENPT_API_URL`/`GREENPT_SYSTEM_PROMPT` in an `.env` file before running "
        "`streamlit run greenpt_ui.py`."
    )


if __name__ == "__main__":
    main()

