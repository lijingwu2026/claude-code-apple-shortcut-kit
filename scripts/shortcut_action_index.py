#!/usr/bin/env python3
"""Shortcut action corpus index: "to build some action, where is a byte-for-byte real sample?"

## Why it exists (the lesson of 2026-07-30)

When generating or modifying a shortcut programmatically, **hand-writing the parameter schema of an
action you have never seen fails silently** (Shortcuts does not validate parameters, and `shortcuts sign`
signs them anyway; the break only shows at run time on a device). So the discipline is: **use only
action types that have a real sample**.

The trouble is that I answered "is there a sample?" wrong twice in a row. The first time I said "6 are
missing, please hand-build a harness shortcut for me", when 3 of them were in two shortcuts in the same repo.
The second time I said "only `addnewevent` is a hard gap", and one sentence from the user, "go look at the time
tracker in iCloud Drive", filled all of them (that one file has 525 actions / 53 types).

**Conclusion: run this script before you start. Do not guess, do not ask.**

## Corpus (scanned by default)

| Source | Contents |
|---|---|
| every `*.shortcut` under the current directory (the project; in a source checkout, run from its root) | your own products + backups |
| every `*.shortcut` and `*.wflow` under the plugin's `examples/` (next to `scripts/`) | the examples shipped with the plugin, including `action-library/` (one neutralized sample per action type), so a user with no shortcuts of their own still has samples |
| `*.shortcut` at the iCloud Drive root | saved from elsewhere (often **the largest ones**) |
| `*.shortcut` in the Shortcuts app's iCloud Documents folder | files shortcuts read and write |
| system Gallery `*.wflow` | Apple's official samples (unsigned bare plists) |
| `*.wflow` under `~/Library/Application Support/apple-shortcut-kit/action-library/` (`local`) | your own library built by `build_action_library.py --sbench` (optional; for your own use only) |
| every `*.shortcut` under each directory in `SHORTCUT_CORPUS` (`:`-separated) | anything else you add |

⚠️ **Not scannable**: shortcuts that are installed but never exported (`~/Library/Shortcuts/` and Group
Containers are blocked by TCC; reading them needs Full Disk Access for the terminal). `shortcuts list`
shows names but not contents -> to get one into the corpus, export it to a file first.

## Usage

    python3 shortcut_action_index.py                      # full index (listed by type, with sample locations)
    python3 shortcut_action_index.py addnewevent exit     # only these (fuzzy match)
    python3 shortcut_action_index.py --dump addnewevent   # print the full parameter schema of the first sample
    python3 shortcut_action_index.py --check dictionary exit addnewevent   # answers yes/no only; exit code = number missing
    python3 shortcut_action_index.py --param 'conditional:WFCondition=4'  # samples with that parameter value, grouped by client version
    python3 shortcut_action_index.py --param 'conditional:WFCondition=4' --for MyShortcut.shortcut  # exit non-zero when the target's generation has 0 samples
    python3 shortcut_action_index.py --toolkit appendnote  # Apple's ToolKit catalog: an action's setting keys and legal values (not proof a value works)
    python3 shortcut_action_index.py --selftest            # self-check the --param logic with synthetic fixtures
    python3 shortcut_action_index.py --list 菜单 --lang ja,zh_CN  # catalog layer: which actions exist (two columns, not joined; see the output notes)
"""
import argparse
import collections
import json
import os
import pathlib
import plistlib
import pprint
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from shortcut_io import open_shortcut  # noqa: E402

PROJECT = pathlib.Path.cwd()
PLUGIN_EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / 'examples'  # the plugin's bundled examples; absent in a source checkout
LOCAL_LIBRARY = pathlib.Path.home() / 'Library/Application Support/apple-shortcut-kit/action-library'  # build_action_library.py --sbench
ICLOUD_DRIVE = pathlib.Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs'
SHORTCUTS_DOCS = pathlib.Path.home() / 'Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents'
GALLERY = pathlib.Path('/System/Library/PrivateFrameworks/WorkflowKit.framework'
                       '/Resources/Gallery.bundle/Contents/Resources')
LOCTABLE = pathlib.Path('/System/Library/PrivateFrameworks/WorkflowKit.framework'
                        '/Resources/Localizable.loctable')
PREFIX = 'is.workflow.actions.'
# Apple's ToolKit action catalog (--toolkit; build_action_library.py --audit), extracted by Viticci (MIT). Looked up in this order.
TOOLKIT_FILES = ('toolkit-v78-first-party-parameter-keys.json', 'toolkit-v78-first-party-enum-cases.json')
_ROOT = pathlib.Path(__file__).resolve().parent.parent          # the plugin root; in a source checkout, the automation folder
TOOLKIT_DIRS = [_ROOT / 'data' / 'toolkit']                      # the plugin's bundled copy
if _ROOT.name == 'automation':                                   # source checkout: the vendored copy
    TOOLKIT_DIRS.append(_ROOT.parent.joinpath('knowledge', 'learning', 'ai', 'upstream-docs', '2026-09',
                                              'shortcuts-toolkit-catalog-viticci'))


def _in_hidden_dir(p: pathlib.Path, root: pathlib.Path = PROJECT) -> bool:
    """True if p's path relative to root has a directory starting with `.`. Under `.claude/worktrees/` are copies of
    checkout files (they would double the sample counts); `.trash/` holds deleted files. ⚠️ It must use the
    relative path: when the clone itself lives under `~/.something/`, a dot-dir in the absolute path must not
    exclude the whole corpus."""
    return any(part.startswith('.') for part in p.relative_to(root).parts)


