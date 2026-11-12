#!/usr/bin/env python3
"""Report likely roots without scanning contents, launching Codex, or changing settings."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys


def discover(home=None, environ=None, platform=None):
    env = os.environ if environ is None else environ
    home = Path(home if home is not None else Path.home()).absolute()
    platform = sys.platform if platform is None else platform
    candidates = []

    def add(path, category, origin):
        path = Path(path).absolute()
        # lexists reports redirects even when their destination is unavailable.
        exists = os.path.lexists(path)
        redirected = False
        error = None
        if exists:
            try:
                info = os.lstat(path)
                redirected = stat.S_ISLNK(info.st_mode) or bool(
                    getattr(info, 'st_file_attributes', 0) & 0x400)
            except OSError as exc:
                error = str(exc)
        candidates.append(dict(path=str(path), category=category, origin=origin,
                               exists=exists, is_redirect=redirected, error=error))

    add(env.get('CODEX_HOME') or home / '.codex', 'codex-home',
        'CODEX_HOME' if env.get('CODEX_HOME') else 'default-home-candidate')
    if env.get('CODEX_SQLITE_HOME'):
        add(env['CODEX_SQLITE_HOME'], 'sqlite-state', 'CODEX_SQLITE_HOME')
    add(home / '.cache/codex-runtimes', 'downloaded-runtimes', 'observed-layout-candidate')
    add(home / '.agents/skills', 'user-skills', 'user-skill-candidate')
    if platform == 'win32':
        local = Path(env.get('LOCALAPPDATA') or home / 'AppData/Local')
        roaming = Path(env.get('APPDATA') or home / 'AppData/Roaming')
        add(roaming / 'Codex', 'desktop-profile', 'roaming-appdata-candidate')
        add(local / 'OpenAI/Codex', 'desktop-backend', 'local-appdata-candidate')
        add(local / 'Codex', 'desktop-logs', 'local-appdata-candidate')
        # Package identities vary. Listing direct package names is not data traversal.
        package_root = local / 'Packages'
        if package_root.is_dir() and not (os.lstat(package_root).st_file_attributes & 0x400
                                          if os.name == 'nt' else package_root.is_symlink()):
            try:
                for entry in package_root.iterdir():
                    if 'codex' in entry.name.lower():
                        add(entry, 'packaged-app-data', 'package-name-hint')
            except OSError:
                pass
    elif platform == 'darwin':
        add(home / 'Library/Application Support/Codex', 'desktop-profile', 'macos-candidate')
        add(home / 'Library/Caches/Codex', 'desktop-cache', 'macos-candidate')
    else:
        add(Path(env.get('XDG_CONFIG_HOME') or home / '.config') / 'Codex',
            'desktop-profile', 'xdg-candidate')
        add(Path(env.get('XDG_CACHE_HOME') or home / '.cache') / 'codex',
            'desktop-cache', 'xdg-candidate')
    return dict(schema_version=1, candidates=candidates,
                cli_on_path=shutil.which('codex', path=env.get('PATH', '')),
                needs_confirmation=[
                    'Candidates are hints, not a complete authoritative installation map.',
                    'Config-file overrides, alternate users and launch environments need inspection.',
                    'Link/ancestor topology must be checked before inventory or mutation.',
                    'No default recursive content scan or authentication reads were performed.'
                ])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', help='Override home for an isolated or alternate-user inventory')
    args = parser.parse_args()
    print(json.dumps(discover(args.home), ensure_ascii=True, indent=2))
