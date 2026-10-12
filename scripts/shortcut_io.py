#!/usr/bin/env python3
"""Read and write Apple `.shortcut` files programmatically (verified 2026-07-30).

## Key fact: a `.shortcut` is signed, not encrypted

A `.shortcut` file starts with `AEA1` (Apple Encrypted Archive), but its profile field is **0**
= `hkdf_sha256_hmac__none__ecdsa_p256`. The middle segment `none` is the encryption-algorithm slot.
**The payload is not encrypted; it only carries an ECDSA-P256 signature.** When `aea decrypt`
fails with `-sign-pub is required`, it is not asking for a decryption key. It is asking for the
**public key used to verify the signature**, and that key sits inside the file's own auth data
(a `SigningCertificateChain` bplist; the leaf cert's SubjectPublicKeyInfo).
-> No external key is needed to read or write the file completely.

## Full pipeline

    read:   .shortcut  --[take leaf cert public key]--> aea decrypt --> AA01 (Apple Archive)
                       --[yaa extract]--> Shortcut.wflow (binary plist) --> plistlib
    write:  dict --[plistlib FMT_BINARY]--> Shortcut.wflow
                 --[/usr/bin/shortcuts sign -m anyone]--> .shortcut

The write path **does not need Apple's private key**. Per `man shortcuts`: `-m anyone` is notarized
through iCloud and anyone can import the result;
`-m people-who-know-me` is signed locally and only your own devices, or people who have you in
their contacts, can import it.

## Usage

    from shortcut_io import open_shortcut, save_shortcut
    d = open_shortcut('xxx.shortcut')
    d['WFWorkflowActions'][11]['WFWorkflowActionParameters']['WFTextActionText'] = '...'
    save_shortcut(d, 'variant.shortcut')

CLI (quick look at the structure; changes nothing):

    python3 shortcut_io.py <file.shortcut>            # list each action's identifier
    python3 shortcut_io.py <file.shortcut> --prompts  # dump only the askllm prompts

Dependencies: `/usr/bin/aea` · `/usr/bin/yaa` · `/usr/bin/shortcuts` · `openssl` (all ship with macOS)
"""
import argparse
import pathlib
import plistlib
import struct
import subprocess
import tempfile


def _pubkey_pem(shortcut: pathlib.Path, tmp: pathlib.Path) -> pathlib.Path:
    """Take the signature-verification public key (PEM SPKI) from the .shortcut's own auth data.

    ⚠️ aea only accepts PEM. DER and a bare x9.63 key (65 bytes) both fail with `Error parsing public key file`.
    """
    raw = shortcut.read_bytes()
    if raw[:4] != b'AEA1':
        raise ValueError(f'not an AEA1 archive: {raw[:4]!r}')
    auth_size = struct.unpack('<I', raw[8:12])[0]
    chain = plistlib.loads(raw[12:12 + auth_size])['SigningCertificateChain']
    der = tmp / 'leaf.der'
    der.write_bytes(bytes(chain[0]))          # chain[0] = leaf
    pem = tmp / 'leaf.pem'
    pem.write_bytes(subprocess.run(
        ['openssl', 'x509', '-inform', 'DER', '-in', str(der), '-pubkey', '-noout'],
        check=True, capture_output=True).stdout)
    return pem


def open_shortcut(path) -> dict:
    """.shortcut -> the plist dict of Shortcut.wflow (WFWorkflowActions is at the top level)."""
    path = pathlib.Path(path)
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        pem = _pubkey_pem(path, tmp)
        aa = tmp / 'payload.aa'
        subprocess.run(['/usr/bin/aea', 'decrypt', '-i', str(path), '-o', str(aa),
                        '-sign-pub', str(pem)], check=True, capture_output=True)
        outdir = tmp / 'x'
        outdir.mkdir()
        subprocess.run(['/usr/bin/yaa', 'extract', '-i', str(aa), '-d', str(outdir)],
                       check=True, capture_output=True)
        return plistlib.loads(next(outdir.rglob('*.wflow')).read_bytes())


