"""公開候補・Git index・全refの内容を検査し、機密の値を出力しない。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'secret-key': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)'),
    'credential-literal': re.compile(rb'(?i)(?:api[_-]?key|password|token|secret)["\x27]?\s*[=:]\s*["\x27][A-Za-z0-9_+/-]{8,}["\x27]'),
    'personal-home-path': re.compile(rb'(?:[A-Z]:[\\/]+Users[\\/]+[^\s"<>]+|/(?:home|Users)/[^\s"<>]+)'),
    'local-drive-path': re.compile(rb'[A-Z]:[\\/]+(?!demo[\\/]|example[\\/])[^\s"<>]+'),
}
PUBLIC_ROOTS = {'gentrace','tests','scripts','docs','.github'}
SENSITIVE_SUFFIXES = {'.db','.sqlite','.sqlite3','.csv','.tsv','.log','.bak','.key','.pem','.jpg','.jpeg','.webp','.gif','.mp4','.safetensors','.onnx','.ckpt','.pt','.pth'}
PUBLIC_TEXT_SUFFIXES = {'.py','.md','.txt','.json','.yml','.yaml','.cmd','.vbs'}


def git(*args: str) -> bytes:
    return subprocess.check_output(['git','-C',str(ROOT),*args],stderr=subprocess.PIPE)


def public_files() -> list[str]:
    """明示したマニフェストだけを配布対象にする。"""
    paths=[s.strip() for s in (ROOT/'publication-files.txt').read_text(encoding='utf-8').splitlines() if s.strip() and not s.startswith('#')]
    if len(paths)!=len(set(paths)):
        raise ValueError('公開マニフェストに重複があります。')
    for name in paths:
        p=Path(name)
        if p.is_absolute() or '..' in p.parts or '\\' in name or not (ROOT/p).is_file() or (ROOT/p).is_symlink():
            raise ValueError('公開マニフェストに不正または存在しないファイルがあります。')
    return paths


def check_content(name: str, payload: bytes, image_hashes: dict) -> list[str]:
    """一致した値は表示せず、分類だけ返す。"""
    reasons=[]
    p=Path(name)
    if any(part.casefold() in {'data','logs','exports','backups','cache','.cache','.venv','venv','__pycache__','.git'} for part in p.parts) and p.name!='.gitkeep':
        reasons.append('private-directory')
    if p.suffix.lower() in SENSITIVE_SUFFIXES or '.db-' in p.name or p.name.startswith('.env') and p.name!='.env.example' or p.name in {'settings.json','config.local.json'}:
        reasons.append('private-file-type')
    if payload.startswith((b'SQLite format 3',b'\xff\xd8')):
        reasons.append('private-binary')
    if p.suffix.lower()=='.png' or payload.startswith(b'\x89PNG'):
        if hashlib.sha256(payload).hexdigest()!=image_hashes.get(name):
            reasons.append('unreviewed-image')
        return reasons
    if b'\x00' in payload:
        reasons.append('unexpected-binary')
    for category,pattern in PATTERNS.items():
        if pattern.search(payload):
            reasons.append(category)
    username=os.environ.get('USERNAME','')
    if len(username)>2 and username.encode('utf-8') in payload:
        reasons.append('current-username')
    return reasons


def audit(history: bool=False, staged: bool=False) -> dict:
    hashes=json.loads((ROOT/'docs/screenshots/manifest.json').read_text(encoding='utf-8'))
    files=public_files()
    findings=[]
    for name in files:
        reasons=check_content(name,(ROOT/name).read_bytes(),hashes)
        if reasons: findings.append({'scope':'publication','file':name,'categories':reasons})
    git_present=(ROOT/'.git').exists()
    if git_present:
        candidates=git('ls-files','--cached','--others','--exclude-standard','-z').decode('utf-8').split('\0')
        for name in filter(None,candidates):
            if name not in files and not name.startswith('.agents/'):
                findings.append({'scope':'worktree','file':name,'categories':['not-in-publication-manifest']})
            path=ROOT/name
            if path.is_file() and name not in files:
                reasons=check_content(name,path.read_bytes(),hashes)
                if reasons:findings.append({'scope':'worktree','file':name,'categories':reasons})
        if staged:
            for name in filter(None,git('ls-files','-z').decode('utf-8').split('\0')):
                reasons=check_content(name,git('show',':'+name),hashes)
                if reasons:findings.append({'scope':'index','file':name,'categories':reasons})
    history_count=0
    identity_review=False
    if history:
        if not git_present:raise ValueError('履歴監査にはGitリポジトリが必要です。')
        for entry in git('rev-list','--objects','--all').decode('utf-8').splitlines():
            oid,_,name=entry.partition(' ')
            kind=git('cat-file','-t',oid).strip()
            payload=git('cat-file',kind.decode(),oid) if kind in {b'blob',b'commit',b'tag'} else b''
            if kind==b'blob':
                history_count+=1
                reasons=check_content(name,payload,hashes)
            elif kind in {b'commit',b'tag'}:
                reasons=[k for k,p in PATTERNS.items() if p.search(payload)]
                addresses=re.findall(rb'<([^<>]+@[^<>]+)>',payload)
                identity_review=identity_review or any(
                    not address.endswith(b'@users.noreply.github.com') for address in addresses
                )
                username=os.environ.get('USERNAME','')
                if len(username)>2 and username.encode('utf-8') in payload:
                    reasons.append('current-username')
            else:continue
            if reasons:findings.append({'scope':'history','file':name or kind.decode(),'object':oid[:12],'categories':reasons})
    return {'publication_files':len(files),'history_blobs':history_count,'commit_identity_needs_review':identity_review,'findings':findings,'passed':not findings and not identity_review}


def export_source(target: Path) -> None:
    """検査済みの内容だけを、Git履歴なしで新しいZIPへ保存する。"""
    result=audit()
    if not result['passed']:
        raise ValueError('公開監査に未解決項目があるため配布物を作成しません。')
    if target.exists():raise FileExistsError('既存の配布物は上書きしません。別の保存名を指定してください。')
    files=public_files()
    hashes=json.loads((ROOT/'docs/screenshots/manifest.json').read_text(encoding='utf-8'))
    # 検査後の書換えも、実際に書き込む同じバイト列を検査して防ぐ。
    payloads=[]
    for name in files:
        content=(ROOT/name).read_bytes()
        if check_content(name,content,hashes):raise ValueError('公開候補が検査後に変化しました。')
        payloads.append((name,content))
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,content in payloads:
            archive.writestr('GenTrace/'+name,content)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history',action='store_true')
    parser.add_argument('--staged',action='store_true')
    parser.add_argument('--export',type=Path)
    args=parser.parse_args()
    try:
        result=audit(args.history,args.staged)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if not result['passed']:return 1
        if args.export:export_source(args.export)
        return 0
    except (OSError,ValueError,subprocess.CalledProcessError) as exc:
        print(f'公開検査を完了できません: {type(exc).__name__}',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
