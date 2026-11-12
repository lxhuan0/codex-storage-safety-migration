# A recoverable unit

## Write down the contract

For each unit record: source, active destination, independent baseline, staging/parked path, selected mechanism, runtime version/content fingerprint, writers, required metadata, verification results, recovery entry, and current stage. Use unique destinations. Never overwrite a nonempty unexpected target.

Keep the journal and recovery interpreter outside both the source and updater-controlled caches. Flush journal changes and retain the previous valid record. Validate bound paths when resuming: a journal is not authorization to operate on arbitrary replacement paths.

Default to copied payloads plus an intact parked original until verification is sufficient. If the user wants all backup payloads off the system drive, explicitly account for the baseline, working copy, and temporary peak space on the destination. Two directories on one disk help against mistakes, not disk failure. Free-space requirements must come from measured payloads and temporary peaks, not a universal fixed reserve.

## Testing that answers a concrete question

Start with a fixture containing Unicode names, empty directories, representative metadata, and a known payload. Add only relevant risks. On Windows, foreign-owned/sandbox-accessible objects require real privileged tests with the existing identities, not fabricated replacement accounts. For runtimes, check a representative actual operation or native module, not just `--version`. Isolate environment variables in the test child process.

Exercise failures before the switch, after parking but before linking, and during latest-data return. Verify both the restored application path and payloads. Synthetic success is evidence about a mechanism, not proof of full production integration.

For databases, stop writers and treat the main file plus WAL/SHM and related databases as a consistency group. A live file copy is not a consistent backup. Inspect backup files by raw reads when DB APIs might create sidecars or mutate evidence. On an isolated writable copy, use appropriate SQLite consistency checks; never infer logical consistency solely from matching hashes.

## Suggested stage model

| Observed stage | Meaning | Safe next decision |
| --- | --- | --- |
| Planned | No source mutation | Refresh cold inventory or cancel |
| CopiedVerified | Destination verified, source still authoritative | Revalidate source; switch only while cold |
| Parked | Original renamed, application path absent | Restore intact original if source is still absent; inspect any partial destination |
| Linked | Redirect/config points to verified destination | Confirm target and launch behavior; baseline remains untouched |
| RestartVerified | Relevant use succeeded after restart | Retire the specifically verified source payload if authorized |
| SourceRetired | Original payload no longer on system drive | Restore latest active data through a separately staged return |

The physical filesystem outranks a possibly stale journal. If a crash happened between a filesystem change and journal update, reconcile both before continuing. Never blindly execute the next stage by name. The bundled executor uses more granular names (`Captured`, `CopiesVerified`, `ApplicationVerified`, `ReturningLatest`, `ReturnReady`, `ReturnedLatest`, and `RetiringOriginal`) for those intervals; inspect its exact contract rather than hand-editing stages.

Prefer copy-before-switch when practical to reduce downtime. If the chosen mechanism parks first, keep original bodies intact and make the unlinked interval explicit; recovery must work without the migrated runtime. Do not batch unrelated units into a single failure domain.

## Latest-data return

Once the application writes to the destination, the original baseline is stale. Stop writers, snapshot the active destination, copy its latest contents to a fresh return staging tree, verify it, then replace only the expected redirect/configuration. Retain destination data until the restored application is verified. Refuse a newly created ordinary source directory rather than overwrite or merge it silently.

## Advanced original-record retention is optional

One Windows case retained empty native C file records while keeping bodies and exact security metadata on D, so old identity-dependent recovery tooling could rehydrate them. This is specialized, not a recommended default: zero-length files are not backups, consume metadata space, confuse old scripts, and require precise stream/security/identity journals. This package intentionally does not ship that destructive controller. Use ordinary verified backups and an explicit retirement policy unless a proven identity dependency justifies a separately engineered implementation.

## Reporting

Report actual transferred bytes, source bodies still retained, observed space reclaimed, backup location, stage, application checks completed, and remaining gaps. A rollback script prepared but never exercised on real post-migration data must be labeled as such. Do not claim complete reversibility from a synthetic test alone.
