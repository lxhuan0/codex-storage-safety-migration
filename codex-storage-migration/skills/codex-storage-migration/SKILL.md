---
name: codex-storage-migration
description: Inventory, plan, test, and recover Codex storage relocation between local drives, especially Windows C-to-D migrations, while preserving history, permissions, and rollback options. Use for storage relocation rather than model or API migration.
---

# Codex storage migration

Turn a space-saving request into small, observable, recoverable changes. Never promise zero impact. Includes discovery/inventory and a restricted Windows NTFS executor, not a universal unattended mover.

## Start from the requested outcome

Determine whether the user wants inventory, a plan, synthetic testing, actual relocation, or recovery. Respect exclusions and pauses. Do not execute migration when asked only for a plan. Existing authorization can cover subsequent steps within its scope; do not repeatedly ask for permission already given.

Run `scripts/discover.py` to obtain installation hints without reading application contents. Confirm OS, install type, actual Codex home, app-data directories, destination filesystem, available space, active writers, and current runtime generation. Resolve paths from the environment and observed installation, never from this skill's examples. Desktop, CLI, extensions, and managed installs can have different roots and launch environments; discovery is not exhaustive.

Use current primary documentation to verify settings supported by the installed version. Read [platform choices](references/platforms.md) before choosing configuration, a filesystem link, or package-manager relocation.

## Inventory before choosing a method

Use `scripts/inventory.py` with explicit roots to obtain a metadata-only, no-link-following inventory. Reports may contain private paths: keep them local. The helper does not prove migration eligibility, verify ACLs/streams, or measure actual allocated bytes.

Show source, logical size, existing redirects, expected space reclaimed, active writers, method, and confidence. Rank independent eligible items by likely reclaimed space, largest first; group dependent data together. Exclude small items when the benefit does not justify downtime. Do not add parent and child totals, count existing redirects as fresh savings, or count the same hardlinked payload twice.

Separate application state from recoverable caches, runtimes, packaged application binaries, worktrees, authentication/browser profiles, and migration backups. A cache can contain useful offline assets; its name is not permission to delete it.

## Prove the selected unit, then switch it

Read [migration and recovery](references/migration-recovery.md). For each selected unit:

1. Establish the complete dependency group and what must survive: bytes, streams, timestamps, security, link topology, and application behavior. Pick the least invasive supported mechanism.
2. Prepare an independent recovery entry and durable journal on a stable path outside the source tree. Its interpreter must not depend on the runtime being moved. Log the stage, exact paths, errors, and final exit code; make the window stay open.
3. Test the mechanism on the smallest representative synthetic fixture. Add checks only for new risks: foreign ownership, native modules, long paths, SQLite companions, or interrupted recovery. Reuse valid mechanism evidence; do not rerun an expensive full synthetic suite for every ordinary leaf.
4. For mutable state and active runtimes, stop all relevant writers during an agreed maintenance window. Broad filesystem access does not imply a Windows elevated token. Never terminate unrelated applications or change security software automatically.
5. Revalidate the cold source and version, copy to the destination, independently verify, switch the original path/configuration, then verify application behavior. Stop if an unexpected source reappears. Keep existing recovery material intact.
6. Record copy verified, switched, restart verified, and source space reclaimed separately. Delay source retirement until its required verification succeeds. Backups belong on the user-selected volume; explain when that shares the same disk failure domain as active data.

Prefer one directory or one inseparable dependency group per entry. Show progress by phase and file count. Estimate time from a representative measured run, filesystem cost, and file count, rather than bytes alone. Completed units must not restart because a later unit fails.

For eligible ordinary Windows directories, read [executor contract and commands](references/executor.md) before using `scripts/migrate.py`. It supports copy-before-switch, resumable jobs, intact-original recovery, latest-data return, and separately authorized source retirement. It refuses unsupported topology/filesystems, requires a stable external Python, and never treats its file-copy PASS as actual application verification. Do not adapt it to package binaries, sandbox identity trees, auditing-sensitive files, or worktrees merely by bypassing its guards. If configuration relocation is supported and preferable, use that instead; the executor implements original-path junctions only.

## When something changes or fails

Read [failure lessons](references/failure-lessons.md) for snapshot mismatches, security-software interference, runtime updates, misleading package locations, and sandbox permissions.

Inspect actual paths and journal stages before retrying. Never infer success from an exit code alone, nor data loss from a stopped operation alone. Restore an unlinked intact original when appropriate; after new writes have occurred on the destination, recover the latest destination data rather than overwrite it with the old baseline. Do not disable protection, recreate sandbox accounts, or widen ACLs as a shortcut.

Do not distribute this skill's reports with usernames, absolute private paths, tokens, session content, browser databases, machine SIDs, or raw local logs. Read [evidence and sources](references/evidence-sources.md) when stating support or publishing results.
