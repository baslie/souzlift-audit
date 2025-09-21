"""Setup helper for souzlift-audit on Windows.

This script automates sections 2–6 of docs/guides/windows-dev.md:

1. Ensures the repository exists at C:\\Users\\Roman\\Desktop\\souzlift-audit.
2. Creates/updates the local virtual environment (.venv).
3. Installs dependencies from requirements.txt.
4. Exports development environment variables and applies migrations.

Run with Python 3.11:

    python setup_windows_dev.py

The script assumes Git and Python are on PATH.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


BASE_PATH = Path(r"C:\Users\Roman\Desktop")
REPO_NAME = "souzlift-audit"
DEFAULT_REPO_URL = "https://github.com/baslie/souzlift-audit.git"


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    """Execute a subprocess command and echo it to stdout."""

    printable_cmd = " ".join(cmd)
    print(f"\n→ {printable_cmd}")
    subprocess.run(cmd, check=True, cwd=cwd, env=env)


def ensure_repo(base_path: Path, repo_url: str) -> Path:
    """Clone the repository if it does not exist and return its path."""

    repo_path = base_path / REPO_NAME
    if repo_path.exists():
        print(f"Каталог {repo_path} уже существует — клонирование пропущено.")
    else:
        base_path.mkdir(parents=True, exist_ok=True)
        print(f"Клонируем репозиторий {repo_url} в {repo_path} …")
        run(["git", "clone", repo_url, str(repo_path)])
    return repo_path


def ensure_venv(repo_path: Path) -> Path:
    """Create a virtual environment if needed and return its python.exe path."""

    venv_path = repo_path / ".venv"
    python_in_venv = venv_path / "Scripts" / "python.exe"
    if not python_in_venv.exists():
        print("Создаём виртуальное окружение .venv …")
        run([sys.executable, "-m", "venv", str(venv_path)])
    return python_in_venv


def install_dependencies(python_in_venv: Path, repo_path: Path) -> None:
    """Install pip dependencies inside the virtual environment."""

    run([str(python_in_venv), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python_in_venv), "-m", "pip", "install", "-r", "requirements.txt"], cwd=repo_path)


def apply_migrations(python_in_venv: Path, repo_path: Path) -> None:
    """Run Django migrations with development environment variables."""

    env = os.environ.copy()
    env.update(
        {
            "DJANGO_ENV": "dev",
            "DJANGO_SECRET_KEY": "dev-secret-key",
            "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1",
        }
    )
    backend_dir = repo_path / "backend"
    run([str(python_in_venv), "manage.py", "migrate"], cwd=backend_dir, env=env)


def main() -> None:
    repo_path = ensure_repo(BASE_PATH, DEFAULT_REPO_URL)
    python_in_venv = ensure_venv(repo_path)
    install_dependencies(python_in_venv, repo_path)
    apply_migrations(python_in_venv, repo_path)
    print(
        "\nСреда готова. При необходимости активируйте окружение командой "
        ".\\.venv\\Scripts\\Activate.ps1 и запустите python manage.py runserver."
    )


if __name__ == "__main__":
    main()
