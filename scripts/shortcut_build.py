#!/usr/bin/env python3
"""Build helpers for `.shortcut` patch scripts, and the write-gate every build goes through.

## Helpers (one copy of what the product patch scripts duplicated)

    uid(tag)                 deterministic UUID, hex 8-4-4-4-12 (same tag → same UUID → reruns give the same plist md5)
    var(name) / out(u, name) bare refs: a named variable / the output of the action whose UUID is u
    attach(ref)              WFTextTokenAttachment (single-ref params such as setvariable WFInput)
    tok(template, refs)      "{{name}}" → ￼ + attachmentsByRange; offsets are UTF-16 code units
    setvar(name, ref)        setvariable action reading `ref`
    locate(actions, pred)    index of the one action matching pred; raises on 0 or >1 matches

## Write-gate: write(actions_or_plist, target, feature=..., source=..., regression=...)

The QA choice comes from `.shortcut-dev.json`, the first one found in `target`'s directory or its parents, then
the current directory or its parents (written by `doctor.py --setup`). No file → the build stops before signing
and prints the setup command; there is no default. The file holds {"qa": "builtin" | "own" | "none"} and, for
"own", "regression_cmd": the user's own test command.

The plist is signed (shortcut_io.save_shortcut) to a hidden tmp file next to `target`, read back, and gated.
Gates run in this order; the first failure stops the build:

    1 audit_wiring   audit_wiring.audit_actions on the read-back actions; any ERROR (C1–C6) stops.
    2 coverage       qa=builtin only: ac_coverage.py --spec <product>/specs/PRD.md --cases <product>/specs/ac-matrix.md
                     when both exist; non-zero stops. No specs/PRD.md stops, naming its path (the target's own
                     folder + specs/PRD.md when no product folder is found) and both routes: the shortcut-spec
                     skill, or your own spec saved as specs/PRD.md. PRD.md present, no ac-matrix.md → one INFO line
                     naming the matrix and the next step (shortcut-qa skill); the build goes on.
    3 regression     `regression=` / --regression "<cmd>" overrides; else qa=own → regression_cmd;
                     qa=builtin → every <product>/scripts/*regression*.py run as `python3 <script> <tmp>`;
                     the tmp file path is appended as the last argument; none found → INFO line. Non-zero stops.
                     qa=none → one INFO line: wiring audit only, no coverage or regression gate.
    4 real-sample    every action identifier in the new file that is not in the source file must have
                     ≥1 sample in the shortcut_action_index corpus (the tmp file itself excluded); missing stops.

"product" = nearest ancestor directory of `target` that contains `specs/` or `scripts/`.
"source" = `source=` if given, else `target` if it already exists, else none (every identifier counts as new).
All pass → os.replace(tmp, target). Any stop → GateError (exit 1), target untouched, tmp removed.

## Delivery

After os.replace: print the plist md5 (WFWorkflowActions, protocol §7.9 ⑦b) and the caller's one-line visible
feature, then open the import dialog with `open -a Shortcuts <target>` — only in an interactive run
(CLAUDE_CODE_ENTRYPOINT=cli, or no entrypoint and a TTY on stdin), never with SHORTCUT_NO_OPEN=1.
Otherwise the open command is printed. The click on Add in that dialog is Apple's: the `shortcuts` CLI has
run / list / view / sign and no import, so a person always confirms the import.
When `shortcuts list` already has the target's name (file stem), an interactive run first deletes every copy of it
through replace_old.replace() (one 削除), because the import would add a second same-named shortcut; キャンセル or no
answer → GateError with the target written and nothing opened. A non-interactive run prints both commands.

## Usage

    from shortcut_build import tok, var, out, uid, setvar, locate, write
    write(plist, OUT, feature='entry row shows 📊 today', source=SRC)

    python3 shortcut_build.py BUILT TARGET --feature TEXT [--source SRC] [--regression "CMD"]
    python3 shortcut_build.py --selftest     # tempdir only; `open` replaced by a recording stub
"""
import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import pathlib
import plistlib
import re
import shlex
import subprocess
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from shortcut_io import open_shortcut, save_shortcut  # noqa: E402
from audit_wiring import audit, audit_actions  # noqa: E402
import shortcut_action_index  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1] if HERE.parent.name == 'automation' else HERE.parent   # source checkout: scripts/ · plugin: scripts/
AC_COVERAGE = ROOT / 'scripts/ac_coverage.py'
CONFIG = '.shortcut-dev.json'
QA_CHOICES = ('builtin', 'own', 'none')
OBJ = '￼'
SETVAR = 'is.workflow.actions.setvariable'


