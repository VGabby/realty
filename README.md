# realty

Dynamic skill-based real estate image pipeline powered by Gemini. Each skill defines a catalog of phases; an LLM agent plans which phases to run, executes them, reviews the result, and replans on the fly — skipping phases that aren't needed and adding remediation phases when quality falls short.

## Skills

| Skill | Command | What it does |
|---|---|---|
| `real-estate-declutter` | `declutter <image>` | Removes portable clutter via inpainting, adds surgical cleanup only when needed |
| `virtual-staging` | `stage <image>` | Adds furniture and decor to empty rooms, refines only when staging quality is low |

## Setup

```bash
git clone <repo>
cd realty
uv sync
export GEMINI_API_KEY=<your-key>
```

## Usage

```bash
# Declutter a listing photo
uv run declutter samples/livingroom-01.jpg

# Virtually stage an empty room
uv run stage samples/empty-bedroom.jpg
```

Output per run: `runs/<id>/final.jpg`, `runs/<id>/manifest.json`, `runs/<id>/narration.md`

Open `viewer.html` in a browser and load any `manifest.json` to inspect the full run — phases, attempt scores, planner decisions, and before/after comparison.

## How it works

```
phases.json (skill catalog)
        ↓
default_entry_phase   ← no LLM call
        ↓
┌─────────────────────────────┐
│  execute()  →  verify()     │
│       ↓                     │
│  plan_next()  ──→ "done"    │
│       │                     │
│       └── "add_phase" → loop│
└─────────────────────────────┘
```

1. The pipeline loads the skill's `phases.json` catalog
2. Starts with the entry phase (e.g. `broad_removal`)
3. After each phase, a cheap LLM call reviews the result and decides: **done** or **add next phase**
4. Stops when quality is sufficient — surgical phases only run when needed

## Adding a new skill

Create `.claude/skills/<your-skill>/phases.json` with your phase catalog and prompt files. The pipeline engine (`src/pipeline/agent.py`) handles orchestration automatically.

## Tests

```bash
uv run pytest                   # unit tests (no network)
uv run pytest -m integration    # live Gemini tests (requires GEMINI_API_KEY)
uv run ruff check .             # lint
```
