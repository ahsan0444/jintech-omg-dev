#!/usr/bin/env python3
"""
PostToolUse hook: syntax/lint feedback on every Edit/Write/MultiEdit inside the
OMG repo, run through the `omg` Podman container (repo is bind-mounted there
at /var/www/OMG — same mapping used by .claude/hooks/perl-syntax-check.sh and
the perlcritic skill).

Checks per extension:
  .pm/.pl/.t  -> `perl -c` (with -I <container-root>/lib) and
                 `perlcritic --severity 4 --quiet` (skipped silently if the
                 binary isn't in the container).
  .tt         -> parse-only check with Template::Parser, using the repo's
                 START_TAG/END_TAG ('<%' / '%>' from config.yml).

Only runs when the edited file sits inside a git repo whose root basename is
`omg` (override with OMG_LINT_REPOS, a comma-separated list of basenames) and
the `omg` container is running. The container-running check is cached to a
per-session file under /tmp so it isn't re-shelled out on every edit.

Output contract (PostToolUse): on a real failure, print
  {"decision": "block", "reason": "<file>: <trimmed errors>"}
and exit 0 (the edit already happened; this only feeds the reason back to
Claude). On success, skip, or any internal error: exit 0 with no output.
Never let a bug here block a tool call.
"""
import json
import os
import re
import subprocess
import sys
import time

CONTAINER_NAME = os.environ.get('OMG_LINT_CONTAINER_NAME', 'omg')
CONTAINER_ROOT = os.environ.get('OMG_LINT_CONTAINER_ROOT', '/var/www/OMG')
PERLCRITIC_BIN_CANDIDATES = [
    os.environ.get('OMG_LINT_PERLCRITIC_BIN', ''),
    'perlcritic',
    '/opt/local/bin/perlcritic',
]
PERLCRITIC_BIN_CANDIDATES = [b for b in PERLCRITIC_BIN_CANDIDATES if b]

REPO_BASENAMES = [
    n.strip() for n in os.environ.get('OMG_LINT_REPOS', 'omg').split(',') if n.strip()
]

TT_START_TAG = os.environ.get('OMG_LINT_TT_START_TAG', '<%')
TT_END_TAG = os.environ.get('OMG_LINT_TT_END_TAG', '%>')

MAX_ERROR_LINES = 30
EXEC_TIMEOUT = 8
CONTAINER_CHECK_TTL = 10  # seconds


