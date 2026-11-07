"""Build and fully checksum a portable, ZIP64 BO1/BO5 model bundle.

Uses explicit public-model/catalogue allowlists. Never walks private runtime,
account databases, credentials, training checkpoints, or Python environments.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import time
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

VERIFY_SCRIPT=r'''"""Check the extracted model bundle. Standard Python only; no network."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--quick',action='store_true',help='Check only presence and sizes.')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    manifest=json.loads((root/'MODELES_SHA256.json').read_text(encoding='utf-8'))
    failures=[]
    for index,(name,record) in enumerate(manifest['files'].items(),1):
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            failures.append(name+': absent');continue
        if path.stat().st_size!=record['bytes']:
            failures.append(name+': taille incorrecte');continue
        if not args.quick:
            digest=hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(8*1024*1024),b''):digest.update(chunk)
            if digest.hexdigest()!=record['sha256']:failures.append(name+': SHA256 incorrect')
        if index%300==0:print(str(index)+' fichiers verifies',flush=True)
    if failures:
        print('\n'.join(failures));return 1
    print('OK : '+str(len(manifest['files']))+' fichiers modeles/catalogue verifies'+(' (tailles uniquement).' if args.quick else ' (SHA256).'))
    return 0

if __name__=='__main__':sys.exit(main())
'''

LAUNCHER=r'''@echo off
setlocal
cd /d "%~dp0"
set "CHAT_PYTHON="
if defined DRESSME_PYTHON_EXE set "CHAT_PYTHON=%DRESSME_PYTHON_EXE%"
if not defined CHAT_PYTHON if exist ".venv-app\Scripts\python.exe" set "CHAT_PYTHON=.venv-app\Scripts\python.exe"
if not defined CHAT_PYTHON if exist ".venv\Scripts\python.exe" set "CHAT_PYTHON=.venv\Scripts\python.exe"
if not defined CHAT_PYTHON (
  echo Environnement Python absent. Installer requirements-integrated.lock.txt dans .venv ou .venv-app.
  exit /b 1
)
"%CHAT_PYTHON%" verifier_modeles.py --quick
if errorlevel 1 exit /b 1
"%CHAT_PYTHON%" -c "import torch,sys; print('PyTorch',torch.__version__,'CUDA',torch.cuda.is_available()); sys.exit(0 if torch.cuda.is_available() else 1)"
if errorlevel 1 (
  echo Ce lanceur utilise NF4 sur GPU NVIDIA. Un PC CPU seul necessite une autre configuration.
  exit /b 1
)
if /i "%~1"=="--check" (
  echo Verification terminee. Aucun serveur lance et aucune base modifiee.
  exit /b 0
)
set "DRESSME_BO1_DIR=%~dp0bo1\score"
set "DRESSME_PARSER_ADAPTER=%~dp0bo5\parser_for_local\parser_adapter"
set "DRESSME_CACHE=%~dp0.cache"
set "DRESSME_ALLOW_DOWNLOADS=0"
set "DRESSME_RAG_MODE=hybrid"
set "DRESSME_LLM=off"
set "DRESSME_PARSER_DEVICE=cuda:0"
set "DRESSME_PARSER_PRECISION=nf4"
set "FRONTEND_ORIGINS=http://127.0.0.1:8000,http://localhost:8000"
echo DressMe : http://127.0.0.1:8000/app#assistant
"%CHAT_PYTHON%" -m uvicorn api:app --host 127.0.0.1 --port 8000
'''

README='''# DressMe — modèles du chat BO1/BO5

Extraire le CONTENU de ce ZIP directement dans la racine de votre projet
DressMe, là où se trouve api.py. Le ZIP n'ajoute pas un dossier DressMe parent.
Sous Windows, conserver le dossier .cache, même si son nom commence par un point.

Arborescence fournie :
  .cache/models/models--Qwen--Qwen3-1.7B/snapshots/70d244cc86ccca08cf5af4e1e306ecf908b1ad5e/
  .cache/models/models--intfloat--multilingual-e5-small/snapshots/614241f622f53c4eeff9890bdc4f31cfecc418b3/
  bo1/score/
  bo5/parser_for_local/parser_adapter/
  data/ (catalogue public coherent a 653 articles et exports associes)

Les snapshots contiennent les vrais fichiers, pas des liens vers un cache
exterieur. Les repertoires blobs et refs ne sont pas necessaires a ces revisions
explicitement epinglees. Les images de bo1/score/img sont toutes fournies.

Verifier l'extraction, depuis la racine du projet :
  py -3.11 verifier_modeles.py
Verification rapide des presences/tailles :
  py -3.11 verifier_modeles.py --quick

