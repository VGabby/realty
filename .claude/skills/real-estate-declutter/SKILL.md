# Real Estate Declutter Skill (v1)

## 1. Trigger

Activate when the user says:
- `declutter <image-path>`
- `remove clutter from <image-path>`
- `clean up <image-path>` (real estate context)

## 2. Environment check

Before starting:
1. Confirm `GEMINI_API_KEY` is set: `echo $GEMINI_API_KEY`
2. Confirm input file exists: `ls <input-path>`
3. Confirm `uv` is available: `uv --version`

Halt with a clear message if any check fails.

## 3. Run setup

```bash
run_id = "<YYYY-MM-DDTHH-MM-SSZ>_<stem>"   # e.g. 2026-04-22T10-00-00Z_livingroom-01
mkdir -p runs/<run_id>
cp <input> runs/<run_id>/input.jpg
```

Initialize `manifest.json` and `narration.md` in `runs/<run_id>/`.

## 4. Planning step

```bash
uv run pipeline-plan --input runs/<run_id>/input.jpg --out runs/<run_id>/plan.json
```

Parse the JSON stdout to confirm success. Append plan block to narration. On failure: record error, halt.

## 5. Phase 1 loop (Broad Removal)

Threshold: `config.phase1_threshold` (default 7.0) · Max attempts: `config.max_retries["phase1"]` (default 3)

See pseudocode in §10.

## 6. Phase 2 loop (Surgical Fixes)

Threshold: `config.phase2_threshold` (default 8.0) · Max attempts: `config.max_retries["phase2"]` (default 2)

Input: Phase 1 `final_output.path`. Same loop shape as Phase 1.

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

Append to `narration.md` after each step using the **exact templates** from SPEC.md §8.7. No prose outside templates. Substituting only `{}` placeholders.

## 10. Pseudocode

```pseudocode
# Real Estate Declutter — Phase Loop (v1 · pseudocode, not executable)

GIVEN: input_image_path, optional config_path
       config := load(config_path) OR RunConfig()  # defaults per §8.2

# ── Setup ─────────────────────────────────────────────────────────
run_id    := f"{utc_now_iso_compact()}_{stem(input_image_path)}"
run_dir   := Path("runs") / run_id
mkdir run_dir
copy input_image_path → run_dir/input.jpg
manifest := new Manifest(schema_version=1, run_id=run_id, created_at=utc_now(),
                          input=ImageRef.from_file(run_dir/input.jpg),
                          config=config, phases=[])
narration := open(run_dir/narration.md, "a")
narrate_header(narration, manifest)

# ── Plan ──────────────────────────────────────────────────────────
narrate_section(narration, "## Plan")
try:
    plan_json := bash("pipeline-plan --input {run_dir}/input.jpg --out {run_dir}/plan.json")
    manifest.plan := EditPlan.model_validate_json(read(run_dir/plan.json))
    narrate_plan(narration, manifest.plan)
except CLIError as e:
    record_error(manifest, phase="plan", error=e); write(manifest); HALT

# ── Phase helpers ─────────────────────────────────────────────────
def run_phase(phase_id, threshold, max_attempts, source_path):
    phase := new PhaseRecord(phase_id=phase_id,
                             name=("broad_removal" if phase_id==1 else "surgical_fixes"),
                             prompt_file=f"prompts/phase{phase_id}_{...}.md",
                             attempts=[])
    hint := None
    FOR attempt IN 1..max_attempts:
        narrate_attempt_header(narration, phase_id, attempt)
        out_path := run_dir / f"phase{phase_id}_attempt{attempt}.jpg"
        review_path := run_dir / f"phase{phase_id}_attempt{attempt}_review.json"
        try:
            edit_meta := bash("pipeline-edit --phase {phase_id} \
                --input {source_path} --plan {run_dir}/plan.json \
                --attempt {attempt} --hint '{hint or ""}' --out {out_path}")
            verdict_meta := bash("pipeline-review --phase {phase_id} \
                --image {out_path} --out {review_path}")
        except CLIError as e:
            record_error(manifest, phase=f"phase{phase_id}", error=e); write(manifest); HALT
        rec := AttemptRecord(attempt=attempt, ..., hint=hint,
                             edit_output=ImageRef.from_json(edit_meta),
                             review=Verdict.model_validate_json(read(review_path)),
                             accepted=(verdict.score >= threshold),
                             retry_reason=None)
        phase.attempts.append(rec)
        narrate_attempt_body(narration, rec)
        IF rec.accepted:
            phase.final_output := rec.edit_output
            phase.accepted := True
            BREAK
        ELSE IF attempt < max_attempts:
            hint := synthesize_hint(rec.review.issues, rec.review.suggestions)
            rec.retry_reason := f"score {rec.review.score} < {threshold}; hint: {hint!r}"
            narrate_retry(narration, rec.retry_reason)
        ELSE:
            best := argmax(phase.attempts, key=lambda a: a.review.score)
            phase.final_output := best.edit_output
            phase.accepted := False
            narrate_escalation(narration, phase_id, best.review.score, threshold)
    RETURN phase

# ── Phase 1: Broad removal (threshold 7.0, max 3 attempts) ────────
p1 := run_phase(phase_id=1, threshold=config.phase1_threshold,
                max_attempts=config.max_retries["phase1"],
                source_path=run_dir/"input.jpg")
manifest.phases.append(p1)

# ── Phase 2: Surgical fixes (threshold 8.0, max 2 attempts) ───────
p2 := run_phase(phase_id=2, threshold=config.phase2_threshold,
                max_attempts=config.max_retries["phase2"],
                source_path=p1.final_output.path)
manifest.phases.append(p2)

# ── Finalize ──────────────────────────────────────────────────────
copy p2.final_output.path → run_dir/final.jpg
manifest.final_output := ImageRef.from_file(run_dir/final.jpg)
manifest.outcome := "accepted" if (p1.accepted and p2.accepted) else "escalated"
manifest.completed_at := utc_now()
write_manifest(run_dir/manifest.json, manifest)
narrate_final(narration, manifest)
PRINT run_dir
```

## 11. Retry hint synthesis

Given `verdict.issues` and `verdict.suggestions`, produce a single-sentence imperative hint of ≤120 chars:
- If `suggestions` is non-empty: use `suggestions[0]` verbatim (truncated to 120 chars).
- Else: rephrase `issues[0]` as a positive instruction (e.g., "shadow under bottle remains" → "preserve the soft shadow gradient where objects were removed").

The raw `issues` + `suggestions` stay in the manifest; only the synthesized hint is passed to `--hint`.
