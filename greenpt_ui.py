"""Streamlit UI for GreenPT Idea Assistant."""
import traceback
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st

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


def main() -> None:
    st.set_page_config(page_title="GreenPT Idea Assistant", page_icon="🧠")
    st.title("GreenPT Idea Assistant")
    st.caption("Chat live with GreenPT's LLM about your project.")

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
        
        # 显示项目列表和消息数量
        if project_keys:
            st.markdown("**Your Projects:**")
            for proj_key in project_keys:
                proj_state = projects[proj_key]
                msg_count = len(proj_state.get("history", [])) - 1  # 减去初始问候
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
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    user_prompt = st.chat_input("Describe your idea...")
    if user_prompt:
        prompt_clean = user_prompt.strip()
        if not prompt_clean:
            st.warning("Please enter a short description of your idea.")
            return

        is_follow_up = bool(project_state.get("last_blueprint"))
        project_state["history"].append({"role": "user", "content": prompt_clean})

        if is_follow_up:
            # 后续对话：基于已有蓝图进行对话
            blueprint = project_state["last_blueprint"]
            history_payload = [dict(msg) for msg in project_state["history"][:-1]]
        else:
            # 首次生成：使用完整的蓝图生成提示词
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
                        # 使用基于蓝图的对话函数
                        reply = call_greenpt_chat_with_blueprint(
                            prompt_clean,
                            blueprint,
                            tone,
                            model_choice,
                            history=history_payload,
                            max_tokens=2000,
                        )
                    else:
                        # 首次生成蓝图
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