def corpus() -> list[tuple[str, pathlib.Path, str]]:
    """Return [(source label, path, format)]. Format = 'signed' (.shortcut) / 'raw' (.wflow)."""
    items, seen = [], set()

    def add(label, p, fmt):
        if p.resolve() not in seen:
            seen.add(p.resolve())
            items.append((label, p, fmt))

    extra = [pathlib.Path(d).expanduser() for d in os.environ.get('SHORTCUT_CORPUS', '').split(os.pathsep) if d]
    for label, root in [('project', PROJECT), ('plugin', PLUGIN_EXAMPLES)] + [('extra', d) for d in extra]:
        for p in sorted(root.rglob('*.shortcut')) if root.is_dir() else []:
            if 'archive/' in str(p) or _in_hidden_dir(p, root):
                continue
            add(label, p, 'signed')
        if label == 'plugin' and root.is_dir():
            for p in sorted(root.rglob('*.wflow')):
                if not _in_hidden_dir(p, root):
                    add(label, p, 'raw')
    for label, root in (('iCloud', ICLOUD_DRIVE), ('Shortcuts', SHORTCUTS_DOCS)):
        for p in sorted(root.glob('*.shortcut')) if root.is_dir() else []:
            add(label, p, 'signed')
    for p in sorted(LOCAL_LIBRARY.rglob('*.wflow')) if LOCAL_LIBRARY.is_dir() else []:
        add('local', p, 'raw')
    if GALLERY.is_dir():
        for p in sorted(GALLERY.glob('*.wflow')):
            add('Gallery', p, 'raw')
    return items


def load(path: pathlib.Path, fmt: str) -> list:
    if fmt == 'raw':
        return plistlib.loads(path.read_bytes())['WFWorkflowActions']
    return open_shortcut(path)['WFWorkflowActions']


def build_index() -> tuple[dict, list]:
    """-> ({action_id: [(source label, file name, action index), ...]}, [(source label, file name, action count, type count)])"""
    index = collections.defaultdict(list)
    files = []
    for label, path, fmt in corpus():
        try:
            acts = load(path, fmt)
        except Exception as e:                      # one bad file must not take down the whole index
            files.append((label, path.stem, -1, f'read failed: {type(e).__name__}'))
            continue
        for i, a in enumerate(acts):
            index[a['WFWorkflowActionIdentifier']].append((label, path.stem, i))
        files.append((label, path.stem, len(acts),
                      len({a['WFWorkflowActionIdentifier'] for a in acts})))
    return dict(index), files


def short(ident: str) -> str:
    return ident[len(PREFIX):] if ident.startswith(PREFIX) else ident


# ⚠️ The corpus is **live**: a file you just generated and saved this round counts toward the sample count on the next scan.
# So the conclusion "a sample exists" gets polluted by your own output -- and §7.3/§7.4 discipline 1 "use only
# action types that have a sample" depends entirely on it. Measured (2026-08-03): `--check format.number` reported 5 samples,
# of which **4 were products just written that round**; the only truly pre-existing sample was 1, and its parameter value was not the one needed.
# -> I nearly read "my guess" as "the corpus supports this value". See problem-log C16 / protocol §7.9 ⑧.
_FRESH_SECONDS = 24 * 3600


def _fresh_stems() -> set:
    """Stems of corpus files saved within the last 24h -- very likely this round's own products.
    Plugin and local-library files are skipped: they are never this round's output, and a fresh clone or a library
    rebuild gives them new mtimes."""
    import time
    now = time.time()
    out = set()
    for label, path, _fmt in corpus():
        if label in ('plugin', 'local'):
            continue
        try:
            if now - path.stat().st_mtime < _FRESH_SECONDS:
                out.add(path.stem)
        except OSError:
            pass
    return out


def _resolve_ident(index: dict, query: str) -> str | None:
    """Resolve a query word to a unique identifier -- exactly the same matching rule as --check/--dump
    (substring match on the identifier; with several hits take the one with the most samples). No third rule is invented."""
    hits = [k for k in index if query in k]
    if not hits:
        return None
    return sorted(hits, key=lambda k: -len(index[k]))[0]


def _read_client_version(path: pathlib.Path):
    """Read WFWorkflowMinimumClientVersion at the top level of a corpus file (not an action-level field).
    .wflow (raw / unsigned, including the synthetic fixtures of --selftest) goes straight through plistlib;
    .shortcut (signed) goes through shortcut_io's signature verification and decryption."""
    if path.suffix == '.wflow':
        d = plistlib.loads(path.read_bytes())
    else:
        d = open_shortcut(path)
    return d.get('WFWorkflowMinimumClientVersion')


def _param_query(index: dict, ident: str, key: str, value: str, fresh: set) -> dict:
    """Among all samples of ident, those whose parameter KEY equals VALUE -- grouped by WFWorkflowMinimumClientVersion.
    -> {version: {'total': N, 'fresh': N}} (fresh uses the existing _fresh_stems(); no separate mtime logic).
    Values are compared as strings (in a plist the number 4 and the string "4" can both occur)."""
    samples = index.get(ident, [])
    by_stem = collections.defaultdict(list)
    for _label, stem, i in samples:
        by_stem[stem].append(i)

    stem_to_file = {}
    for _label, path, fmt in corpus():
        stem_to_file.setdefault(path.stem, (path, fmt))

    groups: dict = collections.defaultdict(lambda: {'total': 0, 'fresh': 0})
    for stem, indices in by_stem.items():
        entry = stem_to_file.get(stem)
        if entry is None:
            continue
        path, fmt = entry
        try:
            full = plistlib.loads(path.read_bytes()) if fmt == 'raw' else open_shortcut(path)
        except Exception:
            continue
        acts = full.get('WFWorkflowActions', [])
        version = full.get('WFWorkflowMinimumClientVersion')
        for i in indices:
            if i >= len(acts):
                continue
            params = acts[i].get('WFWorkflowActionParameters', {})
            if key not in params:
                continue
            if str(params[key]) != str(value):
                continue
            g = groups[version]
            g['total'] += 1
            if stem in fresh:
                g['fresh'] += 1
    return dict(groups)


# ── ① Catalog layer: --list (added 2026-09-07, per shortcut-experience-codify plan §A-1) ────────
#
# There are two data sources, **side by side and not joined**: the system loctable (_load_loctable below, 45 languages, knows names only)
# + the local corpus (build_index above, which certainly has real samples). The identifier <-> display-name mapping does not
# exist on this machine -- I ruled out, one by one: AssistantIntents metadata / PlugIns / XPCServices / Shortcuts.momd /
# Assets.car / the whole Shortcuts.app tree / the binaries of 9 related frameworks (all swallowed into the dyld shared cache) / the app
# executable's strings (only 11 hard-coded). So the two sections below are listed independently, **with no cross-column guessing or stitching**.

