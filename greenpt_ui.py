import os
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

DEFAULT_GREENPT_API_URL = "https://api.greenpt.ai/v1/ideas"
GREENPT_API_URL = os.getenv("GREENPT_API_URL", DEFAULT_GREENPT_API_URL)
GREENPT_API_KEY = os.getenv("GREENPT_API_KEY")


def call_greenpt(prompt: str, tone: Optional[str] = None) -> Tuple[str, List[Dict[str, str]]]:
    """
    Call the GreenPT API and normalize the result into a summary + three options.
    """
    if not GREENPT_API_KEY:
        raise ValueError(
            "Missing GREENPT_API_KEY. Set it in your environment or a .env file."
        )

    payload = {
        "prompt": prompt,
        "tone": tone,
        "max_options": 3,
    }

    headers = {
        "Authorization": f"Bearer {GREENPT_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    response = requests.post(
        GREENPT_API_URL,
        json=payload,
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    agent_summary = (
        data.get("agent_summary")
        or data.get("summary")
        or data.get("message")
        or "GreenPT responded without a summary."
    )

    raw_options = (
        data.get("options")
        or data.get("ideas")
        or data.get("choices")
        or []
    )

    normalized_options: List[Dict[str, str]] = []
    if isinstance(raw_options, list):
        for idx, option in enumerate(raw_options[:3], start=1):
            if isinstance(option, dict):
                option_id = option.get("id") or f"idea-{idx}"
                title = (
                    option.get("title")
                    or option.get("label")
                    or option.get("name")
                    or f"Idea {idx}"
                )
                description = (
                    option.get("description")
                    or option.get("text")
                    or option.get("summary")
                    or ""
                )
            else:
                option_id = f"idea-{idx}"
                title = f"Idea {idx}"
                description = str(option)

            normalized_options.append(
                {
                    "id": option_id,
                    "title": title.strip(),
                    "description": description.strip(),
                }
            )

    if not normalized_options:
        normalized_options = [
            {
                "id": "fallback-1",
                "title": "Prototype & Pilot",
                "description": "Set up a small-scale pilot to validate the idea with minimal resources.",
            },
            {
                "id": "fallback-2",
                "title": "Research & Partner",
                "description": "Collect supporting research and identify partners who can accelerate the idea.",
            },
            {
                "id": "fallback-3",
                "title": "Community Feedback",
                "description": "Share the concept with the community to capture early feedback.",
            },
        ]

    return agent_summary.strip(), normalized_options


def _select_option(option: Dict[str, str]) -> None:
    st.session_state["selected_option"] = option


def main() -> None:
    st.set_page_config(page_title="GreenPT Idea Assistant", page_icon="🧠")
    st.title("GreenPT Idea Assistant")
    st.caption(
        "Describe your idea and let GreenPT propose three actionable directions."
    )

    if "options" not in st.session_state:
        st.session_state["options"] = []
    if "agent_summary" not in st.session_state:
        st.session_state["agent_summary"] = ""
    if "selected_option" not in st.session_state:
        st.session_state["selected_option"] = None

    with st.form("idea_form", clear_on_submit=False):
        prompt = st.text_area(
            "What are you building?",
            placeholder="e.g. Circular packaging program for local restaurants",
        )
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
        submitted = st.form_submit_button("Ask GreenPT", use_container_width=True)

    if submitted:
        if not prompt.strip():
            st.warning("Please add a short description of your idea first.")
        else:
            with st.spinner("Calling GreenPT..."):
                try:
                    summary, options = call_greenpt(prompt.strip(), tone)
                except ValueError as missing_key:
                    st.error(str(missing_key))
                except requests.HTTPError as http_err:
                    st.error(f"GreenPT returned an error: {http_err.response.text}")
                except requests.RequestException as req_err:
                    st.error(f"Could not reach GreenPT: {req_err}")
                else:
                    st.session_state["agent_summary"] = summary
                    st.session_state["options"] = options
                    st.session_state["selected_option"] = None

    if st.session_state["agent_summary"]:
        st.subheader("Agent takeaway")
        st.write(st.session_state["agent_summary"])

    options = st.session_state["options"]
    if options:
        st.subheader("Pick your next move")
        cols = st.columns(len(options))
        for col, option in zip(cols, options):
            with col:
                st.button(
                    option["title"],
                    key=f"select-{option['id']}",
                    help=option["description"],
                    use_container_width=True,
                    on_click=_select_option,
                    args=(option,),
                )
                st.caption(option["description"])

    if st.session_state["selected_option"]:
        selection = st.session_state["selected_option"]
        st.success(f"You selected: {selection['title']}")
        if selection["description"]:
            st.info(selection["description"])

    st.divider()
    st.markdown(
        "Need API access? Set `GREENPT_API_KEY` (and optionally `GREENPT_API_URL`) "
        "in an `.env` file or your shell before running `streamlit run greenpt_ui.py`."
    )


if __name__ == "__main__":
    main()

