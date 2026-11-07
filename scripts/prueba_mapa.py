"""Genera assets/nucleos.json: núcleos de población de España (GeoNames, CC BY 4.0) con más de 800 habitantes."""
import io
import json
import urllib.request
import zipfile
from pathlib import Path

datos = urllib.request.urlopen("https://download.geonames.org/export/dump/ES.zip", timeout=120).read()
z = zipfile.ZipFile(io.BytesIO(datos))
out = []
with z.open("ES.txt") as f:
    for linea in io.TextIOWrapper(f, encoding="utf-8"):
        c = linea.rstrip("\n").split("\t")
        if c[6] != "P" or c[7] not in ("PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC"):
            continue
        pob = int(c[14] or 0)
        if pob < 800:
            continue
        out.append([c[1], round(float(c[4]), 4), round(float(c[5]), 4), pob])
out.sort(key=lambda x: -x[3])
Path("prueba").mkdir(exist_ok=True)
Path("prueba/nucleos.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(len(out), out[:5])
print([x for x in out if 27.9 < x[1] < 28.7 and -17.5 < x[2] < -16][:30])