def _load_loctable():
    """The system's own 45-language action string table -- exists only on this Mac (or the same OS version); if it cannot
    be read, return None (callers must handle that gracefully and not assume it is always there)."""
    try:
        return plistlib.loads(LOCTABLE.read_bytes())
    except OSError:
        return None


def _loc_action_names(loctable: dict) -> list:
    """All keys in the en group that end with `(Action Name)`, suffix removed -- the full set of "which actions can be
    named" on the loctable side. The count changes with the iOS version; do not copy it into a comment, run `--list` and read the line it prints."""
    tail = ' (Action Name)'
    en = loctable.get('en', {})
    return sorted(k[:-len(tail)] for k in en if k.endswith(tail))


def _loc_search(loctable: dict, keyword: str) -> list:
    """Filter the `(Action Name)` entries by keyword -- the keyword may be Chinese/Japanese, so do not try only the English base name;
    try the value in each of the 45 languages, and any hit counts."""
    tail = ' (Action Name)'
    bases = _loc_action_names(loctable)
    if not keyword:
        return bases
    kw = keyword.lower()
    hits = []
    for base in bases:
        if kw in base.lower():
            hits.append(base)
            continue
        full_key = base + tail
        for lang, table in loctable.items():
            if lang in ('LocProvenance', 'en'):
                continue
            v = table.get(full_key)
            if v and kw in str(v).lower():
                hits.append(base)
                break
    return hits


def _mined_output_names(ident: str) -> collections.Counter:
    """Across all corpus files, collect "what other actions call the output of some sample of this identifier" --
    it reads the `OutputName` literal carried by the downstream ActionOutput references to it in real samples. No table lookup, no
    guessing, no dependence on the loctable (the loctable has no entry for this identifier at all) -- this value is the
    default output name the device language actually displayed when that shortcut was authored. The corpus this was written
    against is almost entirely authored in Japanese, so it is labelled ja directly, with no language detection (the top of the `--list` output already says the two
    columns are not joined; this is the other side of the same thing: this value is not looked up from the loctable either)."""
    counts = collections.Counter()
    for _label, path, fmt in corpus():
        try:
            acts = load(path, fmt)
        except Exception:
            continue
        own_uuids = {a['WFWorkflowActionParameters']['UUID']
                     for a in acts
                     if a.get('WFWorkflowActionIdentifier') == ident
                     and 'UUID' in a.get('WFWorkflowActionParameters', {})}
        if not own_uuids:
            continue

        def walk(o):
            if isinstance(o, dict):
                if o.get('Type') == 'ActionOutput' and o.get('OutputUUID') in own_uuids:
                    name = o.get('OutputName')
                    if name:
                        counts[name] += 1
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        walk(acts)
    return counts


_CORPUS_META_CACHE: dict = {}
_UNREADABLE = object()          # kept distinct from "the file really has no WFWorkflowMinimumClientVersion"


def _corpus_meta() -> tuple:
    """({stem: (path, fmt)}, {stem: version}) -- the latter is filled on demand.

    The cache key = the tuple of paths of the current `corpus()`, so after `--selftest` monkeypatches corpus() it
    does not hit the previous cache (the cache itself must not become yet another broken instrument)."""
    items = corpus()
    key = tuple(str(p) for _label, p, _fmt in items)
    if key not in _CORPUS_META_CACHE:
        files: dict = {}
        for _label, path, fmt in items:
            files.setdefault(path.stem, (path, fmt))
        _CORPUS_META_CACHE[key] = (files, {})
    return _CORPUS_META_CACHE[key]


def _stem_version(stem: str, meta=None):
    """WFWorkflowMinimumClientVersion at the top level of a corpus file -- each file is decrypted once per process.

    ⚠️ The reason is performance, not convenience: the original code re-decrypted every file containing an identifier each time
    that identifier was queried, and a product build script that runs the setting-value lookup queries ~30 identifiers at a time and runs it twice per build
    -> thousands of AEA1 decryptions (measured: a run did not finish in 7 minutes; `--list` without a keyword timed out for the same reason).
    **Fill on demand instead of a full scan at startup** -- someone querying one or two identifiers should not pay for the whole corpus
    (the full-scan version measured `--list text.match` going from 10 s to 40 s).

    `meta`: if the caller has already fetched `_corpus_meta()`, pass it in. ⚠️ **Not passing it is expensive** -- `_corpus_meta()`
    internally does one `rglob` over the whole project (measured 0.22 s); inside a per-stem loop that gets multiplied by the number of files
    x the number of identifiers (measured 0.22 x 80 x 21 ≈ 336 s, exactly why that build script's setting-value lookup could not finish)."""
    files, vers = meta if meta is not None else _corpus_meta()
    if stem not in vers:
        entry = files.get(stem)
        if entry is None:
            vers[stem] = _UNREADABLE
        else:
            path, fmt = entry
            try:
                full = plistlib.loads(path.read_bytes()) if fmt == 'raw' else open_shortcut(path)
                vers[stem] = full.get('WFWorkflowMinimumClientVersion')
            except Exception:                      # skip a bad file, same policy as build_index()
                vers[stem] = _UNREADABLE
    return vers[stem]


def _ident_version_groups(index: dict, ident: str) -> dict:
    """Count all samples of an identifier grouped by WFWorkflowMinimumClientVersion -- a simplified version of `_param_query()`
    without the parameter filter, reused by the catalog layer `--list` and by the setting-value lookup that a product build script runs.
    A separate implementation: it neither changes nor shares `_param_query` itself (existing --param behavior is untouched).
    -> {version: {'total': N, 'fresh': N}}, 'fresh' is defined as in `_fresh_stems()`."""
    fresh = _fresh_stems()
    samples = index.get(ident, [])
    by_stem = collections.defaultdict(list)
    for _label, stem, i in samples:
        by_stem[stem].append(i)
    meta = _corpus_meta()                          # fetch it only once -- it contains a whole-project rglob,
                                                   # and inside the loop below it would be multiplied by the number of files (see _stem_version)
    groups: dict = collections.defaultdict(lambda: {'total': 0, 'fresh': 0})
    for stem, indices in by_stem.items():
        version = _stem_version(stem, meta)        # each file is decrypted once per process; see that function's note
        if version is _UNREADABLE:                 # not in the corpus / cannot be opened: skip (same policy as before)
            continue
        g = groups[version]
        g['total'] += len(indices)
        if stem in fresh:
            g['fresh'] += len(indices)
    return dict(groups)


