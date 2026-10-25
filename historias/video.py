"""Montaje de cada parte: fotos tratadas con movimiento lento, grano, parpadeos, subtítulos palabra a palabra y
tarjeta final ("CONTINUARÁ… / FIN")."""
from __future__ import annotations

import logging
import math
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import ALTO, ANCHO, ASSETS, CUENTA, ETIQUETA_TIPO, FPS, NOMBRE, RAIZ

log = logging.getLogger(__name__)
ROJO = (214, 30, 40)
BLANCO = (245, 242, 236)
INICIO_VOZ = 0.25
TARJETA = 3.6
FUNDIDO = 0.9


@lru_cache(maxsize=None)
def fuente(tipo: str, tam: int) -> ImageFont.FreeTypeFont:
    if tipo == "maquina":
        f = ASSETS / "SpecialElite-Regular.ttf"
        if f.exists():
            return ImageFont.truetype(str(f), tam)
        tipo = "Black"
    return ImageFont.truetype(str(RAIZ / "assets" / "fonts" / f"Inter-{tipo}.otf"), tam)


def _ajustar(txt, tipo, tam, ancho):
    f = fuente(tipo, tam)
    while f.getlength(txt) > ancho and tam > 26:
        tam -= 3
        f = fuente(tipo, tam)
    return f


def _partir(txt, f, ancho):
    lineas, act = [], ""
    for w in txt.split():
        p = (act + " " + w).strip()
        if f.getlength(p) > ancho and act:
            lineas.append(act)
            act = w
        else:
            act = p
    return lineas + ([act] if act else [])