class GateError(SystemExit):
    """A gate failed: nothing was written. Uncaught, it exits 1 with the message."""


# ── helpers ──────────────────────────────────────────────────────────────────

def uid(tag: str) -> str:
    h = hashlib.md5(tag.encode()).hexdigest().upper()
    return f'{h[:8]}-{h[8:12]}-4{h[13:16]}-8{h[17:20]}-{h[20:32]}'


def var(name: str) -> dict:
    return {'Type': 'Variable', 'VariableName': name}


def out(uuid_: str, name: str) -> dict:
    return {'Type': 'ActionOutput', 'OutputUUID': uuid_, 'OutputName': name}


def attach(ref: dict) -> dict:
    return {'WFSerializationType': 'WFTextTokenAttachment', 'Value': ref}


def _u16(s: str) -> int:
    return len(s.encode('utf-16-le')) // 2


def tok(template: str, refs: dict | None = None) -> dict:
    """`{{name}}` → ￼ bound to refs[name]. Offsets count UTF-16 code units (an emoji = 2), which is what
    Shortcuts stores and what audit_wiring C6 checks. No placeholder → no attachmentsByRange key (as in
    every real sample: 3245 plain token strings, none with an empty dict)."""
    if OBJ in template:
        raise ValueError('template already contains ￼; write each placeholder as {{name}}')
    s, att, i = '', {}, 0
    while i < len(template):
        if template.startswith('{{', i):
            j = template.index('}}', i)
            att[f'{{{_u16(s)}, 1}}'] = refs[template[i + 2:j]]
            s += OBJ
            i = j + 2
        else:
            s += template[i]
            i += 1
    return {'WFSerializationType': 'WFTextTokenString',
            'Value': {'string': s, 'attachmentsByRange': att} if att else {'string': s}}


def setvar(name: str, ref: dict) -> dict:
    """WFInput must be a ref, not a bare string (a bare string leaves the variable empty, protocol §7.6b)."""
    return {'WFWorkflowActionIdentifier': SETVAR,
            'WFWorkflowActionParameters': {'WFVariableName': name, 'WFInput': attach(ref)}}


def locate(actions: list, pred, what: str = 'target') -> int:
    hits = [i for i, a in enumerate(actions) if pred(a)]
    if len(hits) != 1:
        raise LookupError(f'{what}: expected exactly 1 matching action, found {len(hits)} at {hits}')
    return hits[0]


def plist_md5(actions: list) -> str:
    return hashlib.md5(plistlib.dumps(actions, fmt=plistlib.FMT_BINARY)).hexdigest()


# ── write-gate ───────────────────────────────────────────────────────────────

def product_dir(target: pathlib.Path) -> pathlib.Path | None:
    # Exact-case names: macOS is case-insensitive, so `is_dir()` alone would take ~/Library (it has `Scripts/`).
    for d in target.resolve().parents:
        if any(n in ('specs', 'scripts') and (d / n).is_dir() for n in os.listdir(d)):
            return d
    return None


