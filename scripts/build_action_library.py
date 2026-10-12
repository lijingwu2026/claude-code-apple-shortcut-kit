#!/usr/bin/env python3
"""Build an action library: one neutralized sample per Apple Shortcuts action type.

More examples for your own Mac (optional), from ShortcutsBench:
1. Download the raw dataset linked from https://github.com/EachSheep/ShortcutsBench (a zip on Google Drive,
   about 750 MB, password `shortcutsbench`). It unpacks to `1_final_detailed_records_remove_repeat.json`.
2. Run:
       python3 scripts/build_action_library.py --sbench <dir>/1_final_detailed_records_remove_repeat.json
   It writes sbench-<version>.wflow to ~/Library/Application Support/apple-shortcut-kit/action-library/ (or --out DIR),
   where shortcut_action_index.py finds them as the `local` source. It loads the whole file: about 8 GB peak memory.
ShortcutsBench is Apache-2.0, but its shortcuts come from sharing sites whose terms allow personal, non-commercial
use only. The library you build is for your own use on your own Mac: never share or publish it.

    python3 scripts/build_action_library.py --check [--sbench FILE]   # shape: each library action vs its source sample
    python3 scripts/build_action_library.py --audit [DIR]   # privacy: print every surviving string, key and number; fail on leaks
    python3 scripts/build_action_library.py --kept FILE     # write, per bundled action, every kept string and number as JSON
    python3 scripts/build_action_library.py --selftest

Without --sbench (source checkout only; the plugin refuses it): rebuild the bundled library
`examples/action-library/gen-<version>.wflow` from the author's own shortcuts, i.e. the `project`, `iCloud` and
`Shortcuts` sources of `shortcut_action_index.corpus()`; `plugin`, `local` and `extra` never enter it.
Shortcuts belong to their authors: only their neutralized structure goes into a library.
Only Apple identifiers (`is.workflow.actions.*`, `com.apple.*`) are kept: an app id under APP_ID_KEYS that is not
`com.apple.*` → APP_PLACEHOLDER, and a TeamIdentifier beside it → TEAM_PLACEHOLDER.
Without --sbench, types that only Apple's Gallery has are skipped (every Mac has them). Per type the sample is the
non-Gallery one ranked by (newest WFWorkflowMinimumClientVersion, most parameter keys); ties → the first read. Neutralizing keeps the identifier, every key,
integers and bools, and strings under ALLOW; non-integer floats → 1.0; AUTHORED_NUMBERS → 1; every number under a location
key → 0 and its strings → placeholders; token strings keep each U+FFFC at its UTF-16 offset with every other code unit
→ `x`; UUIDs → new deterministic UUIDs (consistent within one action); bytes → empty; every other string → a placeholder.
"""
import argparse
import collections
import json
import pathlib
import plistlib
import re
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import shortcut_action_index as sai  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
IN_SOURCE = HERE.parent.name == 'automation'          # source checkout: scripts/ · plugin: scripts/
ROOT = HERE.parents[1] if IN_SOURCE else HERE.parent
BUNDLED = (ROOT / 'automation' / 'shortcut-kit' / 'examples' if IN_SOURCE else ROOT / 'examples') / 'action-library'
OWN = ('project', 'iCloud', 'Shortcuts')              # the corpus sources the bundled library is built from
SKIP_SOURCE = 'macstories.net'                        # its terms forbid derived works
APPLE_PREFIXES = ('is.workflow.actions.', 'com.apple.')
CATALOG = (ROOT / 'knowledge' / 'learning' / 'ai' / 'upstream-docs' / '2026-09'
           / 'shortcuts-toolkit-catalog-viticci')     # --audit only, never copied; absent in the plugin
FFFC = '￼'

