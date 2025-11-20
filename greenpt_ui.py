"""Streamlit UI for GreenPT Idea Assistant."""
import hashlib
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
            "title": "🧩 Deliverables you want",
            "content": (
                "The Deliverables multiselect in the sidebar lets you choose which blueprint sections to generate, "
                "such as Backend, APIs, Data, Frontend, DevOps, and Roadmap. Pick only what you need for this "
                "project to keep results focused."
            ),
            "position": "deliverables",
            "scroll_target": "#tutorial-deliverables-anchor",
        },
        {
            "title": "⚙️ Detail level & Auto-build",
            "content": (
                "Detail level controls how deep the blueprint goes, from a quick outline to an execution playbook. "
                "Use the Auto-build toggle right below it when you are ready to generate runnable project files."
            ),
            "position": "detail",
            "scroll_target": "#tutorial-detail-anchor",
            "scroll_offset": 60,
        },
        {
            "title": "📁 Projects & chat history",
            "content": (
                "Use the Projects list in the sidebar to review previous runs, switch teams, or create a new one. "
                "Each project keeps its own chat history and build artifacts so experiments stay isolated."
            ),
            "position": "projects",
            "scroll_target": "#tutorial-projects-anchor",
            "scroll_offset": 140,
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
        const doc = window.parent?.document || document;
        if (!doc) { return; }
        const root = doc.getElementById('tutorial-root');
        if (root) { root.remove(); }
        const style = doc.getElementById('tutorial-style');
        if (style) { style.remove(); }
    })();
    </script>
    """.strip()
    html(cleanup_script, height=0, width=0)


def show_tutorial_modal() -> None:
    """Display a floating tutorial modal managed fully on the client."""
    tutorial_steps = get_tutorial_steps()
    if not tutorial_steps:
        _remove_tutorial_dom()
        return

    steps_signature = json.dumps(tutorial_steps, ensure_ascii=False, sort_keys=True)
    tutorial_version = hashlib.md5(steps_signature.encode("utf-8")).hexdigest()[:12]

    script_template = """