def qa_config(target: pathlib.Path) -> dict:
    """The first .shortcut-dev.json above target, else above the cwd. Missing or invalid → GateError with the fix."""
    cwd = pathlib.Path.cwd().resolve()
    DOCTOR = shlex.quote(str(HERE / 'doctor.py'))
    for d in [*target.parents, cwd, *cwd.parents]:
        f = d / CONFIG
        if f.is_file():
            cfg = json.loads(f.read_text())
            if cfg.get('qa') not in QA_CHOICES or (cfg['qa'] == 'own' and not cfg.get('regression_cmd')):
                raise GateError(f'❌ {f}: qa must be one of {"/".join(QA_CHOICES)}; "own" also needs "regression_cmd"')
            cfg['path'] = str(f)
            return cfg
    raise GateError(f'❌ no {CONFIG} found above {target.parent} or the current directory — choose how builds are '
                    f'tested, once per project (run from the project root):\n'
                    f'   python3 {DOCTOR} --setup --qa builtin\n'
                    f'   python3 {DOCTOR} --setup --qa own --regression-cmd "<your test command>"\n'
                    f'   python3 {DOCTOR} --setup --qa none')


def _run(cmd: list, label: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, 'SHORTCUT_KIT_SCRIPTS': str(HERE)})
    if r.returncode != 0:
        print((r.stdout + r.stderr)[-2500:])
        raise GateError(f'❌ gate {label} failed (exit {r.returncode}): {shlex.join(cmd)}')
    counts = [ln.strip() for ln in r.stdout.splitlines() if re.search(r'(?<![\w-])\d+/\d+\s+\w', ln)][-2:]
    print(f'  ✅ {label}: {shlex.join(cmd[-2:])} exit 0' + ''.join(f'\n       {c}' for c in counts))


def _gate_audit(actions: list) -> None:
    findings = audit_actions(actions)
    errs = [m for lv, m in findings if lv == 'ERROR']
    warns = [m for lv, m in findings if lv == 'WARN']
    for m in errs:
        print(f'  🔴 {m}')
    if errs:
        raise GateError(f'❌ gate 1 audit_wiring: {len(errs)} ERROR')
    print(f'  ✅ 1 audit_wiring: 0 ERROR, {len(warns)} WARN')


def _gate_coverage(product: pathlib.Path | None, qa: str, folder: pathlib.Path) -> None:
    """`folder` = the target's directory: where specs/PRD.md belongs when no product folder is found."""
    if qa != 'builtin':
        print(f'  ℹ️ 2 coverage gate not run: qa = {qa}')
        return
    prd, matrix = (product / 'specs/PRD.md', product / 'specs/ac-matrix.md') if product else (None, None)
    if not (prd and prd.is_file()):
        raise GateError(f'❌ gate 2 coverage: qa = builtin needs {prd or folder / "specs/PRD.md"}, and it is '
                        'missing. Add the spec one of two ways, then build again:\n'
                        '   - run the shortcut-spec skill (it interviews you and writes specs/PRD.md)\n'
                        '   - or save your own spec as specs/PRD.md with stories as `### US-n` and acceptance '
                        'criteria as `**ACm …**` lines')
    if not matrix.is_file():
        print(f'  ℹ️ 2 coverage gate skipped: missing {matrix}\n       matrix: run the shortcut-qa skill')
        return
    _run([sys.executable, str(AC_COVERAGE), '--spec', str(prd), '--cases', str(matrix)], '2 coverage')


def _gate_regression(product: pathlib.Path | None, regression: str | None, tmp: pathlib.Path, cfg: dict) -> None:
    qa = cfg['qa']
    regression = regression or (cfg.get('regression_cmd') if qa == 'own' else None)
    if regression:
        cmds = [shlex.split(regression) + [str(tmp)]]
    elif qa == 'none':
        print('  ℹ️ 3 qa = none: wiring audit only — no coverage or regression gate ran')
        return
    else:
        scripts = sorted((product / 'scripts').glob('*regression*.py')) if product else []
        cmds = [[sys.executable, str(s), str(tmp)] for s in scripts]
    if not cmds:
        print('  ℹ️ 3 regression gate skipped: no regression command and no <product>/scripts/*regression*.py')
    for cmd in cmds:
        _run(cmd, '3 regression')


