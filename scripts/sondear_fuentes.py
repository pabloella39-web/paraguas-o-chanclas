"""Prueba qué fuentes de datos económicos responden desde GitHub Actions."""
import json, time, requests
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
P = {
 "yahoo_q1": "https://query1.finance.yahoo.com/v8/finance/chart/%5EIBEX?range=1mo&interval=1d",
 "yahoo_q2": "https://query2.finance.yahoo.com/v8/finance/chart/GC=F?range=1mo&interval=1d",
 "yahoo_btc": "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?range=1mo&interval=1d",
 "stooq_csv": "https://stooq.com/q/d/l/?s=%5Eibex&i=d",
 "stooq_ult": "https://stooq.com/q/l/?s=%5Eibex+%5Espx+xauusd+cb.f&f=sd2t2ohlcv&h&e=csv",
 "coingecko": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd,eur&include_24hr_change=true",
 "coingecko_chart": "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=30&interval=daily",
 "kraken": "https://api.kraken.com/0/public/Ticker?pair=XBTUSD",
 "ff_semana": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
 "frankfurter": "https://api.frankfurter.app/latest?from=EUR&to=USD,GBP,JPY",
 "fed_cal": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
 "rss_expansion": "https://e00-expansion.uecdn.es/rss/portada.xml",
 "rss_expansion_mercados": "https://e00-expansion.uecdn.es/rss/mercados.xml",
 "rss_cincodias": "https://feeds.elpais.com/mrss-s/pages/ep/site/cincodias.elpais.com/portada",
 "rss_elpais_eco": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada",
 "rss_eleconomista": "https://www.eleconomista.es/rss/rss-mercados.php",
 "rss_europapress": "https://www.europapress.es/rss/rss.aspx?ch=00136",
 "rss_investing": "https://es.investing.com/rss/news.rss",
 "rss_bce": "https://www.ecb.europa.eu/rss/press.html",
 "rss_fed": "https://www.federalreserve.gov/feeds/press_all.xml",
 "rss_consilium": "https://www.consilium.europa.eu/es/rss/pressreleases.ashx",
}
res = {}
for k, u in P.items():
    try:
        t = time.time(); r = requests.get(u, headers=UA, timeout=20)
        res[k] = {"status": r.status_code, "ms": int((time.time()-t)*1000), "len": len(r.content),
                  "tipo": r.headers.get("content-type"), "muestra": r.text[:400]}
    except Exception as e:
        res[k] = {"error": str(e)[:200]}
    print(k, res[k].get("status"), res[k].get("len"), res[k].get("error", ""))
import os; os.makedirs("diagnostico", exist_ok=True)
json.dump(res, open("diagnostico/fuentes.json", "w"), ensure_ascii=False, indent=1)
