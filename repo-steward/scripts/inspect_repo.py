"""Summarize a trusted local worktree. Never print paths, remotes, keys, diffs or Git stderr."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

BLOCKED_ENV_SELECTORS = (
    'GIT_DIR',
    'GIT_WORK_TREE',
    'GIT_INDEX_FILE',
    'GIT_COMMON_DIR',
    'GIT_OBJECT_DIRECTORY',
    'GIT_ALTERNATE_OBJECT_DIRECTORIES',
    'GIT_NAMESPACE',
    'GIT_CONFIG',
    'GIT_CONFIG_GLOBAL',
    'GIT_CONFIG_SYSTEM',
    'GIT_CONFIG_COUNT',
    'GIT_CONFIG_PARAMETERS',
)

OPERATION_MARKERS = (
    'MERGE_HEAD',
    'CHERRY_PICK_HEAD',
    'REVERT_HEAD',
    'rebase-merge',
    'rebase-apply',
    'sequencer',
    'BISECT_START',
    'index.lock',
    'HEAD.lock',
)

HEX_OID_RE = re.compile(rb'(?:[0-9a-f]{40}|[0-9a-f]{64})')


def _strip_single_newline(raw: bytes) -> bytes:
    """Remove only Git's single terminating newline; paths themselves may contain newlines."""
    if raw.endswith(b'\r\n'):
        return raw[:-2]
    if raw.endswith(b'\n'):
        return raw[:-1]
    return raw


def inspect(repo: str) -> dict:
    if any(key in os.environ for key in BLOCKED_ENV_SELECTORS):
        raise ValueError('Git context or config overrides set; inspect manually in that context.')

    env = dict(
        os.environ,
        GIT_OPTIONAL_LOCKS='0',
        GIT_TERMINAL_PROMPT='0',
        GIT_ALLOW_PROTOCOL='',
        LC_ALL='C',
    )

    def git(*args, allow_codes=(0,)):
        result = subprocess.run(
            ['git', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', *args],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
        if result.returncode not in allow_codes:
            raise ValueError('Git inspection unavailable (worktree, trust, permissions or Git state).')
        return result

    if git('rev-parse', '--is-inside-work-tree').stdout.strip() != b'true':
        raise ValueError('Not a working tree; no worktree status available.')

    gitdir = Path(os.fsdecode(_strip_single_newline(git('rev-parse', '--absolute-git-dir').stdout)))
    prefix = _strip_single_newline(git('rev-parse', '--show-prefix').stdout)
    is_worktree_root = (prefix == b'')
    is_shallow = git('rev-parse', '--is-shallow-repository').stdout.strip() == b'true'

    def git_bool_config(key: str) -> bool:
        res = git('config', '--type=bool', '--get', key, allow_codes=(0, 1))
        return res.returncode == 0 and res.stdout.strip() == b'true'

    sparse_checkout = git_bool_config('core.sparseCheckout')
    signing_configured = {
        'commit': git_bool_config('commit.gpgsign'),
        'tag': git_bool_config('tag.gpgsign'),
    }

    operations = []
    for marker in OPERATION_MARKERS:
        try:
            (gitdir / marker).lstat()
        except FileNotFoundError:
            continue
        operations.append(marker)

    records = git(
        'status',
        '--porcelain=v2',
        '--branch',
        '-z',
        '--no-renames',
        '--untracked-files=normal',
        '--ignore-submodules=none',
        '--no-ahead-behind',
    ).stdout

    headers = {}
    counts = dict(
        staged=0,
        unstaged=0,
        unmerged=0,
        untracked_entries=0,
        submodule_changes=0,
    )

    for row in records.split(b'\0'):
        if not row:
            continue
        if row.startswith(b'# '):
            key, _, value = row[2:].partition(b' ')
            headers[key] = value
        elif row.startswith(b'? '):
            counts['untracked_entries'] += 1  # A whole directory can be one entry.
        elif row.startswith(b'u '):
            counts['unmerged'] += 1
        elif row.startswith(b'1 ') and len(row) >= 9:
            staged_flag = row[2:3] != b'.'
            unstaged_flag = row[3:4] != b'.'
            counts['staged'] += int(staged_flag)
            counts['unstaged'] += int(unstaged_flag)
            # Porcelain v2 field 3 (bytes 5..9) starts with 'S' for submodules.
            if row[5:6] == b'S':
                counts['submodule_changes'] += 1
        else:
            raise ValueError('Unexpected status record; inspect manually.')

    head = headers.get(b'branch.oid', b'')
    branch = headers.get(b'branch.head', b'')
    if not branch or not (head == b'(initial)' or HEX_OID_RE.fullmatch(head)):
        raise ValueError('Incomplete HEAD information; inspect manually.')

    return dict(
        head=None if head == b'(initial)' else head.decode('ascii'),
        head_state=(
            'unborn'
            if head == b'(initial)'
            else 'detached'
            if branch == b'(detached)'
            else 'attached'
        ),
        is_worktree_root=is_worktree_root,
        is_shallow=is_shallow,
        sparse_checkout=sparse_checkout,
        signing_configured=signing_configured,
        upstream_configured=b'branch.upstream' in headers,
        operations=operations,
        counts=counts,
        remote_state='not_checked',
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.', help='directory in a trusted worktree')
    try:
        print(json.dumps(inspect(parser.parse_args().repo), indent=2))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        reason = (
            str(exc)
            if isinstance(exc, ValueError)
            else 'Git, repository or inspection timeout unavailable.'
        )
        print(json.dumps({'error': reason}), file=sys.stderr)
        sys.exit(2)
