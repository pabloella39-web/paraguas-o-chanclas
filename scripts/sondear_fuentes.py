"""Prueba qué fuentes de cotizaciones (bolsas, materias primas) responden desde GitHub Actions."""
import json, os, time, requests
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "application/json,text/html,*/*", "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}
CNBC = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
        ".IBEX%7C.SPX%7C.IXIC%7C.DJI%7C.GDAXI%7C.STOXX50E%7C.N225%7C@GC.1%7C@LCO.1%7C@CL.1%7C@SI.1%7CEUR%3D"
        "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")
P = {
 "cnbc": CNBC,
 "cnbc_hist": "https://ts-api.cnbc.com/harmony/app/charts/1M.json?symbol=.IBEX",
 "google_fin": "https://www.google.com/finance/quote/IBEX:INDEXBME?hl=es",
 "bolsamadrid": "https://www.bolsamadrid.es/esp/aspx/Indices/Resumen.aspx",
 "nasdaq_api": "https://api.nasdaq.com/api/quote/SPX/info?assetclass=index",
 "ft": "https://markets.ft.com/data/indices/tearsheet/summary?s=IBEX:MCX",
 "boerse_frankfurt": "https://api.boerse-frankfurt.de/v1/data/quote_box/single?isin=ES0SI0000005&mic=XMAD",
 "investing": "https://es.investing.com/indices/spain-35",
}
res = {}
for k, u in P.items():
    try:
        t = time.time(); r = requests.get(u, headers=UA, timeout=20)
        res[k] = {"status": r.status_code, "ms": int((time.time()-t)*1000), "len": len(r.content), "muestra": r.text[:600]}
    except Exception as e:
        res[k] = {"error": str(e)[:200]}
# Yahoo imitando la huella TLS de Chrome (curl_cffi), como hace yfinance
try:
    from curl_cffi import requests as cr
    s = cr.Session(impersonate="chrome")
    for k, u in {"yahoo_cffi": "https://query1.finance.yahoo.com/v8/finance/chart/%5EIBEX?range=1mo&interval=1d",
                 "yahoo_cffi_q2": "https://query2.finance.yahoo.com/v8/finance/chart/GC=F?range=1mo&interval=1d"}.items():
        r = s.get(u, timeout=20)
        res[k] = {"status": r.status_code, "len": len(r.content), "muestra": r.text[:600]}
except Exception as e:
    res["yahoo_cffi"] = {"error": str(e)[:300]}
try:
    import yfinance as yf
    df = yf.download(["^IBEX", "GC=F", "BZ=F", "^GSPC"], period="1mo", interval="1d", progress=False)
    res["yfinance"] = {"status": 200 if len(df) else 0, "len": len(df), "muestra": df.tail(3).to_string()[:900]}
except Exception as e:
    res["yfinance"] = {"error": str(e)[:300]}
for k, v in res.items():
    print(k, v.get("status"), v.get("len"), v.get("error", ""))
os.makedirs("diagnostico", exist_ok=True)
json.dump(res, open("diagnostico/fuentes2.json", "w"), ensure_ascii=False, indent=1)
