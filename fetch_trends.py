#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_trends.py  -  Scarica le serie storiche di Google Trends per i sottostanti
                    del sito Jensen e produce un file `sentiment.json`.

Per ogni sottostante crea DUE serie:
  - "w5y"  : 5 anni, granularita' SETTIMANALE (piu' fine)
  - "max"  : massimo storico disponibile, granularita' MENSILE (piu' lungo)

Strategia termini: combina piu' varianti (nome azienda, nome+"stock", ticker)
sommando i loro segnali, per un proxy di interesse di ricerca piu' robusto.

USO:
  pip install pytrends pandas
  python fetch_trends.py                 # parte dal sottoinsieme di TEST
  python fetch_trends.py --all           # tutti i sottostanti (lungo!)
  python fetch_trends.py --only AAPL MSFT ENI    # solo alcuni

NOTE IMPORTANTI (limiti di Google Trends):
  * I valori sono RELATIVI (0-100, normalizzati sul picco di OGNI serie):
    confrontabili nel tempo per lo stesso asset, NON tra asset diversi.
  * 5 anni -> dato settimanale; oltre -> mensile. Non esiste giornaliero su anni.
  * Google applica RATE LIMITING: lo script fa pause tra le richieste. Con molti
    ticker puo' servire piu' di una sessione (se vieni bloccato, riprova piu' tardi).
  * pytrends e' NON ufficiale: puo' rompersi se Google cambia le API interne.
"""

import json
import time
import argparse
import sys
from datetime import datetime

try:
    import pandas as pd
    from pytrends.request import TrendReq
except ImportError:
    print("ERRORE: servono pytrends e pandas.\n  pip install pytrends pandas")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Mappa sigla -> nome esteso (la tua, incollata qui).
# Aggiorna questa mappa quando aggiungi sottostanti.
# ---------------------------------------------------------------------------
SOTTOSTANTI = {
    "A2": "A2A", "AAL": "American Airlines", "AAPL": "Apple", "ABBV": "AbbVie",
    "ABI": "Anheuser-Busch InBev", "ABNB": "Airbnb", "ABNd": "ABN Amro",
    "ABX": "Barrick Gold", "ADBE": "Adobe", "ADSGn": "Adidas", "ADYEN": "Adyen",
    "AEGON": "Aegon", "AI": "Air Liquide", "AIR": "Airbus", "AIRF": "Air France-KLM",
    "AIRP": "Air Liquide", "ALB": "Albemarle", "ALSO": "Alstom", "ALV": "Allianz",
    "ALVG": "Allianz", "AMD": "Advanced Micro Devices", "AMPF": "Amplifon",
    "AMZN": "Amazon", "ANGLOAMERICAN": "Anglo American", "ARM": "Arm Holdings",
    "ASML": "ASML", "AV": "Aviva", "AXA": "AXA", "AXAF": "AXA", "AXP": "American Express",
    "AZMT": "Azimut", "BABA": "Alibaba", "BAC": "Bank of America", "BAER": "Julius Baer",
    "BAMI": "Banco BPM", "BARC": "Barclays", "BASFn": "BASF", "BAYGn": "Bayer",
    "BBVA": "BBVA", "BBY": "Best Buy", "BCU": "Brunello Cuccinelli", "BE": "Bloom Energy",
    "BHB": "BHB", "BIDU": "Baidu", "BKNG": "Booking", "BLDP": "Ballard",
    "BMPS": "Monte dei Paschi di Siena", "BMWG": "BMW", "BMY": "Bristol-Myers Squibb",
    "BNPP": "BNP Paribas", "BNTX": "BioNTech", "BOSSn": "Hugo Boss", "BP": "BP",
    "BRBY": "Burberry", "BWXT": "BWXT", "C": "Citigroup", "CAGR": "Credit Agricole",
    "CBKG": "Commerzbank", "CCL": "Carnival", "CFR": "Richemont", "CIGNA": "Cigna",
    "CLF": "Cleveland-Cliffs", "COIN": "Coinbase", "CONG": "Continental",
    "CPRI": "Capri Holdings", "CPRI_M": "Campari", "CRM": "Salesforce",
    "DAL": "Delta Air Lines", "DANO": "Danone", "DBKGn": "Deutsche Bank",
    "DHER": "Delivery Hero", "DHLn": "Deutsche Post DHL", "DIAS": "DiaSorin",
    "DOCU": "DocuSign", "EL": "Estee Lauder", "ELE": "Endesa", "EMII": "Bper Banca",
    "ENEL": "Enel", "ENGIE": "Engie", "ENI": "Eni", "ENPH": "Enphase",
    "ENR1n": "Siemens Energy", "ESLX": "EssilorLuxottica", "EXC": "Exelon",
    "EXPE": "Expedia", "EZJ": "easyJet", "F": "Ford", "FBK": "FinecoBank",
    "FCX": "Freeport-McMoRan", "FL": "Foot Locker", "FSLR": "First Solar",
    "FTMIB": "FTSE MIB", "G": "Generali", "GAP": "Gap", "GDAXI": "DAX",
    "GLEN": "Glencore", "GM": "General Motors", "GOLD": "Barrick Gold",
    "GOOGL": "Alphabet", "HEIN": "Heineken", "HMb": "H&M",
    "HPE": "Hewlett Packard Enterprise", "HRMS": "Hermes",
    "HSCE": "Hang Seng China Enterprises", "HUM": "Humana", "IBE": "Iberdrola",
    "IFXGn": "Infineon", "ILMN": "Illumina", "ING": "ING", "INTC": "Intel",
    "ISP": "Intesa Sanpaolo", "IVG": "Iveco", "JCI": "Johnson Controls", "JD": "JD.com",
    "JPM": "JPMorgan", "KO": "Coca-Cola", "LDOF": "Leonardo", "LHAG": "Lufthansa",
    "LI": "Li Auto", "LLY": "Eli Lilly", "LUMN": "Lumen", "LVMH": "LVMH",
    "M9CXWESY": "M9CXWESY", "MBGn": "Merck KGaA", "MDBI": "Mediobanca", "META": "Meta",
    "MICP": "Michelin", "MONC": "Moncler", "MRCG": "Merck", "MRK": "Merck & Co",
    "MRNA": "Moderna", "MSFT": "Microsoft", "MSTR": "MicroStrategy", "MT": "ArcelorMittal",
    "N225E": "Nikkei 225", "NASDAQ": "Nasdaq 100", "NDXG": "Nasdaq 100", "NEE": "NextEra",
    "NEM": "Newmont", "NESN": "Nestle", "NEXII": "Nexi", "NFLX": "Netflix", "NKE": "Nike",
    "NOVOb": "Novo Nordisk", "NVAX": "Novavax", "NVDA": "NVIDIA", "ORCL": "Oracle",
    "OREP": "L'Oreal", "OXY": "Occidental", "P911_p": "Porsche", "PATH": "UiPath",
    "PERP": "Pernod Ricard", "PFE": "Pfizer", "PG": "Procter & Gamble", "PIRC": "Pirelli",
    "PLTR": "Palantir", "PLUG": "Plug Power", "PNDORA": "Pandora", "PRTP": "Kering",
    "PRY": "Prysmian", "PST": "Poste Italiane", "PSTG": "Pure Storage", "PUMG": "Puma",
    "PVH": "PVH", "PYPL": "PayPal", "QCOM": "Qualcomm", "RACE": "Ferrari",
    "RBIV": "Raiffeisen Bank", "RCOP": "Remy Cointreau", "RENA": "Renault", "REP": "Repsol",
    "RHMG": "Rheinmetall", "RIVN": "Rivian", "RL": "Ralph Lauren", "RO": "Roche",
    "ROG": "Roche", "RUN": "Sunrun", "RWEG": "RWE", "SAN": "Santander", "SAPG": "SAP",
    "SASY": "Sanofi", "SATG": "Sartorius", "SD3E": "SD3E", "SD3EX": "SD3EX",
    "SEDG": "SolarEdge", "SFER": "Salvatore Ferragamo", "SGEF": "SGS", "SGOB": "Saint-Gobain",
    "SHEL": "Shell", "SIEGn": "Siemens", "SMCI": "Super Micro", "SNAP": "Snap",
    "SOGEN": "Societe Generale", "SOGN": "Societe Generale", "SOLCYB35": "SOLCYB35",
    "SPMI": "Saipem", "SRG": "Snam", "SSMI": "Swiss Market Index", "STLAM": "Stellantis",
    "STMPA": "STMicroelectronics", "STOXX50E": "Euro Stoxx 50", "SX6P": "STOXX Europe 600",
    "SX7E": "STOXX Europe 600 Financials", "TEF": "Telefonica", "TENR": "Tenaris",
    "TLIT": "Telecom Italia", "TPR": "Tapestry", "TRIP": "Tripadvisor", "TSLA": "Tesla",
    "TSM": "TSMC", "TTEF": "TotalEnergies", "TUI1n": "TUI", "UAA": "Under Armour",
    "UAL": "United Airlines", "UBER": "Uber", "UBIP": "Ubisoft", "UCG": "UniCredit",
    "UHR": "Swatch", "UNH": "UnitedHealth", "UPS": "UPS", "V": "Visa", "VERB": "Verb",
    "VIE": "Veolia", "VOD": "Vodafone", "VOW": "Volkswagen", "VOWG": "Volkswagen",
    "VRTX": "Vertex", "VUSA": "S&P 500", "VWS": "Vestas", "VZ": "Verizon", "WMT": "Walmart",
    "XOM": "Exxon Mobil", "ZALG": "Zalando", "ZM": "Zoom", "h1876": "h1876",
}

# Sottoinsieme di partenza per testare senza farsi bloccare subito.
TEST_TICKERS = ["AAPL", "MSFT", "TSLA", "NVDA", "ENI", "ENEL", "RACE", "G"]

# ---------------------------------------------------------------------------
# Costruzione dei termini di ricerca per un asset.
# Restituisce una lista di query da sommare (max 2-3 per non esagerare).
# ---------------------------------------------------------------------------
def build_terms(sigla, nome):
    terms = []
    if nome and nome != sigla:
        terms.append(nome)                 # es. "Apple"
        terms.append(f"{nome} stock")      # es. "Apple stock" (intento finanziario)
    else:
        terms.append(sigla)
    # il ticker puro aiuta solo se ha senso come parola di ricerca (>=3 lettere)
    if len(sigla) >= 3 and sigla.isalpha():
        terms.append(sigla)
    # dedup mantenendo l'ordine
    seen, out = set(), []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower()); out.append(t)
    return out[:3]


def fetch_one(pytrends, terms, timeframe, geo=""):
    """Interroga Trends per i termini dati e SOMMA i segnali in un'unica serie.
       Ritorna (dates[], values[]) oppure ([],[]) se nessun dato."""
    combined = None
    for term in terms:
        ok = False
        for attempt in range(3):                 # qualche retry per i blocchi
            try:
                pytrends.build_payload([term], timeframe=timeframe, geo=geo)
                df = pytrends.interest_over_time()
                ok = True
                break
            except Exception as e:
                wait = 8 * (attempt + 1)
                print(f"      retry '{term}' ({timeframe}) tra {wait}s [{e}]")
                time.sleep(wait)
        if not ok or df is None or df.empty or term not in df.columns:
            continue
        serie = df[term].astype(float)
        combined = serie if combined is None else combined.add(serie, fill_value=0)
        time.sleep(2.0)                          # pausa cortese tra i termini

    if combined is None or combined.empty:
        return [], []
    # rinormalizzo la somma a 0-100 (per coerenza con la scala Trends)
    m = combined.max()
    if m and m > 0:
        combined = (combined / m) * 100.0
    dates = [d.strftime("%Y-%m-%d") for d in combined.index]
    values = [round(float(v), 1) for v in combined.values]
    return dates, values


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="tutti i sottostanti della mappa")
    ap.add_argument("--only", nargs="+", help="solo queste sigle")
    ap.add_argument("--geo", default="", help="geo (es. IT, US). Vuoto = mondiale")
    ap.add_argument("--out", default="sentiment.json")
    ap.add_argument("--pause", type=float, default=6.0, help="pausa tra sottostanti (s)")
    args = ap.parse_args()

    if args.only:
        tickers = args.only
    elif args.all:
        tickers = sorted(SOTTOSTANTI.keys())
    else:
        tickers = TEST_TICKERS
    print(f"Scarico Google Trends per {len(tickers)} sottostanti (geo='{args.geo or 'mondiale'}').")

    pytrends = TrendReq(hl="en-US", tz=0)
    result = {}

    for i, sig in enumerate(tickers, 1):
        nome = SOTTOSTANTI.get(sig, sig)
        terms = build_terms(sig, nome)
        print(f"[{i}/{len(tickers)}] {sig} ({nome}) -> termini: {terms}")

        # 5 anni settimanale
        d5, v5 = fetch_one(pytrends, terms, "today 5-y", args.geo)
        time.sleep(args.pause)
        # massimo storico (mensile): Trends accetta 'all' per tutto lo storico
        dmax, vmax = fetch_one(pytrends, terms, "all", args.geo)

        result[sig] = {
            "sigla": sig,
            "nome": nome,
            "terms": terms,
            "w5y":  {"dates": d5,   "values": v5},
            "max":  {"dates": dmax, "values": vmax},
        }
        print(f"      5y: {len(d5)} punti | max: {len(dmax)} punti")
        # salvataggio incrementale: se vieni bloccato, non perdi il lavoro fatto
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        time.sleep(args.pause)

    print(f"\nFatto. Scritto {args.out} con {len(result)} sottostanti.")
    print("Caricalo accanto a index.html (come gli altri JSON) per la scheda Sentiment.")


if __name__ == "__main__":
    main()