def save_shortcut(plist: dict, path, mode: str = 'anyone') -> pathlib.Path:
    """plist dict -> a signed .shortcut (mode: anyone | people-who-know-me)."""
    path = pathlib.Path(path)
    with tempfile.TemporaryDirectory() as td:
        w = pathlib.Path(td) / 'Shortcut.wflow'
        w.write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_BINARY))
        subprocess.run(['/usr/bin/shortcuts', 'sign', '-m', mode,
                        '-i', str(w), '-o', str(path)], check=True, capture_output=True)
    return path


def _flatten(v):
    """WFTextTokenString -> plain string (￼ = variable placeholder, kept as is)."""
    if isinstance(v, dict):
        inner = v.get('Value')
        if isinstance(inner, dict) and 'string' in inner:
            return inner['string']
        return {k: _flatten(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_flatten(x) for x in v]
    return v


def _label(ident: str, p: dict) -> str:
    """Pick the most informative one-line summary of an action (for reading the flow in --tree)."""
    short = ident.replace('is.workflow.actions.', '').replace('com.apple.', '')
    bits = []
    for key, fmt in (('WFMenuItemTitle', 'item={}'), ('WFVariableName', 'var={}'),
                     ('WFDictionaryKey', 'key={}'), ('WFQuantitySampleType', 'health={}'),
                     ('WFStatisticsOperation', 'op={}'), ('WFGetFilePath', 'file={}'),
                     ('WFFileDestinationPath', '→file={}'), ('CalendarName', 'cal={}'),
                     ('WFGenerativeResultType', 'llm→{}'), ('WFCondition', 'cond={}')):
        if key in p:
            bits.append(fmt.format(_flatten(p[key])))
    for key in ('WFMenuPrompt', 'WFAskActionPrompt', 'WFTextActionText', 'Text',
                'WFNotificationActionBody'):
        if key in p:
            txt = _flatten(p[key])
            if isinstance(txt, str) and txt.strip():
                bits.append(repr(txt[:46] + ('…' if len(txt) > 46 else '')))
                break
    if 'WFMenuItems' in p:
        bits.append('items=' + str(p['WFMenuItems']))
    return f'{short}  ' + ' '.join(bits)


def print_tree(acts: list) -> None:
    """Print the control flow indented by WFControlFlowMode (0 = block start, 1 = next branch, 2 = block end)."""
    depth = 0
    for i, a in enumerate(acts):
        ident = a.get('WFWorkflowActionIdentifier', '?')
        p = a.get('WFWorkflowActionParameters', {})
        mode = p.get('WFControlFlowMode')
        is_block = ident.endswith(('choosefrommenu', 'conditional', 'repeat.each',
                                   'repeat.count'))
        if is_block and mode == 2:
            depth = max(0, depth - 1)
        indent = '  ' * depth
        marker = {0: '┌', 1: '├', 2: '└'}.get(mode if is_block else None, ' ')
        print(f'{i:4d} {indent}{marker} {_label(ident, p)}')
        if is_block and mode in (0, 1):
            if mode == 0:
                depth += 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('shortcut')
    ap.add_argument('--prompts', action='store_true', help='dump only the askllm prompts')
    ap.add_argument('--tree', action='store_true', help='print indented by control flow (for reading the flow structure)')
    args = ap.parse_args()

    acts = open_shortcut(args.shortcut)['WFWorkflowActions']
    print(f'{len(acts)} actions')
    if args.tree:
        print_tree(acts)
        return
    for i, a in enumerate(acts):
        ident = a.get('WFWorkflowActionIdentifier', '?')
        params = a.get('WFWorkflowActionParameters', {})
        if args.prompts:
            if ident != 'is.workflow.actions.askllm':
                continue
            print(f'\n=== action {i} · model={_flatten(params.get("WFLLMModel"))} '
                  f'· result={params.get("WFGenerativeResultType")} ===')
            print(_flatten(params.get('WFLLMPrompt')))
        else:
            print(f'{i:4d}  {ident}')


if __name__ == '__main__':
    main()
