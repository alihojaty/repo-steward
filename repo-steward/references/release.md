# Versioning, release and recovery

## Release decision record

1. Identify release unit (service, library, image, independent package or synchronized workspace), channel, release branch, authoritative version file/tool, last relevant published tag/artifact and exact candidate SHA. A tag for another package is not this package's baseline. Verify ancestry; don't trust lexical tag order or the newest repo-wide tag. If the publication record is inaccessible, say so and keep the proposal provisional.
2. Inspect the complete change range, public interfaces, compatibility, migrations, deprecations and dependency graph. Use the team's versioning scheme. Under SemVer for a stable public API distinguish breaks (major), compatible additions (minor), compatible fixes (patch); check prerelease and 0.x conventions separately. Do not decide solely from commit prefixes. For independently versioned packages account for dependent version ranges and release order.
3. Deliver current → proposed version per unit, rationale, source range, user-facing notes, migration instructions and rollback owner/plan. Use [release template](../assets/release.md). Validate linkage of version metadata, changelog and lockfile if applicable. If CI owns tagging or publication, use its process; do not race it with a manual tag.
4. Gate each actual release step on authorization, verified target SHA, required CI, approvals and absence of a conflicting published version. Verify provenance/signing per team policy and that built artifacts match the approved SHA/digest. Inspect CI triggers **before** pushing a branch or tag: if that write itself deploys/publishes, disclose the effect and require authorization for the combined effect. Never reuse or move a published version. After each authorized step verify tag target, registry version/digest or deployment record separately. Missing access is unknown, not success.
5. Keep the report explicit: `merged`, `tagged`, `artifact published`, `deployed` are four different facts. For a partial release (e.g. tag exists, registry timed out), query actual state before retry; don't duplicate or retag.

## Recover: diagnose before changing anything

| Situation | First response |
|---|---|
| Uncommitted work overlaps requested work | Preserve index and worktree; show conflicting paths and ask how to split. No automatic stash/checkout. |
| Merge/rebase/cherry-pick already in progress | Identify operation and conflicted paths; ask its owner. Neither continue nor abort implicitly. Validate conflict resolution semantically, not by selecting one side wholesale. |
| Wrong commit on shared branch | Propose a new revert via the normal PR flow, test the resulting tree. For merge commits identify the correct mainline with an owner; do not guess. |
| Wrong local unpublished commit | Verify it is genuinely unpublished; describe reversible alternatives and what happens to staged/unstaged changes. Do not rewrite first and explain later. |
| Bad release or schema migration | Determine whether flag rollback, binary rollback or forward fix is safe for current data and other running versions. Reverting source does not undo a migration. Use a new release; coordinate data recovery with an owner and verified backups. |
| Credential committed | Stop publishing/logging, notify privately, revoke/rotate first. Assess exposure and coordinate any cleanup under incident policy. An ignore rule or deletion commit does not erase history. |
| API timeout after a write | Record intended object, revision and last confirmed effect. Query host/registry for that identity; if unverifiable, stop rather than retry blindly. |

For hotfix/backport: identify all supported branches affected, the original fix and required adaptations. Track each backport in its own reviewed PR, test against that branch and check whether the fix reached the integration branch. Do not assume a clean cherry-pick is a correct fix.
