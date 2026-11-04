"""Official PyTorch wheels using verified HTTP ranges when a full transfer stalls."""
import concurrent.futures
import hashlib
import html
import os
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / '.cache' / 'downloads'


def download(package, filename):
    index = f'https://download.pytorch.org/whl/cu126/{package}/'
    listing = urllib.request.urlopen(index, timeout=30).read().decode()
    links = [html.unescape(s) for s in re.findall(r'href="([^"]+)"', listing)]
    url = next(u for u in links if urllib.parse.unquote(urllib.parse.urlparse(u).path).endswith('/' + filename))
    url = urllib.parse.urljoin(index, url)
    expected = urllib.parse.parse_qs(urllib.parse.urlparse(url).fragment)['sha256'][0]
    url = url.split('#')[0]
    target = DEST / filename
    if target.is_file() and hashlib.file_digest(target.open('rb'), 'sha256').hexdigest() == expected:
        print('Verified existing', filename, flush=True)
        return
    req = urllib.request.Request(url, method='HEAD')
    size = int(urllib.request.urlopen(req, timeout=30).headers['Content-Length'])
    # An interrupted Windows write can leave a correctly sized sparse tail.
    # Repair only zero-filled ranges, then verify the entire official SHA256.
    if target.is_file() and target.stat().st_size == size:
        block = 32 * 1024**2
        missing = []
        with target.open('rb') as source:
            for i in range((size+block-1)//block):
                start,end=i*block,min(size,(i+1)*block)
                for position in (start,start+(end-start)//2,max(start,end-65536)):
                    source.seek(position)
                    data=source.read(min(65536,end-position))
                    if data and not any(data):
                        missing.append(i)
                        break
        for i in missing:
            start,end=i*block,min(size,(i+1)*block)-1
            req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
            with urllib.request.urlopen(req,timeout=60) as response:
                if response.status != 206:
                    raise RuntimeError('Range repair refused')
                data=response.read()
            if len(data)!=end-start+1:
                raise RuntimeError('Incomplete repair range')
            with target.open('r+b') as output:
                output.seek(start);output.write(data);output.flush();os.fsync(output.fileno())
            print('Repaired sparse range',i,flush=True)
        with target.open('rb') as source:
            if hashlib.file_digest(source,'sha256').hexdigest()==expected:
                print('Repaired and verified official SHA256:',filename,flush=True)
                return
    if shutil.disk_usage(DEST).free < size * 2 + 1024**3:
        raise RuntimeError('Not enough free disk space for verified chunked download')
    partsize = 32 * 1024**2
    def part(i):
        start, end = i * partsize, min(size, (i+1)*partsize)-1
        path = DEST / (filename + f'.part{i:03d}')
        if path.is_file() and path.stat().st_size == end-start+1:
            return path
        request = urllib.request.Request(url, headers={'Range': f'bytes={start}-{end}'})
        with urllib.request.urlopen(request, timeout=60) as response, path.open('wb') as output:
            if response.status != 206:
                raise RuntimeError('Server did not honor range request')
            shutil.copyfileobj(response, output, 1024*1024)
        if path.stat().st_size != end-start+1:
            raise RuntimeError('Incomplete range')
        print(f'{package}: part {i+1}/{(size+partsize-1)//partsize}', flush=True)
        return path
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        parts = list(pool.map(part, range((size+partsize-1)//partsize)))
    temporary=target.with_suffix('.assembling')
    with temporary.open('wb') as output:
        for path in parts:
            with path.open('rb') as source:
                shutil.copyfileobj(source, output, 1024*1024)
        output.flush();os.fsync(output.fileno())
    with temporary.open('rb') as source:
        actual = hashlib.file_digest(source,'sha256').hexdigest()
    if actual != expected:
        raise RuntimeError('Official wheel SHA256 verification failed')
    temporary.replace(target)
    # Only exact file paths generated and verified above; no directory deletion.
    for path in parts:
        path.unlink()
    print('Verified official SHA256:',filename,flush=True)


if __name__ == '__main__':
    DEST.mkdir(parents=True,exist_ok=True)
    download('torch','torch-2.8.0+cu126-cp311-cp311-win_amd64.whl')
    download('torchvision','torchvision-0.23.0+cu126-cp311-cp311-win_amd64.whl')
