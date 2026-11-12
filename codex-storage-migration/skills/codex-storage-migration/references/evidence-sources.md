# Evidence boundaries and primary sources

Origin: a Windows Codex desktop storage-relocation case, summarized without raw personal files. Documentation checked 2026-11-12; confirm against the version being used.

## What the case supports

- Some histories, databases, browser-profile storage, and runtime generations were switched to another local drive; several had raw byte/metadata checks and synthetic interrupted-recovery checks.
- Browser destination-baseline payload hashes and the original-path junction were independently checked. This did not establish every browser login or computer-use integration behavior.
- A current Python generation returned migration PASS. This alone did not prove every production workload or real latest-data rollback.
- A later Node generation stopped in the parked stage. At skill creation, restoration and security-product resolution remained outstanding. It is a failure lesson, not a claimed successful migration.
- Windows mechanisms were exercised. macOS/Linux production relocation, arbitrary filesystems, universal updater compatibility, and universal zero-loss behavior were not established.

No raw sessions, authentication files, SIDs, usernames, inventory exports, or absolute case paths belong in this repository. Do not turn successful historical versions into a compatibility matrix for current versions.

## Generic executor validation added after the originating case

The repository now includes an independently written, parameterized Windows NTFS executor. Isolated tests exercise real filesystem copies, junctions, streams, security metadata, closed SQLite, copied executable launch, source retirement, and latest-data return, including a second-volume fixture on the development computer. Global app-process checks are mocked for fixture-only operations; separate tests cover process guard decisions and native enumeration. Original and destination bytes are synthetic.

This is materially stronger than the initial documentation-only package, but is not independent-machine production validation. Check `VALIDATION.json` and CI results for the actual environments run. Hosted CI configurations are supplied without claiming those jobs have already executed. Neither these synthetic tests nor a single local volume pair establish all sandbox, updater, login, native dependency, or security-product behavior.

## Sources to re-check

- [Codex environment variables](https://learn.chatgpt.com/docs/config-file/environment-variables): home/state configuration; launcher and version scope matter.
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference): verify keys such as `sqlite_home` for the installed build.
- [OpenAI Codex source](https://github.com/openai/codex): primary implementation evidence; use a version/commit corresponding to the installation rather than assuming `main` matches it.
- [Microsoft mklink](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/mklink): distinguishes directory junctions, symlinks, and hardlinks.
- [Microsoft robocopy](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/robocopy): data/attribute/time/security/owner options and exit-code semantics. Default copying is not full metadata preservation; handle junctions deliberately. Never use `/MIR` or purge options as an unreviewed migration shortcut.
- [Microsoft CopyFileW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-copyfilew) and [FindFirstStreamW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-findfirststreamw): implementation primitives; reparse behavior, metadata and stream support need explicit checking.
- [SQLite online backup](https://www.sqlite.org/backup.html) and [WAL](https://www.sqlite.org/wal.html): consistent backup methods and shared-memory/locking constraints. Filesystem-specific validation is still required.

These sources document primitives; they do not endorse this community skill or prove a complete Codex desktop migration is supported.