# Numbers that are an amount the author chose (seconds to wait, times to repeat), not a mode or code → 1.
AUTHORED_NUMBERS = {'WFDelayTime', 'WFRepeatCount'}
# Keys whose subtree is a place: numbers → 0 (strings take the usual placeholders).
LOCATION_KEYS = {'WFLocation', 'placemark', 'region', 'latitude', 'longitude'}
# Keys whose integers may have 7+ digits without being a phone number or an account ID (--audit).
LONG_INT_KEYS = frozenset()

# String-valued keys whose values define behavior (enums, units, Health types, formats, system identifiers).
ALLOW = frozenset('''
WFSerializationType Type WFLLMModel WFGenerativeResultType WFInputType Unit WFQuantitySampleType Property
WFFileLocationType WFStatisticsOperation WFHKSampleFilteringUnit WFDateActionMode WFDateFormatStyle
WFTimeFormatStyle WFDateFormat WFGetDictionaryValueType CoercionItemClass WFAdjustOperation PropertyName
PropertyUserInfo WFHTTPMethod WFHTTPBodyType WFMathOperation WFScientificMathOperation WFContentItemPropertyName
WFRoundMode WFTimeUntilUnit WFTextSeparator WFEncodeMode Mode WFCountType WFAlertTime WFAlertCondition
WFAlertEnabled WFContentItemInputParameter AssertionType operation WFItemSpecifier
TeamIdentifier BundleIdentifier AppIntentIdentifier appContainerBundleIdentifier systemName AppBundleIdentifier UserActivityType
WFContentItemSortOrder WFContentItemSortProperty WFRecordingStart WFRecordingEnd WFRecordingCompression WFAttribute
WFInsertPosition WFWhenToPlay ratMode WFDictateTextStopListening WFAppendFileWriteMode WFMediaAudioFormat WFPickingMode
WFFileSizeFormat WFQRErrorCorrectionLevel WFDeviceDetail WFGetDirectionsActionApp WFGetDirectionsActionMode
WFDistanceUnit WFIPAddressSourceOption WFGetTextFromPDFTextType WFFileType WFDateSpecifier WFURLComponent
WFCellularDetail WFNetworkDetailsNetwork WFWiFiDetail WFHashType WFHideAppMode WFImageCombineMode WFImageFormat
WFImageCropPosition WFImageFlipDirection WFMaskType WFImageResizeKey WFNoInputBehavior WFListeningMode
WFPDFDocumentMergeBehavior WFPDFIncludedPages WFNSUnitType WFMeasurementUnitType WFPosition WFNoOutputSurfaceBehavior
WFImagePosition WFColorRepresentationType WFSizingMethod WFTextAlignment WFTextPosition WFPlayMusicActionRepeat
WFPlayMusicActionShuffle WFPosterType WFShutdownMode WFConfiguration WFMediaType WFSearchMapsActionApp
WFSearchWebDestination WFMediaRouteOperation WFCameraCaptureQuality WFCaseType WFVPNOperation WFWeatherForecastType
Accuracy changeOperation backgroundSound textSize InputMode Class Subject HMShortcutsSerializedDictionaryProtocol
HMActionSetSerializedDictionaryProtocol ExtensionBundleIdentifier storageServiceIdentifier IntentClassName
WFAppIdentifier providerBundleIdentifier WFTodoistReminderType WFTrelloPosition WFTrelloItemType WFPocketItemState
'''.split())
# Keys whose value names an app (or an app's activity): kept only when it is Apple's.
APP_ID_KEYS = frozenset('''BundleIdentifier AppBundleIdentifier ExtensionBundleIdentifier WFAppIdentifier
providerBundleIdentifier appContainerBundleIdentifier UserActivityType'''.split())
APP_PLACEHOLDER, TEAM_PLACEHOLDER = 'com.example.app', '0000000000'
# Non-ASCII characters allowed to survive: the token placeholder and Apple's own math-operator enum values.
ALLOWED_NON_ASCII = {FFFC: None, '×': 'WFMathOperation', '÷': 'WFMathOperation', '…': 'WFMathOperation'}
VAR_KEYS = {'VariableName', 'WFVariableName', 'OutputName', 'CustomOutputName'}
DICT_KEY_KEYS = {'WFDictionaryKey'}
UUID_KEYS = {'UUID', 'OutputUUID', 'GroupingIdentifier', 'workflowIdentifier'}   # some authored IDs are UUID-shaped, not hex
UUID_RE = re.compile(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')
PLACEHOLDER_RE = re.compile(r'(?:Text|Variable|key)\d*|https://example\.com|[x￼]*|1')
ENUM_KEY_RE = re.compile(r'(?:Type|Mode|Style|Unit|Operation|Method|Format|Identifier|Class|Specifier|Condition|Operator|Kind)$')


def under_location(path) -> bool:
    return any(isinstance(p, str) and (p in LOCATION_KEYS or p.startswith('CLLocation')) for p in path)


def third_party(v) -> bool:
    return isinstance(v, str) and v != '' and not v.startswith('com.apple.')


def xout(s: str) -> str:
    """Every UTF-16 code unit except U+FFFC → 'x', so attachmentsByRange offsets still land on their U+FFFC."""
    return ''.join(c if c == FFFC else 'x' * (2 if ord(c) > 0xFFFF else 1) for c in s)


class Neutralizer:
    """One per action: placeholders and new UUIDs are consistent within the action (UUIDs derive from the
    identifier and their order, so re-runs write the same bytes)."""

    def __init__(self, ident):
        self.ident = ident
        self.maps = {'uuid': {}, 'Variable': {}, 'Text': {}, 'key': {}}

    def _name(self, kind, value):
        m = self.maps[kind]
        if value not in m:
            n = len(m) + 1
            m[value] = f'key{n}' if kind == 'key' else (kind if n == 1 else f'{kind}{n}')
        return m[value]

    def string(self, key, s, path=()):
        if key in APP_ID_KEYS and third_party(s):
            return APP_PLACEHOLDER
        if key in ALLOW:
            return s
        if s == '':
            return s
        if key in UUID_KEYS or UUID_RE.fullmatch(s):
            m = self.maps['uuid']
            if s.upper() not in m:
                m[s.upper()] = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{self.ident}#{len(m)}')).upper()
            return m[s.upper()]
        if key == 'string':                                   # the text of a WFTextTokenString
            if 'WFKey' in path[-3:] and FFFC not in s:
                return self._name('key', s)
            return xout(s)
        if re.match(r'(?i)https?://', s):
            return 'https://example.com'
        if key in VAR_KEYS:
            return self._name('Variable', s)
        if key in DICT_KEY_KEYS:
            return self._name('key', s)
        if re.fullmatch(r'-?\d+(?:\.\d+)?', s):
            return '1'
        return self._name('Text', s)

    def walk(self, o, path=()):
        if isinstance(o, dict):
            out = {k: self.walk(v, path + (k,)) for k, v in o.items()}
            if 'TeamIdentifier' in out and any(third_party(o.get(k)) for k in APP_ID_KEYS):
                out['TeamIdentifier'] = TEAM_PLACEHOLDER                # the team of a third-party app
            return out
        if isinstance(o, list):
            return [self.walk(v, path) for v in o]
        if isinstance(o, str):
            return self.string(path[-1] if path else None, o, path)
        if isinstance(o, bytes):
            return b''
        if isinstance(o, (int, float)) and not isinstance(o, bool):
            if under_location(path):
                return type(o)(0)                             # a place someone was: zero, same shape
            if path and path[-1] in AUTHORED_NUMBERS:
                return type(o)(1)                             # a chosen amount, not a mode: neutral 1
            if isinstance(o, float) and not o.is_integer():
                return 1.0                                    # a measured or chosen fraction: neutral 1.0
        return o                                              # int / integer float / bool / datetime


def _version_key(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def load_own():
    """-> [(label, path, version, actions)] for every readable `project` / `iCloud` / `Shortcuts` file, plus Gallery
    (read only to find the Gallery-only types)."""
    out = []
    for label, path, fmt in sai.corpus():
        if label not in OWN + ('Gallery',):
            continue
        try:
            full = plistlib.loads(path.read_bytes()) if fmt == 'raw' else sai.open_shortcut(path)
        except Exception:
            continue
        out.append((label, path, full.get('WFWorkflowMinimumClientVersion'), full.get('WFWorkflowActions', [])))
    return out


def load_sbench(path: pathlib.Path):
    """-> ([(label, name, version, actions)] for every ShortcutsBench record with a version, number of skipped records)."""
    out, skipped = [], 0
    for n, r in enumerate(json.loads(path.read_bytes())):
        if SKIP_SOURCE in str(r.get('Source')):
            skipped += 1
            continue
        w = r.get('shortcut') or {}
        version = _version_key(w.get('WFWorkflowMinimumClientVersion'))
        if version > 0:                                       # no version → the sample's file name would be unknown
            out.append(('ShortcutsBench', pathlib.Path(f'{path.name}#{n}'), version, w.get('WFWorkflowActions', [])))
    return out, skipped


def select(files):
    """-> {ident: (version, path, index, action, label)}, plus the Gallery-only identifiers."""
    best, labels = {}, {}
    for label, path, version, acts in files:
        for i, a in enumerate(acts):
            ident = a['WFWorkflowActionIdentifier']
            if not ident.startswith(APPLE_PREFIXES):
                continue
            labels.setdefault(ident, set()).add(label)
            if label == 'Gallery':
                continue
            rank = (_version_key(version), len(a.get('WFWorkflowActionParameters', {})))
            if ident not in best or rank > best[ident][0]:
                best[ident] = (rank, (version, path, i, a, label))
    gallery_only = sorted(k for k, v in labels.items() if v == {'Gallery'})
    return {k: v[1] for k, v in best.items()}, gallery_only


def neutralize(action):
    return {'WFWorkflowActionIdentifier': action['WFWorkflowActionIdentifier'],
            'WFWorkflowActionParameters': Neutralizer(action['WFWorkflowActionIdentifier']).walk(action.get('WFWorkflowActionParameters', {}))}


def build(chosen, out: pathlib.Path, prefix: str):
    by_version = {}
    for ident in sorted(chosen):
        version, _path, _i, action, _label = chosen[ident]
        by_version.setdefault(version, []).append(neutralize(action))
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob(f'{prefix}*.wflow'):
        old.unlink()
    for version, acts in sorted(by_version.items(), key=lambda kv: _version_key(kv[0])):
        doc = {'WFWorkflowMinimumClientVersion': version, 'WFWorkflowActions': acts}
        (out / f'{prefix}{version}.wflow').write_bytes(plistlib.dumps(doc, fmt=plistlib.FMT_XML, sort_keys=True))
    return by_version


def library(root: pathlib.Path):
    """-> [(file name, version, action)] from the library .wflow files under root."""
    out = []
    for p in sorted(root.rglob('*.wflow')):
        d = plistlib.loads(p.read_bytes())
        for a in d['WFWorkflowActions']:
            out.append((p.name, d.get('WFWorkflowMinimumClientVersion'), a))
    return out


def leaves(o, path=()):
    """Yield (key path, value) for every leaf."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, path + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, path + (i,))
    else:
        yield path, o


def last_key(path):
    return next((p for p in reversed(path) if isinstance(p, str)), None)


def check(chosen, gallery_only, root: pathlib.Path) -> int:
    lib = library(root)
    problems, enum_like, ranges = [], set(), 0
    seen = set()
    for fname, version, a in lib:
        ident = a['WFWorkflowActionIdentifier']
        seen.add(ident)
        if ident not in chosen:
            problems.append(f'{fname}: {ident} has no source sample')
            continue
        src_version, _p, _i, src, _label = chosen[ident]
        if version != src_version:
            problems.append(f'{ident}: file version {version} ≠ source version {src_version}')
        s = dict(leaves(src.get('WFWorkflowActionParameters', {})))
        d = dict(leaves(a.get('WFWorkflowActionParameters', {})))
        if set(s) != set(d):
            problems.append(f'{ident}: key paths differ: {sorted(map(str, set(s) ^ set(d)))[:5]}')
            continue
        for path, sv in s.items():
            dv, k = d[path], last_key(path)
            if isinstance(sv, (int, float)) and not isinstance(sv, bool) and (
                    under_location(path) or k in AUTHORED_NUMBERS or isinstance(sv, float) and not sv.is_integer()):
                want = 0 if under_location(path) else 1
                if type(sv) is not type(dv) or dv != want:
                    problems.append(f'{ident}: {path} number not neutralized: {sv!r} → {dv!r}')
            elif isinstance(sv, (bool, int, float)) and (type(sv) is not type(dv) or sv != dv):
                problems.append(f'{ident}: {path} number/bool {sv!r} → {dv!r}')
            elif isinstance(sv, str) and k in ALLOW and dv != (
                    APP_PLACEHOLDER if k in APP_ID_KEYS and third_party(sv) else
                    TEAM_PLACEHOLDER if k == 'TeamIdentifier' and any(third_party(s.get(path[:-1] + (ak,))) for ak in APP_ID_KEYS) else sv):
                problems.append(f'{ident}: allowlisted {path} changed')
            elif isinstance(sv, str) and sv != dv and not UUID_RE.fullmatch(sv) and (ENUM_KEY_RE.search(k or '') or re.fullmatch(r'[A-Z][A-Za-z]*(?: [A-Za-z]+)*', sv)):
                enum_like.add((short(ident), k, sv))
        spans = {path[:j + 2] for path in d for j, p in enumerate(path[:-1]) if p == 'attachmentsByRange'}
        for span in sorted(spans, key=str):                   # every range must sit on a U+FFFC of its string
            ranges += 1
            m = re.fullmatch(r'\{(\d+), (\d+)\}', span[-1])
            text = d.get(span[:-2] + ('string',))
            if not m or not isinstance(text, str):
                problems.append(f'{ident}: range {span[-1]} without a string')
                continue
            units = text.encode('utf-16-le')
            start, length = int(m.group(1)), int(m.group(2))
            if units[2 * start:2 * (start + length)].decode('utf-16-le', 'replace') != FFFC * length:
                problems.append(f'{ident}: range {span[-1]} not on U+FFFC')
    missing = sorted(set(chosen) - seen)
    for m in missing:
        problems.append(f'{m}: missing from the library')
    print(f'library: {len(lib)} actions / {len(seen)} identifiers in {len({f for f, _v, _a in lib})} file(s); '
          f'source types {len(chosen) + len(gallery_only)} − Gallery-only {len(gallery_only)} = {len(chosen)}')
    print(f'ranges checked: {ranges}')
    print(f'replaced strings with an enum-like key or value: {len(enum_like)}')
    for row in sorted(enum_like):
        print(f'  {row[0]} · {row[1]} = {row[2]!r}')
    print(f'shape problems: {len(problems)}')
    for p in problems:
        print(f'  ❌ {p}')
    return 1 if problems else 0


def short(ident):
    return sai.short(ident)


def catalog_enums(catalog: pathlib.Path):
    """-> {(tool id, parameter key): {enum case ids and titles}} from the Viticci catalog (empty if absent)."""
    try:
        tools = json.loads((catalog / 'toolkit-v78-first-party-parameter-keys.json').read_text())['tools']
        types = json.loads((catalog / 'toolkit-v78-first-party-enum-cases.json').read_text())['types']
    except FileNotFoundError:
        return {}
    out = {}
    for tid, tool in tools.items():
        for prm in tool.get('parameters', []):
            names = {prm.get('typePythonName')} | set(prm.get('typePythonNames') or [])
            cases = {c[f] for n in names if n in types for c in types[n]['cases'] for f in ('id', 'title') if c.get(f)}
            if cases:
                out.setdefault((tid, prm['key']), set()).update(cases)
    return out


def audit(root: pathlib.Path) -> int:
    enums = catalog_enums(CATALOG)
    strings, keys, numbers, fails, review = {}, set(), set(), [], {}
    entries = list(library(root))
    if not entries:
        print(f'audit failures: 1\n  ❌ no *.wflow actions found in {root}')
        return 1
    for fname, _version, a in entries:
        ident = a['WFWorkflowActionIdentifier']
        lv = dict(leaves(a))
        for path, v in lv.items():
            keys.update(p for p in path if isinstance(p, str))
            k = last_key(path)
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                numbers.add(v)
                if under_location(path) and v != 0:
                    fails.append(f'{fname}: {short(ident)} number {v!r} under a location key {path}')
                elif isinstance(v, float) and not v.is_integer() and v != 1.0:
                    fails.append(f'{fname}: {short(ident)} non-integer float {v!r} in {k}')
                elif isinstance(v, int) and len(str(abs(v))) >= 7 and k not in LONG_INT_KEYS:
                    fails.append(f'{fname}: {short(ident)} {len(str(abs(v)))}-digit integer {v!r} in {k}')
                continue
            if not isinstance(v, str):
                continue
            strings.setdefault(v, set()).add(k)
            for c in v:
                if ord(c) > 127 and (c not in ALLOWED_NON_ASCII or ALLOWED_NON_ASCII[c] not in (None, k)):
                    fails.append(f'{fname}: non-ASCII {c!r} in {k}')
                    break
            for m in re.finditer(r'(?i)https?://[^\s"<>]*', v):
                if m.group(0) != 'https://example.com':
                    fails.append(f'{fname}: URL {m.group(0)} in {k}')
            if k in APP_ID_KEYS and v not in ('', APP_PLACEHOLDER) and not v.startswith('com.apple.'):
                fails.append(f'{fname}: {short(ident)} {k} = {v!r} is a third-party app id')
            if k == 'TeamIdentifier' and v != TEAM_PLACEHOLDER and not any(
                    isinstance(lv.get(path[:-1] + (ak,)), str) and lv[path[:-1] + (ak,)].startswith('com.apple.') for ak in APP_ID_KEYS):
                fails.append(f'{fname}: {short(ident)} TeamIdentifier = {v!r} is not beside a com.apple.* app id')
            if k in ALLOW:
                top = path[1] if len(path) > 1 and all(isinstance(p, int) for p in path[2:]) else None
                cases = enums.get((ident, top)) if top == k else None
                if cases is not None and v not in cases:
                    fails.append(f'{fname}: {short(ident)} {k} = {v!r} is not a catalog enum value')
                elif cases is None and v:
                    review.setdefault((k, v), set()).add(short(ident))
            elif (len(v) > 3 and k != 'WFWorkflowActionIdentifier'
                    and not PLACEHOLDER_RE.fullmatch(v) and not UUID_RE.fullmatch(v)):
                fails.append(f'{fname}: {short(ident)} {k} = {v!r} is not allowlisted, a placeholder, a UUID or an identifier')
    for k in keys:
        if any(ord(c) > 127 for c in k):
            fails.append(f'non-ASCII dictionary key {k!r}')
    print(f'surviving strings: {len(strings)} distinct (UUIDs and x-strings collapsed below)')
    for v in sorted(strings):
        if UUID_RE.fullmatch(v):
            continue
        shown = v if not re.fullmatch(r'[x￼]+', v) else f'<x/U+FFFC string, {len(v)} units>'
        print(f'  {shown!r}  ← {", ".join(sorted(map(str, strings[v])))}')
    print(f'  (+ {sum(1 for v in strings if UUID_RE.fullmatch(v))} regenerated UUIDs)')
    print(f'dictionary keys: {len(keys)} distinct')
    print('  ' + ' '.join(sorted(keys)))
    print(f'numbers: {len(numbers)} distinct')
    print('  ' + ' '.join(map(repr, sorted(numbers))))
    print(f'allowlisted values with no catalog enum to check (review by eye): {len(review)}'
          + ('' if enums else ' — enum check skipped: the Viticci catalog is not in this checkout'))
    for (k, v), idents in sorted(review.items()):
        print(f'  {k} = {v!r}  ← {", ".join(sorted(idents)[:3])}{" …" if len(idents) > 3 else ""}')
    print(f'audit failures: {len(fails)}')
    for f in fails:
        print(f'  ❌ {f}')
    return 1 if fails else 0


def kept(path: pathlib.Path):
    rows = {}
    for fname, version, a in library(BUNDLED):
        row = {'file': fname, 'strings': set(), 'numbers': set()}
        for p, v in leaves(a.get('WFWorkflowActionParameters', {})):
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                row['numbers'].add(f'{last_key(p)}={v!r}')
            elif isinstance(v, str) and last_key(p) in ALLOW:
                row['strings'].add(f'{last_key(p)}={v}')
        rows[a['WFWorkflowActionIdentifier']] = {'file': fname, 'strings': sorted(row['strings']),
                                                 'numbers': sorted(row['numbers'])}
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f'wrote {len(rows)} actions to {path}')


def selftest() -> int:
    """(a) without --sbench only project / iCloud / Shortcuts samples are chosen: a `local`, `plugin` or `extra` file
    changes nothing; (b) --sbench skips macstories.net records and writes the other records' types to --out."""
    import tempfile
    results = []

    def act(ident):
        return {'WFWorkflowActionIdentifier': 'is.workflow.actions.' + ident,
                'WFWorkflowActionParameters': {'WFInput': 'private text'}}

    with tempfile.TemporaryDirectory(prefix='build_action_library_selftest_') as tmp:
        tmp = pathlib.Path(tmp)

        def wflow(name, *idents):
            f = tmp / f'{name}.wflow'
            f.write_bytes(plistlib.dumps({'WFWorkflowMinimumClientVersion': 900, 'WFWorkflowActions': [act(i) for i in idents]}))
            return f
        entries = [('project', wflow('proj', 'p', 'shared'), 'raw'), ('iCloud', wflow('icloud', 'i'), 'raw'),
                   ('Shortcuts', wflow('docs', 's'), 'raw'), ('Gallery', wflow('gal', 'g', 'shared'), 'raw'),
                   ('plugin', wflow('plug', 'plug'), 'raw'), ('extra', wflow('extra', 'x'), 'raw'),
                   ('local', wflow('local', 'loc', 'p'), 'raw')]
        orig = sai.corpus
        try:
            sai.corpus = lambda: entries
            chosen, gallery_only = select(load_own())
            sai.corpus = lambda: [e for e in entries if e[0] != 'local']
            chosen_without_local, _ = select(load_own())
        finally:
            sai.corpus = orig
        want = {'is.workflow.actions.' + i for i in ('p', 'i', 's', 'shared')}
        results.append(('(a) without --sbench: exactly the project / iCloud / Shortcuts types are chosen',
                        set(chosen) == want, sorted(chosen)))
        results.append(('(a) every chosen sample is labelled project, iCloud or Shortcuts',
                        {v[4] for v in chosen.values()} <= set(OWN), sorted({v[4] for v in chosen.values()})))
        results.append(('(a) a local file present leaves the choice unchanged',
                        {k: v[1] for k, v in chosen.items()} == {k: v[1] for k, v in chosen_without_local.items()}, ''))
        results.append(('(a) Gallery-only types are reported, not chosen', gallery_only == ['is.workflow.actions.g'],
                        gallery_only))

        records = [{'Source': ['https://routinehub.co/shortcut/1'],
                    'shortcut': {'WFWorkflowMinimumClientVersion': 900, 'WFWorkflowActions': [act('benchA')]}},
                   {'Source': ['https://www.macstories.net/shortcuts/x'],
                    'shortcut': {'WFWorkflowMinimumClientVersion': 900, 'WFWorkflowActions': [act('benchMS')]}},
                   {'Source': ['https://sharecuts.app/2'],
                    'shortcut': {'WFWorkflowMinimumClientVersion': 1106, 'WFWorkflowActions': [act('benchB')]}}]
        bench = tmp / 'bench.json'
        bench.write_text(json.dumps(records))
        out = tmp / 'local-library'
        files, skipped = load_sbench(bench)
        chosen, _ = select(files)
        build(chosen, out, 'sbench-')
        written = {a['WFWorkflowActionIdentifier'] for _f, _v, a in library(out)}
        results.append(('(b) --sbench: 1 macstories.net record skipped', skipped == 1, skipped))
        results.append(('(b) --sbench: only the other 2 records\' types are written to --out',
                        written == {'is.workflow.actions.benchA', 'is.workflow.actions.benchB'}, sorted(written)))
        results.append(('(b) --sbench: files are named sbench-<version>.wflow',
                        sorted(f.name for f in out.iterdir()) == ['sbench-1106.wflow', 'sbench-900.wflow'],
                        sorted(f.name for f in out.iterdir())))
    for label, ok, detail in results:
        print(f'  {"✅" if ok else "❌"} {label}' + ('' if ok else f'  [got: {detail}]'))
    passed = sum(ok for _l, ok, _d in results)
    print(f'\n{passed}/{len(results)} PASS')
    return 0 if passed == len(results) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('--sbench', type=pathlib.Path, metavar='FILE',
                    help='build your own library from ShortcutsBench (see below for where to get it)')
    ap.add_argument('--out', type=pathlib.Path, metavar='DIR', help=f'with --sbench: where to write (default {sai.LOCAL_LIBRARY})')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--audit', nargs='?', const=str(BUNDLED), metavar='DIR')
    ap.add_argument('--kept', metavar='FILE')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.kept:
        kept(pathlib.Path(args.kept))
        return 0
    if args.audit:
        return audit(pathlib.Path(args.audit))
    if args.out and not args.sbench:
        ap.error('--out needs --sbench')
    if args.sbench:
        if not args.sbench.is_file():
            sys.exit(f'{args.sbench} not found: see --help for where to download it')
        files, skipped = load_sbench(args.sbench)
        out, prefix = (args.out or sai.LOCAL_LIBRARY).expanduser(), 'sbench-'
        print(f'ShortcutsBench: {len(files)} records read, {skipped} from {SKIP_SOURCE} skipped')
    else:
        if not IN_SOURCE:
            sys.exit('Without --sbench this rebuilds the bundled library from the author\'s own shortcuts, which only '
                     'works in the source checkout. To build your own library, run with --sbench FILE (see --help).')
        files, out, prefix = load_own(), BUNDLED, 'gen-'
    chosen, gallery_only = select(files)
    if args.check:
        return check(chosen, gallery_only, out)
    by_version = build(chosen, out, prefix)
    print(f'wrote {sum(map(len, by_version.values()))} actions to {out}: '
          + ', '.join(f'{prefix}{v}.wflow ({len(a)})' for v, a in sorted(by_version.items(), key=lambda kv: _version_key(kv[0]))))
    print('chosen samples by source: ' + ', '.join(f'{k} {n}' for k, n in collections.Counter(v[4] for v in chosen.values()).most_common()))
    if not args.sbench:
        print(f'skipped Gallery-only: {len(gallery_only)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
