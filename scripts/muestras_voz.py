"""Genera muestras de voces (edge-tts) con un fragmento del guion económico para elegir la más natural."""
import asyncio, json, os
import edge_tts

TEXTO = ("¿El petróleo por encima de ciento diez dólares y el Ibex aguantando el tipo? Pues así arranca este "
         "miércoles. El Ibex cerró ayer en 19.092 puntos, un 0,3 % más, y lo hizo esquivando las caídas del resto "
         "de Europa, mientras en Wall Street el Dow Jones subía un 1 %. Y ojo al crudo, porque el Brent ya anda "
         "por los 110 dólares el barril, algo que acabarás notando en la gasolinera.")

async def main():
    os.makedirs("muestras", exist_ok=True)
    voces = await edge_tts.list_voices()
    es = [v["ShortName"] for v in voces if v["Locale"].startswith("es-ES")]
    multi = [v["ShortName"] for v in voces if "Multilingual" in v["ShortName"]]
    json.dump({"es-ES": es, "multilingual": multi}, open("muestras/voces.json", "w"), indent=1)
    candidatas = es + [m for m in multi if m.split("-")[2].startswith(("Andrew", "Ava", "Emma", "Brian", "Vivienne",
                                                                        "Remy", "Seraphina", "Florian"))]
    for n, voz in enumerate(candidatas, 1):
        for rate in ("+5%", "+15%"):
            ruta = f"muestras/{n:02d}_{voz}_{rate.replace('+', 'mas')}.mp3"
            try:
                await edge_tts.Communicate(TEXTO, voz, rate=rate).save(ruta)
                print("ok", ruta)
            except Exception as e:
                print("error", voz, e)

asyncio.run(main())
