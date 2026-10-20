"""Sube al repositorio (y por tanto a la página web) un archivo en mitad de la ejecución de GitHub Actions.

Se usa para que el texto del post esté en la página antes de la hora de publicación, sin esperar al final.
"""
from __future__ import annotations

import logging
import os
import subprocess

from .config import RAIZ

log = logging.getLogger(__name__)


def subir(rutas: list, mensaje: str):
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    git = ["git", "-C", str(RAIZ), "-c", "user.name=parte-bot", "-c", "user.email=parte-bot@users.noreply.github.com"]
    try:
        subprocess.run(git + ["add", *map(str, rutas)], check=True)
        if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode == 0:
            return
        subprocess.run(git + ["commit", "-q", "-m", mensaje], check=True)
        for _ in range(3):
            subprocess.run(git + ["pull", "-q", "--rebase", "--autostash"], check=False)
            if subprocess.run(git + ["push", "-q"]).returncode == 0:
                log.info("Texto del post publicado en la web (%s)", mensaje)
                return
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo subir el texto antes de tiempo: %s", e)
