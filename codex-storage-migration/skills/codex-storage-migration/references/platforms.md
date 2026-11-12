# Choose the mechanism for the observed installation

## Supported configuration first

Check the installed version and current official documentation for `CODEX_HOME`, `CODEX_SQLITE_HOME`, and `sqlite_home`; do not assume every version or launcher supports the same settings. Moving Codex home does not automatically move desktop browser profiles, downloaded runtimes, application packages, or extension-specific storage. A desktop process launched from a shortcut may not inherit variables set in a terminal. Verify effective paths after restart and check that history, login, and configuration remain visible.

A changed home can make existing history appear absent while the original files remain intact. Inventory and back up the complete relevant state before changing discovery paths. Do not solve apparent history loss by editing session providers or rewriting databases without separate evidence.

## Windows filesystem redirects

For eligible local directories on a filesystem supporting the required semantics, a directory junction can preserve the original pathname. It does not preserve every updater's behavior: an update may replace the link with an ordinary directory. Observe the target and actual data location after updates.

Inspect every ancestor and nested reparse point before copy, rename, retirement, or recovery. Never recursively follow an unknown junction into another tree. File links and hardlinks require separate handling; hardlinks cannot bridge volumes. A matching SHA-256 does not prove ownership, DACLs, ADS, directory timestamps, or hardlink topology were preserved.

Administrator membership, an elevated process token, and backup/restore privileges are distinct. Sandboxed helper identities may legitimately exist even on a computer with one interactive user. Preserve exact required identities and access rather than assigning everything to the interactive user.

For MSIX/AppX binaries, prefer supported Windows package relocation when available for that package and destination. Do not manually move WindowsApps. A public registration path can remain an alias; verify physical location, package status, and launch behavior. This requires installation-specific validation.

## Other operating systems and filesystems

The planning and state-machine principles generalize. Windows junction, ADS, SID, ACL, and package procedures do not. For macOS/Linux, independently validate symlinks, ownership, modes, ACLs/xattrs, executable bits, application sandbox/entitlements, mount availability, and update behavior before a real cutover. No production macOS/Linux migration was established by the originating case.

Do not assume exFAT, FAT, cloud-sync folders, removable drives, SMB, or NFS preserve local NTFS/APFS/ext4 behavior. Active SQLite state requires filesystem-specific locking and durability validation. A missing destination at boot can make the application unavailable.
