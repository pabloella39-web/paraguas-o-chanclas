"""Composición del vídeo vertical: mapa animado, tarjetas, subtítulos y atribuciones."""
from __future__ import annotations

import logging
import math
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import mapa
from .config import (ALTO, ANCHO, ATRIBUCION_AEMET, ATRIBUCION_GOOGLE, ATRIBUCION_OPENMETEO, FPS, NOMBRE_CANAL, REGIONES,
                     VISTA_GENERAL)
from .mapa import fuente

log = logging.getLogger(__name__)

MAPA_Y0, MAPA_Y1 = 360, 1400
MAPA_H = MAPA_Y1 - MAPA_Y0
AREA_MARCADORES = (24, 20, 930, MAPA_H - 10)  # relativo al mapa; x<930 deja libre la columna de botones de TikTok
SUB_Y = 1515
TRANSICION = 0.6
# La portada (miniatura con la fecha) solo ocupa los 2 primeros fotogramas: TikTok la usa de miniatura, pero
# el espectador ya ve movimiento y oye la voz desde el primer instante (un segundo quieto = deslizar).
PORTADA_FIJA = PORTADA_FIN = 2 / 30
ACENTO = (255, 196, 45)

PILLS = {"intro": None, "general": "MÁS CALOR Y MÁS FRÍO", "cierre": "¡HASTA MAÑANA!"}


def vista_de(seg):
    if seg in REGIONES and REGIONES[seg]["vista"]:
        return REGIONES[seg]["vista"]
    return VISTA_GENERAL


def foco_de(seg):
    return seg if seg in REGIONES else None


# ---------------------------------------------------------------- utilidades de dibujo
def _ease_back(t):
    t = min(max(t, 0), 1)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _ajustar(txt, peso, tam, ancho):
    f = fuente(peso, tam)
    while f.getlength(txt) > ancho and tam > 20:
        tam -= 2
        f = fuente(peso, tam)
    return f


def _fondo():
    img = Image.new("RGB", (ANCHO, ALTO), mapa.MAR_ARRIBA)
    img.paste(mapa.MAR_ABAJO, (0, MAPA_Y1, ANCHO, ALTO))
    return img


def _fundido_bordes(img_mapa: Image.Image) -> Image.Image:
    """Difumina el borde superior e inferior del mapa con el color de fondo."""
    im = img_mapa.convert("RGBA")
    h = 120
    for color, y0, invert in ((mapa.MAR_ARRIBA, 0, False), (mapa.MAR_ABAJO, MAPA_H - h, True)):
        alfa = np.linspace(255, 0, h) if not invert else np.linspace(0, 255, h)
        capa = Image.new("RGBA", (ANCHO, h), color + (0,))
        capa.putalpha(Image.fromarray(np.repeat(alfa[:, None], ANCHO, axis=1).astype(np.uint8)))
        im.alpha_composite(capa, (0, y0))
    return im.convert("RGB")


def _trocear_subtitulos(texto: str, max_car=30):
    palabras = texto.split()
    trozos, actual = [], []
    for p in palabras:
        prueba = " ".join(actual + [p])
        if actual and (len(prueba) > max_car or re.search(r"[.,;:!?]$", actual[-1]) and len(" ".join(actual)) > 12):
            trozos.append(" ".join(actual))
            actual = [p]
        else:
            actual.append(p)
    if actual:
        trozos.append(" ".join(actual))
    return trozos


