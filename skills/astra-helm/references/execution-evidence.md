# Worktree instructions and execution evidence

Use this reference when entering or resuming a worktree, before tests that write persistent data, or when deciding whether additional review is justified.

## Worktree instruction freshness

On entry or resumption, identify the active checkout, relevant instruction files, and their referenced guides. Compare them with the intended maintained source when a recent instruction revision is known. A main-checkout edit does not automatically update existing worktrees. Record the checked source and file identities in the existing plan or handoff; do not repeat the comparison every turn. Recheck when the checkout, relevant instructions, or known maintained revision changes.

If instructions diverge, reconcile current guidance with branch-specific contracts and existing user edits. Neither the newest timestamp nor the largest file establishes authority. Preserve new domain rules and referenced guides; never overwrite a worktree with a blind copy of another branch's AGENTS.md. Coordinate instruction writes with that worktree's owner. Within authorized maintenance scope, make and verify a focused instruction patch. Otherwise report the divergence and continue unaffected authorized work.

## Persistent test isolation

Before tests that may write saves, databases, or other durable application data, require a fail-closed gate in the actual test launcher or application startup, before any persistent write. The gate must obtain every effective local data destination from the application's runtime configuration, resolve symlinks, and confirm that each is within an explicitly designated isolated test root. For remote persistence, verify the actual endpoint/database is an explicitly authorized isolated test resource; a local-path check cannot establish that boundary. Missing, unreadable, or mismatched destinations stop the affected test with a nonzero result. A path supplied only as a command-line argument, a copied configuration, or a successful process exit does not prove the application used it. Do not inspect or mutate ordinary user data to prove isolation, and do not repurpose HOME or other system variables.

Prefer the project's existing gate. If absent, add a narrow pre-write check within the authorized test harness work; if that is not in scope or cannot run before startup writes, leave the mutating test unrun and explain the gap. Continue static checks and other isolated work. Do not substitute a generic external wrapper that only validates the requested path. Existing temporary-directory unit fixtures and in-memory mocks are sufficient when their actual destinations are explicit and cannot fall back to a user profile.

Record the checked executable/test copy, runtime-resolved destinations, relevant configuration and evidence with the test result. The gate runs on every launch that can write persistent application data; reuse the coordinator's inspection of its unchanged implementation instead of asking again. Revalidate after changing the checkout, executable, configuration, environment or invocation. Include a negative probe proving that an unexpected destination prevents test execution without touching the real user profile.

If a previous launch used an unverified destination, stop further mutating launches, qualify its evidence, and preserve the current state. Assess impact through non-sensitive metadata. Do not claim restoration or repair user data without a verified recovery source and appropriate authorization.

## Regression evidence

For a bugfix, establish that the focused regression check detects the pre-fix behavior before accepting it. Prefer running the same check against an isolated pre-fix copy; a narrow reversible fault injection can establish sensitivity when that is more practical. If neither is feasible, record the evidence gap rather than claiming a demonstrated regression. Do not force full-suite replay or mutation testing on unrelated changes.

Exercise the boundary claimed by the test: persisted reload for restore defects, production input dispatch for interaction defects, and exact edge values for numeric or timing defects. A failed UI action must fail its interaction check; a direct owner call may be a separate component check, never a fallback that turns the failed interaction green. Preserve meaningful assertions and existing boundary coverage when updating fixtures. Self-readback, nonnegative-only checks and conditional skips do not establish the original behavioral claim.

Visual evidence must show the relevant state in its real screen context at the required viewport. An isolated widget, clipped capture or empty background does not establish integrated screen behavior. Keep what a fixture proves separate from physical-device or real-world acceptance.

## Review scope and reuse

For additional independent review, identify the concrete risk or missing evidence and the owned review scope in the existing assignment or journal. Do not create a reviewer merely because a slot is available or a report says it is ready.

After corrections, reuse accepted findings, source identity, tests, and visual evidence where still applicable. Inspect the changed area and affected integration boundaries. Reopen accepted scope only when new findings or relevant source, dependency, or environment changes invalidate its evidence; state which evidence is affected and why. A changed commit alone does not invalidate unrelated checks. Record acceptance against a clear source/behavior boundary and proceed to the remaining authorized work.

## Native verification boundaries

Before native diagnostics, identify the shipping entry point and exact flow under test in the brief. Distinguish local export/restore, cloud recovery, and low-level database operations; proof for one does not establish another. Preserve valid evidence when redirecting a diagnostic to the correct product flow.

Keep owned test environments available until the required runtime and visual reviews finish. Coordinate cleanup across platform workers and the coordinator so an early teardown does not force avoidable setup. Bound repeated environment failures, preserve their evidence, and report the affected verification gap without claiming a pass.

For native encryption, recovery, and resource-lifetime changes, run a small representative probe against the actual native backend early, once test isolation is verified. Match encryption state, key transitions, backup/restore APIs, and close/reopen or fresh-process behavior to the shipping flow before investing in a large mock-only implementation. Plain SQLite or mocked filesystem success does not establish SQLCipher or native-platform compatibility. If the backend or device is unavailable, retain that verification gap explicitly.

For release or readiness inspectors, define negative acceptance cases in the initial brief: missing or unreadable artifacts, failed verifier commands, absent signing evidence, and unsupported profiles must report an unverified or failed gate rather than success. Protect those behaviors with focused tests.

For interface changes, include distinct loading, empty, error/retry, and populated states in the initial acceptance criteria where applicable. Review populated fixtures at relevant narrow and wide sizes and in supported light/dark themes, including contrast. Keep native-device or real-content limitations separate from the evidence a web preview actually supplies.