def _fmt_version_groups(groups: dict) -> str:
    """{version: {'total','fresh'}} -> one human-readable line, shaped like "5 sample(s) -- gen 1106: 20 / gen 5015: 54"."""
    if not groups:
        return '0 samples'
    total = sum(g['total'] for g in groups.values())
    parts = []
    for version in sorted(groups, key=lambda v: (v is None, v)):
        g = groups[version]
        vlabel = '(no version field)' if version is None else f'gen {version}'
        fresh_note = f' (incl. {g["fresh"]} saved in the last 24h)' if g['fresh'] else ''
        parts.append(f'{vlabel}: {g["total"]}{fresh_note}')
    return f'{total} sample(s) — ' + ' / '.join(parts)


# ── ToolKit catalog: --toolkit ──────────────────────────────────────────────────────────────────
#
# Apple's own list of each first-party action's setting keys and their legal values (a macOS 27 / iOS 27 snapshot of the ToolKit
# database, extracted by Viticci, MIT). It says which key exists and which value is legal -- never that a value works; that stays
# with the real samples (`--param … --for`). Known holes: control flow (If / Menu / Repeat) has no entry, and some entries miss
# keys that real files use.

# Identifiers whose real samples use keys their catalog entry does not list. Measured 2026-10-12 over corpus() minus `local`
# (project, iCloud, Gallery: 83 files, 72 catalog-covered identifiers), ignoring the plist container keys UUID, WFControlFlowMode,
# GroupingIdentifier, CustomOutputName, WFInput and AppIntentDescriptor. A missing key is either a catalog hole or a retired old key.
TOOLKIT_KEY_GAPS = frozenset('''
com.apple.mobilenotes.SharingExtension is.workflow.actions.addnewreminder is.workflow.actions.appendnote
is.workflow.actions.askllm is.workflow.actions.documentpicker.open is.workflow.actions.downloadurl
is.workflow.actions.list is.workflow.actions.runworkflow
'''.split())
TOOLKIT_HEADER = ('Apple ToolKit catalog, macOS 27 / iOS 27 snapshot, extracted by Viticci (MIT): '
                  'legal keys and values, not proof that a value works.')
TOOLKIT_SHOWN = 40          # most enum cases / candidate actions printed at once


def toolkit_dir() -> pathlib.Path | None:
    """The first of TOOLKIT_DIRS that holds both catalog files, else None."""
    return next((d for d in TOOLKIT_DIRS if all((d / f).is_file() for f in TOOLKIT_FILES)), None)


def toolkit_load(d: pathlib.Path) -> tuple[dict, dict]:
    """-> ({tool id: entry}, {enum type name: entry}) from the catalog folder d."""
    keys, enums = (json.loads((d / f).read_text()) for f in TOOLKIT_FILES)
    return keys['tools'], enums['types']


def _toolkit_match(tools: dict, query: str) -> tuple[list, str]:
    """-> (identifiers, how they matched). The first tier with a hit wins: the identifier itself (with or without the
    `is.workflow.actions.` prefix -- the name `--list` shows) / its last segment / the display name / a substring of either.
    Case-insensitive."""
    q = query.strip().lower()
    tiers = [('identifier', lambda t, n: t.lower() in (q, PREFIX + q)),
             ('last identifier segment', lambda t, n: t.rsplit('.', 1)[-1].lower() == q),
             ('display name', lambda t, n: n == q),
             ('substring', lambda t, n: q in t.lower() or q in n)]
    for how, hit in tiers:
        found = sorted(t for t, v in tools.items() if hit(t, v['displayName'].lower()))
        if found:
            return found, how
    return [], ''


def _toolkit_cmd(query: str) -> int:
    d = toolkit_dir()
    if d is None:
        print('❌ the Apple ToolKit catalog was not found; looked in:', file=sys.stderr)
        for p in TOOLKIT_DIRS:
            print(f'   {p}', file=sys.stderr)
        return 1
    tools, types = toolkit_load(d)
    hits, how = _toolkit_match(tools, query)
    if not hits:
        print(f'❌ no action in the Apple ToolKit catalog matches「{query}」', file=sys.stderr)
        print('   Control flow is never in it: If (`conditional`), Menu (`choosefrommenu`) and Repeat (`repeat.*`) have no entry '
              '-- use `--dump` for those. Otherwise run `--list <keyword>` to confirm the name.', file=sys.stderr)
        return 1
    also = []
    if len(hits) > 1 and how != 'substring':                 # several exact hits: take the one in Shortcuts' own namespace, and say so
        own = [t for t in hits if t.startswith(PREFIX)]
        if len(own) == 1:
            hits, also = own, [t for t in hits if t not in own]
    if len(hits) > 1:
        print(f'❌ 「{query}」 matches {len(hits)} actions in the Apple ToolKit catalog ({how}); name one of them:', file=sys.stderr)
        for t in hits[:TOOLKIT_SHOWN]:
            print(f'   {t}  —  {tools[t]["displayName"]}', file=sys.stderr)
        if len(hits) > TOOLKIT_SHOWN:
            print(f'   … {len(hits) - TOOLKIT_SHOWN} more', file=sys.stderr)
        return 1

    tid = hits[0]
    params = tools[tid].get('parameters', [])
    print(TOOLKIT_HEADER)
    print(f'{tid} — {tools[tid]["displayName"]}' + ('' if how == 'identifier' else f'   (matched on the {how})'))
    if also:
        print('Also matches (not shown): ' + '; '.join(f'{t} ({tools[t]["displayName"]})' for t in also))
    why = (['lists 0 parameters'] if tools[tid].get('parameterCount', 0) == 0 else []) \
        + (['is used in real samples with keys it does not list'] if tid in TOOLKIT_KEY_GAPS else [])
    if why:
        print(f'⚠️ This entry {" and ".join(why)}: a key missing here is not proof it is illegal; check `--dump`.')
    for p in params:
        names = list(dict.fromkeys(n for n in [p.get('typePythonName'), *(p.get('typePythonNames') or [])] if n))
        print(f'  {p["key"]:24s} {p.get("name", "-"):26s} {" / ".join(names) or "-"}  [{", ".join(p.get("platforms", []))}]')
        cases = list(dict.fromkeys((c['id'], c['title']) for n in names if n in types for c in types[n]['cases']))
        for cid, title in cases[:TOOLKIT_SHOWN]:
            print(f'      {cid}' + (f'  {title}' if title != cid else ''))
        if len(cases) > TOOLKIT_SHOWN:
            print(f'      … {len(cases) - TOOLKIT_SHOWN} more cases (type {", ".join(names)} in the enum-cases file)')
    return 0


