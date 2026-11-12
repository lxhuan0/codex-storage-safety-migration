# Windows executor: contract, commands, and recovery

Use this reference only for a selected real unit or an isolated test. Python 3.12+ is required. Discovery/inventory also run on other operating systems; the mutating backend deliberately refuses non-Windows. It requires ordinary directories on fixed local NTFS volumes.

## What the implementation does

`migrate.py prepare` creates a private job on the target volume, copies an independent toolkit there, binds paths and directory identities, and emits separate launchers. It does not rename or change the source. Use a Python installation outside the source being moved, including its standard library and virtual-environment base.

The snapshot is taken when `apply` begins while cold, avoiding old preflight cache snapshots. The source directory identity must still match preparation. For `--kind runtime`, preparation also requires one or more `--pin` relative executable/version marker paths and records their hashes. A changed marker stops application before source mutation; new cache files are captured while cold without failing merely because preparation was earlier. Select all meaningful generation markers; pinning a text version label alone does not prove all binaries stayed unchanged. The agent must still confirm version and functional evidence.

`apply` snapshots bytes, SHA-256, named streams, file attributes, creation/write times, owner/group, and effective ordered DACL entries. It creates and verifies **both** a baseline and active copy before parking the original. Only then does it create the original-path junction. The intact original is kept on the source volume. This reduces the failure interval compared with park-before-copy.

It does not preserve native file IDs in copies, SACL/audit metadata, or inherited-vs-explicit ACE origin. Copies use protected DACLs with equivalent ordered ACE access, owner and group; future inheritance from the destination parent is deliberately blocked. If exact inheritance/auditing/file-identity semantics are required, defer this executor and engineer a separate reviewed method. Ownership failures stop before source rename; the tool never takes ownership or recreates accounts. Privilege-dependent foreign-owned trees have not been validated by this generic release.

Sparse/compressed/encrypted/offline/recall files, hardlinked files, nested reparse points, package-managed binaries, and topology-dependent worktrees need another implementation. Unsupported filesystem flags are refused. This executor is designed for a trusted filesystem during a maintenance window, not hostile concurrent path replacement. File and stream content is read to verify migration; private data is never uploaded.

## Prepare one unit

First inventory and select the scope; substitute observed paths. These examples are placeholders, not an installation layout requirement.

```console
python -B scripts/migrate.py prepare --source "C:\Example\selected-data" --target-parent "D:\Example\migration-jobs" --original-parent "C:\Example\migration-originals" --kind data
```

The parent directories must already exist. `original-parent` must be on the source volume, outside the source and updater discovery paths; use a dedicated folder, not the source's parent. `target-parent` must not contain or be inside the source. For a genuine cross-volume move the two parents are on different volumes. Same-volume tests are permitted but do not reclaim that volume's space.

`--kind` is `data`, `runtime`, `sqlite`, or `browser`. Kind selects known process blockers, not automatic eligibility. For browser it also blocks Chrome and Edge; Codex and ChatGPT executable names are blocked by default. Add known writer executable names with repeated `--block-process`. Process discovery checks executable paths under the source/parked/active roots but cannot detect every command-line interpreter user, open handle, service, browser helper, or alternate identity. The agent must establish a complete writer list and the user must close them. The tool does not kill processes.

For a runtime, additionally supply repeated `--pin "relative-path-to-executable-or-critical-module"` options. Those paths are relative to the selected source, never absolute paths to another installation. Markers are not executed by preparation.

The job contains its own `tools/`, `journal.json`, manifest seals, and four CMD entries. The entries use a readable UTF-8-with-BOM PowerShell launcher so non-ASCII interpreter paths survive legacy CMD code pages; delayed expansion is disabled for paths containing `!`. There is no encoded command or execution-policy bypass. If local PowerShell policy blocks the helper, use the documented direct Python command rather than changing system policy automatically. Source paths are recorded in private runtime journals, never in the public repository. Keep the job on a reliable disk; it is the recovery location. No automatic administrator launch is requested. Use an elevated terminal only when actually necessary for the unit's metadata.

## Apply and inspect

```console
python -B scripts/migrate.py apply --job "D:\Example\migration-jobs\codex-migration-JOBID" --execute --writers-stopped
python -B scripts/migrate.py status --job "D:\Example\migration-jobs\codex-migration-JOBID"
```

