"""Control de calidad antes de publicar: comprobaciones medibles sobre el vídeo ya montado y sobre lo que las capas
han ido anotando al dibujar. «grave» = no se publica (queda como artefacto y se avisa); «aviso» = se publica y queda
anotado en el historial y en el registro para corregir la causa.

Cada fallo que encuentre el dueño debe acabar aquí como una regla más (ver guiones/INSTRUCCIONES.md)."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

INCIDENCIAS: list[tuple[str, str]] = []      # (nivel, texto) anotadas por las capas mientras se dibuja
CIUDADES_DIA: dict[int, set] = {}            # vídeos de varios días: ciudades colocadas en el mapa de cada día
QUIETO_AVISO = 20                            # segundos seguidos con el mapa casi sin cambios (solo avisa: los
                                             # bloques por días de los especiales son tranquilos y están bien así)


def anotar(nivel: str, texto: str) -> None:
    if (nivel, texto) not in INCIDENCIAS:
        INCIDENCIAS.append((nivel, texto))
        log.warning("Control (%s): %s", nivel, texto)


def reiniciar() -> None:
    INCIDENCIAS.clear()
    CIUDADES_DIA.clear()


def _movimiento(video: Path):
    """Por cada segundo: fracción del mapa que cambia respecto al segundo anterior, y brillo medio del fotograma."""
    import numpy as np
    w, h = 270, 480
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf", f"fps=1,scale={w}:{h},format=gray",
                        "-f", "rawvideo", "-"], capture_output=True, timeout=600)
    a = np.frombuffer(p.stdout, np.uint8)
    a = a[:len(a) // (w * h) * w * h].reshape(-1, h, w).astype(np.int16)
    if len(a) < 3:
        return [], []
    mapa = a[:, 92:348, :]
    return list((abs(mapa[1:] - mapa[:-1]) > 14).mean(axis=(1, 2))), list(a.mean(axis=(1, 2)))


def revisar(video: Path, dur_min: float = 0, dur_max: float = 0) -> dict:
    """Devuelve {"graves": [...], "avisos": [...]} con todo lo encontrado."""
    graves = [t for n, t in INCIDENCIAS if n == "grave"]
    avisos = [t for n, t in INCIDENCIAS if n != "grave"]
    try:
        mov, brillo = _movimiento(Path(video))
        dur = len(brillo)
        if dur_max and dur > dur_max + 2:
            graves.append(f"dura {dur} s (máximo {dur_max:.0f})")
        if dur_min and dur < dur_min - 2:
            graves.append(f"dura {dur} s (mínimo {dur_min:.0f})")
        negros = sum(1 for b in brillo[1:-1] if b < 6)
        if negros >= 2:
            graves.append(f"{negros} s de pantalla en negro")
        ini, peor = None, (0, 0)
        for k, m in enumerate(mov + [1.0]):
            if m < 0.12:
                ini = k if ini is None else ini
            elif ini is not None:
                if k - ini > peor[0]:
                    peor = (k - ini, ini)
                ini = None
        if peor[0] >= QUIETO_AVISO:
            txt = f"plano casi quieto durante {peor[0]} s (desde el {peor[1] // 60}:{peor[1] % 60:02d})"
            avisos.append(txt)
    except Exception as e:  # noqa: BLE001
        avisos.append(f"no se pudo analizar el vídeo: {e}")
    if len(CIUDADES_DIA) >= 3:   # vídeos de varios días: que el mapa no enseñe siempre las mismas ciudades
        dias = [CIUDADES_DIA[k] for k in sorted(CIUDADES_DIA)]
        comunes, todas = set.intersection(*dias), set.union(*dias)
        if todas and len(comunes) / max(len(s) for s in dias) > 0.85:
            avisos.append(f"el mapa repite casi las mismas ciudades todos los días ({len(comunes)} de "
                          f"{max(len(s) for s in dias)})")
    res = {"graves": graves, "avisos": avisos}
    log.info("Control de calidad: %d graves, %d avisos%s", len(graves), len(avisos),
             "".join(f"\n  · [{'GRAVE' if t in graves else 'aviso'}] {t}" for t in graves + avisos))
    return res


def bloquea(res: dict) -> bool:
    """¿Hay que dejar el vídeo sin publicar? (se puede forzar con OMITIR_CONTROL=1 / «sin-control»)"""
    if res.get("graves") or res.get("avisos"):
        try:
            Path("aviso_control.txt").write_text(
                ("NO PUBLICADO por el control de calidad: " if res.get("graves") and not os.environ.get("OMITIR_CONTROL")
                 else "Publicado con avisos del control de calidad: ")
                + "; ".join(res.get("graves", []) + res.get("avisos", [])), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return bool(res.get("graves")) and not os.environ.get("OMITIR_CONTROL")
