# Virtual Staging Skill (v1)

## 1. Trigger

Activate when the user says:
- `stage <image-path>`
- `virtually stage <image-path>`
- `add furniture to <image-path>`

## 2. Environment check

Before starting:
1. Confirm `GEMINI_API_KEY` is set: `echo $GEMINI_API_KEY`
2. Confirm input file exists: `ls <input-path>`
3. Confirm `uv` is available: `uv --version`

Halt with a clear message if any check fails.

## 3. Run setup

```bash
run_id = "<YYYY-MM-DDTHH-MM-SSZ>_stage_<stem>"   # e.g. 2026-04-22T10-00-00Z_stage_bedroom-01
mkdir -p runs/<run_id>
cp <input> runs/<run_id>/input.jpg
```

Initialize `manifest.json` and `narration.md` in `runs/<run_id>/`.

## 4. Planning step

Virtual staging skips the declutter-plan step. Instead, build a minimal EditPlan directly:

```json
{
  "removable_objects": [],
  "structural_keep": ["all existing architectural elements"],
  "rationale": "Virtual staging: add furniture and decor to empty/sparse room.",
  "phase1_instructions": "Add tasteful, listing-appropriate furniture per the system prompt.",
  "phase2_instructions": "Refine staging: fix shadow mismatches, edge seams, and lighting inconsistencies."
}
```

Write this to `runs/<run_id>/plan.json`.

## 5. Phase 1 loop (Initial Staging)

Threshold: 7.0 · Max attempts: 3

```bash
pipeline-edit --phase 1 \
  --input runs/<run_id>/input.jpg \
  --plan runs/<run_id>/plan.json \
  --attempt <n> \
  --hint "<hint or empty>" \
  --out runs/<run_id>/phase1_attempt<n>.jpg \
  --prompt-file .claude/skills/virtual-staging/prompts/phase1_generate.md
```

Review with staging rubric:
```bash
pipeline-review --phase 1 \
  --image runs/<run_id>/phase1_attempt<n>.jpg \
  --out runs/<run_id>/phase1_attempt<n>_review.json \
  --rubric-file .claude/skills/virtual-staging/prompts/review_rubric.md
```

## 6. Phase 2 loop (Refinement)

Threshold: 8.5 · Max attempts: 2

Input: Phase 1 `final_output.path`. Same loop shape, using `phase2_refine.md`:

```bash
pipeline-edit --phase 2 \
  --input runs/<run_id>/phase1_final.jpg \
  --plan runs/<run_id>/plan.json \
  --attempt <n> \
  --hint "<hint or empty>" \
  --out runs/<run_id>/phase2_attempt<n>.jpg \
  --prompt-file .claude/skills/virtual-staging/prompts/phase2_refine.md

pipeline-review --phase 2 \
  --image runs/<run_id>/phase2_attempt<n>.jpg \
  --out runs/<run_id>/phase2_attempt<n>_review.json \
  --rubric-file .claude/skills/virtual-staging/prompts/review_rubric.md
```

## 7. Finalize

```bash
cp runs/<run_id>/phase2_attempt<n>.jpg runs/<run_id>/final.jpg
```

Set `outcome = "accepted"` if both phases accepted, else `"escalated"`. Write final manifest. Append final narration block. Print `runs/<run_id>`.

## 8. Error handling

On any CLI exit ≠ 0:
1. Record `ErrorRecord` in manifest with `stderr_tail` (last 2KB).
2. Append error block to narration.
3. Write manifest. Halt.

## 9. Narration contract

Same narration templates as declutter skill (SPEC.md §8.7). Use `stage` instead of `declutter` in run_id prefix for clarity. No prose outside templates.

## 10. Retry hint synthesis

Same rules as declutter skill: use `suggestions[0]` verbatim if non-empty, else rephrase `issues[0]` as a positive instruction. Max 120 chars.

## 11. Rubric axes (staging-specific)

| Axis | Weight | Meaning |
|---|---|---|
| `staging_authenticity` | 0.4 | Physical realism — shadows, reflections, scale |
| `style_coherence` | 0.4 | Aesthetic match to room — finishes, period, appeal |
| `technical_quality` | 0.2 | Edge seams, lighting consistency |

Note: these axis names differ from the declutter rubric (`realism`, `completeness`, `artifacts`). The Verdict JSON schema accommodates both since `rubric` is a dict. The composite formula in the review rubric prompt overrides the score calculation.
