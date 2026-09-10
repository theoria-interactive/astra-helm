#!/usr/bin/env python3
"""Build the public update manifest after reviewing a skill release."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def build(root, notes):
    version = json.loads((root / 'policy.json').read_text())['version']
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('policy version must be a numeric major.minor.patch release')
    if not notes or any(not isinstance(note, str) or not note.strip() for note in notes):
        raise ValueError('provide at least one nonempty release note')
    paths = [root / 'SKILL.md', root / 'policy.json']
    if (root / 'telemetry-config.json').is_file():
        paths.append(root / 'telemetry-config.json')
    for directory, extensions in [('references', {'.md'}), ('scripts', {'.py'}), ('agents', {'.yaml'})]:
        for path in (root / directory).rglob('*'):
            if path.is_file() and path.suffix in extensions and not any(p.startswith('.') or p == '__pycache__' for p in path.relative_to(root).parts):
                paths.append(path)
    files = {}
    for path in sorted(paths):
        relative = path.relative_to(root)
        if any((root.joinpath(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
            raise ValueError(f'refusing symlink: {relative}')
        files[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'version': version, 'notes': notes, 'files': files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--note', action='append', required=True)
    args = parser.parse_args()
    manifest = build(args.root, args.note)
    (args.root / 'update-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f"Built {manifest['version']} manifest for {len(manifest['files'])} files")


if __name__ == '__main__':
    main()