class Parte:
    def __init__(self, imagenes: list[Image.Image], palabras: list, voz_dur: float, total: float, *, titulo: str,
                 n: int, de: int, tipo: str, semilla: int = 1, inicios: list[float] | None = None,
                 ambiente: str = ""):
        self.imgs, self.total, self.voz_dur = imagenes, total, voz_dur
        self.titulo, self.n, self.de, self.tipo = titulo, n, de, tipo
        self.palabras = [(a + INICIO_VOZ, b + INICIO_VOZ, w) for a, b, w in palabras]
        self.fin_voz = INICIO_VOZ + voz_dur
        rnd = np.random.default_rng(semilla)
        # Cada foto entra cuando la narración llega al tramo de texto que ilustra (inicios, en s de locución);
        # sin inicios, reparto uniforme. La última sigue bajo la tarjeta final.
        if inicios and len(inicios) == len(imagenes):
            self.inicios = [0.0] + [INICIO_VOZ + x for x in inicios[1:]]
        else:
            paso = max(4.0, self.fin_voz / max(1, len(imagenes)))
            self.inicios = [k * paso for k in range(len(imagenes))]
        self.inicios.append(total + TARJETA)
        self.niebla = self._niebla(rnd)
        self.lluvia = ambiente in ("lluvia", "tormenta")
        self.relampagos = sorted(rnd.uniform(4, max(5, total - 6), size=3)) if ambiente == "tormenta" else []
        self.mov = [(rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.choice([1, -1])) for _ in imagenes]
        self.parpadeos = sorted(rnd.uniform(3, max(4, total - 5), size=max(2, int(total / 14))))
        self.grano = [self._grano(rnd) for _ in range(6)]
        self.capa = self._capa_fija()
        self.negro = Image.new("RGB", (ANCHO, ALTO), (0, 0, 0))
        self.grupos = self._grupos()

    # ------------------------------------------------------------ capas fijas
    def _niebla(self, rnd):
        base = rnd.random((ALTO // 48, ANCHO // 24)).astype(np.float32)
        im = Image.fromarray((base * 255).astype(np.uint8)).resize((ANCHO * 2, ALTO), Image.BICUBIC)
        im = im.filter(ImageFilter.GaussianBlur(40))
        a = np.asarray(im).astype(np.float32) / 255
        alfa = (np.clip(a - 0.35, 0, 1) * 150).astype(np.uint8)
        capa = Image.new("RGBA", (ANCHO * 2, ALTO), (200, 205, 215, 0))
        capa.putalpha(Image.fromarray(alfa))
        return capa

    def _gotas(self, t):
        capa = Image.new("RGBA", (ANCHO, ALTO), (0, 0, 0, 0))
        d = ImageDraw.Draw(capa)
        rnd = np.random.default_rng(int(t * FPS))
        for _ in range(110):
            x, y = rnd.uniform(-100, ANCHO), rnd.uniform(0, ALTO)
            largo = rnd.uniform(40, 90)
            d.line([(x, y), (x + largo * 0.25, y + largo)], fill=(200, 210, 225, int(rnd.uniform(40, 95))), width=2)
        return capa

    def _grano(self, rnd):
        g = rnd.normal(0, 1, (ALTO // 2, ANCHO // 2)).astype(np.float32)
        a = np.clip(np.abs(g) * 14, 0, 34).astype(np.uint8)
        im = Image.fromarray(np.where(g > 0, 255, 0).astype(np.uint8)).convert("RGBA").resize((ANCHO, ALTO))
        im.putalpha(Image.fromarray(a).resize((ANCHO, ALTO)))
        return im

    def _capa_fija(self):
        capa = Image.new("RGBA", (ANCHO, ALTO), (0, 0, 0, 0))
        # viñeta
        y, x = np.ogrid[:ALTO, :ANCHO]
        d = np.sqrt(((x - ANCHO / 2) / (ANCHO * 0.62)) ** 2 + ((y - ALTO / 2) / (ALTO * 0.6)) ** 2)
        vin = np.clip((d - 0.55) * 1.6, 0, 1) ** 1.4 * 235
        capa.putalpha(Image.fromarray(vin.astype(np.uint8)))
        # degradados arriba y abajo para leer los textos
        for y0, y1, a0, a1 in ((0, 520, 200, 0), (1350, ALTO, 0, 215)):
            alfa = np.linspace(a0, a1, y1 - y0).astype(np.uint8)
            banda = Image.new("RGBA", (ANCHO, y1 - y0), (0, 0, 0, 0))
            banda.putalpha(Image.fromarray(np.repeat(alfa[:, None], ANCHO, axis=1)))
            capa.alpha_composite(banda, (0, y0))
        d = ImageDraw.Draw(capa)
        f = fuente("Bold", 30)
        txt = " ".join(NOMBRE)  # espaciado
        d.text((ANCHO // 2, 118), txt, font=f, fill=ROJO + (255,), anchor="mm")
        ft = _ajustar(self.titulo, "maquina", 74, 900)
        for k, ln in enumerate(_partir(self.titulo, ft, 900)[:2]):
            d.text((ANCHO // 2, 190 + k * (ft.size + 8)), ln, font=ft, fill=BLANCO + (255,), anchor="ma",
                   stroke_width=3, stroke_fill=(0, 0, 0, 255))
        pill = f"PARTE {self.n} DE {self.de}"
        fp = fuente("Black", 34)
        w = fp.getlength(pill) + 48
        y = 190 + 2 * (ft.size + 8) + 12 if len(_partir(self.titulo, ft, 900)) > 1 else 190 + ft.size + 30
        etiqueta = ETIQUETA_TIPO.get(self.tipo, "")
        fe = fuente("Bold", 26)
        we = fe.getlength(etiqueta) + 36 if etiqueta else 0
        x0 = ANCHO // 2 - (w + we + 16) // 2
        d.rounded_rectangle([x0, y, x0 + w, y + 58], radius=29, fill=ROJO + (255,))
        d.text((x0 + w / 2, y + 29), pill, font=fp, fill=(255, 255, 255, 255), anchor="mm")
        if etiqueta:
            x1 = x0 + w + 16
            d.rounded_rectangle([x1, y + 6, x1 + we, y + 52], radius=23, outline=(230, 230, 230, 220), width=2)
            d.text((x1 + we / 2, y + 29), etiqueta, font=fe, fill=(230, 230, 230, 255), anchor="mm")
        d.text((ANCHO // 2, ALTO - 70), CUENTA, font=fuente("SemiBold", 26), fill=(200, 200, 200, 170), anchor="mm")
        return capa

    def _grupos(self):
        """Subtítulos: grupos de hasta 3 palabras (cortando en la puntuación)."""
        grupos, act = [], []
        for w in self.palabras:
            act.append(w)
            if len(act) == 3 or w[2][-1:] in ".,;:?!…":
                grupos.append(act)
                act = []
        if act:
            grupos.append(act)
        return grupos

    # ------------------------------------------------------------ fotogramas
    def _foto(self, i: int, t: float) -> Image.Image:
        i = min(i, len(self.imgs) - 1)
        im = self.imgs[i]
        W, H = im.size
        local = max(0.0, t - self.inicios[i] + FUNDIDO)
        p = min(1.0, local / (self.inicios[i + 1] - self.inicios[i] + 2 * FUNDIDO))
        dx, dy, zdir = self.mov[min(i, len(self.mov) - 1)]
        z = 1.0 + 0.07 * (p if zdir > 0 else 1 - p)
        cw, ch = W / 1.18 / z * 1.0, H / 1.18 / z
        cx = W / 2 + dx * (W - cw) / 2 * (p - 0.5)
        cy = H / 2 + dy * (H - ch) / 2 * (p - 0.5)
        caja = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        return im.resize((ANCHO, ALTO), Image.BILINEAR, box=caja)

    def fotograma(self, t: float) -> Image.Image:
        i = max(k for k in range(len(self.imgs)) if self.inicios[k] <= t)
        img = self._foto(i, t)
        if i + 1 < len(self.imgs):
            resto = self.inicios[i + 1] - t
            if resto < FUNDIDO:
                img = Image.blend(img, self._foto(i + 1, t), 1 - resto / FUNDIDO)
        for tr in self.relampagos:  # relámpago
            if 0 <= t - tr < 0.25:
                img = Image.blend(img, Image.new("RGB", (ANCHO, ALTO), (235, 240, 255)), 0.45 * (1 - (t - tr) / 0.25))
        for tp in self.parpadeos:  # parpadeo de luz
            if 0 <= t - tp < 0.35:
                k = t - tp
                img = Image.blend(img, self.negro, 0.55 if k < 0.08 or 0.16 < k < 0.22 else 0.15)
        img = img.convert("RGBA")
        desp = int((t * 22) % ANCHO)  # niebla que se desplaza despacio
        img.alpha_composite(self.niebla.crop((desp, 0, desp + ANCHO, ALTO)))
        if self.lluvia:
            img.alpha_composite(self._gotas(t))
        img.alpha_composite(self.grano[int(t * FPS / 3) % len(self.grano)])  # cambia cada 3 fotogramas
        img.alpha_composite(self.capa)
        d = ImageDraw.Draw(img)
        # Portada / gancho: título enorme los dos primeros segundos
        if t < 2.0:
            a = 1.0 if t < 1.3 else 1 - (t - 1.3) / 0.7
            ov = Image.new("RGBA", (ANCHO, ALTO), (0, 0, 0, int(150 * a)))
            img.alpha_composite(ov)
            d = ImageDraw.Draw(img)
            f = _ajustar(self.titulo, "maquina", 120, 960)
            lineas = _partir(self.titulo, f, 960)
            y = ALTO // 2 - len(lineas) * (f.size + 10) // 2 - 60
            for k, ln in enumerate(lineas):
                d.text((ANCHO // 2, y + k * (f.size + 10)), ln, font=f, fill=BLANCO + (int(255 * a),), anchor="ma",
                       stroke_width=4, stroke_fill=(0, 0, 0, int(255 * a)))
            d.text((ANCHO // 2, y + len(lineas) * (f.size + 10) + 40), f"PARTE {self.n}", font=fuente("Black", 64),
                   fill=ROJO + (int(255 * a),), anchor="ma")
        # Subtítulos
        elif t < self.fin_voz + 0.3:
            g = next((g for g in self.grupos if g[0][0] - 0.05 <= t <= g[-1][1] + 0.25), None)
            if g:
                f = _ajustar(" ".join(w[2] for w in g), "Black", 84, 940)
                txt = " ".join(w[2] for w in g)
                x = (ANCHO - f.getlength(txt)) / 2
                y = 1180
                for w in g:
                    pal = w[2] + " "
                    activo = w[0] - 0.05 <= t <= w[1] + 0.05
                    d.text((x, y), pal, font=f, fill=(ROJO if activo else BLANCO) + (255,), stroke_width=7,
                           stroke_fill=(0, 0, 0, 255))
                    x += f.getlength(pal)
        # Tarjeta final
        if t >= self.fin_voz + 0.2:
            k = min(1.0, (t - self.fin_voz - 0.2) / 0.5)
            img.alpha_composite(Image.new("RGBA", (ANCHO, ALTO), (0, 0, 0, int(200 * k))))
            d = ImageDraw.Draw(img)
            alfa = int(255 * k)
            if self.n < self.de:
                d.text((ANCHO // 2, 760), "CONTINUARÁ...", font=fuente("maquina", 104), fill=BLANCO + (alfa,),
                       anchor="mm")
                d.text((ANCHO // 2, 900), f"La PARTE {self.n + 1} ya está en mi perfil", font=fuente("Bold", 46),
                       fill=ROJO + (alfa,), anchor="mm")
                flecha_y = 1010 + 12 * math.sin(t * 6)
                d.polygon([(ANCHO // 2 - 40, flecha_y), (ANCHO // 2 + 40, flecha_y), (ANCHO // 2, flecha_y + 46)],
                          fill=ROJO + (alfa,))
            else:
                d.text((ANCHO // 2, 760), "FIN", font=fuente("maquina", 150), fill=BLANCO + (alfa,), anchor="mm")
                d.text((ANCHO // 2, 900), "Lunes, miércoles, viernes y finde: historia nueva", font=fuente("Bold", 46),
                       fill=BLANCO + (alfa,), anchor="mm")
                d.text((ANCHO // 2, 975), "Sígueme para no perderte la de mañana", font=fuente("SemiBold", 38),
                       fill=ROJO + (alfa,), anchor="mm")
        return img.convert("RGB")


def renderizar(parte: Parte, audio: Path, salida: Path):
    n = round(parte.total * FPS)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{ANCHO}x{ALTO}",
           "-r", str(FPS), "-i", "-", "-i", str(audio), "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-maxrate", "6M", "-bufsize", "12M",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-t", f"{parte.total:.3f}", "-movflags", "+faststart", str(salida)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k in range(n):
        proc.stdin.write(parte.fotograma(k / FPS).tobytes())
        if k % (FPS * 15) == 0:
            log.info("Render %d/%d", k, n)
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg falló")
