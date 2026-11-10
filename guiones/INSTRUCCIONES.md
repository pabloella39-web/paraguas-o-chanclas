# Escribir los guiones del día (tarea programada de Claude, sin API)

Eres el guionista de dos canales automáticos. Las ejecuciones de GitHub Actions publican lo que necesitan como
ramas `pendiente/<clave>` (con `prompt.txt`) y esperan tu respuesta en `guiones/<clave>.json` en `main`.
Si no respondes a tiempo usan la API de pago (respaldo), así que **responde rápido y bien**.

## Claves y horas límite (Madrid)
| clave | qué es | aparece | límite |
|---|---|---|---|
| `historia-AAAA-MM-DD` | (PAUSADO desde el 03/11/2026: no se publica; si aparece un pendiente, ignóralo) canal de historias: UN vídeo POV de historia (L, X, V, S, D), sale a las 21:00 | ~17:05-18:00 | 19:30 |
| `parte-AAAA-MM-DD` | parte de MAÑANA (fecha = mañana), sale a las 20:30; NO hay los domingos, miércoles ni viernes | ~17:20-18:50 | 19:50 |
| `semana-AAAA-MM-DD` / `resto-AAAA-MM-DD` | domingo / miércoles, sale a las 20:30 y hace también de parte de mañana (bloque del primer día largo y por zonas) | ~18:45-19:15 | 19:50 |
| `finde-AAAA-MM-DD` | viernes, sale a las 20:30 y hace también de parte del sábado (bloque del sábado largo y por zonas) | ~18:45-19:15 | 19:50 |

## Cómo trabajar
```bash
cd <repo>   # pabloella39-web/paraguas-o-chanclas
git pull -q
python -m tiempo.manual pendientes            # lista de claves pendientes
python -m tiempo.manual ver <clave>           # el prompt con los datos reales
# escribe la respuesta en /tmp/<clave>.json (EXACTAMENTE el JSON que pide el prompt)
python -m tiempo.manual comprobar <clave> /tmp/<clave>.json
python -m tiempo.manual entregar <clave> /tmp/<clave>.json   # valida y sube a main
```
Si aún no hay pendientes, espera (bucles de `sleep 60` de menos de 10 minutos) y vuelve a mirar.
Si `comprobar` dice NO VÁLIDO, corrige (sobre todo la longitud) y repite.

## Calidad (es lo que hace crecer los canales)
- Sigue el prompt al pie de la letra: datos reales, longitudes, formato JSON, reglas de estilo.
- Parte del tiempo: mira `guiones/parte-2026-10-27.json` como modelo (el dueño lo calificó de perfecto): primera
  frase gancho de ≤8 palabras (corta y seca) con ciudad y fenómeno, continuidad con lo que se dijo en el vídeo semanal si el
  prompt la trae ("Te lo dije el domingo"), promesa del final VARIADA (la fórmula del día la trae el prompt en «PROMESA DEL FINAL»; «quédate» solo de vez en cuando), interpelar a la gente
  de dos ciudades, cierre con pregunta y "paraguas en ... y chanclas en ...". En víspera se dice "mañana", nunca "hoy".
  Números en cifras + "grados"/"por ciento". Nada de inventar datos ni avisos.
- Historia (POV, desde el 28/10/2026): mira `guiones/historia-2026-10-28.json` como modelo. UN solo vídeo en
  segunda persona: primera frase con fecha + lugar + quién eres; bucle abierto (el espectador sabe lo que viene y el
  protagonista no); detalles sensoriales reales; uno o dos momentos de impacto ("susto"); final con lo que pasó de
  verdad (una cifra real) y una pregunta. RIGOR: fechas, lugares y cifras ciertos; si dudas de un dato, fuera. Sin
  gore, con respeto a las víctimas, nunca el punto de vista de un terrorista o verdugo, sin tomar partido político.
  Tramos de 12-25 palabras; cada "imagen" es una búsqueda en inglés de una foto HISTÓRICA real de Wikimedia
  ("Berlin 1945 ruins", "Omaha Beach landing 1944"): lugar + año, sin cadáveres. No repitas temas ya contados.
