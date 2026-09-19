# Bounded worker context

Use this reference for long packages or repeated context recovery. Compaction alone is neither a failure nor a reason to replace a worker. A screenshot or count does not establish how much work occurred between compactions. Look for new verified behavior and whether recovery repeats work already completed. These are provisional workflow rules, not measured improvements to model performance.

## Keep reads and output focused

Search for the relevant symbols and read bounded sections before loading entire files. Load only instructions and references relevant to the package. Save verbose test/build output to a package-local file, retain the actual exit status, and inspect a summary plus relevant failures. Summarizing output must not hide failing checks. Avoid repeatedly printing unchanged files, full diffs, histories, or logs; retain paths and inspect changed areas as needed. Do not truncate away evidence needed for correctness.

## Keep one working checkpoint

For a long package, use an existing package plan or one local file at the path supplied in the brief, such as `work/astra-helm/<run-id>/<assignment-id>-checkpoint.md`. The worker owns this file; it is not a coordinator journal. Keep it out of published source unless the project explicitly requires it. Prefer a short current-state note over an append-only transcript. Include:

- the bounded deliverable, acceptance criteria, and critical constraints;
- current decisions and invariants, owned/changed files, and relevant source identity;
- verified behavior, exact checks and evidence paths, and what those checks do not prove;
- remaining failures or blockers, active command/session IDs and their status, and the exact next step.

Update it at meaningful milestones, before a planned handoff, or when key state changes. Do not write it after every tool call or send it to the parent for routine approval. On resumption, read it and confirm relevant source/environment state; resume the next step without replaying valid checks or rediscovering settled decisions. The note is a navigation aid, not proof that a test passed; consult referenced evidence when needed. Never mark an active command complete because context was compacted.

## Reassess recovery that displaces progress

Repeated rediscovery, broad rereads, rerunning unchanged passing checks, or repeated promises to finish without closing a behavioral slice warrant reassessment. First narrow reads, repair the checkpoint, and keep the current worker moving. Compaction with continued verified progress needs no intervention.

If recovery remains material, report the concrete repeated work once at a natural milestone as an impediment to package completion. Astra can narrow the remaining package or accept a completed coherent slice before handing off the remainder with a fresh brief and checkpoint. Preserve unresolved requirements and the parent scope. Keep a tightly coupled slice with its owner until a safe boundary; do not reset mid-edit, add overlapping ownership, or wait for acknowledgement at every milestone. Stop an old worker before assigning overlapping replacement work.

Record a material scope change in the existing replan/report events with the evidence, completed slice, remaining work and next action. Do not invent compaction counts or token usage when they are unavailable. Do not change model, effort, context limits, or worker solely because a compaction occurred.
