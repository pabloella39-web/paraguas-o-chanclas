"""Compara voces femeninas de ElevenLabs con el mismo texto del parte y mide la 'reverberación' de cada una.
Métrica: % de tramos entre palabras con energía residual (colas de eco). Cuanto más bajo, más seca la voz."""
import json, os, subprocess, wave
from pathlib import Path
import numpy as np, requests
K = {"xi-api-key": os.environ["ELEVENLABS_API_KEY"].strip()}
OUT = Path("muestras"); OUT.mkdir(exist_ok=True)
TEXTO = ("Ojo, Málaga: hoy sopla fuerte, con rachas de ochenta kilómetros por hora. Quédate, que al final te digo "
         "dónde hará más calor y más frío. En el norte, lluvia en Bilbao y Santander, con dieciséis grados. "
         "Y tú, ¿hoy eres de paraguas o de chanclas?")
VOCES = {"Anabel (actual)": "7sPWPWuzGi4J8JnaQcQw", "Maite Jimenez": "BXtvkfRgOYGPQKVRgufE",
         "Maia": "jipeLrCHZ6ByxrU2JP9i", "Sofia": "pN4aFdNIp2mvGfTwy1Oj", "Cristina": "6eHm1OlVfyf3wZacL2k3"}
def metrica(wav):
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    sr = 48000; n = int(0.02 * sr)
    e = np.array([np.sqrt(np.mean(x[i:i + n] ** 2)) + 1e-9 for i in range(0, len(x) - n, n)])
    db = 20 * np.log10(e / e.max())
    return round(float(np.mean((db > -45) & (db < -28)) * 100), 1)
res = []
for i, (nombre, vid) in enumerate(VOCES.items(), 1):
    if "actual" not in nombre:  # añadir a la cuenta si es de la biblioteca (si ya está, no pasa nada)
        pass
    for estilo in (0.25,):
        r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}", headers=K,
                          params={"output_format": "mp3_44100_128"},
                          json={"text": TEXTO, "model_id": os.environ.get("ELEVEN_MODEL") or "eleven_v4", "language_code": "es",
                                "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": estilo,
                                                   "use_speaker_boost": True, "speed": 1.05}}, timeout=120)
        if r.status_code != 200:
            print("ERROR", nombre, r.status_code, r.text[:200]); continue
        mp3 = OUT / f"{i:02d}_{nombre.split()[0]}.mp3"; mp3.write_bytes(r.content)
        wav = mp3.with_suffix(".wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "48000", "-ac", "1", str(wav)], check=True)
        m = metrica(wav); wav.unlink()
        res.append({"voz": nombre, "id": vid, "eco": m}); print(f"{nombre}: eco {m}")
(OUT / "eco.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
print("::notice::" + " | ".join(f"{r['voz']}: {r['eco']}" for r in res))
