#!/usr/bin/env python3
"""Check this Mac can read, build and sign shortcuts, list the corpus roots found, and set up QA for a project.

    python3 doctor.py                         # checks + corpus roots + the next command; exit 1 if anything is missing
    python3 doctor.py --setup                 # asks once (TTY) which QA every build runs, writes ./.shortcut-dev.json
    python3 doctor.py --setup --qa builtin    # coverage gate (specs/PRD.md + specs/ac-matrix.md) + scripts/*regression*.py
    python3 doctor.py --setup --qa own --regression-cmd "pytest -q tests/test_shortcut.py"   # your own test command
    python3 doctor.py --setup --qa none       # wiring audit and real-sample check only; prints the risk of no tests
    python3 doctor.py --selftest              # tempdir only

The write-gate (shortcut_build.py) reads the nearest .shortcut-dev.json and refuses to build without one.
Run --setup again to change the choice. `regression_cmd` gets the built file's path appended as its last argument.
--setup then prints where the spec (specs/PRD.md) comes from: the shortcut-spec skill, or your own document.
"""
import argparse
import collections
import contextlib
import io
import json
import os
import pathlib
import platform
import shlex
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
CHOICES = {'builtin': 'coverage gate + the product\'s scripts/*regression*.py (the shortcut-qa skill builds both)',
           'own': 'your own test command, run on every build',
           'none': 'wiring audit and real-sample check only; no spec or regression tests'}
NONE_RISK = ('Without tests, nothing checks the spec\'s acceptance criteria or your regression script, so a change can '
             'break a feature and you see it only when it runs on your iPhone.')


def checks() -> list[str]:
    """-> one fix line per missing prerequisite."""
    missing = []
    if platform.system() != 'Darwin':
        missing.append(f'macOS required (this is {platform.system()}): shortcuts are signed with /usr/bin/shortcuts')
    for b in ('/usr/bin/shortcuts', '/usr/bin/aea', '/usr/bin/yaa'):
        if not pathlib.Path(b).exists():
            missing.append(f'{b} not found: it ships with macOS 12+; update macOS')
    if not shutil.which('openssl'):
        missing.append('openssl not found on PATH: macOS ships /usr/bin/openssl; restore it or `brew install openssl`')
    if sys.version_info < (3, 10):
        missing.append(f'python3 >= 3.10 required (this is {platform.python_version()}): `brew install python`')
    return missing


def corpus_roots() -> None:
    sys.path.insert(0, str(HERE))
    import shortcut_action_index as sai
    counts = collections.Counter(label for label, _p, _f in sai.corpus())
    roots = [('project', sai.PROJECT), ('iCloud', sai.ICLOUD_DRIVE), ('Shortcuts', sai.SHORTCUTS_DOCS),
             ('Gallery', sai.GALLERY), ('local', sai.LOCAL_LIBRARY)]
    print('corpus roots (real samples the write-gate and the agent copy from):')
    for label, root in roots:
        state = f'{counts[label]} file(s)' if root.is_dir() else 'not found'
        print(f'  {label:9s} {state:12s} {root}')
    if not sai.LOCAL_LIBRARY.is_dir():
        print('  local (optional, for your own use only): more examples from ShortcutsBench. Download the raw dataset '
              'linked from https://github.com/EachSheep/ShortcutsBench (zip password shortcutsbench), then run')
        print(f'    python3 {shlex.quote(str(HERE / "build_action_library.py"))} --sbench '
              '<dir>/1_final_detailed_records_remove_repeat.json')
    if counts['extra']:
        print(f'  {"extra":9s} {counts["extra"]} file(s)  SHORTCUT_CORPUS')
    print('  add more: SHORTCUT_CORPUS=<dir>[:<dir>...]; export a shortcut with Share → Export File to add it')


