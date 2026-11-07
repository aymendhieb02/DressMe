# Intégration BO1/BO5 et comptes utilisateurs

La branche intégrée ajoute le chat BO1/BO5 à l'application de l'équipe. Le genre choisi à l'inscription ou dans **Account** est lu automatiquement depuis le compte authentifié ; une demande explicite garde la priorité.

La correction des tenues répétitives et du choix des vêtements selon l’usage est documentée dans [diagnostics/RELEVANCE_FIX.md](diagnostics/RELEVANCE_FIX.md).

Le guide actuel, le lancement et les validations sont dans [docs/SESSION_GENDER_INTEGRATION.md](docs/SESSION_GENDER_INTEGRATION.md). **Le verrou commun actuel est `requirements-integrated.lock.txt`** ; les anciens verrous et bilans décrivent les environnements antérieurs.

Le guide de l'équipe ci-dessous et la procédure BO6 restent disponibles. L'ancien guide local BO1/BO5 est conservé dans [docs/BO1_BO5_LOCAL.md](docs/BO1_BO5_LOCAL.md).

---

# DressMe

Integrated DressMe app for Windows. The landing page, sign-in, Style Engine, Shopping, BO6 wardrobe and BO7 Studio run from one FastAPI app on port **8001**. The app uses SQLite; BO6 garment inference runs as a separate local service on port **18022**.

## Install first

- Git
- Python 3.11, 64-bit
- Node.js 20.19+ or 22.12+ (npm is included)
- PowerShell
- The approved BO6 model bundle from the team (`model_weights.pt` and `attribute_heads.pt`); these large private artifacts are not stored in Git.

The setup script installs the Python dependencies into isolated environments, installs the landing page dependencies, builds the landing page, and creates `.env` from `.env.example` with a local secret. Network access is needed during installation. The default database is SQLite at `var/dressme.sqlite`.

## First run after cloning

Run from the repository root in PowerShell:

```powershell
git clone <repository-url> projet_integration
cd projet_integration
.\scripts\dev\setup.ps1 -Developer -IncludeBo6
```

Restore the model files from the approved team bundle location. The script verifies their checksums before copying them:

```powershell
.\scripts\dev\restore-model-bundle.ps1 -SourceBundlePath 'D:\path\to\approved\bundle'
```

Apply database migrations, start both services, then check them:

```powershell
& .\.venv-app\Scripts\python.exe -m alembic upgrade head
.\scripts\dev\start.ps1 -AppPort 8001 -Bo6Port 18022
.\scripts\dev\check.ps1 -AppPort 8001 -Bo6Port 18022
```

Open **http://localhost:8001/**. The BO6 service on port 18022 is internal; the browser stays on port 8001. Do not start a separate Vite server for the integrated app.

## After pulling updates

```powershell
git pull
.\scripts\dev\setup.ps1 -Developer -IncludeBo6
& .\.venv-app\Scripts\python.exe -m alembic upgrade head
.\scripts\dev\start.ps1 -AppPort 8001 -Bo6Port 18022
.\scripts\dev\check.ps1 -AppPort 8001 -Bo6Port 18022
```

Keep the local `.env`, SQLite database, private image folder, and restored BO6 weights when updating. They are machine-specific and are not pulled from Git. If model files are already restored and pass checksum verification, the restore step can be skipped.

To stop services started by the project scripts:

```powershell
.\scripts\dev\stop.ps1
```

## Local configuration

Password recovery saves messages to a local `.eml` mailbox by default; it does not send email externally. SMTP delivery needs private SMTP settings in `.env`. Redis and Avaturn are optional; virtual try-on runs in mock mode unless separately configured. Some inherited Style Engine and Shopping features may download model weights the first time they are used.