Chaque collegue doit disposer du code ACTUEL de l'application fusionnee et
installer ses dependances Python depuis requirements-integrated.lock.txt.
Cette archive est un paquet de modeles et de donnees, pas une installation de
Python, des bibliotheques, du pilote NVIDIA ou du code de toute l'application.

Dans votre propre .env, les chemins sont relatifs a la racine du projet :
  DRESSME_BO1_DIR=bo1/score
  DRESSME_PARSER_ADAPTER=bo5/parser_for_local/parser_adapter
  DRESSME_CACHE=.cache
  DRESSME_RAG_MODE=hybrid
  DRESSME_ALLOW_DOWNLOADS=0
  DRESSME_LLM=off

Configuration GPU deja validee :
  DRESSME_PARSER_DEVICE=cuda:0
  DRESSME_PARSER_PRECISION=nf4
Le mode NF4 exige un GPU NVIDIA compatible. Un PC CPU seul demande une
configuration differente ; les dependances et pilotes restent a installer.

Appliquer les migrations de votre base, puis lancer l'application :
  .\\.venv\\Scripts\\python.exe -m alembic upgrade head
  .\\.venv\\Scripts\\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
Si votre environnement s'appelle .venv-app, utilisez ce nom a la place.

Le RAG reconstruit son index local au premier usage. Aucun token Hugging Face
n'est necessaire pour charger les modeles fournis hors ligne. L'archive ne
contient aucun .env, compte utilisateur, dressing prive ou conversation.

Les poids BO6, les modeles de recherche photo des autres ecrans et leurs
services externes ne font pas partie de ce paquet centre sur le chat BO1/BO5.
Le modele visual.pt et les checkpoints d'entrainement ne sont pas utilises par
le chat actuel et ne sont pas inclus.

