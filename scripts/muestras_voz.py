"""Muestras de Remy (voz multilingüe) intentando forzar el español de España con <lang xml:lang='es-ES'>."""
import asyncio, inspect, os
import edge_tts
import edge_tts.communicate as ec

TEXTO = ("¿El petróleo por encima de ciento diez dólares y el Ibex aguantando el tipo? Pues así arranca este "
         "miércoles. El Ibex cerró ayer en 19.092 puntos, un 0,3 % más, y lo hizo esquivando las caídas del resto "
         "de Europa. Y ojo al crudo, porque el Brent ya anda por los 110 dólares el barril, algo que acabarás "
         "notando en la gasolinera.")

original = ec.mkssml
print("firma mkssml:", inspect.signature(original))


def con_lang(*args, **kw):
    args = list(args)
    args[-1] = f"<lang xml:lang='es-ES'>{args[-1]}</lang>"
    return original(*args, **kw)


async def main():
    os.makedirs("muestras", exist_ok=True)
    for etiqueta, parche in (("normal", False), ("es-ES", True)):
        ec.mkssml = con_lang if parche else original
        for voz in ("fr-FR-RemyMultilingualNeural", "es-ES-XimenaNeural"):
            ruta = f"muestras/{voz}_{etiqueta}.mp3"
            try:
                await edge_tts.Communicate(TEXTO, voz, rate="+8%").save(ruta)
                print("ok", ruta, os.path.getsize(ruta))
            except Exception as e:
                print("error", ruta, repr(e))
    ec.mkssml = original

asyncio.run(main())
