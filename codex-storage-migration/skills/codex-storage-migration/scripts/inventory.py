#!/usr/bin/env python3
"""Read-only, explicit-root metadata inventory. JSON goes to stdout only.

Not a security boundary against concurrent path replacement. Run on a trusted,
stable tree. No content reads, ACL/ADS enumeration, migration, or deletion.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import sys


def is_redirect(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & 0x400
    )


def native(path):
    value = os.fspath(path)
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        if value.startswith('\\\\'):
            return '\\\\?\\UNC\\' + value[2:]
        return '\\\\?\\' + value
    return value


def inspect_root(value, limit=20):
    # abspath normalizes syntax but deliberately does not resolve links.
    root = Path(os.path.abspath(os.path.expanduser(value)))
    result = dict(root=str(root), logical_file_bytes=0, files=0, directories=0,
                  skipped_redirects=[], special_files=[], hardlinked_files=0,
                  errors=[], largest_files=[], complete=True)
    candidates = []
    try:
        for ancestor in reversed((root, *root.parents)):
            info = os.lstat(native(ancestor))
            if is_redirect(info):
                result['skipped_redirects'].append(str(ancestor))
                result['complete'] = False
                result['reason'] = 'Root or ancestor is a redirect; target not scanned'
                return result
    except OSError as exc:
        result['errors'].append(dict(path=str(root), error=str(exc)))
        result['complete'] = False
        return result

    pending = [root]
    while pending:
        path = pending.pop()
        try:
            info = os.lstat(native(path))
            if is_redirect(info):
                result['skipped_redirects'].append(str(path))
                continue
            if stat.S_ISDIR(info.st_mode):
                result['directories'] += 1
                with os.scandir(native(path)) as children:
                    pending.extend(path / entry.name for entry in children)
            elif stat.S_ISREG(info.st_mode):
                result['files'] += 1
                result['logical_file_bytes'] += info.st_size
                result['hardlinked_files'] += int(info.st_nlink > 1)
                candidates.append(dict(path=str(path), bytes=info.st_size))
                # Bound retained path metadata for large trees.
                if len(candidates) > max(100, limit * 2):
                    candidates.sort(key=lambda item: item['bytes'], reverse=True)
                    del candidates[limit:]
            else:
                result['special_files'].append(str(path))
        except OSError as exc:
            result['errors'].append(dict(path=str(path), error=str(exc)))
            result['complete'] = False
    result['largest_files'] = sorted(
        candidates, key=lambda item: item['bytes'], reverse=True
    )[:limit]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', action='append', required=True,
                        help='Explicit local root; repeat to scan multiple trees')
    parser.add_argument('--largest', type=int, default=20)
    args = parser.parse_args()
    if args.largest < 0 or args.largest > 10000:
        parser.error('--largest must be between 0 and 10000')
    reports = [inspect_root(path, args.largest) for path in args.root]
    print(json.dumps(dict(
        schema_version=1, mode='metadata-only', roots=reports,
        limitations=[
            'Logical sizes, not allocated disk space; hardlinks can be counted repeatedly.',
            'Roots may overlap. Do not sum nested or overlapping root totals.',
            'Redirects skipped. No ACL, ADS, xattr, owner, consistency or eligibility proof.',
            'Live metadata scan is not atomic; paths in reports may be private.'
        ]), ensure_ascii=True, indent=2))
    return 0 if all(report['complete'] for report in reports) else 2


if __name__ == '__main__':
    sys.exit(main())