def setup(qa: str | None, cmd: str | None) -> int:
    if qa is None:
        if not sys.stdin.isatty():
            print('choose QA for this project, then re-run with --qa:')
            for k, v in CHOICES.items():
                print(f'  --qa {k:8s} {v}')
            return 2
        for i, (k, v) in enumerate(CHOICES.items(), 1):
            print(f'  {i}. {k:8s} {v}')
        qa = list(CHOICES)[int(input('which QA should every build run? [1-3] ')) - 1]
        if qa == 'own':
            cmd = input('your test command (the built file path is appended): ').strip()
    if qa == 'own' and not cmd:
        print('--qa own needs --regression-cmd "<your test command>"')
        return 2
    cfg = {'qa': qa, **({'regression_cmd': cmd} if qa == 'own' else {})}
    out = pathlib.Path.cwd() / '.shortcut-dev.json'
    out.write_text(json.dumps(cfg, ensure_ascii=False) + '\n')
    print(f'wrote {out}: {json.dumps(cfg, ensure_ascii=False)}')
    print('where the spec (requirements document) comes from:')
    print('  - run the shortcut-spec skill (it interviews you and writes specs/PRD.md)')
    print('  - or bring your own from any tool: save it as specs/PRD.md with stories as `### US-n` '
          'and acceptance criteria as `**ACm …**` lines')
    if qa == 'builtin':
        print('  without that file, builds stop')
    if qa == 'none':
        print(f'risk of qa = none: {NONE_RISK}')
    return 0


def selftest() -> int:
    ok = True

    def check(label, cond, detail=''):
        nonlocal ok
        ok &= bool(cond)
        print(f'  {"✅" if cond else "❌"} {label}' + (f' — {detail}' if detail and not cond else ''))

    tmp = pathlib.Path(tempfile.mkdtemp(prefix='doctor_selftest_')).resolve()
    saved_cwd = os.getcwd()
    try:
        os.chdir(tmp)                         # --setup writes ./.shortcut-dev.json; keep it out of the caller's project
        print('=== --setup spec guidance (no specs/PRD.md in the project) ===')
        for qa in ('builtin', 'none'):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = setup(qa, None)
            log = buf.getvalue()
            check(f'qa={qa}: config written, both spec routes printed',
                  rc == 0 and json.loads((tmp / '.shortcut-dev.json').read_text()) == {'qa': qa}
                  and 'run the shortcut-spec skill' in log and 'bring your own' in log
                  and '`### US-n`' in log and '`**ACm …**`' in log, log)
            check(f'qa={qa}: "builds stop" line ' + ('printed' if qa == 'builtin' else 'not printed'),
                  ('without that file, builds stop' in log) == (qa == 'builtin'), log)
            check(f'qa={qa}: none risk sentence ' + ('printed' if qa == 'none' else 'not printed'),
                  (NONE_RISK in log) == (qa == 'none'), log)
    finally:
        os.chdir(saved_cwd)
        shutil.rmtree(tmp, ignore_errors=True)
    print('selftest:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('--setup', action='store_true', help='write ./.shortcut-dev.json (the QA every build runs)')
    ap.add_argument('--qa', choices=list(CHOICES))
    ap.add_argument('--regression-cmd', help='with --qa own: your test command')
    ap.add_argument('--selftest', action='store_true', help='tempdir-only selftest of --setup')
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.setup:
        return setup(args.qa, args.regression_cmd)

    missing = checks()
    for m in missing:
        print(f'❌ {m}')
    if missing:
        return 1
    print('✅ macOS, shortcuts / aea / yaa / openssl, python3 >= 3.10')
    corpus_roots()
    cfg = next((d / '.shortcut-dev.json' for d in [pathlib.Path.cwd(), *pathlib.Path.cwd().parents]
                if (d / '.shortcut-dev.json').is_file()), None)
    if cfg:
        print(f'QA: {cfg.read_text().strip()} ({cfg})')
        print(f'next: python3 {shlex.quote(str(HERE / "shortcut_io.py"))} --tree "<your exported .shortcut>"')
    else:
        print(f'QA: not set up. next: python3 {shlex.quote(str(HERE / "doctor.py"))} --setup')
    return 0


if __name__ == '__main__':
    sys.exit(main())
