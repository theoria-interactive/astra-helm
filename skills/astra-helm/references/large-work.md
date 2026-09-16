# Large-work scheduling

Read this reference only for an epic, milestone, issue set, or genuinely large unstructured scope. Use an existing plan as the starting structure and preserve its identifiers and boundaries. If no usable breakdown exists, create stable local item IDs with explicit deliverables, dependencies, owned areas, and acceptance criteria. Split an oversized item when necessary while retaining its parent ID. Closely coupled small items may share one package when that reduces coordination cost.

Maintain a compact item table in the existing plan artifact or `work/astra-helm/<run-id>/plan.md`. Track parent, item ID, prerequisites, ownership, status, current assignment or agent ID, and evidence. Useful states include queued, running, awaiting review, corrections, accepted, and blocked. Preserve the plan path and current queue in handoff or compaction notes; update the artifact rather than repeating the full plan in messages.

Before dispatch, settle shared contracts enough to make ready packages independent. Give shared files one owner or sequence their writes. Use supported isolated checkouts only when needed and include integration. Never assign conflicting edits concurrently. Select the worker model and effort from each package's difficulty rather than the epic's total size.

Dispatch ready independent substantive packages up to available host capacity and any user limit. Capacity is a ceiling, not a utilization target. Keep dependent, overlapping, tightly coupled, or trivial work together or sequenced. When only one substantive package is ready, use one worker and record the dependency or ownership reason. Do not invent work to fill slots.

Each package gets a fresh self-contained brief and nonoverlapping ownership. Link the assignment to its item, parent, prerequisites, owned paths, and plan reference. Record why packages run in parallel or remain sequenced. A reused worker taking a different package receives a new assignment ID and fresh brief.

For long-running verification, the coordinator owns the suite process/session, its eventual exit result and the remaining failure inventory. Give repair workers a bounded group of failures, explicit file ownership, focused checks and a completion condition. Do not combine indefinite suite monitoring with an open-ended repair package. A running command or a promise to validate later is a progress report, not acceptance. If follow-through repeatedly fails, narrow the package and stop the old worker before assigning a replacement; do not infer that every such failure requires higher model effort.

As workers return, inspect actual changes and evidence, update item state, and correct that worker while unrelated packages continue. Release dependents only after prerequisites are reviewed, accepted, and available in the working state. Dispatch newly ready packages when capacity becomes available. Use bounded native waits only when no useful coordination work remains.

After item acceptance, verify combined behavior against the parent criteria. Assign integration fixes with explicit ownership. One successful child report does not complete the parent scope. Continue through all authorized items and integration review; if some are blocked, continue independent work and report the precise blocker and affected dependents.

Use one journal run for the parent scope. Preserve milestone dispatch, report, review, replan, and finish events, and keep the detailed dependency table in `plan_ref`. The parent `finish` follows combined integration review or accurately records the incomplete blocked or failed outcome.