def _gate_corpus(actions: list, source_ids: set, tmp: pathlib.Path) -> None:
    new = sorted({a['WFWorkflowActionIdentifier'] for a in actions} - source_ids)
    if not new:
        print('  ✅ 4 real-sample: no action identifier new to the source file')
        return
    index, _ = shortcut_action_index.build_index()
    missing = [i for i in new if not any(stem != tmp.stem for _lb, stem, _ in index.get(i, []))]
    if missing:
        raise GateError(f'❌ gate 4 real-sample: no real sample of {", ".join(missing)} — export a shortcut '
                        'that uses it into the corpus first (shortcut_action_index.py --list / --dump)')
    print(f'  ✅ 4 real-sample: {len(new)} new identifier(s) all have samples')


def _interactive() -> bool:
    # CLAUDE_CODE_ENTRYPOINT is "cli" in an interactive Claude Code session (seen in this session's env).
    # Headless `claude -p` sets "sdk-cli": claude 2.1.296's own code does set(ENTRYPOINT, print ? "sdk-cli" :
    # "cli") and rewrites an inherited "cli" to "sdk-cli" (read 2026-10-10; the runtime check was denied).
    # launchd: no entrypoint and no TTY. The Bash tool has no TTY, so isatty alone would never fire there.
    if os.environ.get('SHORTCUT_NO_OPEN') == '1':
        return False
    ep = os.environ.get('CLAUDE_CODE_ENTRYPOINT')
    return ep == 'cli' if ep else sys.stdin.isatty()


def write(actions_or_plist, target, *, feature: str, source=None, regression: str | None = None) -> str:
    """Gate, then land `target` and open the import dialog (interactive runs). Returns the plist md5."""
    target = pathlib.Path(target).resolve()
    source = pathlib.Path(source) if source else (target if target.exists() else None)
    src_plist = open_shortcut(source) if source else None
    if isinstance(actions_or_plist, dict):
        plist = actions_or_plist
    elif src_plist is None:
        raise ValueError('actions given without a source file to take the plist from; pass a full plist')
    else:
        plist = copy.deepcopy(src_plist)
        plist['WFWorkflowActions'] = actions_or_plist
    source_ids = {a['WFWorkflowActionIdentifier'] for a in src_plist['WFWorkflowActions']} if src_plist else set()

    cfg = qa_config(target)
    tmp = target.with_name(f'.{target.stem}.build-{uuid.uuid4().hex[:8]}{target.suffix}')
    product = product_dir(target)
    print(f'build {target.name} (product: {product or "none"} · qa = {cfg["qa"]} from {cfg["path"]})')
    try:
        save_shortcut(plist, tmp)
        actions = open_shortcut(tmp)['WFWorkflowActions']
        _gate_audit(actions)
        _gate_coverage(product, cfg['qa'], target.parent)
        _gate_regression(product, regression, tmp, cfg)
        _gate_corpus(actions, source_ids, tmp)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)

    md5 = plist_md5(actions)
    print(f'✅ wrote {target} · plist md5 {md5}\n   after import you will see: {feature}')
    cmd = ['open', '-a', 'Shortcuts', str(target)]
    import replace_old  # here, not at the top: it imports this module
    if _interactive():
        replace_old.replace(target.stem, target)  # GateError (nothing opened) unless the old copy is gone
        subprocess.run(cmd, check=True)
        print('   import dialog opened — press 追加 (Add); the click is Apple\'s, no CLI import exists')
    elif replace_old.listed(target.stem):
        print(f'   not opening (non-interactive run); {target.stem} already exists, so delete it (one 削除), '
              f'then import: {replace_old.retry(target.stem, target)}')
    else:
        print(f'   not opening (non-interactive run); to import: {shlex.join(cmd)}')
    return md5