<script>
(function() {
    const steps = __STEPS_JSON__;
    const tutorialVersion = "__TUTORIAL_VERSION__";
    const rootWindow = window.parent || window;
    const doc = rootWindow.document;
    if (!doc || !Array.isArray(steps) || steps.length === 0) {
        return;
    }

    const dismissedKey = "greenptTutorialDismissed-" + tutorialVersion;
    const stepKey = "greenptTutorialStep-" + tutorialVersion;
    const sessionShownKey = "greenptTutorialShown-" + tutorialVersion;
    const localStorage = rootWindow.localStorage || window.localStorage;
    const sessionStorage = rootWindow.sessionStorage || window.sessionStorage;

    const hasSeenThisSession =
        sessionStorage && sessionStorage.getItem(sessionShownKey) === "true";
    const dismissedGlobally =
        localStorage && localStorage.getItem(dismissedKey) === "true";

    if (dismissedGlobally && hasSeenThisSession) {
        removeExisting();
        return;
    }

    let currentStep = 0;
    if (sessionStorage) {
        const stored = parseInt(sessionStorage.getItem(stepKey) || "0", 10);
        if (!Number.isNaN(stored)) {
            currentStep = Math.max(0, Math.min(stored, steps.length - 1));
        }
    }

    removeExisting();
    injectStyle();
    const wrapper = buildOverlay();
    doc.body.appendChild(wrapper);
    if (sessionStorage) {
        sessionStorage.setItem(sessionShownKey, "true");
    }
    attachHandlers(wrapper);
    renderStep();

    function injectStyle() {
        const existingStyle = doc.getElementById("tutorial-style");
        if (existingStyle) {
            existingStyle.remove();
        }
        const style = doc.createElement("style");
        style.id = "tutorial-style";
        style.textContent = `
            .tutorial-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                backdrop-filter: blur(2px);
                background-color: rgba(0, 0, 0, 0.6);
                z-index: 999990;
            }
            .tutorial-modal {
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
            }
            .tutorial-modal[data-position="center"] {
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
            }
            .tutorial-modal[data-position="left"] {
                top: 140px;
                left: 360px;
            }
            .tutorial-modal[data-position="deliverables"] {
                top: 110px;
                left: 360px;
            }
            .tutorial-modal[data-position="projects"] {
                top: 260px;
                left: 360px;
            }
            .tutorial-modal[data-position="bottom"] {
                bottom: 180px;
                left: 50%;
                transform: translateX(-50%);
            }
            .tutorial-modal[data-position="detail"] {
                top: 200px;
                left: 360px;
            }
            .tutorial-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 16px;
                border-bottom: 1px solid #eee;
                padding-bottom: 8px;
            }
            .tutorial-title {
                margin: 0;
                font-size: 18px;
                font-weight: 700;
                color: #1f77b4;
            }
            .tutorial-content {
                font-size: 15px;
                line-height: 1.5;
                margin-bottom: 20px;
                color: #444;
            }
            .tutorial-buttons {
                display: flex;
                justify-content: flex-end;
                gap: 10px;
            }
            .tutorial-btn {
                padding: 8px 16px;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
                border: 1px solid transparent;
                background: #f5f5f5;
                color: #333;
            }
            .tutorial-btn-primary {
                background-color: #ff4b4b;
                color: #fff;
                border-color: #ff4b4b;
            }
            .tutorial-btn-primary:hover {
                background-color: #ff2b2b;
            }
            .tutorial-btn-secondary {
                background-color: #fff;
                color: #333;
                border-color: #ccc;
            }
            .tutorial-btn-secondary:hover {
                background-color: #f0f0f0;
            }
            .tutorial-btn-quiet {
                background: transparent;
                color: #888;
                border: none;
            }
            .tutorial-btn-quiet:hover {
                color: #333;
                background: #f5f5f5;
            }
        `;
        doc.head.appendChild(style);
    }

    function buildOverlay() {
        const wrapper = doc.createElement("div");
        wrapper.id = "tutorial-root";
        wrapper.innerHTML = `
            <div class="tutorial-overlay"></div>
            <div class="tutorial-modal" data-position="center">
                <div class="tutorial-header">
                    <h3 class="tutorial-title"></h3>
                    <span class="tutorial-count"></span>
                </div>
                <div class="tutorial-content"></div>
                <div class="tutorial-buttons">
                    <button class="tutorial-btn tutorial-btn-quiet" data-action="skip">Skip</button>
                    <button class="tutorial-btn tutorial-btn-secondary" data-action="prev">Back</button>
                    <button class="tutorial-btn tutorial-btn-primary" data-action="next">Next</button>
                </div>
            </div>
        `;
        return wrapper;
    }

    function attachHandlers(wrapper) {
        wrapper.addEventListener("click", (event) => {
            const target = event.target.closest("[data-action]");
            if (!target) {
                return;
            }
            event.preventDefault();
            handleAction(target.getAttribute("data-action") || "");
        });
    }

    function handleAction(action) {
        if (action === "skip" || action === "finish") {
            dismiss();
            return;
        }
        if (action === "prev" && currentStep > 0) {
            currentStep -= 1;
            persistStep();
            renderStep();
            return;
        }
        if (action === "next" && currentStep < steps.length - 1) {
            currentStep += 1;
            persistStep();
            renderStep();
        }
    }

    function renderStep() {
        const step = steps[currentStep];
        if (!step) {
            return;
        }
        const root = doc.getElementById("tutorial-root");
        const modal = root?.querySelector(".tutorial-modal");
        if (!root || !modal) {
            return;
        }
        const titleEl = modal.querySelector(".tutorial-title");
        const countEl = modal.querySelector(".tutorial-count");
        const contentEl = modal.querySelector(".tutorial-content");
        const backBtn = modal.querySelector('[data-action="prev"]');
        const primaryBtn = modal.querySelector('[data-action="next"]');

        titleEl.textContent = step.title || "";
        countEl.textContent = String(currentStep + 1) + "/" + String(steps.length);
        contentEl.textContent = step.content || "";
        modal.setAttribute("data-position", step.position || "center");

        backBtn.style.visibility = currentStep === 0 ? "hidden" : "visible";

        if (currentStep === steps.length - 1) {
            primaryBtn.textContent = "Finish";
            primaryBtn.setAttribute("data-action", "finish");
        } else {
            primaryBtn.textContent = "Next";
            primaryBtn.setAttribute("data-action", "next");
        }

        focusSidebar(step);
    }

    function persistStep() {
        if (sessionStorage) {
            sessionStorage.setItem(stepKey, String(currentStep));
        }
    }

    function dismiss() {
        if (localStorage) {
            localStorage.setItem(dismissedKey, "true");
        }
        if (sessionStorage) {
            sessionStorage.removeItem(stepKey);
        }
        removeExisting();
    }

    function removeExisting() {
        const existingRoot = doc.getElementById("tutorial-root");
        if (existingRoot) {
            existingRoot.remove();
        }
        const style = doc.getElementById("tutorial-style");
        if (style) {
            style.remove();
        }
    }

    function focusSidebar(step) {
        const sidebar =
            doc.querySelector('section[data-testid="stSidebar"]') ||
            doc.querySelector('div[data-testid="stSidebar"]');
        if (!sidebar) {
            return;
        }
        if (step.scroll_target) {
            const target = doc.querySelector(step.scroll_target);
            if (target && typeof target.scrollIntoView === "function") {
                target.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        }
        if (step.scroll_offset) {
            const offset = Number(step.scroll_offset);
            if (!Number.isNaN(offset) && offset !== 0) {
                if (typeof sidebar.scrollBy === "function") {
                    sidebar.scrollBy({ top: offset, left: 0, behavior: "smooth" });
                } else {
                    sidebar.scrollTop += offset;
                }
            }
        }
    }
})();
</script>
""".strip()

    script = (
        script_template.replace("__STEPS_JSON__", json.dumps(tutorial_steps, ensure_ascii=False))
        .replace("__TUTORIAL_VERSION__", tutorial_version)
    )

    html(script, height=0, width=0)

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
    st.set_page_config(page_title="Hackathon Hacker", page_icon="👨‍💻")
    st.title("Hackathon Hacker")
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
        st.markdown('<div id="tutorial-deliverables-anchor"></div>', unsafe_allow_html=True)
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

        st.markdown('<div id="tutorial-detail-anchor"></div>', unsafe_allow_html=True)
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
        st.markdown('<div id="tutorial-projects-anchor"></div>', unsafe_allow_html=True)
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