class Particulas:
    """Adornos de la estación que caen o flotan por el fondo: hojas (otoño), nieve (invierno), pétalos (primavera)
    y destellos de sol (verano). Sutiles: no tapan datos ni subtítulos."""

    def __init__(self, est: str, semilla: int = 7):
        rnd = np.random.default_rng(semilla)
        self.est = est
        n = {"otono": 16, "invierno": 46, "primavera": 18, "verano": 22}[est]
        self.p = [{"x": rnd.uniform(0, ANCHO), "y": rnd.uniform(0, ALTO), "v": rnd.uniform(40, 110),
                   "amp": rnd.uniform(15, 60), "w": rnd.uniform(0.4, 1.2), "fase": rnd.uniform(0, 6.3),
                   "giro": rnd.uniform(-90, 90), "tipo": int(rnd.integers(0, 4)), "tam": rnd.uniform(0.6, 1.25)}
                  for _ in range(n)]
        self.sprites = {}

    def _sprite(self, tipo, tam_idx, ang_idx):
        k = (tipo, tam_idx, ang_idx)
        if k in self.sprites:
            return self.sprites[k]
        escala = (0.6 + tam_idx * 0.13) * {"otono": 1.8, "primavera": 1.5, "invierno": 1.25}.get(self.est, 1.2)
        s = 3
        if self.est == "otono":
            cols = [(214, 120, 40), (190, 70, 30), (232, 172, 60), (160, 90, 45)]
            W, H = int(46 * escala * s), int(28 * escala * s)
            im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.polygon([(0, H / 2), (W * 0.35, 0), (W, H / 2), (W * 0.35, H)], fill=cols[tipo] + (185,))
            d.line([(0, H / 2), (W, H / 2)], fill=(110, 50, 20, 160), width=s)
        elif self.est == "invierno":
            R = int(8 * escala * s)
            im = Image.new("RGBA", (2 * R, 2 * R), (0, 0, 0, 0))
            ImageDraw.Draw(im).ellipse([0, 0, 2 * R - 1, 2 * R - 1], fill=(255, 255, 255, 190))
        elif self.est == "primavera":
            cols = [(255, 182, 206), (255, 220, 232), (250, 160, 190), (255, 240, 245)]
            W, H = int(30 * escala * s), int(18 * escala * s)
            im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(im).ellipse([0, 0, W - 1, H - 1], fill=cols[tipo] + (190,))
        else:  # verano: destello cálido difuminado
            R = int(14 * escala * s)
            im = Image.new("RGBA", (2 * R, 2 * R), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            for k2 in range(6, 0, -1):
                d.ellipse([R - R * k2 / 6, R - R * k2 / 6, R + R * k2 / 6, R + R * k2 / 6],
                          fill=(255, 214, 110, int(40 + 25 * (6 - k2))))
        im = im.resize((max(1, im.width // s), max(1, im.height // s)), Image.LANCZOS)
        if self.est in ("otono", "primavera"):
            im = im.rotate(ang_idx * 30, expand=True, resample=Image.BICUBIC)
        self.sprites[k] = im
        return im

    COLOR = {"otono": (214, 120, 40), "invierno": (150, 200, 255), "primavera": (250, 150, 190),
             "verano": (255, 196, 45)}

    def fondo(self, img: Image.Image):
        """Bruma del color de la estación en la parte baja + etiqueta con la estación."""
        if getattr(self, "_fondo", None) is None:
            capa = Image.new("RGBA", (ANCHO, ALTO), (0, 0, 0, 0))
            h = ALTO - MAPA_Y1
            alfa = (np.linspace(0, 95, h) ** 1.0).astype(np.uint8)
            banda = Image.new("RGBA", (ANCHO, h), self.COLOR[self.est] + (0,))
            banda.putalpha(Image.fromarray(np.repeat(alfa[:, None], ANCHO, axis=1)))
            capa.alpha_composite(banda, (0, MAPA_Y1))
            from .estacion import NOMBRES
            d = ImageDraw.Draw(capa)
            txt = NOMBRES[self.est]
            f = fuente("Black", 30)
            w = f.getlength(txt) + 74
            d.rounded_rectangle([30, 292, 30 + w, 340], radius=24, fill=(8, 20, 45, 200),
                                outline=self.COLOR[self.est] + (255,), width=3)
            sp = self._sprite(1, 2, 1)
            sp = sp.resize((min(40, sp.width), min(40, sp.height)))
            capa.alpha_composite(sp, (42, 296 + (44 - sp.height) // 2))
            d.text((30 + 58, 316), txt, font=f, fill=self.COLOR[self.est] + (255,), anchor="lm")
            self._fondo = capa
        img.alpha_composite(self._fondo)

    def dibujar(self, img: Image.Image, t: float):
        sube = self.est == "verano"
        for p in self.p:
            y = (p["y"] + (-1 if sube else 1) * p["v"] * t * (0.45 if self.est == "invierno" else 1)) % (ALTO + 80) - 40
            x = (p["x"] + p["amp"] * math.sin(p["w"] * t + p["fase"])) % ANCHO
            ang = int(((p["giro"] * t) % 360) // 30)
            sp = self._sprite(p["tipo"], int((p["tam"] - 0.6) / 0.65 * 5), ang)
            img.paste(sp, (int(x), int(y)), sp)


class Compositor:
    def __init__(self, prev, plan, total, fecha_txt, extremos, titular: str = "", *, datos_seg=None, vistas=None,
                 pills=None, portada_txt=None, capas=None, sin_marcadores=(), fecha=None, estacion_override=None):
        """Opcionales para los vídeos especiales (fin de semana, avisos):
        datos_seg: {bloque: lista de ciudades} para los marcadores de ese bloque (en vez de self.prev).
        vistas: {bloque: (lon0, lon1, lat0, lat1)}. pills: {bloque: texto de la etiqueta}.
        portada_txt: (marca, texto grande, texto pequeño). capas: {bloque: función(img, proyección, dt)} que dibuja
        encima del mapa. sin_marcadores: bloques sin marcadores de ciudades."""
        self.datos_seg = datos_seg or {}
        self.vistas = vistas or {}
        self.pills = {**PILLS, **(pills or {})}
        self.portada_txt = portada_txt
        self.capas = capas or {}
        self.sin_marcadores = set(sin_marcadores)
        from .estacion import estacion
        self.particulas = Particulas(estacion_override or estacion(fecha or __import__("datetime").date.today()))
        self.prev = prev
        self.titular = (titular or "¿PARAGUAS O CHANCLAS?").upper()
        # La intro se dibuja ya sobre la región más relevante (la que va justo después)
        regiones = [p["seg"] for p in plan if p["seg"] in REGIONES]
        self.alias = {"intro": regiones[0]} if regiones else {}
        self.plan = plan  # [{seg, inicio, fin, texto}]
        self.total = total
        self.fecha_txt = fecha_txt.upper()
        self.extremos = extremos
        self._cache_mapa = {}
        self._cache_marc = {}
        self._subs = _subtitulos_karaoke(plan)
        # Ventanas visuales: cada bloque empieza un poco antes que su voz
        self.ventanas = []
        for i, p in enumerate(plan):
            ini = 0 if i == 0 else max(plan[i - 1]["fin"], p["inicio"] - 0.35)
            fin = total if i == len(plan) - 1 else max(p["fin"], plan[i + 1]["inicio"] - 0.35)
            self.ventanas.append((ini, fin, p["seg"]))
        self.cabecera = self._cabecera()

    # ------------------------------------------------ capas estáticas
    def _cabecera(self):
        im = Image.new("RGBA", (ANCHO, MAPA_Y0), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        f1 = fuente("ExtraBold", 34)
        d.text((ANCHO / 2, 150), NOMBRE_CANAL, font=f1, fill=ACENTO, anchor="ma")
        f2 = _ajustar(self.fecha_txt, "Black", 72, 960)
        d.text((ANCHO / 2 + 3, 196 + 4), self.fecha_txt, font=f2, fill=(0, 0, 0, 120), anchor="ma")
        d.text((ANCHO / 2, 196), self.fecha_txt, font=f2, fill=(255, 255, 255), anchor="ma")
        return im

    def _atribucion(self, d):
        fnt = fuente("SemiBold", 22)
        usadas = {x for c in self.prev for x in c.get("fuentes", [])}
        lineas = [txt for nombre, txt in (("AEMET", ATRIBUCION_AEMET), ("Open-Meteo", ATRIBUCION_OPENMETEO),
                                          ("Google", ATRIBUCION_GOOGLE)) if nombre in usadas or "demo" in usadas]
        for i, txt in enumerate(lineas):
            d.text((ANCHO / 2, MAPA_Y1 + 8 + i * 28), txt, font=fnt, fill=(225, 232, 245), anchor="ma")

    def vista_de(self, seg):
        return self.vistas.get(seg) or vista_de(seg)

    def mapa_estatico(self, seg):
        clave = (self.vista_de(seg), foco_de(seg))
        if clave not in self._cache_mapa:
            self._cache_mapa[clave] = _fundido_bordes(mapa.dibujar_mapa(clave[0], ANCHO, MAPA_H, foco=clave[1]))
        return self._cache_mapa[clave]

    def marcadores(self, seg):
        if seg not in self._cache_marc:
            vista = self.vista_de(seg)
            pr = mapa.Proyeccion(vista, ANCHO, MAPA_H)
            if seg in self.sin_marcadores:
                lista, estilo = [], "mini"
            elif seg in self.datos_seg:
                lista, estilo = self.datos_seg[seg], "mini"
            elif seg in ("general", "cierre"):
                lista, estilo = self.prev, "mini"
            elif seg in REGIONES:
                lista, estilo = [c for c in self.prev if c["region"] == seg], "tarjeta"
            else:
                lista, estilo = [], "mini"
            self._cache_marc[seg] = (estilo, mapa.marcadores(lista, pr, estilo, AREA_MARCADORES))
        return self._cache_marc[seg]

    # ------------------------------------------------ fotograma
    def ventana(self, t):
        for i, (a, b, seg) in enumerate(self.ventanas):
            if a <= t < b or i == len(self.ventanas) - 1:
                return i, a, seg
        return 0, 0, self.ventanas[0][2]

    def fotograma(self, t) -> Image.Image:
        i, ini, seg_real = self.ventana(t)
        prev_real = self.ventanas[i - 1][2] if i > 0 else seg_real
        seg, prev_seg = self.alias.get(seg_real, seg_real), self.alias.get(prev_real, prev_real)
        img = _fondo()
        dt = t - ini
        en_trans = self.vista_de(prev_seg) != self.vista_de(seg) and dt < TRANSICION
        if en_trans:
            vista = mapa.interpolar_vista(self.vista_de(prev_seg), self.vista_de(seg), dt / TRANSICION)
            m = _fundido_bordes(mapa.dibujar_mapa(vista, ANCHO, MAPA_H, foco=foco_de(seg), ss=1))
        else:
            m = self.mapa_estatico(seg)
        img.paste(m, (0, MAPA_Y0))
        self.particulas.dibujar(img, t)
        capa = Image.new("RGBA", (ANCHO, ALTO), (0, 0, 0, 0))
        d = ImageDraw.Draw(capa)

        # Marcadores con animación de entrada escalonada (en el gancho no: solo el titular sobre el mapa)
        if not en_trans and seg_real != "intro":
            t_marc = dt - (TRANSICION if self.vista_de(prev_seg) != self.vista_de(seg) else 0.1)
            estilo, items = self.marcadores(seg)
            for k, (im, (x, y), (px, py)) in enumerate(items):
                s = _ease_back((t_marc - k * (0.06 if estilo == "mini" else 0.15)) / 0.35)
                if s <= 0.02:
                    continue
                if estilo == "tarjeta":
                    cx, cy = x + im.width / 2, y + im.height
                    d.line([(cx, MAPA_Y0 + cy), (px, MAPA_Y0 + py)], fill=(255, 255, 255, int(200 * min(s, 1))), width=3)
                    d.ellipse([px - 9, MAPA_Y0 + py - 9, px + 9, MAPA_Y0 + py + 9], fill=(255, 255, 255),
                              outline=(8, 20, 45), width=3)
                w, h = max(1, int(im.width * s)), max(1, int(im.height * s))
                imr = im.resize((w, h), Image.BILINEAR) if (w, h) != im.size else im
                capa.alpha_composite(imr, (int(x + (im.width - w) / 2), int(MAPA_Y0 + y + (im.height - h) / 2)))

        # Capas propias de un bloque (p. ej. zonas con aviso)
        if not en_trans and seg_real in self.capas:
            self.capas[seg_real](capa, mapa.Proyeccion(self.vista_de(seg), ANCHO, MAPA_H), dt)
        # Extremos del día en el bloque general
        if seg_real == "general" and not en_trans:
            self._chips_extremos(capa, d, dt)

        img = img.convert("RGBA")
        self.particulas.fondo(img)
        img.alpha_composite(self.cabecera)
        img.alpha_composite(capa)
        d = ImageDraw.Draw(img)
        self._pill(img, d, seg_real, dt)
        if seg_real == "intro":
            self._intro(img, d, t)
        if seg_real == "cierre":
            self._cierre(img, d, dt)
        self._atribucion(d)
        self._subtitulo(img, d, t)
        if t < PORTADA_FIN:
            # Portada (primer fotograma = miniatura en TikTok) que se desvanece al empezar
            alfa = 1.0 if t < PORTADA_FIJA else 1 - (t - PORTADA_FIJA) / (PORTADA_FIN - PORTADA_FIJA)
            portada = self.portada()
            if alfa < 1:
                portada = portada.copy()
                portada.putalpha(portada.getchannel("A").point(lambda a: int(a * alfa)))
            img.alpha_composite(portada)
        return img.convert("RGB")

    # ------------------------------------------------ portada / miniatura
    def portada(self) -> Image.Image:
        """Miniatura legible en la cuadrícula del perfil (que recorta a 3:4: todo va en la franja central)."""
        if getattr(self, "_portada", None) is not None:
            return self._portada
        im = Image.new("RGBA", (ANCHO, ALTO), (6, 16, 38, 238))
        d = ImageDraw.Draw(im)
        partes = self.fecha_txt.split(" ", 1)  # "MARTES", "20 DE OCTUBRE"
        dia_sem, resto = partes[0], (partes[1] if len(partes) > 1 else "")
        marca = "EL TIEMPO EN ESPAÑA"
        lineas_extra = None
        if self.portada_txt:
            marca, dia_sem, resto = self.portada_txt[:3]
            lineas_extra = self.portada_txt[3] if len(self.portada_txt) > 3 else None
        cy = ALTO / 2
        # Marca
        d.text((ANCHO / 2, cy - 520), marca, font=_ajustar(marca, "ExtraBold", 50, 980), fill=ACENTO, anchor="mm")
        # Fecha enorme
        f1 = _ajustar(dia_sem, "Black", 190, 980)
        d.text((ANCHO / 2 + 5, cy - 340 + 8), dia_sem, font=f1, fill=(0, 0, 0, 150), anchor="mm")
        d.text((ANCHO / 2, cy - 340), dia_sem, font=f1, fill=(255, 255, 255), anchor="mm")
        f2 = _ajustar(resto, "Black", 104, 980)
        d.text((ANCHO / 2, cy - 180), resto, font=f2, fill=(255, 255, 255), anchor="mm")
        # Tiempo dominante del día + extremos
        cuenta = {}
        for c in self.prev:
            cuenta[c["icono"]] = cuenta.get(c["icono"], 0) + 1
        orden = sorted(cuenta, key=lambda k: -cuenta[k])[:2]
        tam = 300
        xs = [ANCHO / 2 - tam / 2] if len(orden) == 1 else [ANCHO / 2 - tam - 20, ANCHO / 2 + 20]
        for x, ic in zip(xs, orden):
            im.alpha_composite(mapa.icono(ic, tam), (int(x), int(cy - 70)))
        if lineas_extra is not None:
            pares = lineas_extra
        else:
            calor, frio = self.extremos["calor"], self.extremos["frio"]
            pares = ((f"MÁX {calor['tmax']}° {calor['nombre'].upper()}", (255, 160, 60)),
                     (f"MÍN {frio['tmin']}° {frio['nombre'].upper()}", (140, 205, 255)))
        for k, (txt, col) in enumerate(pares):
            f = _ajustar(txt, "Black", 64, 960)
            d.text((ANCHO / 2, cy + 300 + k * 86), txt, font=f, fill=col, anchor="mm")
        # Pastilla con la pregunta del canal
        txt = "¿PARAGUAS O CHANCLAS?"
        f3 = fuente("Black", 54)
        w = f3.getlength(txt) + 70
        d.rounded_rectangle([ANCHO / 2 - w / 2, cy + 470, ANCHO / 2 + w / 2, cy + 560], radius=45, fill=ACENTO)
        d.text((ANCHO / 2, cy + 515), txt, font=f3, fill=(15, 25, 50), anchor="mm")
        self._portada = im
        return im

    def _pill(self, img, d, seg, dt):
        txt = self.pills.get(seg, REGIONES.get(seg, {}).get("titulo"))
        if not txt:
            return
        f = fuente("Black", 40)
        w = f.getlength(txt) + 60
        s = _ease_back(dt / 0.3)
        x0 = ANCHO / 2 - w / 2 * s
        d.rounded_rectangle([x0, 286, ANCHO / 2 + w / 2 * s, 344], radius=29, fill=ACENTO)
        if s > 0.7:
            d.text((ANCHO / 2, 316), txt, font=f, fill=(15, 25, 50), anchor="mm")

    def _chips_extremos(self, capa, d, dt):
        a = min(1, max(0, (dt - 1.2) / 0.4))
        if a <= 0:
            return
        f1, f2 = fuente("ExtraBold", 26), fuente("Black", 34)
        for i, (etq, c, valor, col) in enumerate((
                ("MÁS CALOR", self.extremos["calor"]["nombre"], f"{self.extremos['calor']['tmax']}°", (255, 140, 60)),
                ("MÁS FRÍO", self.extremos["frio"]["nombre"], f"{self.extremos['frio']['tmin']}°", (120, 190, 255)))):
            x0 = 40 + i * 450
            y0 = MAPA_Y0 + 8
            d.rounded_rectangle([x0, y0, x0 + 420, y0 + 64], radius=20, fill=(8, 20, 45, int(220 * a)),
                                outline=col + (int(255 * a),), width=3)
            d.text((x0 + 20, y0 + 32), etq, font=f1, fill=col + (int(255 * a),), anchor="lm")
            d.text((x0 + 400, y0 + 32), f"{c} {valor}", font=_ajustar(f"{c} {valor}", "Black", 34, 230),
                   fill=(255, 255, 255, int(255 * a)), anchor="rm")

    def _intro(self, img, d, t):
        """Gancho: titular grande sobre la zona más relevante + promesa de lo que llega al final."""
        banda = Image.new("RGBA", (ANCHO, 330), (0, 0, 0, 0))
        alfa = np.linspace(215, 0, 330).astype(np.uint8)
        banda.putalpha(Image.fromarray(np.repeat(alfa[:, None], ANCHO, axis=1)))
        banda = Image.composite(Image.new("RGBA", banda.size, (5, 12, 30, 255)), banda, banda.getchannel("A"))
        img.alpha_composite(banda, (0, MAPA_Y0))
        d = ImageDraw.Draw(img)
        palabras = self.titular.split()
        lineas = [self.titular] if len(self.titular) <= 16 or len(palabras) < 2 else \
            [" ".join(palabras[:(len(palabras) + 1) // 2]), " ".join(palabras[(len(palabras) + 1) // 2:])]
        for k, txt in enumerate(lineas):
            s = _ease_back((t - 0.05 - k * 0.12) / 0.35)
            if s <= 0.02:
                continue
            f = _ajustar(txt, "Black", max(10, int(112 * s)), int(980 * max(s, 0.1)))
            y = MAPA_Y0 + 95 + k * 120
            d.text((ANCHO / 2 + 4, y + 6), txt, font=f, fill=(0, 0, 0, 160), anchor="mm")
            d.text((ANCHO / 2, y), txt, font=f, fill=(255, 255, 255) if k == 0 and len(lineas) > 1 else ACENTO,
                   anchor="mm")
        s = _ease_back((t - 0.9) / 0.4)
        if s > 0.02:
            txt = self.pills.get("promesa") or "QUÉDATE: AL FINAL, DÓNDE HARÁ MÁS CALOR Y MÁS FRÍO"
            f = _ajustar(txt, "ExtraBold", int(34 * min(s, 1.2)), 960)
            w = f.getlength(txt) + 50
            y = MAPA_Y0 + 95 + len(lineas) * 120 - 10
            d.rounded_rectangle([ANCHO / 2 - w / 2, y - 30, ANCHO / 2 + w / 2, y + 30], radius=30,
                                fill=(255, 255, 255, 235))
            d.text((ANCHO / 2, y), txt, font=f, fill=(15, 25, 50), anchor="mm")

    def _cierre(self, img, d, dt):
        s = _ease_back((dt - 0.4) / 0.4)
        if s <= 0.02:
            return
        w, h = 800 * s, 300 * s
        cx, cy = ANCHO / 2, MAPA_Y0 + MAPA_H - 220
        d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=36 * s, fill=ACENTO)
        if s > 0.8:
            oscuro = (15, 25, 50)
            d.text((cx, cy - 78), "¿PARAGUAS O CHANCLAS?", font=fuente("Black", 50), fill=oscuro, anchor="mm")
            d.text((cx, cy - 18), "¡Dímelo en comentarios!", font=fuente("ExtraBold", 42),
                   fill=oscuro, anchor="mm")
            d.line([(cx - 300, cy + 26), (cx + 300, cy + 26)], fill=(15, 25, 50, 90), width=3)
            d.text((cx, cy + 74), "Sígueme · el tiempo de cada día", font=fuente("ExtraBold", 38), fill=oscuro,
                   anchor="mm")

    def _subtitulo(self, img, d, t):
        """Frase corta en pantalla con la palabra que se está diciendo resaltada (estilo karaoke)."""
        trozo = next((c for c in self._subs if c["ini"] <= t < c["fin"]), None)
        if not trozo:
            return
        palabras = trozo["palabras"]
        txt = " ".join(w for _, _, w in palabras)
        f = _ajustar(txt, "Black", 62, 900)
        lineas = [palabras]
        if f.size < 50 and len(palabras) > 2:
            mitad = (len(palabras) + 1) // 2
            lineas = [palabras[:mitad], palabras[mitad:]]
            f = _ajustar(max((" ".join(w for _, _, w in l) for l in lineas), key=len), "Black", 62, 900)
        actual = max((k for k, (a, _, _) in enumerate(palabras) if a <= t), default=0)
        alto = len(lineas) * (f.size + 16)
        anchomax = max(f.getlength(" ".join(w for _, _, w in l)) for l in lineas) * 1.04
        d.rounded_rectangle([ANCHO / 2 - anchomax / 2 - 30, SUB_Y - 20, ANCHO / 2 + anchomax / 2 + 30,
                             SUB_Y + alto + 8], radius=28, fill=(0, 0, 0, 175))
        k_global = 0
        espacio = f.getlength(" ") * 1.5   # algo más de aire para que el resaltado no pegue las palabras
        for n, l in enumerate(lineas):
            ancho_linea = sum(f.getlength(w) for _, _, w in l) + espacio * (len(l) - 1)
            x = ANCHO / 2 - ancho_linea / 2
            y = SUB_Y + n * (f.size + 16)
            for _, _, palabra in l:
                ancho = f.getlength(palabra)
                if k_global == actual:
                    d.rounded_rectangle([x - 5, y - 2, x + ancho + 5, y + f.size + 10], radius=12, fill=ACENTO)
                    d.text((x, y), palabra, font=f, fill=(15, 25, 50))
                else:
                    d.text((x, y), palabra, font=f, fill=(255, 255, 255))
                x += ancho + espacio
                k_global += 1


def _palabras_aproximadas(p) -> list:
    """Si la voz no trae marcas de tiempo por palabra, se reparten según la longitud de cada palabra."""
    pal = p["texto"].split()
    pesos = [len(w) + 2 for w in pal]
    dur, t, out = p["fin"] - p["inicio"], p["inicio"], []
    for w, pe in zip(pal, pesos):
        dd = dur * pe / sum(pesos)
        out.append((t, t + dd, w))
        t += dd
    return out


def _subtitulos_karaoke(plan) -> list[dict]:
    """Agrupa las palabras en frases cortas (máx. ~26 caracteres, corte en signos de puntuación)."""
    trozos = []
    for p in plan:
        palabras = p.get("palabras") or _palabras_aproximadas(p)
        actual = []
        for w in palabras:
            prueba = " ".join(x[2] for x in actual + [w])
            if actual and (len(prueba) > 26 or re.search(r"[.,;:!?]$", actual[-1][2])):
                trozos.append(actual)
                actual = [w]
            else:
                actual.append(w)
        if actual:
            trozos.append(actual)
    out = []
    for i, tr in enumerate(trozos):
        fin = trozos[i + 1][0][0] if i + 1 < len(trozos) else tr[-1][1] + 0.4
        if fin - tr[-1][1] > 0.6:  # pausa larga: el texto no se queda colgado
            fin = tr[-1][1] + 0.3
        out.append({"ini": tr[0][0] - 0.05, "fin": fin, "palabras": tr})
    return out


def renderizar(comp: Compositor, audio: Path, salida: Path, total: float):
    n = round(total * FPS)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{ANCHO}x{ALTO}",
           "-r", str(FPS), "-i", "-", "-i", str(audio),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
           "-t", f"{total:.3f}", "-movflags", "+faststart", str(salida)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k in range(n):
        proc.stdin.write(comp.fotograma(k / FPS).tobytes())
        if k % (FPS * 10) == 0:
            log.info("Render %d/%d", k, n)
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg falló al codificar el vídeo")
