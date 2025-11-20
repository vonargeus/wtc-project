"""Streamlit UI for GreenPT Idea Assistant."""
import json
import re
import traceback
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st
from streamlit.components.v1 import html

from api_client import (
    call_greenpt_chat,
    call_greenpt_chat_with_blueprint,
    list_greenpt_models,
)
from config import (
    DEFAULT_BLUEPRINT_SECTIONS,
    DETAIL_LEVELS,
    GENERATED_ROOT,
    GREENPT_MODEL,
    PROJECT_LOGS_ROOT,
)
from file_generator import (
    build_blueprint_prompt,
    generate_build_plan,
    package_directory,
    write_files_from_plan,
)
from project_manager import (
    get_or_create_project_state,
    sanitize_project_slug,
    save_project_log,
)


def get_tutorial_steps() -> list[dict]:
    """Return the sequence of tutorial steps for the floating modal."""
    return [
        {
            "title": "🎯 Welcome to your hackathon assistant",
            "content": (
                "This page helps you turn a rough hackathon idea into a clear blueprint "
                "and ready-to-download project code. In a few steps you will create a project, "
                "describe your idea, and let the assistant build a starter codebase for you."
            ),
            "position": "center",
        },
        {
            "title": "📁 Projects & chat history",
            "content": (
                "Use the Projects area in the sidebar to switch between or create hackathon projects. "
                "Each project has its own chat history, blueprint, and build artifacts, so experiments "
                "stay isolated and you can come back to them later."
            ),
            "position": "left",
        },
        {
            "title": "🧩 Deliverables you want",
            "content": (
                "The Deliverables multiselect in the sidebar lets you choose which blueprint sections to generate, "
                "such as Backend, APIs, Data, Frontend, DevOps, and Roadmap. Pick only what you need for this "
                "project to keep results focused."
            ),
            "position": "left",
        },
        {
            "title": "⚙️ Detail level & Auto-build",
            "content": (
                "Use Detail level to choose between a short outline, a detailed blueprint, or a full execution playbook. "
                "Turn on Auto-build project files when you are ready for the assistant to generate real source code and "
                "package it into a ZIP."
            ),
            "position": "left",
        },
        {
            "title": "💬 Describe your idea",
            "content": (
                "Type your hackathon idea in the chat box at the bottom, including the problem, target users, "
                "and preferred tech stack. The assistant will answer with a structured blueprint you can iterate "
                "on with follow-up questions."
            ),
            "position": "bottom",
        },
        {
            "title": "📦 Download & iterate",
            "content": (
                "After Auto-build completes, use the Download project zip button in the main area or the Previous Build "
                "section to grab your code. Keep chatting in the same project to refine specific parts without losing "
                "your existing blueprint."
            ),
            "position": "center",
        },
    ]


def _remove_tutorial_dom() -> None:
    """Remove tutorial overlay DOM nodes from the parent document."""
    cleanup_script = """
    <script>
    (function() {
        const doc = window.parent?.document;
        if (!doc) { return; }
        const root = doc.getElementById('tutorial-root');
        if (root) { root.remove(); }
        const style = doc.getElementById('tutorial-style');
        if (style) { style.remove(); }
        const handler = doc.getElementById('tutorial-handler');
        if (handler) { handler.remove(); }
    })();
    </script>
    """.strip()
    html(cleanup_script, height=0, width=0)


def _render_tutorial_dom(body_html: str, css_block: str) -> None:
    """Inject the tutorial overlay into the parent document via JS."""
    payload = f"""
    <script>
    (function() {{
        const doc = window.parent?.document;
        if (!doc) {{ return; }}

        const existingRoot = doc.getElementById('tutorial-root');
        if (existingRoot) {{ existingRoot.remove(); }}
        const existingStyle = doc.getElementById('tutorial-style');
        if (existingStyle) {{ existingStyle.remove(); }}
        const existingHandler = doc.getElementById('tutorial-handler');
        if (existingHandler) {{ existingHandler.remove(); }}

        const styleEl = doc.createElement('style');
        styleEl.id = 'tutorial-style';
        styleEl.textContent = {json.dumps(css_block)};
        doc.head.appendChild(styleEl);

        const wrapper = doc.createElement('div');
        wrapper.id = 'tutorial-root';
        wrapper.innerHTML = {json.dumps(body_html)};
        doc.body.appendChild(wrapper);

        const handlerScript = doc.createElement('script');
        handlerScript.id = 'tutorial-handler';
        handlerScript.type = 'text/javascript';
        handlerScript.textContent = `
            (function() {{
                function wireTutorialButtons() {{
                    const overlayRoot = document.getElementById('tutorial-root');
                    if (!overlayRoot) {{ return; }}
                    overlayRoot.querySelectorAll('[data-action]').forEach(function(btn) {{
                        btn.addEventListener('click', function(evt) {{
                            evt.preventDefault();
                            const action = btn.getAttribute('data-action');
                            const url = new URL(window.location.href);
                            url.searchParams.set('tutorial_action', action);
                            window.location.href = url.toString();
                        }});
                    }});
                }}
                wireTutorialButtons();
            }})();
        `;
        doc.body.appendChild(handlerScript);
    }})();
    </script>
    """.strip()
    html(payload, height=0, width=0)