# ③ Discipline layer -- for an action you have not used, run all four; for a used action with a new parameter value, run at least --param.
# Written into the --help epilog and the bare-invocation output, and no longer into any rule / skill (see the shortcut-experience-
# codify plan §A-1).
DISCIPLINE = (
    'For an action you have not used before, run all four: `--list` → `--toolkit` → `--dump` → `--param … --for`; '
    'for an action you have used, with a parameter value you have not used before, run at least `--param` '
    '(the 09-05 failure was exactly this layer: `conditional` had been used, but `WFCondition=4` had zero samples in gen 5015).'
)

NO_JOIN_BANNER = (
    '⚠️ The two columns are not joined: the identifier ↔ display-name mapping does not exist on this machine '
    '(I ruled out, one by one: AssistantIntents metadata / PlugIns / XPCServices / Shortcuts.momd / '
    'Assets.car / the whole Shortcuts.app tree / the binaries of 9 related frameworks, all swallowed into the dyld shared cache / '
    'the app executable\'s strings, only 11 hard-coded). '
    'The "① known to the system" and "② local corpus" below are two independent lists; no join is pretended.'
)


def _list_directory(index: dict, queries: list, langs: list) -> None:
    print(NO_JOIN_BANNER)
    print()

    loctable = _load_loctable()
    # The language count and the Action Name count are always computed live -- they change with the iOS version, and a hard-coded literal
    # will rot sooner or later with nothing ever scanning back for it (per CLAUDE.md "Point to changing values")
    n_lang = len(loctable) if loctable else '?'
    n_names = len(_loc_action_names(loctable)) if loctable else '?'
    print(f'① System loctable (`Localizable.loctable`, {n_lang} languages, {n_names} Action Name entries'
          f'{", keyword filter" if queries else ""}) — names only; does not guarantee the corpus has a real sample:\n')
    if loctable is None:
        print('  (this machine cannot read the loctable; skipping this layer)\n')
    else:
        bases = []
        if queries:
            seen = set()
            for q in queries:
                for b in _loc_search(loctable, q):
                    if b not in seen:
                        seen.add(b)
                        bases.append(b)
            bases.sort()
        else:
            bases = _loc_action_names(loctable)
        if not bases:
            print('  (no match)\n')
        else:
            for base in bases:
                extra = ''
                if langs:
                    vals = []
                    for lg in langs:
                        v = loctable.get(lg, {}).get(base + ' (Action Name)')
                        if v:
                            vals.append(f'{lg}:{v}')
                    if vals:
                        extra = '  [' + '  '.join(vals) + ']'
                print(f'  ⚠️ {base}{extra}')
            print()

    print(f'② Local corpus (identifier matches the keyword directly, {len(index)} types have real samples'
          f'{", keyword filter" if queries else ""}) — real samples exist:\n')
    idents = [ident for ident in sorted(index, key=short)
              if not queries or any(q.lower() in ident.lower() for q in queries)]
    if not idents:
        print('  (no match)\n')
    else:
        for ident in idents:
            groups = _ident_version_groups(index, ident)
            print(f'  ✅ {short(ident):32s} real samples ({_fmt_version_groups(groups)})')
            mined = _mined_output_names(ident)
            if mined:
                top = ', '.join(f'{v} ({n}×)' for v, n in mined.most_common(5))
                print(f'      Observed default output names (cross-referenced from samples, not the loctable; '
                      f'the corpus this was written against is mostly Japanese, labelled ja): {top}')
        print()

    print(DISCIPLINE)


