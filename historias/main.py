"""Historia del día para "Lo que Callan las Paredes".

python -m historias.main [--publicar] [--prueba] [--demo] [--fecha AAAA-MM-DD]
  --publicar  genera las 2-3 partes y las deja programadas en TikTok (Upload-Post): primero la última parte y la
              PARTE 1 a las 21:00, para que en el perfil queden en orden de arriba abajo.
  --prueba    genera de verdad pero no publica (los vídeos quedan en la rama pruebas-historias).
  --demo      sin red ni créditos (texto de relleno, voz muda, fondos generados).
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from . import guion, locucion, medios
from .config import (DURACION_MIN_PARTE, HISTORIAL, HORA_PARTE_1, RAIZ, SEPARACION_MIN, VOZ_OBJETIVO, voz)
from .video import INICIO_VOZ, TARJETA, Parte, renderizar

log = logging.getLogger("historias")
TZ = ZoneInfo("Europe/Madrid")
CARACTERES_PARTE_DIARIO = 1100   # lo que gasta el parte del tiempo cada día (tiene prioridad)
HASHTAGS = ["#terror", "#historiasdeterror", "#misterio", "#suspense", "#relatos", "#parati"]


def _wav(datos: np.ndarray, ruta: Path):
    import wave
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(medios.SR)
        w.writeframes((np.clip(datos, -1, 1) * 32767).astype(np.int16).tobytes())


def _leer(ruta: Path) -> np.ndarray:
    import wave
    with wave.open(str(ruta)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def mezclar(voz_wav: Path, total: float, ambiente: str, semilla: int, cliffhanger: bool, salida: Path):
    SR = medios.SR
    n = int(total * SR)
    v = np.zeros(n, np.float32)
    d = _leer(voz_wav)
    i = int(INICIO_VOZ * SR)
    v[i:i + len(d)] = d[: n - i]
    env = np.convolve(np.abs(v), np.ones(int(0.3 * SR)) / int(0.3 * SR), mode="same")
    hay_voz = np.convolve((env > 0.012).astype(np.float32), np.ones(int(0.4 * SR)) / int(0.4 * SR), mode="same")
    m = medios.musica(total, semilla)
    a = medios.ambiente(ambiente, total)
    mezcla = v.copy()
    if m is not None:
        mezcla += m[:n] * (0.20 - 0.09 * hay_voz)
    mezcla += a[:n] * (0.30 - 0.12 * hay_voz)
    fin_voz = INICIO_VOZ + len(d) / SR
    g = medios.golpe() if cliffhanger else None
    if g is not None:
        j = int((fin_voz + 0.15) * SR)
        trozo = g[: max(0, n - j)]
        mezcla[j:j + len(trozo)] += trozo * 0.9
    fo = int(1.2 * SR)
    mezcla[-fo:] *= np.linspace(1, 0, fo)
    pico = np.max(np.abs(mezcla)) or 1
    _wav(mezcla / max(1.0, pico / 0.95), salida)


def horas_publicacion(n: int, ahora: datetime) -> list[datetime]:
    """Devuelve la hora de cada parte (índice 0 = parte 1). La última parte sale primero."""
    p1 = ahora.replace(hour=HORA_PARTE_1[0], minute=HORA_PARTE_1[1], second=0, microsecond=0)
    primera = p1 - timedelta(minutes=SEPARACION_MIN * (n - 1))
    minimo = ahora + timedelta(minutes=15)
    if primera < minimo:
        p1 += minimo - primera
    return [p1 - timedelta(minutes=SEPARACION_MIN * k) for k in range(n)]


def caption(h: dict, k: int, n: int) -> str:
    sig = (f"👉 La PARTE {k + 1} ya está en mi perfil" if k < n else "🔚 Final. ¿Te perdiste el principio? Parte 1 en mi perfil")
    aviso = {"real": "Caso real narrado con voz generada por IA.", "leyenda": "Leyenda popular dramatizada. Voz IA.",
             "ficcion": "Relato de ficción. Voz generada por IA."}[h["tipo"]]
    extra = {"real": ["#casoreal", "#truecrime"], "leyenda": ["#leyendas", "#leyendasurbanas"],
             "ficcion": ["#creepypasta", "#historiasdemiedo"]}[h["tipo"]]
    tags = list(dict.fromkeys(HASHTAGS + extra + [t if t.startswith("#") else "#" + t for t in h.get("hashtags", [])]))
    return (f"{h['caption']}\n\n📖 {h['titulo'].title()} · Parte {k}/{n}\n{sig}\n{aviso}\n\n"
            + " ".join(tags[:12]))[:2200]


def construir(hoy: date, salida: Path, demo: bool) -> dict:
    salida.mkdir(parents=True, exist_ok=True)
    trabajo = Path(tempfile.mkdtemp())
    gratis = demo
    if not demo:
        restante = locucion.creditos_restantes()
        dias = 31 - hoy.day + 1
        necesarios = 3 * 1250 + CARACTERES_PARTE_DIARIO * dias
        if restante is not None and restante < necesarios:
            log.warning("Quedan %d créditos de ElevenLabs y el parte necesita reservarlos: voz gratuita hoy", restante)
            print(f"::warning::Historias con voz gratuita: quedan {restante} créditos de ElevenLabs")
            gratis = True
    pps = locucion.ritmo(voz())
    palabras = int(round(pps * (sum(VOZ_OBJETIVO) / 2)))
    h = guion.historia_demo() if demo else guion.escribir(hoy, palabras)
    v = voz(h.get("narrador", "hombre"), hoy)
    log.info("Narrador: %s → voz %s", h.get("narrador", "hombre"), v)
    n = len(h["partes"])
    usadas: set = set()
    semilla = medios.clave_estable(h["titulo"], hoy)
    videos = []
    for k, p in enumerate(h["partes"], 1):
        base = trabajo / f"parte{k}"
        if demo:
            dur = len(p["texto"].split()) / 2.3
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"anullsrc=r={medios.SR}:cl=mono", "-t", f"{dur:.2f}", str(base) + ".wav"], check=True)
            ws = p["texto"].split()
            pal = [(dur * i / len(ws), dur * (i + 1) / len(ws), w) for i, w in enumerate(ws)]
            wav = Path(str(base) + ".wav")
        elif gratis:
            wav, dur, pal = locucion.narrar_gratis(p["texto"], base)
        else:
            try:
                wav, dur, pal = locucion.narrar(p["texto"], v, base)
            except Exception as e:  # noqa: BLE001
                log.warning("ElevenLabs falló (%s): voz gratuita", e)
                wav, dur, pal = locucion.narrar_gratis(p["texto"], base)
        # Mínimo 1:05 por parte: si la voz se queda corta se ralentiza un poco (máx. 8 %)
        minimo_voz = DURACION_MIN_PARTE - TARJETA - INICIO_VOZ + 0.3
        if dur < minimo_voz:
            f = max(0.92, dur / minimo_voz)
            lenta = base.with_name(base.name + "_lenta.wav")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", f"atempo={f:.4f}",
                            str(lenta)], check=True)
            pal = [(a / f, b / f, w) for a, b, w in pal]
            wav, dur = lenta, locucion.duracion(lenta)
        total = round(max(DURACION_MIN_PARTE + 0.4, INICIO_VOZ + dur + TARJETA), 2)
        imgs = [] if demo else medios.imagenes_para(p["escenas"], h["tipo"], usadas)
        while len(imgs) < 4:
            imgs.append(medios.fondo_procedural(semilla + len(imgs) + 10 * k, h["tipo"]))
        audio = trabajo / f"mezcla{k}.wav"
        mezclar(wav, total, p["ambiente"], semilla + k, k < n, audio)
        video = salida / f"historia_{hoy.isoformat()}_parte{k}.mp4"
        parte = Parte(imgs, pal, dur, total, titulo=h["titulo"], n=k, de=n, tipo=h["tipo"], semilla=semilla + k)
        log.info("Parte %d/%d: %.1f s de voz, %.1f s de vídeo, %d imágenes", k, n, dur, total, len(imgs))
        renderizar(parte, audio, video)
        real = locucion.duracion(video)
        if real < DURACION_MIN_PARTE:
            raise RuntimeError(f"La parte {k} dura {real:.1f} s (< {DURACION_MIN_PARTE})")
        videos.append({"parte": k, "video": str(video), "duracion": real, "caption": caption(h, k, n)})
    return {"fecha": hoy.isoformat(), "titulo": h["titulo"], "tipo": h["tipo"], "pregunta": h.get("pregunta"),
            "resumen": h["partes"][0]["texto"][:160], "voz": "gratuita" if gratis else v, "partes": videos,
            "guion": h}


def publicar(meta: dict, ya: bool = False) -> list:
    """ya=True: se publican al momento (de la última parte a la primera, una tras otra)."""
    from tiempo import uploadpost
    ahora = datetime.now(TZ)
    n = len(meta["partes"])
    horas = [None] * n if ya else horas_publicacion(n, ahora)
    res = []
    for p in sorted(meta["partes"], key=lambda x: -x["parte"]):  # de la última a la primera
        cuando = horas[p["parte"] - 1]
        r = uploadpost.publicar_tiktok(Path(p["video"]), p["caption"], "historias", programado=cuando,
                                       primer_comentario=meta.get("pregunta"))
        p["publicacion"] = r
        res.append(r)
        print(f"::notice::Parte {p['parte']}/{n} " + (f"programada para las {cuando:%H:%M}" if cuando else
                                                         f"publicada: {str(r)[:150]}"))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--publicar", action="store_true")
    ap.add_argument("--prueba", action="store_true")
    ap.add_argument("--ya", action="store_true", help="con --publicar: publicar al momento en vez de programar")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--fecha")
    ap.add_argument("--salida", default=str(RAIZ / "salida_historias"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    hoy = date.fromisoformat(a.fecha) if a.fecha else datetime.now(TZ).date()
    HISTORIAL.mkdir(exist_ok=True)
    hist = HISTORIAL / f"{hoy.isoformat()}.json"
    if a.publicar and hist.exists():
        log.info("La historia de hoy ya está hecha")
        return
    meta = construir(hoy, Path(a.salida), a.demo)
    (Path(a.salida) / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.publicar:
        publicar(meta, a.ya)
        hist.write_text(json.dumps({k: v for k, v in meta.items() if k != "guion"}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"::notice::Historia: {meta['titulo']} ({meta['tipo']}), {len(meta['partes'])} partes: "
          + ", ".join(f"{p['duracion']:.1f} s" for p in meta["partes"]))


if __name__ == "__main__":
    main()
