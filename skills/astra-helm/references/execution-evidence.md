# Worktree instructions and execution evidence

Use this reference when entering or resuming a worktree, before tests that write persistent data, or when deciding whether additional review is justified.

## Worktree instruction freshness

On entry or resumption, identify the active checkout, relevant instruction files, and their referenced guides. Compare them with the intended maintained source when a recent instruction revision is known. A main-checkout edit does not automatically update existing worktrees. Record the checked source and file identities in the existing plan or handoff; do not repeat the comparison every turn. Recheck when the checkout, relevant instructions, or known maintained revision changes.

If instructions diverge, reconcile current guidance with branch-specific contracts and existing user edits. Neither the newest timestamp nor the largest file establishes authority. Preserve new domain rules and referenced guides; never overwrite a worktree with a blind copy of another branch's AGENTS.md. Coordinate instruction writes with that worktree's owner. Within authorized maintenance scope, make and verify a focused instruction patch. Otherwise report the divergence and continue unaffected authorized work.

## Persistent test isolation

Before the first test that may write saves, databases, or other durable data, verify the actual resolved destination and environment. An intended command-line option or a successful process exit is not evidence of isolation. Prefer an existing project probe or fixture that reports the effective destination. Do not inspect or mutate ordinary user data to establish isolation, and do not repurpose HOME or other system variables.

Record the verified environment, relevant configuration, and evidence path with the test result. Reuse that proof while its inputs remain unchanged; recheck after changing the test copy, destination, configuration, or invocation that controls it. A failed isolation check blocks the affected mutating test, not unrelated work. If prior runs used an unverified destination, qualify their evidence and assess the issue through non-sensitive metadata before rerunning only the affected checks safely.

## Review scope and reuse

For additional independent review, identify the concrete risk or missing evidence and the owned review scope in the existing assignment or journal. Do not create a reviewer merely because a slot is available or a report says it is ready.

After corrections, reuse accepted findings, source identity, tests, and visual evidence where still applicable. Inspect the changed area and affected integration boundaries. Reopen accepted scope only when new findings or relevant source, dependency, or environment changes invalidate its evidence; state which evidence is affected and why. A changed commit alone does not invalidate unrelated checks. Record acceptance against a clear source/behavior boundary and proceed to the remaining authorized work.

## Native verification boundaries

Before native diagnostics, identify the shipping entry point and exact flow under test in the brief. Distinguish local export/restore, cloud recovery, and low-level database operations; proof for one does not establish another. Preserve valid evidence when redirecting a diagnostic to the correct product flow.

Keep owned test environments available until the required runtime and visual reviews finish. Coordinate cleanup across platform workers and the coordinator so an early teardown does not force avoidable setup. Bound repeated environment failures, preserve their evidence, and report the affected verification gap without claiming a pass.

For native encryption, recovery, and resource-lifetime changes, run a small representative probe against the actual native backend early, once test isolation is verified. Match encryption state, key transitions, backup/restore APIs, and close/reopen or fresh-process behavior to the shipping flow before investing in a large mock-only implementation. Plain SQLite or mocked filesystem success does not establish SQLCipher or native-platform compatibility. If the backend or device is unavailable, retain that verification gap explicitly.

For release or readiness inspectors, define negative acceptance cases in the initial brief: missing or unreadable artifacts, failed verifier commands, absent signing evidence, and unsupported profiles must report an unverified or failed gate rather than success. Protect those behaviors with focused tests.

For interface changes, include distinct loading, empty, error/retry, and populated states in the initial acceptance criteria where applicable. Review populated fixtures at relevant narrow and wide sizes and in supported light/dark themes, including contrast. Keep native-device or real-content limitations separate from the evidence a web preview actually supplies.