# ── selftest ─────────────────────────────────────────────────────────────────

def selftest() -> int:
    import shutil
    import tempfile
    ok = True

    def check(label, cond, detail=''):
        nonlocal ok
        ok &= bool(cond)
        print(f'  {"✅" if cond else "❌"} {label}' + (f' — {detail}' if detail and not cond else ''))

    def md5f(p):
        return hashlib.md5(p.read_bytes()).hexdigest()

    print('=== helpers (in memory) ===')
    u0, u2 = uid('t0'), uid('t2')
    acts = [
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.gettext',
         'WFWorkflowActionParameters': {'UUID': u0, 'WFTextActionText': tok('160')}},
        setvar('身長', out(u0, 'テキスト')),
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.gettext',
         'WFWorkflowActionParameters': {'UUID': u2, 'WFTextActionText': tok('📊 身長 {{h}} cm', {'h': var('身長')})}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.showresult',
         'WFWorkflowActionParameters': {'Text': tok('{{x}}', {'x': out(u2, 'テキスト')})}},
    ]
    att = acts[2]['WFWorkflowActionParameters']['WFTextActionText']['Value']['attachmentsByRange']
    check('emoji before placeholder → offset {6, 1} (UTF-16; code points would give 5)', list(att) == ['{6, 1}'],
          list(att))
    check('plain text → no attachmentsByRange key', acts[0]['WFWorkflowActionParameters']['WFTextActionText']
          == {'WFSerializationType': 'WFTextTokenString', 'Value': {'string': '160'}})
    check('uid deterministic, hex 8-4-4-4-12', uid('t0') == u0 and len(u0) == 36 and
          all(c in '0123456789ABCDEF-' for c in u0))
    errs = [m for lv, m in audit_actions(acts) if lv in ('ERROR', 'WARN')]
    check('audit_wiring on built actions: 0 ERROR / 0 WARN (C6 passes after emoji)', not errs, errs)
    bad = copy.deepcopy(acts)
    bad[2]['WFWorkflowActionParameters']['WFTextActionText']['Value']['attachmentsByRange'] = {'{5, 1}': var('身長')}
    check('destroy: offset shifted by one → C6 ERROR', any(m.startswith('C6') for lv, m in audit_actions(bad)))
    try:
        locate(acts, lambda a: a['WFWorkflowActionIdentifier'].endswith('gettext'))
        check('locate raises on 2 matches', False)
    except LookupError:
        check('locate raises on 2 matches', True)
    check('locate returns the unique match', locate(acts, lambda a: a['WFWorkflowActionIdentifier'] == SETVAR) == 1)

    tmp = pathlib.Path(tempfile.mkdtemp(prefix='shortcut_build_selftest_')).resolve()
    saved_env, saved_stdin, saved_cwd = dict(os.environ), sys.stdin, os.getcwd()
    try:
        os.chdir(tmp)                         # config lookup must not reach the caller's project
        cfg_file = tmp / CONFIG
        cfg_file.write_text('{"qa": "builtin"}')
        prod = tmp / 'prod'
        (prod / 'scripts').mkdir(parents=True)
        (prod / 'out').mkdir()
        calls, fail_flag, reg_log = tmp / 'open_calls.txt', prod / 'FAIL', tmp / 'reg_args.txt'
        (prod / 'scripts/stub_regression.py').write_text(
            'import pathlib, sys\n'
            f'pathlib.Path({str(reg_log)!r}).write_text(sys.argv[1])\n'
            f'sys.exit(1 if pathlib.Path({str(fail_flag)!r}).exists() else 0)\n')
        shim = tmp / 'bin'
        shim.mkdir()
        (shim / 'open').write_text(f'#!/bin/sh\necho "$@" >> {shlex.quote(str(calls))}\n')
        (shim / 'open').chmod(0o755)
        (shim / 'shortcuts').write_text('#!/bin/sh\n')   # empty `shortcuts list`: no same-named shortcut to replace
        (shim / 'shortcuts').chmod(0o755)
        os.environ['PATH'] = f'{shim}{os.pathsep}{os.environ["PATH"]}'
        if shutil.which('open') != str(shim / 'open') or shutil.which('shortcuts') != str(shim / 'shortcuts'):
            print('  ❌ open/shortcuts stub not first on PATH — aborting before any build')
            return 1
        sys.stdin = open(os.devnull)          # entrypoint-unset case must not depend on the caller's TTY
        target = prod / 'out/T.shortcut'
        plist = {'WFWorkflowActions': acts, 'WFWorkflowClientVersion': '2607.0.2',
                 'WFWorkflowMinimumClientVersion': 900}

        def n_calls():
            return len(calls.read_text().splitlines()) if calls.exists() else 0

        def build(p, env, **kw):
            for k in ('CLAUDE_CODE_ENTRYPOINT', 'SHORTCUT_NO_OPEN'):
                os.environ.pop(k, None)
            os.environ.update(env)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    write(p, target, feature='selftest feature line', **kw)
                    return True, buf.getvalue()
                except GateError as e:
                    return False, buf.getvalue() + str(e)

        (prod / 'specs').mkdir()
        prd_stub = prod / 'specs/PRD.md'      # qa=builtin stops without it; no ac-matrix.md, so coverage only INFOs
        prd_stub.write_text('# spec stub\n')

        print('=== passing build, CLAUDE_CODE_ENTRYPOINT=cli ===')
        passed, log = build(plist, {'CLAUDE_CODE_ENTRYPOINT': 'cli'})
        check('build lands', passed and target.is_file(), log)
        back = open_shortcut(target)['WFWorkflowActions'] if target.is_file() else []
        check('round-trip through shortcut_io: actions identical', back == acts)
        check('audit_wiring on the signed file: 0 ERROR', not [m for lv, m in audit(target) if lv == 'ERROR'])
        check('regression stub ran against the tmp file, not the target',
              reg_log.exists() and pathlib.Path(reg_log.read_text()).name.startswith('.T.build-'))
        check('coverage gate INFO line names only ac-matrix.md',
              f'coverage gate skipped: missing {prod}/specs/ac-matrix.md\n' in log and 'PRD.md' not in log, log)
        check(f'open called exactly once with the target (calls={n_calls()})',
              calls.exists() and calls.read_text().splitlines() == [f'-a Shortcuts {target}'])
        check('md5 + feature line printed', f'plist md5 {plist_md5(acts)}' in log and 'selftest feature line' in log)

        print('=== write-gate destroy cases (entrypoint=cli; each must block, keep target, open 0×) ===')
        c6 = copy.deepcopy(plist)
        c6['WFWorkflowActions'] = bad
        c1 = copy.deepcopy(plist)
        c1['WFWorkflowActions'][3]['WFWorkflowActionParameters']['Text'] = tok(
            '{{x}}', {'x': out(uid('nowhere'), 'テキスト')})
        nosample = copy.deepcopy(plist)
        nosample['WFWorkflowActions'].append({'WFWorkflowActionIdentifier': 'is.workflow.actions.zz.selftest.nosample',
                                               'WFWorkflowActionParameters': {}})
        for label, p, flag, want in (('C6 offset shifted', c6, False, '🔴 C6'),
                                     ('C1 dangling ref', c1, False, '🔴 C1'),
                                     ('regression stub exits 1', plist, True, 'gate 3'),
                                     ('identifier with no corpus sample', nosample, False, 'gate 4')):
            before, n0 = md5f(target), n_calls()
            fail_flag.unlink(missing_ok=True)
            if flag:
                fail_flag.touch()
            passed, log = build(p, {'CLAUDE_CODE_ENTRYPOINT': 'cli'})
            fail_flag.unlink(missing_ok=True)
            left = [f.name for f in target.parent.iterdir() if f.name != 'T.shortcut']
            check(f'{label}: blocked at {want}, target byte-identical, open 0×, tmp removed',
                  not passed and want in log and md5f(target) == before and n_calls() == n0 and not left,
                  f'passed={passed} md5 same={md5f(target) == before} calls+={n_calls() - n0} left={left}\n{log}')

        print('=== delivery without opening (passing builds) ===')
        for label, env in (('entrypoint unset, no TTY', {}),
                           ('headless claude -p (sdk-cli)', {'CLAUDE_CODE_ENTRYPOINT': 'sdk-cli'}),
                           ('SHORTCUT_NO_OPEN=1 with entrypoint=cli',
                            {'CLAUDE_CODE_ENTRYPOINT': 'cli', 'SHORTCUT_NO_OPEN': '1'})):
            n0 = n_calls()
            passed, log = build(plist, env)
            check(f'{label}: lands, open 0×, md5 line + open command printed',
                  passed and n_calls() == n0 and 'plist md5' in log and 'open -a Shortcuts' in log, log)

        print(f'=== QA choice ({CONFIG}; entrypoint=cli) ===')
        own_cmd = f'{shlex.quote(sys.executable)} {shlex.quote(str(prod / "scripts/stub_regression.py"))}'
        for label, cfg, flag, want_pass, want in (
                ('qa=own, own test exits 1', {'qa': 'own', 'regression_cmd': own_cmd}, True, False, 'gate 3'),
                ('qa=own, own test exits 0', {'qa': 'own', 'regression_cmd': own_cmd}, False, True, '3 regression'),
                ('qa=none (failing product regression present, must not run)', {'qa': 'none'}, True, True,
                 'wiring audit only')):
            cfg_file.write_text(json.dumps(cfg))
            fail_flag.unlink(missing_ok=True)
            if flag:
                fail_flag.touch()
            before, n0 = md5f(target), n_calls()
            passed, log = build(plist, {'CLAUDE_CODE_ENTRYPOINT': 'cli'})
            fail_flag.unlink(missing_ok=True)
            check(f'{label}: {"lands, open 1×" if want_pass else "blocked, target byte-identical, open 0×"}',
                  passed == want_pass and want in log and n_calls() == n0 + want_pass
                  and (want_pass or md5f(target) == before), log)
        print('=== coverage gate (qa=builtin; entrypoint=cli) ===')
        cfg_file.write_text('{"qa": "builtin"}')
        prd_stub.unlink()
        target.unlink()
        n0 = n_calls()
        passed, log = build(plist, {'CLAUDE_CODE_ENTRYPOINT': 'cli'})
        left = list(target.parent.iterdir())
        check('no specs/PRD.md: blocked at gate 2, target not created, message names the path and both routes',
              not passed and 'gate 2' in log and not target.exists() and not left and n_calls() == n0
              and f'needs {prod}/specs/PRD.md' in log and 'run the shortcut-spec skill' in log
              and 'save your own spec as specs/PRD.md' in log and '`### US-n`' in log and '`**ACm …**`' in log,
              f'passed={passed} target={target.exists()} left={left}\n{log}')
        loose = tmp / 'loose/L.shortcut'      # no specs/ or scripts/ above it → product None
        loose.parent.mkdir()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                write(plist, loose, feature='selftest feature line')
                passed = True
            except GateError as e:
                passed, msg = False, str(e)
        check('no product folder: blocked at gate 2, message names <target parent>/specs/PRD.md, target not created',
              product_dir(loose) is None and not passed and 'gate 2' in msg
              and f'needs {loose.parent}/specs/PRD.md' in msg and not any(loose.parent.iterdir()),
              f'product={product_dir(loose)} passed={passed}\n{buf.getvalue()}')
        prd_stub.write_text('# spec stub\n')
        passed, log = build(plist, {'CLAUDE_CODE_ENTRYPOINT': 'cli'})
        check('PRD.md present, no ac-matrix.md: INFO names only the matrix + shortcut-qa, build not blocked',
              passed and f'coverage gate skipped: missing {prod}/specs/ac-matrix.md\n' in log
              and 'spec:' not in log and 'matrix: run the shortcut-qa skill' in log, log)
        shutil.rmtree(prod / 'specs')
        cfg_file.unlink()
        before, n0 = md5f(target), n_calls()
        passed, log = build(plist, {'CLAUDE_CODE_ENTRYPOINT': 'cli'})
        check(f'no {CONFIG}: blocked before signing with the setup command, target byte-identical, open 0×',
              not passed and 'doctor.py' in log and '--setup --qa' in log and md5f(target) == before and n_calls() == n0, log)
    finally:
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_env)
        if sys.stdin is not saved_stdin:
            sys.stdin.close()
            sys.stdin = saved_stdin
        shutil.rmtree(tmp, ignore_errors=True)
    print('selftest:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(
        description='Gate a built shortcut plist and land it on TARGET (tmp → gates → os.replace), then deliver it.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='QA choice: the nearest .shortcut-dev.json above TARGET, else above the cwd (doctor.py --setup);\n'
               '  {"qa": "builtin"|"own"|"none"[, "regression_cmd": CMD]}; no file → no build, setup command printed\n'
               'gates, in order (first failure stops; target untouched, tmp removed, exit 1):\n'
               '  1 audit_wiring  any ERROR (C1–C6) on the signed, read-back file\n'
               '  2 coverage      qa=builtin: ac_coverage.py on <product>/specs/PRD.md + ac-matrix.md; no PRD.md → stop,\n'
               '                  naming its path and both routes (shortcut-spec skill, or your own specs/PRD.md);\n'
               '                  PRD.md but no ac-matrix.md → INFO line naming the matrix and the shortcut-qa skill\n'
               '  3 regression    --regression CMD, else qa=own → regression_cmd, qa=builtin → <product>/scripts/\n'
               '                  *regression*.py (tmp path appended); none found → INFO line; qa=none → INFO line\n'
               '  4 real-sample   each action identifier not in the source file needs ≥1 corpus sample\n'
               'product = nearest ancestor of TARGET containing specs/ or scripts/.\n'
               'delivery: prints plist md5 + --feature; runs `open -a Shortcuts TARGET` only when interactive\n'
               '(CLAUDE_CODE_ENTRYPOINT=cli, or unset with a TTY; never with SHORTCUT_NO_OPEN=1), else prints it;\n'
               'a shortcut already listed under TARGET\'s name is deleted first (replace_old.py, one 削除 click).\n'
               'Pressing Add in the import dialog is Apple\'s step: the shortcuts CLI has no import command.')
    ap.add_argument('built', nargs='?', help='built plist: a .shortcut, or a raw .wflow / .plist')
    ap.add_argument('target', nargs='?', help='.shortcut to write')
    ap.add_argument('--feature', help='one line the user will see after import (required with BUILT TARGET)')
    ap.add_argument('--source', help='file the build started from (default: TARGET if it exists)')
    ap.add_argument('--regression', metavar='CMD', help='regression command; the tmp file path is appended')
    ap.add_argument('--selftest', action='store_true', help='tempdir-only selftest; never calls the real open')
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not (args.built and args.target and args.feature):
        ap.error('give BUILT TARGET --feature TEXT, or --selftest')
    built = pathlib.Path(args.built)
    plist = open_shortcut(built) if built.suffix == '.shortcut' else plistlib.loads(built.read_bytes())
    write(plist, args.target, feature=args.feature, source=args.source, regression=args.regression)


if __name__ == '__main__':
    main()
