"""Contraste de fuentes: AEMET frente a los modelos (ECMWF, AROME/Météo-France, ICON, GFS vía Open-Meteo) y Google
si hay clave. Saca lo que merece una frase en el guion: dónde no se ponen de acuerdo y dónde coinciden todos."""
from __future__ import annotations

NOMBRE = {"ecmwf_ifs025": "el europeo (ECMWF)", "meteofrance_seamless": "el francés (Météo-France)",
          "icon_seamless": "el alemán (ICON)", "gfs_seamless": "el americano (GFS)"}


def analizar(prev: list[dict]) -> dict:
    """{"dudas": [...], "seguro": [...]} con frases cortas y datos, ordenadas por importancia."""
    dudas, seguro = [], []
    for c in prev:
        k = c.get("contraste") or {}
        ae, mods = k.get("aemet") or {}, {m: v for m, v in (k.get("modelos") or {}).items() if v}
        mm = {m: v["mm"] for m, v in mods.items() if v.get("mm") is not None}
        tx = {m: v["tmax"] for m, v in mods.items() if v.get("tmax") is not None}
        n = c["nombre"]
        if mm:
            mojan = [m for m, v in mm.items() if v >= 1]
            p_ae = ae.get("lluvia")
            if p_ae is not None and p_ae >= 60 and len(mojan) <= len(mm) // 4:
                dudas.append((p_ae, f"{n}: AEMET da un {p_ae:.0f} % de lluvia pero casi ningún modelo la ve "
                                    f"({len(mojan)} de {len(mm)})"))
            elif p_ae is not None and p_ae <= 20 and len(mojan) >= max(2, len(mm) * 3 // 4):
                dudas.append((60, f"{n}: AEMET apenas da lluvia ({p_ae:.0f} %) pero {len(mojan)} de {len(mm)} "
                                  f"modelos sí la ven (hasta {max(mm.values()):.0f} l/m²)"))
            elif 0 < len(mojan) < len(mm) and max(mm.values()) >= 10 and min(mm.values()) < 1:
                secos = [NOMBRE.get(m, m) for m in mm if mm[m] < 1]
                fuerte = max(mm, key=mm.get)
                dudas.append((max(mm.values()), f"{n}: {NOMBRE.get(fuerte, fuerte)} da {mm[fuerte]:.0f} l/m², "
                                                f"pero {' y '.join(secos)} lo {'dejan' if len(secos) > 1 else 'deja'} seco"))
            elif len(mojan) == len(mm) and len(mm) >= 3 and (p_ae is None or p_ae >= 70) and min(mm.values()) >= 5:
                seguro.append((min(mm.values()), f"{n}: AEMET y todos los modelos coinciden en lluvia "
                                                 f"(entre {min(mm.values()):.0f} y {max(mm.values()):.0f} l/m²)"))
        if len(tx) >= 3:
            rango = max(tx.values()) - min(tx.values())
            t_ae = ae.get("tmax")
            dif = None if t_ae is None else t_ae - sorted(tx.values())[len(tx) // 2]
            if rango >= 5:
                dudas.append((rango * 5, f"{n}: los modelos bailan {rango:.0f} grados en la máxima "
                                         f"(de {min(tx.values()):.0f} a {max(tx.values()):.0f})"))
            elif dif is not None and abs(dif) >= 4:
                dudas.append((abs(dif) * 5, f"{n}: AEMET da {t_ae:.0f} grados y los modelos "
                                            f"{'menos' if dif > 0 else 'más'} ({sorted(tx.values())[len(tx) // 2]:.0f})"))
    # una sola duda por ciudad (la más fuerte)
    vistas, unicas = set(), []
    for x in sorted(dudas, key=lambda x: -x[0]):
        ciudad = x[1].split(":")[0]
        if ciudad not in vistas:
            vistas.add(ciudad); unicas.append(x)
    dudas = unicas; seguro.sort(key=lambda x: -x[0])
    return {"dudas": [t for _, t in dudas[:3]], "seguro": [t for _, t in seguro[:2]]}


def texto(prev: list[dict], cuando: str = "hoy") -> str:
    a = analizar(prev)
    if not a["dudas"] and not a["seguro"]:
        return ""
    t = (f"\n\nCONTRASTE DE FUENTES para {cuando} (AEMET frente a los modelos europeo ECMWF, francés Météo-France, "
         "alemán ICON y americano GFS): ")
    if a["dudas"]:
        t += "NO SE PONEN DE ACUERDO en: " + "; ".join(a["dudas"]) + ". "
    if a["seguro"]:
        t += "COINCIDEN TODOS en: " + "; ".join(a["seguro"]) + ". "
    t += ("Si encaja, dedícale UNA frase natural al contraste más llamativo (p. ej. «ojo en Huelva: AEMET lo ve claro, "
          "pero el modelo europeo lo deja seco; mirad el cielo antes de salir» o «aquí no hay duda: todos los modelos "
          "coinciden»). Sin tecnicismos ni listas de modelos; no lo fuerces si el parte ya va lleno.")
    return t
