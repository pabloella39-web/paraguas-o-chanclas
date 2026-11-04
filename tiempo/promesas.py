"""La promesa del final ("quédate, que al final..."), variada para que no suene siempre igual.

Cada día toca una fórmula distinta (rotación por fecha); el «quédate» solo sale de vez en cuando.
"""
from __future__ import annotations

from datetime import date

# (frase de ejemplo para el guion, texto de la pastilla en pantalla)
PROMESAS = {
    "parte": [
        ("Y lo más caluroso y lo más frío de España, te lo guardo para el final.", "AL FINAL: LO MÁS CALUROSO Y LO MÁS FRÍO"),
        ("Al final, el sitio donde más vas a tiritar mañana.", "AL FINAL: EL RINCÓN MÁS FRÍO"),
        ("Y aguanta, que al final va el sitio más caluroso de mañana.", "AL FINAL: EL SITIO MÁS CALUROSO"),
        ("Al final te cuento dónde sobra la chaqueta y dónde hace falta el abrigo.", "AL FINAL: ¿CHAQUETA O ABRIGO?"),
        ("Y atento al final: de la punta más fría a la más caliente de España.", "ATENTO AL FINAL: EL GRAN CONTRASTE"),
        ("Y no te vayas sin ver qué ciudad se lleva el frío de mañana.", "NO TE VAYAS: LA CIUDAD MÁS FRÍA"),
        ("Lo más extremo de mañana, en calor y en frío, al final del vídeo.", "LO MÁS EXTREMO, AL FINAL"),
        ("Quédate, que al final te digo dónde hará más calor y más frío.", "QUÉDATE: AL FINAL, MÁS CALOR Y MÁS FRÍO"),
    ],
    "finde": [
        ("Y al final, dónde está el mejor plan del finde.", "AL FINAL: EL MEJOR PLAN DEL FINDE"),
        ("Te guardo para el final dónde toca terraza y dónde toca sofá.", "AL FINAL: ¿TERRAZA O SOFÁ?"),
        ("Al final, el sitio con el mejor tiempo del finde.", "EL MEJOR SITIO DEL FINDE, AL FINAL"),
        ("Quédate, que al final te digo dónde merece la pena salir.", "QUÉDATE: AL FINAL, DÓNDE SALIR"),
        ("Y atento al final: ahí va el mejor plan del finde.", "ATENTO AL FINAL: EL MEJOR PLAN"),
    ],
    "semana": [
        ("Y al final, el mejor y el peor día de la semana.", "AL FINAL: EL MEJOR Y EL PEOR DÍA"),
        ("Te guardo para el final qué día tender la ropa y cuál no.", "AL FINAL: ¿QUÉ DÍA TENDER?"),
        ("Al final te digo qué día merece la pena salir y cuál quedarse en casa.", "AL FINAL: EL DÍA BUENO Y EL MALO"),
        ("Y atento al final: el día que más te va a fastidiar.", "ATENTO AL FINAL: EL PEOR DÍA"),
        ("Quédate, que al final va el mejor día y el peor.", "QUÉDATE: EL MEJOR Y EL PEOR DÍA"),
    ],
}


def _de(tipo: str, hoy: date) -> tuple[str, str]:
    lista = PROMESAS[tipo]
    return lista[hoy.toordinal() % len(lista)]


def pill(tipo: str, hoy: date | None = None) -> str:
    return _de(tipo, hoy or date.today())[1]


def nota(tipo: str, hoy: date | None = None) -> str:
    """Instrucción para el prompt: la fórmula de hoy, como inspiración, y qué no repetir."""
    hoy = hoy or date.today()
    frase = _de(tipo, hoy)[0]
    ayer = _de(tipo, date.fromordinal(hoy.toordinal() - 1))[0]
    return (f"PROMESA DEL FINAL: no uses siempre «quédate hasta el final»; hoy toca algo en la línea de «{frase}» "
            f"(adáptalo con tus palabras y a los datos; puede ir en la segunda frase o al cerrar la intro). "
            f"No repitas la de ayer («{ayer}»)"
            + ("" if "Quédate" in frase else " y hoy NO uses la palabra «quédate»") + ".")
