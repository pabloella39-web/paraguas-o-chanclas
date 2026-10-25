"""Descarga el último boletín de avisos CAP de AEMET (España) y lo guarda para estudiarlo."""
import io, json, os, tarfile, requests
clave = os.environ["AEMET_API_KEY"]
r = requests.get("https://opendata.aemet.es/opendata/api/avisos_cap/ultimoelaborado/area/esp",
                 headers={"api_key": clave}, timeout=30)
meta = r.json(); print(meta)
os.makedirs("muestra_avisos", exist_ok=True)
d = requests.get(meta["datos"], timeout=60)
open("muestra_avisos/avisos.tar", "wb").write(d.content)
print("bytes", len(d.content), d.headers.get("content-type"))
try:
    with tarfile.open(fileobj=io.BytesIO(d.content)) as t:
        nombres = t.getnames(); print(len(nombres), nombres[:10])
except Exception as e:
    print("no es tar:", e, d.content[:300])
