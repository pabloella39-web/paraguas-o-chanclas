"""Diagnóstico: guarda el calendario de Forex Factory tal cual llega a GitHub Actions."""
import json, os, requests
os.makedirs("diagnostico", exist_ok=True)
for cual in ("thisweek", "nextweek"):
    r = requests.get(f"https://nfs.faireconomy.media/ff_calendar_{cual}.json", headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    open(f"diagnostico/ff_{cual}.txt", "w").write(f"{r.status_code}\n{r.text}")
    print(cual, r.status_code, len(r.text))
