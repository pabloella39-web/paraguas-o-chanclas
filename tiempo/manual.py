"""Guiones escritos por Claude con el plan normal (tareas programadas), sin gastar la API.

Flujo (GitHub Actions):
  1. La ejecución prepara el prompt con los datos reales del día y lo publica en la rama pendiente/<clave>.
  2. Una tarea programada de Claude lo lee, escribe la respuesta (el mismo JSON que devolvería la API) y la sube a
     main como guiones/<clave>.json.
  3. La ejecución, que espera hasta una hora límite, la recoge y sigue. Si no llega a tiempo → API (respaldo).

CLI (lo usa la tarea programada):
  python -m tiempo.manual pendientes          # claves pendientes y sus ramas
  python -m tiempo.manual ver <clave>         # imprime el prompt
  python -m tiempo.manual comprobar <clave> <archivo.json>
  python -m tiempo.manual entregar <clave> <archivo.json>   # valida, sube a main y borra la rama pendiente
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
GUIONES = RAIZ / "guiones"
TZ = ZoneInfo("Europe/Madrid")
log = logging.getLogger(__name__)


def _git(*args, check=False, **kw):
    return subprocess.run(["git", "-C", str(RAIZ), *args], check=check, capture_output=True, text=True, **kw)


def _publicar_pendiente(clave: str, prompt: str) -> bool:
    """Sube el prompt a la rama pendiente/<clave> (un commit suelto con prompt.txt), con las credenciales del checkout."""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".txt") as f:
            f.write(prompt)
        blob = _git("hash-object", "-w", f.name, check=True).stdout.strip()
        arbol = subprocess.run(["git", "-C", str(RAIZ), "mktree"], input=f"100644 blob {blob}\tprompt.txt\n",
                               capture_output=True, text=True, check=True).stdout.strip()
        env = dict(os.environ, GIT_AUTHOR_NAME="parte-bot", GIT_AUTHOR_EMAIL="parte-bot@users.noreply.github.com",
                   GIT_COMMITTER_NAME="parte-bot", GIT_COMMITTER_EMAIL="parte-bot@users.noreply.github.com")
        sha = subprocess.run(["git", "-C", str(RAIZ), "commit-tree", arbol, "-m", f"Pendiente {clave}"],
                             capture_output=True, text=True, check=True, env=env).stdout.strip()
        r = _git("push", "-qf", "origin", f"{sha}:refs/heads/pendiente/{clave}")
        if r.returncode:
            log.warning("No se pudo publicar el pendiente %s: %s", clave, r.stderr[-300:])
            return False
        log.info("Prompt publicado en la rama pendiente/%s", clave)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo publicar el pendiente %s: %s", clave, e)
        return False


def _traer(clave: str) -> Path:
    rel = f"guiones/{clave}.json"
    _git("fetch", "-q", "origin", "main")
    _git("checkout", "origin/main", "--", rel)
    return RAIZ / rel


def responder(clave: str, prompt: str, limite: str) -> dict | None:
    """Respuesta escrita a mano para este prompt, o None si no llega antes de `limite` (HH:MM, Madrid).
    Solo espera dentro de GitHub Actions (o con ESPERAR_GUION=1); en local solo mira si el archivo existe."""
    ruta = GUIONES / f"{clave}.json"
    espera = os.environ.get("ESPERAR_GUION", "1" if os.environ.get("GITHUB_ACTIONS") else "")
    if not ruta.exists() and espera and espera != "0":
        if os.environ.get("GITHUB_ACTIONS"):
            ruta = _traer(clave)
        if not ruta.exists():
            _publicar_pendiente(clave, prompt)
            h, m = map(int, limite.split(":"))
            while not ruta.exists():
                t = datetime.now(TZ)
                if (t.hour, t.minute) >= (h, m):
                    log.warning("El guion %s no llegó antes de las %s: respaldo con la API", clave, limite)
                    break
                time.sleep(45)
                ruta = _traer(clave)
    if not ruta.exists():
        return None
    try:
        g = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("Guion %s ilegible: %s", clave, e)
        return None
    log.info("Usando el guion escrito con el plan de Claude: guiones/%s.json", clave)
    if os.environ.get("GITHUB_ACTIONS"):
        _git("push", "-q", "origin", "--delete", f"pendiente/{clave}")
    return g


# ------------------------------------------------------------------ CLI para la tarea programada
def _pendientes() -> list[str]:
    r = _git("ls-remote", "origin", "refs/heads/pendiente/*")
    return [l.split("refs/heads/pendiente/")[1] for l in r.stdout.splitlines() if "refs/heads/pendiente/" in l]


def comprobar(clave: str, g: dict, prompt: str = "") -> list[str]:
    """Problemas de forma (los mismos que rechazaría el programa) y de longitud (según lo que pide el prompt)."""
    import re
    errores = []
    m = re.search(r"ENTRE (\d+) Y (\d+) PALABRAS", prompt)
    if m and clave.startswith("historia"):
        lo, hi = int(m.group(1)), int(m.group(2))
        for k, p in enumerate(g.get("partes") or [], 1):
            n = sum(len(t.get("texto", "").split()) for t in p.get("tramos") or [])
            if not lo - 5 <= n <= hi + 12:
                errores.append(f"{n} palabras (pide entre {lo} y {hi})")
    m = re.search(r"Total ≈ (\d+) palabras", prompt)
    if m and isinstance(g.get("segmentos"), dict):
        objetivo = int(m.group(1))
        n = sum(len(str(v).split()) for v in g["segmentos"].values())
        if not 0.92 * objetivo <= n <= 1.10 * objetivo:
            errores.append(f"{n} palabras en total (pide ≈ {objetivo}; entre {round(0.92 * objetivo)} y "
                           f"{round(1.10 * objetivo)})")
    tipo = clave.split("-")[0]
    if tipo == "historia":
        partes = g.get("partes") or []
        if len(partes) != 1:
            errores.append(f"{len(partes)} partes (debe ser UN solo vídeo)")
        for k, p in enumerate(partes, 1):
            tr = p.get("tramos") or []
            n = sum(len(t.get("texto", "").split()) for t in tr)
            if not 8 <= len(tr) <= 11:
                errores.append(f"{len(tr)} tramos (8 a 11)")
            if n < 130:
                errores.append(f"{n} palabras (mínimo ~145)")
            if any(not t.get("imagen") for t in tr):
                errores.append("hay tramos sin 'imagen'")
        for c in ("titulo", "gancho", "etiqueta", "caption", "pregunta", "hashtags", "narrador"):
            if not g.get(c):
                errores.append(f"falta {c}")
    else:
        seg = g.get("segmentos")
        if not isinstance(seg, dict) or not seg:
            errores.append("falta 'segmentos'")
        else:
            vacios = [k for k, v in seg.items() if not str(v).strip()]
            if vacios:
                errores.append(f"segmentos vacíos: {vacios}")
            if tipo == "parte":
                from .config import SEGMENTOS
                faltan = set(SEGMENTOS) - set(seg)
                if faltan:
                    errores.append(f"faltan segmentos: {sorted(faltan)}")
        if not g.get("caption"):
            errores.append("falta caption")
        intro = str((seg or {}).get("intro", "")).strip().lower()
        try:  # "Ojo" vale de vez en cuando, pero no dos veces seguidas
            from datetime import date as _d
            from .guion import aperturas_recientes
            ultima = (aperturas_recientes(_d.today(), 1) or [""])[-1].lower()
        except Exception:  # noqa: BLE001
            ultima = ""
        if intro.split()[:1] and ultima.split()[:1] and intro.split()[0].strip(",:¡!¿?") == ultima.split()[0].strip(",:¡!¿?"):
            errores.append(f'la intro empieza igual que el último vídeo («{ultima}»): varía el arranque')
    return errores


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    orden = sys.argv[1]
    if orden == "pendientes":
        for c in _pendientes():
            print(c)
        return
    clave = sys.argv[2]
    _git("fetch", "-q", "origin", f"pendiente/{clave}")
    prompt = _git("show", "FETCH_HEAD:prompt.txt").stdout
    if orden == "ver":
        print(prompt or f"(no hay pendiente/{clave})")
        return
    g = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    errores = comprobar(clave, g, prompt)
    if errores:
        print("NO VÁLIDO:\n- " + "\n- ".join(errores))
        sys.exit(1)
    print("Válido")
    if orden == "entregar":
        GUIONES.mkdir(exist_ok=True)
        destino = GUIONES / f"{clave}.json"
        destino.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
        _git("pull", "-q", "--rebase", "--autostash")
        _git("add", str(destino), check=True)
        _git("commit", "-q", "-m", f"Guion {clave} (escrito con el plan de Claude)", check=True)
        for _ in range(4):
            if _git("push", "-q").returncode == 0:
                print(f"Entregado: guiones/{clave}.json")
                return
            _git("pull", "-q", "--rebase")
        print("ERROR: no se pudo subir")
        sys.exit(1)


if __name__ == "__main__":
    main()