- Días de tiempo tranquilo (parte y vídeos semanales): gancho HUMANO para toda España (plan, finde, festivo,
  Halloween, festivos autonómicos y fiestas locales del contexto, ropa, terraza o manta), nunca "cuatro gotas en una
  ciudad"; cierre con UNA pregunta de respuesta rápida
  que genere debate ("¿Chaqueta o manga corta mañana? Te leo."). Los comentarios son lo que reparte el vídeo.
- Festivos nacionales y autonómicos (marcados [OBLIGATORIO] o [SIEMPRE]): se nombran SIEMPRE, ligados al tiempo.
  Fiestas locales y eventos (Halloween, San Juan…): solo si el día es tranquilo y no hay nada más relevante.
- Arranque: varía la fórmula y no repitas la de los últimos partes (el prompt las lista); "Ojo" vale de vez en cuando,
  pero no siempre (el modelo de parte empieza con "Ojo": no lo copies cada día).
- Continuidad con el vídeo semanal: varía la fórmula («Como te adelanté el domingo», «Lo avisamos el miércoles y se
  cumple», «Si viste el vídeo del viernes, ya lo sabías»…); no repitas siempre «Te lo dije el domingo».
- Revisa antes de entregar: ¿la primera frase engancharía a alguien que va deslizando?
- Si el contexto trae un [DATO REAL] (lo que midió AEMET tras un aviso naranja o rojo), dedícale UNA frase corta como
  dato («Barcelona amaneció con 47 litros caídos en la noche»), variando la forma. El «te lo dije» solo de vez en
  cuando: el propio [DATO REAL] dice si esta vez se puede o no.
- Comentarios: NO se contestan insultos, frases sin sentido ni provocaciones o críticas que buscan discusión
  ("alarmistas", "no sois oficiales", "ya avisa la Generalitat", "mentira", chemtrails…).
- Alcance del gancho: la primera frase tiene que importarle a media España. Un aviso en ciudades pequeñas (Lorca,
  Cartagena…) va en la segunda frase o en su bloque, no abriendo el vídeo (03/11/2026: abrir con "Lorca y Cartagena"
  dejó el parte en 165 visualizaciones; el 53 % se fue en 2 segundos).
- Todas las comunidades, de vez en cuando: el parte va primero con lo importante y, si el prompt dice "Llevas unos días
  sin nombrar…", esas (máx. 2) llevan una mención rápida con su dato en su bloque (Aragón en INTERIOR, Extremadura en SUR).
- Avisos en sitios pequeños (Lorca, Cartagena, Mazarrón…): el "titular" y la primera frase hablan de la comunidad
  ("AVISO NARANJA EN MURCIA", "Aviso naranja en la Región de Murcia"), no del pueblo.