Lanceur Windows fourni : lancer_chat_local.bat
Apres installation des dependances et migrations, ce lanceur detecte .venv-app
ou .venv, verifie les modeles et active les chemins ci-dessus pour ce processus
uniquement. Il ne modifie pas votre .env, n'installe aucun logiciel et ne lance
aucune migration. Verification seule : lancer_chat_local.bat --check
'''


def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def collect():
    from huggingface_hub import snapshot_download
    from dressme.config import EXPORT,ADAPTER,CACHE
    receipt=json.loads((ADAPTER/'training_receipt.json').read_text(encoding='utf-8'))
    qwen=CACHE/'models/models--Qwen--Qwen3-1.7B/snapshots'/receipt['base_revision']
    e5_revision='614241f622f53c4eeff9890bdc4f31cfecc418b3'
    try:e5=Path(snapshot_download('intfloat/multilingual-e5-small',revision=e5_revision,local_files_only=True))
    except Exception:e5=Path(snapshot_download('intfloat/multilingual-e5-small',revision=e5_revision,cache_dir=str(CACHE/'models'),local_files_only=True))
    files={}
    def add(source,name):
        source=Path(source);name=PurePosixPath(name).as_posix()
        if name.startswith('/') or '..' in PurePosixPath(name).parts:raise ValueError('Unsafe archive member')
        if not source.is_file():raise FileNotFoundError(source)
        with source.open('rb') as stream:
            if stream.read(160).startswith(b'version https://git-lfs.github.com/spec/v1'):
                raise ValueError('Unrestored Git LFS pointer: '+str(source))
        if name in files:raise ValueError('Duplicate member '+name)
        files[name]=source
    def tree(source,prefix):
        if not source.is_dir():raise FileNotFoundError(source)
        for path in sorted(source.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and not path.name.endswith(('.incomplete','.lock')):
                add(path,PurePosixPath(prefix)/path.relative_to(source).as_posix())
    for name in ('catalog.json','config.json','dressme_core.py','emb_clip.npy','emb_ft.npy','outfits.json','scorer.pt'):
        add(EXPORT/name,'bo1/score/'+name)
    tree(EXPORT/'img','bo1/score/img')
    for name in ('adapter_config.json','adapter_model.safetensors','added_tokens.json','chat_template.jinja',
                 'merges.txt','special_tokens_map.json','tokenizer_config.json','tokenizer.json','training_receipt.json','vocab.json'):
        add(ADAPTER/name,'bo5/parser_for_local/parser_adapter/'+name)
    tree(qwen,'.cache/models/models--Qwen--Qwen3-1.7B/snapshots/'+receipt['base_revision'])
    tree(e5,'.cache/models/models--intfloat--multilingual-e5-small/snapshots/'+e5_revision)
    for name in ('catalog.json','catalog_gender.json','config.json','dressme_core.py','emb_clip.npy','emb_ft.npy',
                 'outfits.json','scorer.pt','search_emb.npy','search_meta.json','bo3_emb.npy','bo3_colour_lab.npy','bo3_thresholds.json'):
        add(ROOT/'data'/name,'data/'+name)
    for name in ('img','search_img','completion'):tree(ROOT/'data'/name,'data/'+name)
    return dict(sorted(files.items())),receipt,e5_revision


def main():
    files,receipt,e5_revision=collect()
    size=sum(path.stat().st_size for path in files.values())
    if shutil.disk_usage(ROOT).free<size*3:raise RuntimeError('Not enough free space for ZIP and verification extraction')
    output=ROOT/'output/models';output.mkdir(parents=True,exist_ok=True)
    target=output/'DressMe_modeles_chat_BO1_BO5.zip'
    if target.exists():raise FileExistsError('Refusing to overwrite an existing deliverable: '+str(target))
    partial=target.with_suffix('.zip.part')
    if partial.exists():raise FileExistsError(partial)
    manifest=dict(format='DressMe chat models ZIP64 v1',uncompressed_bytes=size,
        models=dict(qwen='Qwen/Qwen3-1.7B',qwen_revision=receipt['base_revision'],
                    adapter_sha256=receipt['adapter_file_sha256'],e5='intfloat/multilingual-e5-small',e5_revision=e5_revision),files={})
    print(json.dumps(dict(stage='building',files=len(files),bytes=size,output=str(target)),ensure_ascii=False),flush=True)
    started=time.monotonic();done=0
    with zipfile.ZipFile(partial,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as archive:
        for index,(name,source) in enumerate(files.items(),1):
            before=source.stat();digest=hashlib.sha256();last=time.monotonic()
            info=zipfile.ZipInfo(name);info.compress_type=zipfile.ZIP_DEFLATED;info._compresslevel=1
            # Store resolved contents as ordinary files: no external symlink dependencies.
            info.external_attr=0o100644<<16
            with source.open('rb') as src,archive.open(info,'w',force_zip64=True) as dst:
                while chunk:=src.read(8*1024*1024):
                    digest.update(chunk);dst.write(chunk);done+=len(chunk)
                    if time.monotonic()-last>15:
                        print(json.dumps(dict(stage='compressing',member=name,processed_bytes=done,total_bytes=size)),flush=True);last=time.monotonic()
            after=source.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError('Source changed: '+str(source))
            manifest['files'][name]=dict(bytes=after.st_size,sha256=digest.hexdigest())
            if index%300==0:print(json.dumps(dict(stage='building',completed_files=index,total_files=len(files),processed_bytes=done)),flush=True)
        archive.writestr('MODELES_INSTALLATION.md',README)
        archive.writestr('verifier_modeles.py',VERIFY_SCRIPT)
        archive.writestr('lancer_chat_local.bat',LAUNCHER.replace('\n','\r\n').encode('ascii'))
        archive.writestr('MODELES_SHA256.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    # Validate every member's CRC and SHA while extracting a disposable copy.
    check=ROOT/'tmp'/('model-package-check-'+uuid.uuid4().hex[:10]);check.mkdir(parents=True)
    print(json.dumps(dict(stage='verifying',extraction=str(check))),flush=True)
    with zipfile.ZipFile(partial) as archive:
        if len(archive.namelist())!=len(set(archive.namelist())):raise ValueError('Duplicate ZIP members')
        for index,info in enumerate(archive.infolist(),1):
            path=check/PurePosixPath(info.filename)
            if not path.resolve().is_relative_to(check.resolve()):raise ValueError('ZIP traversal member')
            path.parent.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256()
            with archive.open(info) as src,path.open('wb') as dst:
                while chunk:=src.read(8*1024*1024):digest.update(chunk);dst.write(chunk)
            expected=manifest['files'].get(info.filename)
            if expected and (path.stat().st_size!=expected['bytes'] or digest.hexdigest()!=expected['sha256']):
                raise ValueError('Checksum mismatch '+info.filename)
            if index%300==0:print(json.dumps(dict(stage='verifying',completed_files=index,total_files=len(files)+4)),flush=True)
    partial.rename(target)
    zip_hash=sha256(target)
    (output/(target.name+'.sha256')).write_text(zip_hash+'  '+target.name+'\n',encoding='ascii')
    validation=dict(archive=str(target),bytes=target.stat().st_size,sha256=zip_hash,model_files=len(files),
        crc_and_sha256_all_members=True,extraction=str(check),seconds=round(time.monotonic()-started,2))
    (output/'verification.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(stage='complete',**validation),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
