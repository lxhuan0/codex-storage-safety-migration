# Lessons from a Windows migration case

These are observed failure patterns and decision rules, not guarantees for other installations.

## Full-tree snapshots can reject harmless cache writes

A Python runtime gained two CPython bytecode files and two cache-directory timestamp changes between preparation and cold execution. The original strict gate stopped before source mutation. The remedy was to identify the exact diff, preserve code and security checks, and narrowly admit only the observed cache pattern. Do not broadly ignore timestamps, permissions, or all `__pycache__` contents; existing bytecode changes can matter. Re-capture mutable state while cold. If binaries or version fingerprints changed, redo generation-specific verification.

Plugin installation metadata can also be rewritten by the live application. Treat it as mutable state, not a frozen executable fingerprint. A stale preparation snapshot is not a reason to skip a cold source check.

## A generic exit code can hide security-software interference

A Node migration stopped after its original directory was parked and while a destination copy was incomplete. The controller script was subsequently absent. Security-product events at the same timestamp named that script and command. This strongly supported interference, but the raw events did not independently establish the precise detection or quarantine action.

When this happens, inspect source, parked original, copies, journal, and protection history before retrying. Preserve evidence and review the script. Do not regenerate a renamed script to evade detection, disable antivirus, or add broad exclusions automatically. Restore the intact original first when possible. Resolution may require the user's security-product review or vendor analysis, outside the mover itself. Never claim the original was restored until observed.

## Elevated security metadata differs from ordinary file access

An agent with broad filesystem permission may lack an elevated Windows token or restore privilege. Copying file contents as the current user may alter foreign ownership or sandbox access. Verify exact owner/group/DACL and representative sandbox operations with the real existing identities. Synthetic metadata preservation and real application access are different checks.

## Updaters can replace redirects

A runtime update replaced previously redirected directories with a new ordinary source generation while old D copies remained. Do not call this lost data or overwrite the new generation with the old backup. Identify versions and links, account for each generation, then evaluate migration of the current version separately.

## Native tests can accidentally use the test runner's environment

A PowerShell probe inherited module paths and loaded modules from a different runtime. Isolating the child environment corrected the test. Avoid global environment changes as a test fix; inspect actual executable/module paths and use an independent runner.

## Package metadata may show an alias

A Windows package move returned a post-check failure because public registration still showed a C path. Windows events and the physical alias target showed relocation had occurred. Check physical storage and package health before attempting any reverse move. A successful physical move still needs an actual launch check.

## Long paths and byte encodings can manufacture failures

Ordinary Python paths can fail on Windows long names when the underlying extended path works. Use tested long-path APIs where needed. Read UTF-8 JSON and scripts explicitly, accommodating a BOM; do not rely on a machine's default code page.

## Long batches magnify disruption

A multi-entry batch repeatedly ran expensive synthetic administrator checks and gave little phase progress. A later failure forced another maintenance window. Reuse compatible mechanism proofs, retain real-copy verification, use single-unit entries, and record completed units. Do not promise a duration from gigabytes alone: ACL/stream queries and thousands of files dominated parts of this case.