Replace the entire example job path with the generated path. `--writers-stopped` is an explicit attestation, not proof. Writer checks and file-sharing locks are also enforced. Each invocation appends a separate timestamped log; copy/snapshot progress reports every 250 entries. Small units can pass between phase messages quickly; a large file's hash can take time.

Resume `apply` on the same job after investigating the failure. Complete existing files can be reused after hash verification. An incomplete or changed existing payload is preserved and refused rather than overwritten. Do not delete partial trees blindly: identify whether the source is still authoritative and prepare a new job only after reconciling the old one. A source change after capture requires investigation, not a silently refreshed manifest. Other jobs are independent.

## Verify use, then choose whether to release space

After a successful switch, restart Codex and test the relevant operation: browse old conversations, create/read a test item, use the browser, invoke the relocated runtime or plugin. The tool cannot attest these behaviors itself.

```console
python -B scripts/migrate.py mark-verified --job "GENERATED_JOB_PATH" --execute --application-verified
```

This records the caller's actual-use attestation. It is not an automated integration test. The original still consumes source space. To retire that specific original after the user authorizes releasing it, close writers and run:

```console
python -B scripts/migrate.py retire-original --job "GENERATED_JOB_PATH" --execute --writers-stopped
```

This **deletes the manifest-bound original files**, while preserving the verified baseline and active payload on the target. It requires the attestation, verifies backup integrity and original identities/content, and refuses unknown replacements. Interrupted retirement can resume. It uses exact manifest paths and empty-directory removal, not recursive deletion of arbitrary contents. No retirement CMD is auto-generated, so space release is a separate explicit action.

Before retirement, keeping the intact original on the source volume is intentional. If the user wants all backup bodies on the target, explain this temporary stage and perform the authorized retirement after verification. Never report source space reclaimed just because the junction exists.

## Recover the right generation

If parked but unlinked, and no new source exists:

```console
python -B scripts/migrate.py recover-original --job "GENERATED_JOB_PATH" --execute --writers-stopped
```

This verifies and renames the intact original back. It does not use a partial target copy. If the source is already a junction, this action refuses: use latest-data return instead.

After linking, use:

```console
python -B scripts/migrate.py return-latest --job "GENERATED_JOB_PATH" --execute --writers-stopped
```

It snapshots the **current active data**, copies it to a fresh staging tree on the original volume, verifies it, removes only the exact expected junction, and renames staging into place. It preserves target copies. It resumes crashes around link removal or staging rename. If active data changed after the latest snapshot, or an unexpected source reappeared, it refuses rather than restore stale data. Inspect and reconcile that conflict; do not hand-edit journal stages to bypass it.

If the original junction is still intact and the only conflict is that active data gained newer writes while a return was pending, `restart-return --job "GENERATED_JOB_PATH" --execute --writers-stopped` captures a new return attempt, preserving previous staging and manifests. Then run `return-latest` again. It refuses if the original portal is already absent or replaced; that requires explicit physical-state inspection.

If a security product removes the toolkit, preserve the job, inspect protection history, and review the exact code. Do not disable protection, rename code to evade it, or guess that exit code 5 alone establishes quarantine. If the original is still intact and no source exists, a reviewed cold rename of that exact parked directory is the minimal manual recovery; verify paths and contents first. If already linked, do not substitute an old baseline for the latest data.

## Tests and what remains unproven

Run `python -B -m unittest discover -s tests -v` from the repository root on Windows. All filesystem changes use fresh synthetic temporary trees. Tests mock the global writer gate because the synthetic fixtures have no running application; separate tests exercise the gate, native process enumeration, and sharing violations. No production CLI bypass flag exists.

For a second-volume fixture, set `CODEX_MIGRATION_TEST_TARGET_PARENT` to an existing empty-test-capable parent on another local NTFS drive. The suite creates and removes only its own uniquely named fixture below it; it does not use real Codex data. Cross-volume validation on the originating computer passed; the same suite on another computer is stronger evidence than assuming identical behavior.

CI is supplied for Windows and Ubuntu with Python 3.12/3.13. Linux skips the Windows executor and checks discovery/inventory plus explicit platform refusal. CI configuration is not evidence that hosted runs have already passed. Current tests do not certify arbitrary security products, foreign-owned sandbox trees, every real plugin, native module dependency, or application update behavior.