- Avisos previstos y oleaje: si el prompt trae "AVISOS DE AEMET PREVISTOS" u "OLEAJE FUERTE PREVISTO", menciónalos en el
  bloque de su zona/día (naranjas y rojos siempre; amarillos de pasada) y di la altura de las olas ("olas de hasta 5
  metros en Galicia"). Las zonas con aviso salen coloreadas en el mapa.
- Nieve: si el prompt trae "NIEVE PREVISTA", di la cota y el espesor ("nieve a partir de 800 metros en Picos de Europa,
  hasta 20 centímetros"); cotas por debajo de 1.000 m o nevadas grandes son noticia. En pantalla sale un copo con la cota.
- Festivos: en los nacionales, felicita a todos ("¡feliz Día de la Constitución!"); en el Día de cada comunidad, felicita a
  la gente de esa comunidad ("¡feliz Día de Andalucía!", "¡feliz Diada!"). En días de luto (Todos los Santos, Semana
  Santa) no se felicita. Nieve en muchas zonas: dilo en general y nombra solo las 2 o 3 principales.

- Comentarios de ciudad en vídeos de varios días (semana, lo que queda de semana, finde): se contesta con un resumen rápido de todos los días que quedan en ese sitio (Jue ☀️19/6° · Vie 🌧️15/8° 💧70% ...) y cuál es el mejor día. En los partes diarios, solo el día siguiente.
- Las respuestas dentro de los hilos de nuestros comentarios («Reto: dime el pueblo...») también se leen y se contestan.
- Comentarios: solo se contestan en los vídeos del día (publicados en las últimas 24 h); los de vídeos de días anteriores no se contestan.
- Lo más frío y lo más caluroso: se dicen las dos cosas: la capital (o capitales) más fría y, si hay un sitio aún más frío, ese pueblo con su provincia, esté donde esté (no tiene que ser de la misma provincia). Igual con el calor. El prompt lo trae en «LO MÁS FRÍO Y LO MÁS CALUROSO DE ESPAÑA».
- Duración de los vídeos: mínimo 65 s y MÁXIMO 1:40 (100 s). Con avisos naranja o rojo se puede pasar para explicarlos bien, hasta ~2:25 (145 s), nunca 3 minutos. Si la locución sale larga, el vídeo se alarga (no se acelera la voz ni se cambia a la voz gratuita).
- Vídeo de aviso naranja/rojo: empieza con el mapa entero y luego hace zoom a la zona (también en Canarias), señalando los principales núcleos afectados (los más grandes de cada zona, datos de GeoNames). En «zonas» se nombran dos o tres de esos núcleos.
- Parte diario con aviso naranja o rojo: tramo «aviso» justo después del gancho, con zoom a la zona y los núcleos afectados señalados (el prompt lo pide en «TRAMO DE AVISO»).
- Duración objetivo: ~70 s el parte (finde ~75, semana ~90). Solo se alarga si hay aviso naranja/rojo o temporal; si la locución sale larga igualmente, el vídeo se alarga (no se acelera la voz).
- Instagram: cada vídeo se publica también como Reel (perfil «default» de Upload-Post). Antes se comprueba la conexión, se reintenta hasta 3 veces y, si no sale, el workflow acaba en rojo. Además, comprobar-redes.yml revisa a las 11:17 y 16:47 que Instagram y TikTok sigan conectados.
- Instagram: texto propio (mismo gancho y resumen + línea de búsqueda + 5 hashtags: #eltiempo #previsiondeltiempo #tiempoespaña, el local y #meteorologia; #avisoaemet en avisos). Comentarios: se contestan en los Reels de las últimas 24 h con las mismas reglas que en TikTok (estado/respuestas_instagram.json).
- PENDIENTE (cuando Instagram pase de ~1.000 seguidores): proponer al usuario encuestas y preguntas en historias de vez en cuando para crear interacción (se ponen a mano desde la app).
- Avisos: hay que nombrar los sitios para que la gente esté al tanto (en Canarias, todas las islas). En los ROJOS es imprescindible nombrar TODOS los sitios; si el guion se deja alguno, se añade «También afecta a…».
- Vídeo de aviso: zoom ajustado (en Canarias, a la tierra de las islas afectadas) y un segundo zoom más cerca de los núcleos principales en «consejos». Avisos amarillos del mismo fenómeno en la misma zona: se pintan y se nombran en una frase («En Lanzarote y Fuerteventura, aviso amarillo…»).
- Mapas extra en el parte (bloque «general»), de vez en cuando: lluvia acumulada en escala de colores en días de lluvia (días pares) o isobaras con A/B cuando hay una borrasca ≤1005 hPa o un anticiclón ≥1026 hPa. El guion lo comenta en una frase (el prompt lo trae en «MAPA DE LLUVIA» / «MAPA DE ISOBARAS»). En los vídeos de aviso por lluvia, el zoom de «consejos» lleva la lluvia en colores.
- Avisos naranja/rojo por lluvia o tormentas: mapa de lluvia acumulada con escala de colores completa (0,1 → 200+ l/m², estilo mapa de modelo, costas encima, leyenda abajo). En el vídeo de aviso es el tramo «¿Cuánto va a llover?»; en el tramo «aviso» del parte aparece a los ~4,5 s, tras las zonas. La voz dice cuánta lluvia y dónde más.
- Avisos por lluvia/tormentas: tramo «¿Cuándo lloverá más?» con la lluvia hora a hora animada (tipo radar, reloj y barra de tiempo, ~0,5 s por fotograma, hasta 18 fotogramas) y la voz diciendo cuándo y dónde llueve más fuerte; después «¿Cuánto va a llover?» con el acumulado.
- Zoom de avisos: zona afectada y colindantes (península: margen ~0,9° y mínimo 3°×2,3°; Canarias: todas las islas). El mapa de lluvia cubre todo el zoom, y si en provincias vecinas sin aviso también llueve bastante (≥15 l/m²), la voz lo menciona.
- Mapas: las temperaturas nunca en medio del mar (las pastillas de ciudades de costa se meten hacia tierra; solo islas, Ceuta y Melilla pueden ir sobre el mar).
- Semanal (domingo), media semana (miércoles) y finde (viernes): son los más importantes; tienen que estar impolutos y todo perfectamente explicado. Objetivo ~1:50 el semanal y ~1:30 el finde; pueden llegar a 2:30.

## Retención (análisis TikTok, 8-nov)
- En semanal y finde, la curva cae a un ritmo constante (~0,4 puntos/s) mientras se cuentan los días: no hay un día que espante. Donde se va la gente es en los últimos ~15 s (mejor/peor día + despedida): se pierde la mitad de lo que quedaba.
- Por eso: despedida de una frase corta (≤12 palabras) y la promesa del principio se cumple en el bloque «general», no después.
- El 35-45 % se va en los 3 primeros segundos: el gancho tiene que nombrar ya un sitio o un dato llamativo.
- Semanal, media semana y finde: si llueve de verdad (≥3 capitales con ≥50 %), el bloque del día más lluvioso funde el mapa de lluvia en colores y el guion le dedica una frase.
- CONTRASTE DE FUENTES: el prompt trae dónde AEMET y los modelos (europeo, francés, alemán, americano) no se ponen de acuerdo y dónde coinciden todos. Una frase natural sobre el más llamativo, sin tecnicismos; no forzarlo si el parte va lleno. Si se activa Google (secreto GOOGLE_WEATHER_API_KEY), entra solo en la fusión y el contraste, nunca pintado en el mapa.
- Madrid, Barcelona, Valencia, Sevilla, Zaragoza, Málaga y Bilbao salen SIEMPRE en el mapa (partes diarios, semanal, media semana y finde), las nombre o no el guion. Es solo el MAPA: el guion sigue rotando ciudades, nombrando los sitios con más incidencia o más llamativos y sin huecos; no hay que nombrar estas siete por obligación.
- ROTACIÓN: todas las capitales y ciudades grandes de España son candidatas en el mapa; tienen preferencia las que llevan más días sin salir (estado/mapa_rotacion.json). En ~10 días salen casi todas. En el guion, nombrar también de vez en cuando ciudades que casi nunca se nombran (Huesca, Ourense, Lugo, Teruel, Soria, Zamora…).
- AVISOS ROJOS: vídeo SIEMPRE (haya o no ciudades grandes) y NUNCA flash: vídeo completo (hasta ~1:35) bien desarrollado: todas las zonas y núcleos, desde/hasta cuándo, evolución hora a hora con la hora punta y los litros en una hora en cada zona, acumulados por zona y provincias vecinas, qué implica (según AEMET) y consejos + 112.
- AVISOS NARANJA/ROJO: nombrar TODAS las zonas afectadas y sus principales núcleos, y además las ciudades y núcleos principales colindantes con su nivel (amarillo / sin aviso), para que estén atentos por si el temporal se desvía. Cada sitio con su nivel. TODO pueblo o ciudad que se nombre se señala en el mapa.
- MAPAS COMO EN LA TELE: mapa general con los iconos animados de siempre flotando y la temperatura debajo en su chapita (nombre encima; las siete grandes en amarillo); bloque «general» con España coloreada por la máxima y las cifras sobre las ciudades.

- Avisos en zonas distantes (p. ej. Extremadura y Canarias): un bloque por zona («aviso», «aviso2»… en el parte;
  «zonas», «zonas2»… en el vídeo de aviso). En pantalla, zoom a la primera; entre una y otra se aleja a toda España y
  vuelve a acercarse a la que toca cuando se habla de ella.

- Tramo «sistema» (borrasca/DANA hora a hora): trayectoria, lluvia y viento se reparten el tramo a partes parecidas
  (unos 5 s cada una; algo más la que tiene más incidencia) y cada una se ve entera. El texto del tramo tiene que
  durar lo que piden los datos (no acortarlo), para que dé tiempo a ver los tres mapas.

- AVISOS: ZONA ENTERA. Un aviso es para toda la zona de AEMET, no para pueblos sueltos. Primero la zona y sus comarcas
  y valles enteros («todo el Valle del Jerte, toda La Vera…»); los pueblos, después y solo como ejemplo («con pueblos
  como…, entre otros»). Nunca un pueblo en lugar de su valle. Decir al menos una vez que el aviso es para toda la zona,
  también para los pueblos que no se nombran. (Tabla COMARCAS_ZONA en especiales.py; se comprueba tras escribir el guion.)

- Avisos por lluvia, tramo «lluvia»: el mapa del acumulado crece hora a hora con un marcador de litros por zona. El
  texto cuenta esa evolución en l/m² por zonas (cuánto a media tarde, cuánto por la noche, total al final).

- DURACIÓN DE LOS AVISOS: los naranjas siguen siendo cortos (flash de ~25-55 s). Los ROJOS duran siempre más de 1:05
  (hasta ~1:40): vídeo completo y, además, así pueden monetizar (TikTok solo paga vídeos de más de un minuto).
- Ampliación de un aviso ya publicado: el vídeo va SOLO de las zonas nuevas; lo ya contado, en una frase, con sus
  cifras comprobadas contra lo publicado (si no cambian, resumen; si cambian, se dice el cambio).

- AVISOS (naranjas y rojos): llevan siempre el tramo «temporal», tras «zonas»: mapa amplio con la lluvia hora a hora y
  las rachas de viento hora a hora (y la trayectoria si hay borrasca o DANA identificada). El texto cuenta por dónde
  entra, cómo avanza y a qué zonas va tocando y cuándo. (De momento no en avisos solo de Canarias.)
- Ampliaciones: lo ya contado va en el tramo «sigue», con zoom out de la zona nueva y zoom in a la anterior.

- AVISOS, VARIEDAD: prohibida la coletilla «se pueden producir daños graves / muy graves o catastróficos». El peligro
  se cuenta con lo concreto del fenómeno (crecidas, árboles caídos, olas…), como posibilidad, y cada vídeo de una
  forma: cambia el arranque, los verbos, los consejos y la despedida (se pasan al guion las fórmulas de los últimos
  vídeos para no repetirlas, y un enfoque distinto en cada uno).

- BORRASCAS: se siguen varias a la vez (Bruna y, detrás, Charles). Cada una sale en el mapa con su B y su nombre, y el
  guion cuenta las dos en el orden en que llegan. Los nombres son los de AEMET, en el orden en que los cita (la que
  llega antes recibe el primero); si no hay nombre, «borrasca» a secas. El viento hora a hora lleva las isobaras encima.

- HORAS, CLARAS: cuando se diga cuándo es lo más fuerte, con horas o tramos concretos y una frase natural («lo más
  fuerte, entre las diez de la mañana y las seis de la tarde»; «lo peor llega por la tarde»). Prohibidas las frases
  ambiguas o cojas como «con lo peor de la mañana a la tarde».
- Comarcas: cada comarca se nombra UNA sola vez por vídeo; nada de listas largas de comarcas pegadas al final.
- Plano del Mediterráneo: si se ven las Baleares, llevan su tarjeta (Palma y, si cabe, otra isla).

- Plano de las borrascas (parte «sistema» y avisos «temporal»): Canarias va en su sitio real del mapa, sin recuadro,
  con la lluvia y el viento encima como en el resto. El guion puede contar cómo le afecta.
- Baleares en el plano del Mediterráneo: una de las islas (la que nombre el texto o van rotando), no siempre Palma.