# ---------------------------------------------------------------- repo detection
def get_repo_root(file_path):
    start_dir = os.path.dirname(os.path.abspath(file_path))
    try:
        r = subprocess.run(
            ['git', '-C', start_dir, 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def is_covered_repo(repo_root):
    """True if repo_root's basename is one of REPO_BASENAMES."""
    if not repo_root:
        return False
    return os.path.basename(os.path.normpath(repo_root)) in REPO_BASENAMES


# ---------------------------------------------------------------- container check
def _cache_path(session_id):
    return os.path.join('/tmp', f'omg-lint-container-{session_id or "default"}.json')


def container_running(session_id):
    """Cheap, cached check that the `omg` container is up.

    OMG_LINT_FAKE_CONTAINER_DOWN=1 forces "down" without touching podman —
    used by tests that must not depend on a real container.
    """
    if os.environ.get('OMG_LINT_FAKE_CONTAINER_DOWN'):
        return False

    path = _cache_path(session_id)
    now = time.time()
    try:
        with open(path) as f:
            cached = json.load(f)
        if isinstance(cached, dict) and (now - cached.get('ts', 0)) < CONTAINER_CHECK_TTL:
            return bool(cached.get('running'))
    except Exception:
        pass

    running = False
    try:
        r = subprocess.run(
            ['podman', 'ps', '--filter', f'name=^{CONTAINER_NAME}$', '-q'],
            capture_output=True, text=True, timeout=5,
        )
        running = r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        running = False

    try:
        with open(path, 'w') as f:
            json.dump({'ts': now, 'running': running}, f)
    except Exception:
        pass

    return running


# ---------------------------------------------------------------- path mapping
def to_container_path(repo_root, file_path):
    rel = os.path.relpath(os.path.abspath(file_path), repo_root)
    return CONTAINER_ROOT.rstrip('/') + '/' + rel.replace(os.sep, '/')


# ---------------------------------------------------------------- output parsing (pure)
def trim_errors(text, max_lines=MAX_ERROR_LINES):
    lines = (text or '').splitlines()
    trimmed = lines[:max_lines]
    out = '\n'.join(trimmed)
    if len(lines) > max_lines:
        out += f'\n... ({len(lines) - max_lines} more line(s) truncated)'
    return out.strip()


def build_block_reason(rel_path, errors):
    return f'{rel_path}: {trim_errors(errors)}'


def block_json(rel_path, errors):
    return {'decision': 'block', 'reason': build_block_reason(rel_path, errors)}


# ---------------------------------------------------------------- podman exec helper
def podman_exec(args, timeout=EXEC_TIMEOUT):
    """Run `podman exec <CONTAINER_NAME> <args...>`. Returns (rc, stdout+stderr)."""
    try:
        r = subprocess.run(
            ['podman', 'exec', CONTAINER_NAME] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except Exception as e:
        return -1, str(e)


# ---------------------------------------------------------------- checks
def check_perl_syntax(container_path):
    """Run `perl -c -I <root>/lib <path>` in the container. Returns '' on success,
    else the trimmed error output."""
    lib_path = CONTAINER_ROOT.rstrip('/') + '/lib'
    rc, out = podman_exec(['perl', '-I', lib_path, '-c', container_path])
    if rc == 0 or is_env_failure(out):
        return ''
    return out


ENV_FAILURE = re.compile(r'version \S+ required--this is only version|Can\'t locate \S+\.pm in @INC')


def is_env_failure(out):
    """Container dependency drift, not an error in the edited file."""
    return bool(ENV_FAILURE.search(out)) and 'syntax error' not in out


def check_perlcritic(container_path):
    """Run `perlcritic --severity 4 --quiet <path>` in the container. Returns
    ('', '') if clean, ('', '') if perlcritic is missing (skip silently), else
    (errors, ''). perlcritic exits non-zero when it finds violations — that is
    not itself a hook error."""
    last_err = ''
    for binp in PERLCRITIC_BIN_CANDIDATES:
        rc, out = podman_exec([binp, '--severity', '4', '--quiet', container_path])
        if rc == 127 or 'not found' in out.lower() or 'no such file' in out.lower():
            last_err = out
            continue
        if rc == 0:
            return ''
        # perlcritic prints violations to stdout and exits 2 when it finds any
        return out
    # every candidate binary was missing -> skip silently
    return ''


def check_tt_parse(container_path):
    """Parse-only check of a .tt file with Template::Parser, using the repo's
    <% %> tag style. Returns '' on success, else the trimmed error."""
    perl_prog = (
        "use strict; use warnings; use Template::Parser; "
        "my $p = Template::Parser->new({ START_TAG => quotemeta('%s'), "
        "END_TAG => quotemeta('%s') }); "
        "local $/; open(my $fh, '<', $ARGV[0]) or die \"open failed: $!\"; "
        "my $src = <$fh>; close $fh; "
        "my $out = $p->parse($src); "
        "if (!$out) { print STDERR $p->error(), \"\\n\"; exit 1; } "
        "exit 0;"
    ) % (TT_START_TAG, TT_END_TAG)
    rc, out = podman_exec(['perl', '-e', perl_prog, container_path])
    if rc == 0:
        return ''
    return out


# ---------------------------------------------------------------- main
def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get('tool_input', {}) or {}
    file_path = tool_input.get('file_path') or ''
    session_id = data.get('session_id') or ''

    if not file_path:
        sys.exit(0)

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ('.pm', '.pl', '.t', '.tt'):
        sys.exit(0)

    repo_root = get_repo_root(file_path)
    if not is_covered_repo(repo_root):
        sys.exit(0)

    if not container_running(session_id):
        sys.exit(0)

    container_path = to_container_path(repo_root, file_path)
    rel_path = os.path.relpath(os.path.abspath(file_path), repo_root)

    errors = []

    if ext in ('.pm', '.pl', '.t'):
        perl_errors = check_perl_syntax(container_path)
        if perl_errors:
            errors.append(perl_errors)
        else:
            critic_errors = check_perlcritic(container_path)
            if critic_errors:
                errors.append(critic_errors)
    elif ext == '.tt':
        tt_errors = check_tt_parse(container_path)
        if tt_errors:
            errors.append(tt_errors)

    if errors:
        print(json.dumps(block_json(rel_path, '\n'.join(errors))))

    sys.exit(0)


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