def show_tutorial_modal() -> None:
    """Display a floating tutorial modal on top of the whole page."""
    # If the user has dismissed the tutorial, do nothing
    if st.session_state.get("tutorial_dismissed", False):
        _remove_tutorial_dom()
        return

    # Initialize step index
    if "tutorial_step" not in st.session_state:
        st.session_state["tutorial_step"] = 0

    tutorial_steps = get_tutorial_steps()
    current_step = st.session_state["tutorial_step"]

    # Handle navigation actions via query params
    query_params = st.query_params
    action = query_params.get("tutorial_action")
    if action:
        if action == "skip":
            st.session_state["tutorial_dismissed"] = True
            st.session_state["tutorial_step"] = 0
        elif action == "prev":
            st.session_state["tutorial_step"] = max(0, current_step - 1)
        elif action == "next":
            if current_step < len(tutorial_steps) - 1:
                st.session_state["tutorial_step"] = current_step + 1
            else:
                st.session_state["tutorial_dismissed"] = True
        elif action == "finish":
            st.session_state["tutorial_dismissed"] = True
            st.session_state["tutorial_step"] = 0

        st.query_params.clear()
        st.rerun()

    # Refresh step index
    current_step = st.session_state.get("tutorial_step", 0)

    if st.session_state.get("tutorial_dismissed", False):
        _remove_tutorial_dom()
        return
    if current_step < 0 or current_step >= len(tutorial_steps):
        return

    step = tutorial_steps[current_step]

    # CSS Positioning
    position_map = {
        "center": "top: 50%; left: 50%; transform: translate(-50%, -50%);",
        "left": "top: 140px; left: 370px;",  # Shifted right to not cover sidebar
        "bottom": "bottom: 200px; left: 50%; transform: translateX(-50%);",
    }
    position_style = position_map.get(step.get("position", "center"), position_map["center"])

    total_steps = len(tutorial_steps)

    # Logic for buttons
    is_last = current_step == total_steps - 1
    next_label = "Finish" if is_last else "Next"
    next_action = "finish" if is_last else "next"

    title = step.get("title", "")
    content = step.get("content", "")

    buttons = [
        '<button class="tutorial-btn tutorial-btn-quiet" data-action="skip">Skip</button>'
    ]
    if current_step > 0:
        buttons.append(
            '<button class="tutorial-btn tutorial-btn-secondary" data-action="prev">Back</button>'
        )
    buttons.append(
        f'<button class="tutorial-btn tutorial-btn-primary" data-action="{next_action}">{next_label}</button>'
    )

    body_html = f"""
    <div class="tutorial-overlay"></div>
    <div class="tutorial-modal">
        <div class="tutorial-header">
            <h3 class="tutorial-title">{title}</h3>
            <span class="tutorial-count">{current_step + 1}/{total_steps}</span>
        </div>
        <div class="tutorial-content">{content}</div>
        <div class="tutorial-buttons">{''.join(buttons)}</div>
    </div>
    """.strip()

    css_block = f"""
    .tutorial-overlay {{
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background-color: rgba(0, 0, 0, 0.6);
        z-index: 999990;
        backdrop-filter: blur(2px);
    }}
    .tutorial-modal {{
        position: fixed;
        z-index: 999999;
        background: #ffffff;
        border-radius: 12px;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        padding: 24px;
        width: 400px;
        max-width: 90vw;
        font-family: sans-serif;
        color: #333;
        {position_style}
    }}
    .tutorial-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 16px;
        border-bottom: 1px solid #eee;
        padding-bottom: 8px;
    }}
    .tutorial-title {{
        margin: 0;
        font-size: 18px;
        font-weight: 700;
        color: #1f77b4;
    }}
    .tutorial-count {{
        font-size: 12px;
        color: #999;
    }}
    .tutorial-content {{
        font-size: 15px;
        line-height: 1.5;
        margin-bottom: 20px;
        color: #444;
    }}
    .tutorial-buttons {{
        display: flex;
        justify-content: flex-end;
        gap: 10px;
    }}
    .tutorial-btn {{
        text-decoration: none;
        padding: 8px 16px;
        border-radius: 6px;
        font-size: 14px;
        font-weight: 600;
        display: inline-block;
        cursor: pointer;
        border: 1px solid transparent;
        background: #f5f5f5;
        color: #333;
    }}
    .tutorial-btn-primary {{
        background-color: #ff4b4b;
        color: #fff;
        border-color: #ff4b4b;
    }}
    .tutorial-btn-primary:hover {{
        background-color: #ff2b2b;
    }}
    .tutorial-btn-secondary {{
        background-color: #fff;
        color: #333;
        border-color: #ccc;
    }}
    .tutorial-btn-secondary:hover {{
        background-color: #f0f0f0;
    }}
    .tutorial-btn-quiet {{
        background: transparent;
        color: #888;
        border: none;
    }}
    .tutorial-btn-quiet:hover {{
        color: #333;
        background: #f5f5f5;
    }}
    """.strip()

    _render_tutorial_dom(body_html, css_block)