def _selftest() -> int:
    """Check the --param logic with synthetic fixtures (.wflow raw plists, no signing needed), never touching the real corpus.
    Monkeypatch the module-level corpus() (build_index / _fresh_stems / _param_query all take the corpus from it),
    and restore it afterwards. Fixtures go in a scratch temp dir, never in the project (that would pollute the corpus this tool itself scans)."""
    import os
    import shutil
    import tempfile
    import time as _time

    scratch = pathlib.Path(tempfile.mkdtemp(prefix='shortcut_action_index_selftest_')).resolve()
    ident = PREFIX + 'conditional'
    key = 'WFCondition'

    def _mk_corpus_file(name: str, version, cond_value, ago_seconds=None) -> pathlib.Path:
        d = {'WFWorkflowActions': [{'WFWorkflowActionIdentifier': ident,
                                     'WFWorkflowActionParameters': {key: cond_value}}],
             'WFWorkflowMinimumClientVersion': version}
        p = scratch / f'{name}.wflow'
        p.write_bytes(plistlib.dumps(d, fmt=plistlib.FMT_BINARY))
        if ago_seconds is not None:
            t = _time.time() - ago_seconds
            os.utime(p, (t, t))
        return p

    def _mk_target(name: str, version) -> pathlib.Path:
        p = scratch / f'{name}.wflow'
        p.write_bytes(plistlib.dumps({'WFWorkflowActions': [],
                                       'WFWorkflowMinimumClientVersion': version},
                                      fmt=plistlib.FMT_BINARY))
        return p

    # ① a value occurs only in generation A (1000); generation B (2000) has no samples
    p1a = _mk_corpus_file('case1_a', 1000, 4, ago_seconds=48 * 3600)
    # ② both generations (1000 / 2000) have samples
    p2a = _mk_corpus_file('case2_a', 1000, 4, ago_seconds=48 * 3600)
    p2b = _mk_corpus_file('case2_b', 2000, 4, ago_seconds=48 * 3600)
    # ③ self-pollution dimension: the gen-3000 sample's mtime is within the last 24h
    p3a = _mk_corpus_file('case3_a', 3000, 4, ago_seconds=3600)
    target_1000 = _mk_target('target_1000', 1000)
    target_2000 = _mk_target('target_2000', 2000)

    results = []

    def _check(label, ok, detail=''):
        results.append((label, bool(ok), detail))

    global corpus
    orig_corpus = corpus

    try:
        # --- Case ① ---
        corpus = lambda: [('selftest', p1a, 'raw')]  # noqa: E731
        idx, _files = build_index()
        fresh = _fresh_stems()
        real_ident = _resolve_ident(idx, 'conditional')
        _check('① matched the conditional identifier', real_ident == ident, real_ident)
        groups = _param_query(idx, real_ident, key, '4', fresh)
        g2000 = groups.get(2000, {'total': 0, 'fresh': 0})
        n_old_2000 = g2000['total'] - g2000['fresh']
        # ⚠️ The negative and positive halves must be asserted together; without the positive half this check is idle:
        # if version grouping is entirely broken (all samples collapse into one fake generation), the 2000 bucket is still empty
        # -> "gen B = 0" gives the same value in the "mechanism works" and "mechanism fully broken" worlds.
        # Measured: a destroy test that made _read_client_version() always return 9999 still passed this check ✅.
        g1000 = groups.get(1000, {'total': 0, 'fresh': 0})
        _check('① gen A (1000) pre-existing samples = 1 (positive half, so it cannot pass idly when version grouping is entirely broken)',
               g1000['total'] - g1000['fresh'] == 1, g1000)
        _check('① gen B (2000) pre-existing samples = 0', n_old_2000 == 0, n_old_2000)
        target_ver = _read_client_version(target_2000)
        g_for = groups.get(target_ver, {'total': 0, 'fresh': 0})
        n_old_for = g_for['total'] - g_for['fresh']
        _check('① --for pointing at 2000 -> verdict = fail (n=0, should exit non-zero)', n_old_for == 0, n_old_for)

        # --- Case ② ---
        corpus = lambda: [('selftest', p2a, 'raw'), ('selftest', p2b, 'raw')]  # noqa: E731
        idx, _files = build_index()
        fresh = _fresh_stems()
        real_ident = _resolve_ident(idx, 'conditional')
        groups = _param_query(idx, real_ident, key, '4', fresh)
        g1000 = groups.get(1000, {'total': 0, 'fresh': 0})
        g2000b = groups.get(2000, {'total': 0, 'fresh': 0})
        _check('② gen A (1000) sample count = 1', g1000['total'] == 1, g1000)
        _check('② gen B (2000) sample count = 1', g2000b['total'] == 1, g2000b)
        target_ver = _read_client_version(target_1000)
        g_for = groups.get(target_ver, {'total': 0, 'fresh': 0})
        n_old_for = g_for['total'] - g_for['fresh']
        _check('② --for pointing at 1000 -> verdict = pass (n=1, should exit 0)', n_old_for == 1, n_old_for)

        # --- Case ③ self-pollution dimension ---
        corpus = lambda: [('selftest', p3a, 'raw')]  # noqa: E731
        idx, _files = build_index()
        fresh = _fresh_stems()
        _check('③ a file saved within 24h is recognized by _fresh_stems()', p3a.stem in fresh, sorted(fresh))
        real_ident = _resolve_ident(idx, 'conditional')
        groups = _param_query(idx, real_ident, key, '4', fresh)
        g3000 = groups.get(3000, {'total': 0, 'fresh': 0})
        n_old_3000 = g3000['total'] - g3000['fresh']
        _check('③ total samples = 1 but pre-existing = 0 (the fresh sample is excluded)',
               g3000['total'] == 1 and n_old_3000 == 0, g3000)

        # --- Case ④ hidden-directory exclusion (tests only the predicate; the paths are synthetic and never written to disk) ---
        root = pathlib.Path('/home/u/.cache/clone')       # the absolute path itself contains a dot-dir
        _check('④ copies under .claude/worktrees/ are excluded',
               _in_hidden_dir(root / '.claude/worktrees/w1/a.shortcut', root))
        _check('④ files under .trash/ are excluded', _in_hidden_dir(root / '.trash/a.shortcut', root))
        _check('④ a normal path is kept even when root\'s absolute path contains a dot-dir (positive half)',
               not _in_hidden_dir(root / 'products/a.shortcut', root))

        # --- Case ⑤ plugin .wflow library vs the user's project (real corpus(), roots pointed at scratch dirs) ---
        global PROJECT, PLUGIN_EXAMPLES, LOCAL_LIBRARY
        orig_roots = PROJECT, PLUGIN_EXAMPLES, LOCAL_LIBRARY
        corpus = orig_corpus
        PROJECT, PLUGIN_EXAMPLES = scratch / 'proj', scratch / 'plugin_examples'
        LOCAL_LIBRARY = scratch / 'local_library'
        try:
            (PLUGIN_EXAMPLES / 'action-library').mkdir(parents=True)
            PROJECT.mkdir()
            lib = PLUGIN_EXAMPLES / 'action-library' / 'gen-selftest_lib.wflow'
            lib.write_bytes(plistlib.dumps({'WFWorkflowActions': [{'WFWorkflowActionIdentifier': ident,
                                                                    'WFWorkflowActionParameters': {key: 4}}],
                                            'WFWorkflowMinimumClientVersion': 1000}))
            (PROJECT / 'selftest_mine.shortcut').write_bytes(b'not signed; only its mtime matters here')
            idx, _files = build_index()
            fresh = _fresh_stems()
            _check('⑤ a plugin .wflow saved now is indexed',
                   ('plugin', lib.stem, 0) in idx.get(ident, []),
                   [s for s in idx.get(ident, []) if s[0] == 'plugin'])
            _check('⑤ a plugin .wflow saved now is not marked fresh', lib.stem not in fresh, sorted(fresh))
            _check('⑤ a .shortcut in the user\'s project saved now is still marked fresh',
                   'selftest_mine' in fresh, sorted(fresh))

            # --- Case ⑥ the user's local library (build_action_library.py --sbench output) ---
            LOCAL_LIBRARY.mkdir()
            loc = LOCAL_LIBRARY / 'sbench-selftest_local.wflow'
            loc.write_bytes(lib.read_bytes())
            idx, _files = build_index()
            fresh = _fresh_stems()
            _check('⑥ a local-library .wflow saved now is indexed as local',
                   ('local', loc.stem, 0) in idx.get(ident, []),
                   [s for s in idx.get(ident, []) if s[0] == 'local'])
            _check('⑥ a local-library .wflow saved now is not marked fresh', loc.stem not in fresh, sorted(fresh))
        finally:
            PROJECT, PLUGIN_EXAMPLES, LOCAL_LIBRARY = orig_roots

        # --- Case ⑦ ToolKit catalog (--toolkit): read from the catalog that ships with this script; TOOLKIT_DIRS swapped for the lookup order ---
        import contextlib
        import io

        def _toolkit(q):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = _toolkit_cmd(q)
            return rc, out.getvalue(), err.getvalue()

        def _line(lines, pred):
            return next((n for n, ln in enumerate(lines) if pred(ln)), -1)

        warn = 'a key missing here is not proof it is illegal; check `--dump`'
        rc, out, err = _toolkit('appendnote')
        lines = out.splitlines()
        op, ent = (_line(lines, lambda ln, k=k: ln.startswith(f'  {k} ')) for k in ('operation', 'entity'))
        app, pre = (_line(lines, lambda ln, c=c: ln == f'      {c}  {c.title()}') for c in ('append', 'prepend'))
        _check('⑦ --toolkit appendnote: `operation` lists append and prepend, ahead of the next parameter',
               rc == 0 and 0 <= op < app < pre < ent, (rc, op, app, pre, ent))
        rc, out, err = _toolkit('list')
        _check('⑦ --toolkit list resolves to is.workflow.actions.list (not trello.add.list) and prints the gap warning',
               rc == 0 and (out.splitlines() + ['', ''])[1].startswith('is.workflow.actions.list ') and warn in out,
               (rc, out[:300]))
        rc, out, err = _toolkit('setclipboard')
        _check('⑦ an action with parameters and no known gap prints no gap warning (so the warning above is not unconditional)',
               rc == 0 and warn not in out, (rc, warn in out))
        rc, out, err = _toolkit('conditional')
        _check('⑦ --toolkit conditional: not in the catalog, exit 1, the message names the control-flow gap',
               rc == 1 and not out and 'choosefrommenu' in err, (rc, out, err))
        rc, out, err = _toolkit('Append to Note')
        _check('⑦ two display-name hits, one in is.workflow.actions: resolves to it and names the other hit',
               rc == 0 and (out.splitlines() + ['', ''])[1].startswith('is.workflow.actions.appendnote ')
               and 'Also matches (not shown): com.apple.Notes.NoteAppendTextIntent' in out, (rc, out[:300]))
        rc, out, err = _toolkit('fetchcontactintent')
        _check('⑦ two hits and none in is.workflow.actions: exit 1, both listed, nothing picked',
               rc == 1 and not out and 'com.apple.AddressBook.FetchContactIntent' in err
               and 'com.apple.MobileAddressBook.FetchContactIntent' in err, (rc, out, err))

        real = toolkit_dir()
        fake = scratch / 'fake_toolkit'
        fake.mkdir()
        (fake / TOOLKIT_FILES[0]).write_text(json.dumps({'tools': {PREFIX + 'appendnote': {
            'displayName': 'Fake Append', 'parameterCount': 0, 'parameters': []}}}))
        (fake / TOOLKIT_FILES[1]).write_text(json.dumps({'types': {}}))
        saved = list(TOOLKIT_DIRS)
        try:
            TOOLKIT_DIRS[:] = [scratch / 'nope', fake, real]
            _check('⑦ lookup order: a folder without the catalog is skipped, the first folder that has it wins',
                   toolkit_dir() == fake, toolkit_dir())
            _check('⑦ --toolkit reads that first folder', 'Fake Append' in _toolkit('appendnote')[1])
            TOOLKIT_DIRS[:] = [scratch / 'nope_a', scratch / 'nope_b']
            rc, out, err = _toolkit('appendnote')
            _check('⑦ no catalog folder: exit 1, nothing on stdout, every folder looked in is printed',
                   rc == 1 and not out and str(scratch / 'nope_a') in err and str(scratch / 'nope_b') in err, (rc, out, err))
        finally:
            TOOLKIT_DIRS[:] = saved
    finally:
        corpus = orig_corpus
        shutil.rmtree(scratch, ignore_errors=True)

    passed = sum(1 for _l, ok, _d in results if ok)
    for label, ok, detail in results:
        mark = '✅' if ok else '❌'
        print(f'  {mark} {label}' + (f'  [got: {detail}]' if not ok else ''))
    print(f'\n{passed}/{len(results)} PASS')
    return 0 if passed == len(results) else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.epilog = DISCIPLINE
    ap.formatter_class = argparse.RawDescriptionHelpFormatter
    ap.add_argument('query', nargs='*', help='query only these actions (fuzzy match on the identifier suffix)')
    ap.add_argument('--dump', metavar='ACTION', help='print the full parameters of the first sample of that action')
    ap.add_argument('--check', action='store_true',
                    help='answer yes/no only (exit code = number missing; usable as a script gate)')
    ap.add_argument('--param', metavar='ACTION:KEY=VALUE',
                    help='how many real samples of an action have a given parameter value, grouped by WFWorkflowMinimumClientVersion')
    ap.add_argument('--for', dest='for_target', metavar='TARGET.shortcut',
                    help='with --param: read the target file\'s own client version; exit non-zero when that generation has 0 pre-existing samples')
    ap.add_argument('--toolkit', metavar='ACTION',
                    help="Apple's ToolKit catalog: an action's setting keys and their legal values (ACTION = identifier, its last "
                         'segment or the display name). Not proof that a value works; control flow (If / Menu / Repeat) is not in it')
    ap.add_argument('--selftest', action='store_true',
                    help='self-check the --param logic with synthetic fixtures (does not touch the real corpus); exit 0 when all pass')
    ap.add_argument('--list', nargs='*', metavar='KEYWORD', default=None,
                    help='catalog layer: which actions exist -- ① the names in the system loctable (multilingual; names only, '
                         'no guarantee the corpus has a real sample) ② the identifiers in the local corpus (certainly '
                         'have real samples, plus default output names mined from the samples). The two are not the same thing and are not joined; '
                         'see the note at the top of the output. Without a keyword = list everything.')
    ap.add_argument('--lang', metavar='ja,zh_CN', default='',
                    help='with --list: also show the values of these loctable languages (comma-separated language codes)')
    args = ap.parse_args()

    if args.selftest:
        sys.exit(_selftest())

    if args.toolkit is not None:
        sys.exit(_toolkit_cmd(args.toolkit))

    index, files = build_index()

    if args.list is not None:
        langs = [s.strip() for s in args.lang.split(',') if s.strip()]
        _list_directory(index, args.list, langs)
        sys.exit(0)

    if args.dump:
        hits = [k for k in index if args.dump in k]
        if not hits:
            print(f'❌ no action in the corpus matches「{args.dump}」', file=sys.stderr)
            print('   Next step: "use it once in the GUI and export it, then it enters the corpus; '
                  'or run `--list <keyword>` to confirm the name"', file=sys.stderr)
            sys.exit(1)
        ident = sorted(hits, key=lambda k: -len(index[k]))[0]
        label, stem, idx = index[ident][0]
        for lb, path, fmt in corpus():
            if path.stem == stem:
                acts = load(path, fmt)
                print(f'# {ident}\n# Sample: {label} / {stem} / action[{idx}]'
                      f' ({len(index[ident])} sample(s) in total)\n')
                pprint.pprint(acts[idx], width=110)
                return
        print('The sample file could not be found again (did the corpus change between the two scans?)', file=sys.stderr)
        sys.exit(1)

    if args.check:
        missing = []
        fresh = _fresh_stems()
        for q in args.query:
            hits = [k for k in index if q in k]
            if hits:
                ident = sorted(hits, key=lambda k: -len(index[k]))[0]
                samples = index[ident]
                n_fresh = sum(1 for _lb, stem, _i in samples if stem in fresh)
                n_old = len(samples) - n_fresh
                # Tiered; do not shout whenever there is any fresh sample -- see the note below.
                if n_fresh and n_old == 0:
                    note = f' (🔴 **all {len(samples)} sample(s) come from files saved in the last 24h** = zero samples from before you started, i.e. no corpus)'
                elif n_fresh and n_fresh * 2 >= len(samples):
                    note = f' (⚠️ {n_fresh}/{len(samples)} come from files saved in the last 24h; **only {n_old} existed before you started**)'
                elif n_fresh:
                    note = f' (of which {n_fresh} were saved in the last 24h; {n_old} before you started)'
                else:
                    note = ''
                print(f'  {q:26s} ✅ {len(samples)} sample(s){note}')
            else:
                print(f'  {q:26s} ❌ no samples')
            if not hits:
                missing.append(q)
        if missing:
            print(f'\n{len(missing)} missing: {", ".join(missing)}', file=sys.stderr)
        sys.exit(len(missing))

    if args.param:
        if ':' not in args.param or '=' not in args.param.split(':', 1)[1]:
            print(f'❌ --param format must be ACTION:KEY=VALUE, got: {args.param}', file=sys.stderr)
            sys.exit(1)
        action_q, rest = args.param.split(':', 1)
        key, value = rest.split('=', 1)
        ident = _resolve_ident(index, action_q)
        if ident is None:
            print(f'0 samples — no action in the corpus matches「{action_q}」')
            sys.exit(0)
        fresh = _fresh_stems()
        groups = _param_query(index, ident, key, value, fresh)
        total = sum(g['total'] for g in groups.values())
        print(f'# {ident}\n# {key}={value!r} — {total} sample(s) in total, grouped by WFWorkflowMinimumClientVersion\n')
        if not groups:
            print('  0 samples')
        else:
            for version in sorted(groups, key=lambda v: (v is None, v)):
                g = groups[version]
                n_old = g['total'] - g['fresh']
                vlabel = '(no version field)' if version is None else str(version)
                note = ''
                if g['fresh']:
                    note = f' (of which {g["fresh"]} saved in the last 24h; **{n_old} existed before you started**)'
                print(f'  gen {vlabel:>8s} : {g["total"]:3d} sample(s){note}')

        if args.for_target:
            target_path = pathlib.Path(args.for_target)
            if not target_path.is_file():
                print(f'\n❌ --for target file does not exist: {target_path}', file=sys.stderr)
                sys.exit(1)
            target_ver = _read_client_version(target_path)
            g = groups.get(target_ver, {'total': 0, 'fresh': 0})
            n_old = g['total'] - g['fresh']
            if n_old == 0:
                print(f'\n🔴 target gen = {target_ver}; samples in that gen from before you started = 0')
                sys.exit(1)
            print(f'\n✅ target gen = {target_ver}; samples in that gen from before you started = {n_old}')
            sys.exit(0)
        sys.exit(0)

    print(f'corpus = {len(files)} files')
    for label, stem, n, kinds in files:
        print(f'  [{label:9s}] {stem[:34]:34s} '
              + (f'{n:4d} actions / {kinds} types' if n >= 0 else f'  {kinds}'))
    print(f'\n{len(index)} action types in total'
          + (f' (filter: {" ".join(args.query)})' if args.query else ''))
    print()
    for ident in sorted(index, key=short):
        if args.query and not any(q in ident for q in args.query):
            continue
        srcs = index[ident]
        seen, where = set(), []
        for label, stem, i in srcs:
            if stem not in seen:
                seen.add(stem)
                where.append(f'{stem[:16]}[{i}]')
        print(f'  {short(ident):38s} ×{len(srcs):<3d} {" ".join(where[:4])}')

    print()
    print(DISCIPLINE)


if __name__ == '__main__':
    main()
