# Run DressMe

Run everything from the project folder, in PowerShell.

## Every day

Start Docker Desktop, then:

```powershell
.\scripts\dev\start.ps1 -AppPort 8002 -Bo6Port 18023
```

Open <http://localhost:8002/>.

To stop, once no try-on is running:

```powershell
.\scripts\dev\stop.ps1
```

## After `git pull`

```powershell
git lfs pull
.\scripts\dev\stop.ps1
.\.venv-app\Scripts\python.exe -m alembic upgrade head
.\scripts\dev\start.ps1 -AppPort 8002 -Bo6Port 18023
```

Then press **Ctrl+F5** in the browser.

## First time on a new PC

You need Git with Git LFS, Python 3.11, Node.js 20.19+ or 22.12+, and Docker Desktop. Ask the team for the approved BO6 bundle folder.

```powershell
git clone https://github.com/aymendhieb02/DressMe.git
cd DressMe
git lfs pull
.\scripts\dev\setup.ps1 -Developer -IncludeBo6
.\scripts\dev\restore-model-bundle.ps1 -SourceBundlePath 'D:\path\to\approved\bundle'
.\.venv-app\Scripts\python.exe -m alembic upgrade head
docker run -d --name dressme-bo7-local-redis-1 -p 127.0.0.1:6379:6379 redis:7-alpine
.\scripts\dev\start.ps1 -AppPort 8002 -Bo6Port 18023
```

On a GPU with 4 GB of memory, set `DRESSME_PARSER_ENABLED=off` in `.env` before starting.

## Turn on real try-on

Try-on is a labelled mock until you do this. Start your Kaggle notebook first, then set these in `.env`:

```env
VTON_MODE=real
VTON_REMOTE_URL=https://your-ngrok-address
VTON_REMOTE_API_KEY=your-key
```

Restart with `stop.ps1` and `start.ps1`.

### Kaggle notebook

In each new session, run the setup cells, then this cell, then the server cell:

```python
import importlib.util, pathlib, site, subprocess, sys

SRC = "/kaggle/working/fashn_package/vendor/fashn-vton-1.5/src"
pathlib.Path(site.getsitepackages()[0], "fashn_vendor.pth").write_text(SRC + "\n")

for module, package in [("fashn_human_parser", "fashn-human-parser==0.1.1"),
                        ("onnxruntime", "onnxruntime"), ("einops", "einops")]:
    if importlib.util.find_spec(module) is None:
        extra = ["--no-deps"] if module == "fashn_human_parser" else []
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", package, *extra], check=True)
```

## Check that it works

```powershell
.\scripts\dev\check.ps1 -AppPort 8002 -Bo6Port 18023
```

## If something is wrong

| You see | Do this |
| --- | --- |
| Try-on says **Unavailable** | Start Docker Desktop, then run `stop.ps1` and `start.ps1` |
| **The try-on server could not be reached** | Kaggle stopped. Restart the notebook |
| **The try-on server was busy** | Wait a few minutes and send it again |
| The page looks old | Press **Ctrl+F5** |
| `Port is occupied` on start | Run `stop.ps1`, then start again |
