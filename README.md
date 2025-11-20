## GreenPT Hackathon Idea Assistant (Streamlit UI)

GreenPT Hackathon Idea Assistant is a **Streamlit-based web UI** that helps you go from a rough hackathon idea to:

- A structured, multi-section **project blueprint** (architecture, APIs, data, frontend, DevOps, roadmap)
- Optional **auto-generated project files** packaged as a download-ready ZIP
- **Per-project chat history** so you can iterate, ask follow‑up questions, and tweak only specific parts

This repo is the UI layer that talks to the GreenPT API and manages projects, logs, and on-disk generated code.

---

### ✨ Key Features

- **Project-aware chat**
  - Each project has its own chat history, blueprint, and last auto-build result.
  - Switching projects in the sidebar instantly swaps the conversation context.
  - Follow-up questions reuse the existing blueprint instead of regenerating everything.

- **Configurable blueprints**
  - `Deliverables` multiselect lets you choose which sections to generate (Concept, Backend, APIs, Data, Frontend, DevOps, Roadmap).
  - `Detail level` controls how deep the blueprint goes (outline vs detailed vs execution playbook).

- **Auto-build project files**
  - When **Auto-build project files** is enabled, the app:
    1. Asks GreenPT for a JSON build plan (list of files to create).
    2. Generates each file’s content from the blueprint.
    3. Writes everything into `generated_projects/<project-slug>-<timestamp>/`.
    4. Packages the directory into a ZIP and exposes a **Download project zip** button.
  - Previous builds remain available under a **📦 Previous Build – Download** expander.

- **Per-project logs**
  - Every project’s chat history is persisted in `project_logs/<project-slug>.json`.
  - Logs include messages plus an `updated_at` UTC timestamp.

- **Interactive floating tutorial**
  - A multi-step overlay explains:
    - The **Projects** list and “Create New Project” area.
    - The **Deliverables** selector.
    - **Detail level** and **Auto-build** toggles.
    - The chat input and how to iterate.
    - How to download generated code.
  - The tutorial dims the background, supports Next / Back / Skip, and can be reopened from the sidebar.

- **Safer file generation**
  - All output paths are validated with `ensure_safe_path` to prevent directory traversal.
  - Generated code is confined to `generated_projects/` under the repo root.

---

### 🧱 Code Structure (High Level)

```text
.
├── greenpt_ui.py        # Main Streamlit app (UI + orchestration)
├── config.py            # Constants, prompts, paths, and initial assistant greeting
├── api_client.py        # GreenPT API client (chat, models, timeouts, retries)
├── project_manager.py   # Per-project state, slugs, and log persistence
├── file_generator.py    # Build plan + file content generation + ZIP packaging
├── project_logs/        # Saved chat histories per project (JSON)
└── generated_projects/  # Auto-built project directories and code
```

The goal is to keep the UI file (`greenpt_ui.py`) relatively thin by delegating API calls, project state, and file generation to dedicated modules.

---

### ⚙️ Prerequisites

- **Python** 3.8+  
- **pip** (or another package manager like `conda` if you prefer)
- A valid **GreenPT API key**

---

### 📦 Installation

1. Clone or download this repository.
2. Install dependencies (example using pip):

```bash
pip install -r requirements.txt
```

If you don’t have a `requirements.txt`, the core libraries you need are:

- `streamlit`
- `requests`
- `python-dotenv`
- plus any others already used in your environment.

---

### 🔐 Environment Configuration

Configure your GreenPT credentials via environment variables (recommended: a `.env` file in the project root).

```env
GREENPT_API_KEY=your_api_key_here
GREENPT_MODEL=greenpt-1
GREENPT_API_URL=https://api.greenpt.ai/v1/chat/completions
GREENPT_MODELS_URL=https://api.greenpt.ai/v1/models

# Optional: override the default system prompt
# GREENPT_SYSTEM_PROMPT="..."
```

`config.py` reads these values and falls back to sensible defaults if some are missing.

---

### ▶️ Running the App

From the project root:

```bash
streamlit run greenpt_ui.py
```

Streamlit will open a browser tab automatically (typically at `http://localhost:8501`).

---

### 🖱 How to Use the UI

1. **Start a project**
   - In the sidebar, you’ll see a **Projects** section.
   - Either select an existing project from the dropdown, or:
     - Type a new name into **New project name**.
     - Click **➕ Create & Switch** to create a new isolated workspace.

2. **Configure your blueprint**
   - Choose a **Preferred tone** (e.g., Visionary, Practical).
   - Pick a **GreenPT model** (fetched via `list_greenpt_models()`).
   - Use **Deliverables** to select which sections to generate.
   - Set **Detail level** (Concise outline / Detailed blueprint / Execution playbook).
   - Optionally enable **Auto-build project files** if you want code + ZIP automatically.

3. **Describe your hackathon idea**
   - Use the chat input at the bottom: describe your project, stack preferences, constraints, etc.
   - The assistant responds with a structured blueprint.
   - The very first full blueprint for a project is stored as that project’s `last_blueprint`.

4. **Auto-build (optional but powerful)**
   - If **Auto-build project files** is enabled:
     - The app asks GreenPT for a JSON build plan.
     - It generates all files under `generated_projects/<slug>-<timestamp>/`.
     - It then shows:
       - An “Auto-build results” section with the plan.
       - A **Download project zip** button.

5. **Iterate with follow-up questions**
   - Subsequent messages for a project reuse the stored blueprint and chat history.
   - The follow-up system prompt is tuned to:
     - Answer questions about specific sections.
     - Propose focused edits instead of rewriting everything.
   - Example follow-ups:
     - “Only update the API endpoints to support pagination.”
     - “Switch the database from DynamoDB to PostgreSQL, keep everything else the same.”

6. **Download code again later**
   - If you reopen a project that already has a build:
     - The main page shows a **📦 Previous Build – Download** expander.
     - It re-packages the stored directory (if it still exists) and gives you a fresh download button.

---

### 🧪 Error Handling & Robustness

- **Timeouts and retries**
  - `api_client.py` uses dynamic timeouts (based on `max_tokens`) and retries for network timeouts and transient API errors.
  - You’ll see clear error messages in the UI if the API is unreachable or too slow.

- **JSON parsing**
  - `file_generator.py` is defensive when parsing build plans:
    - Strips markdown fences.
    - Extracts the JSON array even if there’s extra text.
    - Provides detailed error messages including the raw response when parsing fails.

- **File system safety**
  - All file writes go through `ensure_safe_path` to avoid escaping the intended project directory.

---

### 🧭 Typical Hackathon Workflow

1. Brainstorm an idea and write 3–8 sentences describing it in the chat.
2. Let GreenPT generate a full blueprint with all deliverables.
3. Turn on **Auto-build** to scaffold a working codebase you can open in your IDE.
4. Iterate:
   - Ask focused questions.
   - Tweak modules (APIs, data model, frontend layout, infra).
5. Use the generated blueprint + code as your starting point for the final demo.

This UI is designed to keep you in flow during a hackathon: fewer tabs, less copy‑paste, and more time building and polishing your project.

<<<<<<< HEAD
=======
---

### 🔄 Recent Improvements & Next Ideas

- Floating onboarding modal now advances steps entirely on the client side, so **Next/Back/Skip** never reload the page and stay responsive even on slower networks.
- Tutorial state persists with browser storage, meaning once a user finishes or skips it the assistant stays out of the way on future visits while still allowing a refreshed tour after clearing storage.
- Next enhancements under consideration: adding a “Replay tutorial” action in the sidebar and letting the overlay spotlight exact UI controls with live highlights.

>>>>>>> feature/new-functions

