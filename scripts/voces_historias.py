"""Busca en la biblioteca de ElevenLabs voces de narrador en español de España y genera una muestra de terror de cada una.

Salida: carpeta muestras/ con NN_nombre.mp3 y voces.json (id, dueño, nombre, descripción).
"""
import json
import os
import re
from pathlib import Path

import requests

API = "https://api.elevenlabs.io/v1"
K = {"xi-api-key": os.environ["ELEVENLABS_API_KEY"].strip()}
OUT = Path("muestras")
OUT.mkdir(exist_ok=True)

TEXTO = ("Nadie en el pueblo quería hablar de la casa del final de la calle. Mi abuela decía que, por las noches, "
         "se oían golpes dentro de las paredes. Tres golpes. Siempre tres. Yo no la creí... hasta la noche en que "
         "me quedé solo en esa casa, y escuché el primero.")

vistos, cand = set(), []
for q in ["narrador", "misterio", "terror", "suspense", "storyteller", "audiolibro", "documental", "narración",
          "intriga", "historias"]:
    for genero in ("male", "female"):
        r = requests.get(f"{API}/shared-voices", headers=K, params={
            "page_size": 50, "language": "es", "search": q, "gender": genero}, timeout=40)
        if r.status_code != 200:
            print("ERR", q, r.status_code, r.text[:200])
            continue
        for v in r.json().get("voices", []):
            if v["voice_id"] in vistos:
                continue
            vistos.add(v["voice_id"])
            txt = " ".join(str(v.get(k) or "") for k in ("accent", "description", "name", "descriptive", "locale"))
            if re.search(r"latin|mexic|argent|colomb|chile|venez|neutro|neutral", txt, re.I):
                continue
            if not re.search(r"spain|peninsular|castil|españa|español de españa|es-es|madrid|iberian", txt, re.I):
                continue
            cand.append(v)

def puntos(v):
    t = (str(v.get("description")) + " " + str(v.get("name")) + " " + str(v.get("use_case"))).lower()
    p = v.get("cloned_by_count") or 0
    for w, b in (("terror", 3), ("misterio", 3), ("suspense", 3), ("narr", 2), ("story", 2), ("profund", 2),
                 ("deep", 2), ("grave", 2), ("audiobook", 1), ("audiolibro", 1)):
        if w in t:
            p *= 1 + b / 4
            p += 500 * b
    return p

cand.sort(key=puntos, reverse=True)
print(f"Candidatas de España: {len(cand)}")
elegidas = []
for v in cand[:14]:
    print(v["voice_id"], v.get("public_owner_id"), v.get("name"), v.get("gender"), v.get("age"), v.get("accent"),
          v.get("use_case"), v.get("cloned_by_count"), (v.get("description") or "")[:120].replace("\n", " "))
for v in cand:
    if len(elegidas) >= 6:
        break
    vid, dueno = v["voice_id"], v.get("public_owner_id")
    # Una voz de la biblioteca hay que añadirla a la cuenta antes de usarla por API
    a = requests.post(f"{API}/voices/add/{dueno}/{vid}", headers=K, json={"new_name": f"HIST {v['name'][:30]}"},
                      timeout=40)
    usar = a.json().get("voice_id", vid) if a.status_code == 200 else vid
    r = requests.post(f"{API}/text-to-speech/{usar}", headers=K, params={"output_format": "mp3_44100_128"}, json={
        "text": TEXTO, "model_id": os.environ.get("ELEVEN_MODEL") or "eleven_v4", "language_code": "es",
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True}},
        timeout=120)
    if r.status_code != 200:
        print("TTS falló", v["name"], r.status_code, r.text[:200])
        continue
    n = len(elegidas) + 1
    nombre = re.sub(r"[^\w]+", "_", v["name"])[:30]
    (OUT / f"{n:02d}_{nombre}.mp3").write_bytes(r.content)
    elegidas.append({"n": n, "voice_id": usar, "original": vid, "nombre": v["name"], "genero": v.get("gender"),
                     "edad": v.get("age"), "acento": v.get("accent"), "descripcion": v.get("description")})
(OUT / "voces.json").write_text(json.dumps(elegidas, ensure_ascii=False, indent=1))
print("Muestras:", [e["nombre"] for e in elegidas])
