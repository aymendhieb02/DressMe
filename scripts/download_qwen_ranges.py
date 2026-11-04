"""Verified, resumable download of the two exact pinned base shards when Hub transfer stalls."""
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dressme.config import ADAPTER, CACHE, hf_auth


def main():
    from huggingface_hub import get_hf_file_metadata, hf_hub_url
    receipt=json.loads((ADAPTER/'training_receipt.json').read_text(encoding='utf-8'))
    revision=receipt['base_revision']
    folder=CACHE/'models'/'models--Qwen--Qwen3-1.7B'/'snapshots'/revision
    index=json.loads((folder/'model.safetensors.index.json').read_text(encoding='utf-8'))
    downloads=CACHE/'qwen_parts'
    downloads.mkdir(parents=True,exist_ok=True)
    for filename in sorted(set(index['weight_map'].values())):
        info=get_hf_file_metadata(hf_hub_url(receipt['base_model'],filename,revision=revision),token=hf_auth())
        if not re.fullmatch(r'[0-9a-f]{64}',info.etag) or not info.size:
            raise RuntimeError('Expected an official LFS SHA256 and known size')
        target=folder/filename
        if target.is_file():
            with target.open('rb') as source:
                if hashlib.file_digest(source,'sha256').hexdigest()==info.etag:
                    print('Verified existing',filename,flush=True)
                    continue
        if shutil.disk_usage(downloads).free < info.size*2+1024**3:
            raise RuntimeError('Insufficient free space')
        block=16*1024**2
        count=(info.size+block-1)//block
        def part(i):
            start,end=i*block,min(info.size,(i+1)*block)-1
            path=downloads/(filename+f'.part{i:03d}')
            if path.is_file() and path.stat().st_size==end-start+1:
                return path
            # Only the signed public storage URL is used here. No HF Authorization
            # header is forwarded to another host.
            req=urllib.request.Request(info.location,headers={'Range':f'bytes={start}-{end}'})
            with urllib.request.urlopen(req,timeout=60) as response,path.open('wb') as output:
                if response.status!=206:
                    raise RuntimeError('Storage did not honor range')
                shutil.copyfileobj(response,output,1024*1024)
            if path.stat().st_size!=end-start+1:
                raise RuntimeError('Incomplete weight range')
            print(f'{filename}: {i+1}/{count}',flush=True)
            return path
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            parts=list(pool.map(part,range(count)))
        temporary=target.with_suffix('.assembling')
        with temporary.open('wb') as output:
            for path in parts:
                with path.open('rb') as source:
                    shutil.copyfileobj(source,output,1024*1024)
            output.flush();os.fsync(output.fileno())
        with temporary.open('rb') as source:
            if hashlib.file_digest(source,'sha256').hexdigest()!=info.etag:
                raise RuntimeError('Base shard SHA256 verification failed')
        temporary.replace(target)
        for path in parts:
            path.unlink()
        print('Official SHA256 verified:',filename,flush=True)


if __name__=='__main__':
    main()