def _clean_project_histories():
    projects = st.session_state.get("projects", {})
    for key, pstate in projects.items():
        new_history = []
        for msg in pstate.get("history", []):
            content = msg.get("content", "") if isinstance(msg, dict) else ""
            # Drop tutorial markup so it never persists into chat history
            if isinstance(content, str) and (
                '<div class="tutorial-modal"' in content
                or "<style>" in content
                or '<div class="tutorial-overlay"' in content
            ):
                continue
            # Trim leading whitespace to avoid Markdown auto code blocks
            if isinstance(content, str):
                msg["content"] = content.lstrip()
            new_history.append(msg)
        pstate["history"] = new_history

_clean_project_histories()


def main() -> None:
    st.set_page_config(page_title="GreenPT Idea Assistant", page_icon="🧠")
    st.title("GreenPT Idea Assistant")
    st.caption("Chat live with GreenPT's LLM about your project.")

    # Show floating tutorial for new or returning users (can be dismissed)
    show_tutorial_modal()

    default_project = sanitize_project_slug(
        st.session_state.get("active_project", "greenpt-starter")
    )
    get_or_create_project_state(default_project)
    st.session_state["active_project"] = default_project

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

        st.markdown("---")
        st.markdown("### 📁 Projects")
        
        projects = st.session_state["projects"]
        project_keys = sorted(projects.keys())
        
        # Show project list and message count
        if project_keys:
            st.markdown("**Your Projects:**")
            for proj_key in project_keys:
                proj_state = projects[proj_key]
                msg_count = len(proj_state.get("history", [])) - 1  # Subtract initial greeting
                has_blueprint = "✓" if proj_state.get("last_blueprint") else "○"
                is_active = "**→**" if proj_key == st.session_state["active_project"] else ""
                st.markdown(f"{is_active} {has_blueprint} `{proj_key}` ({msg_count} messages)")
        
        active_project = st.selectbox(
            "Switch to project",
            options=project_keys,
            index=project_keys.index(st.session_state["active_project"]) if st.session_state["active_project"] in project_keys else 0,
            help="Select a project to view its chat history",
        )
        st.session_state["active_project"] = active_project

        st.markdown("**Create New Project:**")
        new_project_name = st.text_input(
            "New project name",
            value="",
            placeholder="e.g., carbon-tracker",
            label_visibility="collapsed",
        )
        if st.button("➕ Create & Switch", use_container_width=True) and new_project_name.strip():
            new_slug = sanitize_project_slug(new_project_name)
            st.session_state["active_project"] = new_slug
            get_or_create_project_state(new_slug)
            st.rerun()

        st.markdown("---")
        log_hint_path = PROJECT_LOGS_ROOT / f"{st.session_state['active_project']}.json"
        st.caption(f"💾 Logs: `{log_hint_path}`")

    active_project = st.session_state["active_project"]
    project_state = get_or_create_project_state(active_project)

    if project_state.get("last_build"):
        with st.expander("📦 Previous Build - Download", expanded=False):
            build_info = project_state["last_build"]
            project_dir_str = build_info.get("project_dir", "")
            if project_dir_str and Path(project_dir_str).exists():
                st.info(f"Project directory: `{project_dir_str}`")
                try:
                    zip_name, zip_bytes = package_directory(Path(project_dir_str))
                    st.download_button(
                        "Download project zip",
                        data=zip_bytes,
                        file_name=zip_name,
                        mime="application/zip",
                        key=f"download_{active_project}",
                    )
                except Exception as e:
                    st.warning(f"Could not package project: {e}")
            else:
                st.warning("Project directory no longer exists.")

    for message in project_state["history"]:
        content = message.get("content", "")
        # 过滤掉残留的 tutorial HTML 或样式标签
        if not isinstance(content, str):
            content = str(content)
        if "<div class=\"tutorial-modal\"" in content or "<style>" in content or "<div class=\"tutorial-overlay\"" in content:
            continue
        # 去掉开头缩进，防止被识别为 code block（markdown 会把缩进当 code block）
        content = content.lstrip()
        with st.chat_message(message["role"]):
            st.markdown(content, unsafe_allow_html=False)

    user_prompt = st.chat_input("Describe your idea...")
    if user_prompt:
        prompt_clean = user_prompt.strip()
        if not prompt_clean:
            st.warning("Please enter a short description of your idea.")
            return

        is_follow_up = bool(project_state.get("last_blueprint"))
        project_state["history"].append({"role": "user", "content": prompt_clean})

        if is_follow_up:
            # Follow-up chat: chat based on existing blueprint
            blueprint = project_state["last_blueprint"]
            history_payload = [dict(msg) for msg in project_state["history"][:-1]]
        else:
            # First generation: use full blueprint prompt
            blueprint_prompt = build_blueprint_prompt(
                prompt_clean,
                selected_sections,
                DETAIL_LEVELS[detail_mode],
            )
        with st.chat_message("user"):
            st.markdown(prompt_clean)

        with st.chat_message("assistant"):
            with st.spinner("Calling GreenPT..."):
                try:
                    if is_follow_up:
                        # Use chat function with blueprint
                        reply = call_greenpt_chat_with_blueprint(
                            prompt_clean,
                            blueprint,
                            tone,
                            model_choice,
                            history=history_payload,
                            max_tokens=2000,
                        )
                    else:
                        # First time generating blueprint
                        reply = call_greenpt_chat(blueprint_prompt, tone, model_choice, max_tokens=2000)
                except ValueError as missing_key:
                    st.error(str(missing_key))
                    error_message = {"role": "assistant", "content": f"⚠️ {missing_key}"}
                    project_state["history"].append(error_message)
                    save_project_log(active_project, project_state["history"])
                except requests.HTTPError as http_err:
                    error_text = http_err.response.text if http_err.response else str(
                        http_err
                    )
                    st.error(f"GreenPT returned an error: {error_text}")
                    error_message = {
                        "role": "assistant",
                        "content": f"GreenPT error: {error_text}",
                    }
                    project_state["history"].append(error_message)
                    save_project_log(active_project, project_state["history"])
                except requests.RequestException as req_err:
                    st.error(f"Could not reach GreenPT: {req_err}")
                    error_message = {
                        "role": "assistant",
                        "content": "Could not reach GreenPT. Please try again.",
                    }
                    project_state["history"].append(error_message)
                    save_project_log(active_project, project_state["history"])
                else:
                    st.markdown(reply)
                    project_state["history"].append(
                        {"role": "assistant", "content": reply}
                    )
                    if not project_state.get("last_blueprint"):
                        project_state["last_blueprint"] = reply
                    save_project_log(active_project, project_state["history"])

                    if auto_build and not is_follow_up:
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

                                slug = sanitize_project_slug(active_project)

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
                                
                                project_state["last_build"] = {
                                    "plan": plan,
                                    "project_dir": str(project_dir),
                                    "zip_name": zip_name,
                                }
                                
                                st.download_button(
                                    "Download project zip",
                                    data=zip_bytes,
                                    file_name=zip_name,
                                    mime="application/zip",
                                )
                            except ValueError as val_err:
                                error_msg = str(val_err)
                                st.error(f"Build plan error: {error_msg}")
                                if "Raw response:" in error_msg:
                                    with st.expander("View raw response"):
                                        st.code(error_msg.split("Raw response:")[1].strip())
                            except Exception as build_err:
                                st.error(f"Auto-build failed: {build_err}")
                                with st.expander("Error details"):
                                    st.code(traceback.format_exc())


if __name__ == "__main__":
    main()