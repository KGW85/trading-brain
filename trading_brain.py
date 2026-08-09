import json, os, re, html as html_mod
from datetime import datetime
import requests

# Alle Kurse kommen von Yahoo Finance - kostenlos und OHNE Schluessel.
# Damit enthaelt dieses Programm kein Geheimnis und darf bedenkenlos online.
#   S&P Tech = dein echtes Papier QDVE.DE (iShares S&P 500 Info Tech, EUR/XETRA)
#   DAX      = echter Frankfurter Index (^GDAXI, in Euro)
#   Krypto   = in Euro gerechnet, so wie du auch kaufst
MAERKTE = {
    "S&P Tech": "QDVE.DE",
    "Gold":     "GC=F",
    "DAX":      "^GDAXI",
    "Bitcoin":  "BTC-EUR",
    "Ethereum": "ETH-EUR",
}
TREND_TAGE = 200
MOMENTUM_TAGE = 252          # ~12 Monate: misst, welcher Markt am staerksten laeuft
KAPITAL = 2500               # dein Startkapital in Euro

# ==== STRATEGIE-MODUS =================================================
# Hier stellst du ein, wie offensiv gehandelt wird. Einfach das Wort tauschen:
#   "ruhig"      -> alle Maerkte im Aufwaertstrend werden gehalten (gleichgewichtet)
#   "ausgewogen" -> nur die 3 staerksten davon
#   "offensiv"   -> nur die 2 staerksten davon (mehr Chance, groessere Schwankung)
MODUS = "offensiv"
MODUS_ANZAHL = {"ruhig": 5, "ausgewogen": 3, "offensiv": 2}
# =====================================================================

# Dateien liegen immer neben diesem Programm - egal ob auf dem Mac oder online.
HIER = os.path.dirname(os.path.abspath(__file__))
STATUS_DATEI = os.path.join(HIER, "brain_status.json")
DASHBOARD_DATEI = os.path.join(HIER, "dashboard.html")
DEPOT_DATEI = os.path.join(HIER, "depot_positionen.json")

# Laeuft dieses Programm online (GitHub) statt auf deinem Mac?
# Dann bleiben deine Euro-Betraege aus dem Dashboard heraus (Privatsphaere).
ONLINE = os.environ.get("TRADING_BRAIN_ONLINE") == "1"

# ---- Push aufs iPhone (ntfy) -------------------------------------------
# Dein Kanalname steht NICHT hier im Code, sondern in der privaten Datei
# "brain_geheim.json" (bleibt auf deinem Mac) bzw. online in einem GitHub-Secret.
def _lies_kanal():
    aus_umgebung = os.environ.get("NTFY_KANAL")
    if aus_umgebung:
        return aus_umgebung.strip()
    pfad = os.path.join(HIER, "brain_geheim.json")
    if os.path.exists(pfad):
        try:
            return json.load(open(pfad, encoding="utf-8")).get("ntfy_kanal", "")
        except Exception:
            return ""
    return ""


NTFY_KANAL = _lies_kanal()
NTFY_AN = bool(NTFY_KANAL)


def sende_push(titel, text, dringend=False):
    """Schickt eine Benachrichtigung an dein iPhone (ntfy). Fehler stoeren nie den Rest."""
    if not NTFY_AN:
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_KANAL}",
            data=text.encode("utf-8"),
            headers={
                "Title": titel.encode("utf-8"),
                "Priority": "urgent" if dringend else "default",
                "Tags": "rotating_light" if dringend else "chart_with_upwards_trend",
            },
            timeout=15,
        )
        print("  Push ans iPhone gesendet.")
    except Exception as fehler:
        print("  Push nicht gesendet (kein Internet?):", fehler)


def hole_kurse(symbol):
    """Tages-Schlusskurse von Yahoo Finance (aelteste zuerst)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    a = requests.get(url, params={"range": "2y", "interval": "1d"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=20).json()
    try:
        closes = a["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Keine Kursdaten von Yahoo (Symbol pruefen?)")
    return [float(c) for c in closes if c is not None]


# ======================================================================
#   VIKTOR - Welt-Stratege: sammelt Schlagzeilen und markiert, was zaehlt
# ======================================================================
NACHRICHTEN_QUELLEN = [
    ("Tagesschau", "https://www.tagesschau.de/wirtschaft/index~rss2.xml"),
    ("Welt", "https://www.tagesschau.de/ausland/index~rss2.xml"),
    ("Maerkte", "https://news.google.com/rss/search?q=when:1d+DAX+OR+Fed+OR+EZB+OR+Leitzins&hl=de&gl=DE&ceid=DE:de"),
    ("Krypto", "https://news.google.com/rss/search?q=when:1d+Bitcoin+OR+Ethereum+OR+Krypto&hl=de&gl=DE&ceid=DE:de"),
]

# Themen, die deine Werte bewegen koennen -> Viktor hebt sie hervor.
THEMEN = {
    "Zinsen": ["fed", "ezb", "leitzins", "zinssenkung", "zinserhoehung", "zinsen", "notenbank", "powell", "lagarde", "inflation"],
    "Politik": ["wahl", "wahlen", "afd", "koalition", "regierung", "bundestag", "sachsen-anhalt", "haushalt"],
    "Geopolitik": ["iran", "nahost", "krieg", "sanktion", "zoll", "zoelle", "handelsstreit", "china", "russland", "ukraine"],
    "Krypto": ["bitcoin", "ethereum", "krypto", "etf-zufluss", "halving"],
    "Tech": ["nvidia", "apple", "microsoft", "ki-", "chip", "halbleiter", "tech-"],
    "DAX": ["dax", "siemens", "sap", "allianz", "deutsche bank"],
}


def hole_nachrichten(max_pro_quelle=8):
    """Holt Schlagzeilen aus mehreren RSS-Quellen. Fehler stoeren nie den Rest."""
    gesammelt = []
    for quelle, url in NACHRICHTEN_QUELLEN:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            eintraege = re.findall(r"<item>(.*?)</item>", r.text, re.S)[:max_pro_quelle]
            for e in eintraege:
                t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", e, re.S)
                if not t:
                    continue
                titel = html_mod.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip()
                titel = re.sub(r"\s+-\s+[^-]{3,30}$", "", titel)  # " - Quellenname" am Ende weg
                if titel:
                    gesammelt.append({"quelle": quelle, "titel": titel})
        except Exception:
            continue
    return gesammelt


def bewerte_nachrichten(nachrichten):
    """Ordnet jeder Schlagzeile Themen zu. Relevante zuerst."""
    for n in nachrichten:
        klein = n["titel"].lower()
        n["themen"] = sorted({th for th, woerter in THEMEN.items()
                              if any(w in klein for w in woerter)})
    relevant = [n for n in nachrichten if n["themen"]]
    # Nach Anzahl Treffer sortieren (mehr Themen = wahrscheinlich wichtiger)
    relevant.sort(key=lambda n: len(n["themen"]), reverse=True)
    return relevant


def hole_etf_preis(ticker):
    """Aktueller Kurs eines ETFs (fuer die Depot-Bewertung)."""
    j = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                     params={"range": "5d", "interval": "1d"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=20).json()
    return float(j["chart"]["result"][0]["meta"]["regularMarketPrice"])


def rechne_depot():
    """Liest depot_positionen.json und rechnet echten Wert & Gewinn/Verlust.
    Gibt (wert, investiert, gewinn_eur, gewinn_prozent) zurueck - oder None."""
    if not os.path.exists(DEPOT_DATEI):
        return None
    try:
        depot = json.load(open(DEPOT_DATEI, encoding="utf-8"))
    except Exception:
        return None
    investiert = wert = 0.0
    for p in depot.get("positionen", []):
        inv = p.get("investiert_eur", 0)
        investiert += inv
        try:
            preis = hole_etf_preis(p["ticker"])
            einstand = p.get("einstandskurs") or preis
            wert += inv * (preis / einstand)     # Wert waechst/faellt mit dem Kurs
        except Exception:
            wert += inv                          # Kurs nicht erreichbar -> Einstand annehmen
    if investiert <= 0:
        return None
    gewinn = wert - investiert
    return round(wert), round(investiert), round(gewinn), round(gewinn / investiert * 100, 1)


def bewerte(name, symbol):
    kurse = hole_kurse(symbol)
    if len(kurse) < TREND_TAGE:
        raise RuntimeError(f"Nur {len(kurse)} Tage Daten - zu wenig")
    kurs = kurse[-1]
    linie = sum(kurse[-TREND_TAGE:]) / TREND_TAGE
    # Momentum = Kursveraenderung ueber ~12 Monate (wie stark laeuft der Markt?)
    basis = kurse[-(MOMENTUM_TAGE + 1)] if len(kurse) > MOMENTUM_TAGE else kurse[0]
    momentum = round((kurs / basis - 1) * 100, 1)
    return {"markt": name, "kurs": round(kurs, 2), "linie": round(linie, 2),
            "status": "INVESTIERT" if kurs > linie else "CASH",
            "ueber": kurs > linie, "abstand": round((kurs - linie) / linie * 100, 1),
            "momentum": momentum}


# ---- Depot-Bestand von gestern laden (fuer Signal-Erkennung) ----
gestern_gehalten = set()
gestern_da = False
if os.path.exists(STATUS_DATEI):
    try:
        alt = json.load(open(STATUS_DATEI, encoding="utf-8"))
        gestern_da = bool(alt.get("maerkte"))
        for m in alt.get("maerkte", []):
            if m.get("gehalten"):
                gestern_gehalten.add(m["markt"])
    except Exception:
        pass

jetzt = datetime.now()
print("=" * 58)
print("  TRADING BRAIN - Lagecheck", jetzt.strftime("%d.%m.%Y %H:%M"), "| Modus:", MODUS.upper())
print("=" * 58)

# 1) Alle Maerkte bewerten (Kurs, Trend-Linie, Momentum)
ergebnisse = []
for name, symbol in MAERKTE.items():
    try:
        ergebnisse.append(bewerte(name, symbol))
    except Exception as f:
        print(f"  {name:<9} FEHLER: {f}")
        ergebnisse.append({"markt": name, "status": "FEHLER", "meldung": str(f)})

# 2) Modell anwenden: unter den Maerkten IM AUFWAERTSTREND die staerksten waehlen
ok = [e for e in ergebnisse if e.get("status") in ("INVESTIERT", "CASH")]
im_trend = sorted([e for e in ok if e["ueber"]], key=lambda e: e["momentum"], reverse=True)
anzahl = MODUS_ANZAHL.get(MODUS, 2)
gehalten_namen = {e["markt"] for e in im_trend[:anzahl]}
for e in ergebnisse:
    e["gehalten"] = e["markt"] in gehalten_namen

# 3) Uebersicht ausgeben
for e in ok:
    pfeil = "UEBER" if e["ueber"] else "UNTER"
    marker = "  << IM DEPOT" if e["gehalten"] else ""
    print(f"  {e['markt']:<9}{e['kurs']:>11}  {pfeil} Linie ({e['abstand']:+.1f}%)  Mom {e['momentum']:+.1f}%{marker}")

# 4) Signale = Aenderung am Soll-Depot gegenueber gestern
signale = []
if gestern_da:
    for e in ok:
        war, ist = e["markt"] in gestern_gehalten, e["gehalten"]
        if ist and not war:
            signale.append(f"{e['markt']}: KAUFEN (neu unter den {anzahl} staerksten)")
        elif war and not ist:
            grund = "faellt unter die Linie" if not e["ueber"] else "nicht mehr unter den staerksten"
            signale.append(f"{e['markt']}: VERKAUFEN ({grund})")

print("-" * 58)
betrag = round(KAPITAL / max(len(gehalten_namen), 1))
haltetext = ", ".join(sorted(gehalten_namen)) if gehalten_namen else "nichts (alles Cash)"
print(f"  Modell ({MODUS}) haelt {len(gehalten_namen)} Wert(e): {haltetext}")
if gehalten_namen:
    print(f"  Vorschlag: je ~{betrag} EUR pro Wert")
if signale:
    print("  >>> HEUTE ZU TUN:")
    for s in signale:
        print("      -", s)
else:
    print("  Heute zu tun: NICHTS - Depot unveraendert.")
print("-" * 58)

json.dump({"zeitpunkt": jetzt.isoformat(), "modus": MODUS, "maerkte": ergebnisse},
          open(STATUS_DATEI, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("  Gespeichert in:", STATUS_DATEI)


# ======================================================================
#   DASHBOARD BAUEN  (schreibt dashboard.html mit den echten Zahlen)
# ======================================================================
ueber_liste = [e for e in ok if e["ueber"]]            # im Aufwaertstrend
gehalten_liste = [e for e in ok if e.get("gehalten")]  # tatsaechlich im Depot
modus_label = {"ruhig": "Ruhig", "ausgewogen": "Ausgewogen", "offensiv": "Offensiv"}.get(MODUS, MODUS)
kapital_txt = f"{KAPITAL:,}".replace(",", ".")
gruss = "Guten Morgen" if jetzt.hour < 11 else ("Guten Tag" if jetzt.hour < 18 else "Guten Abend")

# Viktor: Schlagzeilen holen und nach Relevanz sortieren
nachrichten = bewerte_nachrichten(hole_nachrichten())
top_themen = []
for n in nachrichten[:12]:
    for t in n["themen"]:
        if t not in top_themen:
            top_themen.append(t)
themen_txt = ", ".join(top_themen[:4]) if top_themen else "ruhige Lage"
print(f"  Viktor: {len(nachrichten)} relevante Schlagzeilen ({themen_txt})")

news_html = ""
for n in nachrichten[:6]:
    tags = "".join(f'<span class="tag">{t}</span>' for t in n["themen"][:2])
    titel = html_mod.escape(n["titel"])[:120]
    news_html += f'<div class="nw"><div class="nwt">{titel}</div><div class="nwm">{n["quelle"]}{tags}</div></div>'
if not news_html:
    news_html = '<div class="nw"><div class="nwt">Keine Schlagzeilen abrufbar.</div></div>'

# Echtes Depot bewerten (Wert, Gewinn/Verlust in Euro)
depot_zahlen = None if ONLINE else rechne_depot()   # online: keine Euro-Betraege zeigen
if depot_zahlen:
    d_wert, d_inv, d_gewinn, d_pct = depot_zahlen
    gv_farbe = "var(--green)" if d_gewinn >= 0 else "var(--red)"
    doro_txt = f'&bdquo;Depotwert {d_wert} &euro; &middot; {d_gewinn:+d} &euro; ({d_pct:+.1f}%) seit Kauf.&ldquo;'
    wert_block = f"<div><div class='n'>{d_wert}&euro;</div><div class='l'>Depotwert</div></div>"
    gv_block = f"<div><div class='n' style='color:{gv_farbe}'>{d_gewinn:+d}&euro;</div><div class='l'>Gewinn/Verlust</div></div>"
else:
    if ONLINE:
        doro_txt = f'&bdquo;Modus {modus_label}: {len(gehalten_liste)} Wert(e) im Depot. Betraege bleiben privat.&ldquo;'
        wert_block = f"<div><div class='n'>{MODUS_ANZAHL.get(MODUS, 2)}</div><div class='l'>Plaetze</div></div>"
    else:
        doro_txt = f'&bdquo;Modus {modus_label}: ich halte {len(gehalten_liste)} Wert(e), je ~{betrag} &euro;.&ldquo;'
        wert_block = f"<div><div class='n'>{kapital_txt}&euro;</div><div class='l'>Kapital</div></div>"
    gv_block = ""

# Ampel-Kacheln (gehaltene Werte mit gruenem Rahmen + Stern)
ampel = ""
for e in ok:
    farbe = "g" if e["ueber"] else "r"
    lage = "ueber" if e["ueber"] else "unter"
    held = " held" if e.get("gehalten") else ""
    star = " &#9733;" if e.get("gehalten") else ""
    ampel += f'<div class="m {farbe}{held}"><div class="dot"></div><div class="nm">{e["markt"]}{star}</div><div class="st">{e["abstand"]:+.1f}% {lage}</div></div>'

# Heute zu tun
if signale:
    tun = "".join(f"<div>&bull; {s}</div>" for s in signale)
else:
    tun = "Nichts zu tun. Depot unveraendert lassen."

# Markt am naechsten an der Linie
naechster = min(ok, key=lambda e: abs(e["abstand"])) if ok else None
nah_txt = f'{naechster["markt"]} ({naechster["abstand"]:+.1f}%)' if naechster else "-"

sina_txt = (f'&bdquo;{len(signale)} Depot-Aenderung(en) heute &ndash; bitte handeln!&ldquo;'
            if signale else '&bdquo;Depot unveraendert &ndash; ich bleibe wachsam.&ldquo;')
rico_txt = ('&bdquo;Modus Offensiv &ndash; groessere Schwankungen sind eingeplant. Augen auf.&ldquo;'
            if MODUS == "offensiv" else '&bdquo;Risiko im Griff &ndash; Gewichtung ausgewogen.&ldquo;')
agenten = [
    ("&#128200;", "Theo", "Trend-Waechter &middot; taeglich",
     f'&bdquo;{len(ueber_liste)} von {len(ok)} Maerkten im Aufwaertstrend. Ich ranke sie nach Staerke.&ldquo;', "ready", "Bereit"),
    ("&#128276;", "Sina", "Signalgeberin &middot; bei Depot-Aenderung", sina_txt, "ready", "Bereit"),
    ("&#128188;", "Doro", "Depot-Verwalterin &middot; laufend", doro_txt, "ready", "Bereit"),
    ("&#128737;", "Rico", "Risiko-Waechter &middot; Veto", rico_txt, "ready", "Bereit"),
    ("&#128301;", "Mira", "Markt-Beobachterin &middot; Fruehwarnung",
     f'&bdquo;Am naechsten an der Linie: {nah_txt}. Den beobachte ich genau.&ldquo;', "ready", "Bereit"),
    ("&#128221;", "Clara", "Chronistin &middot; automatisch",
     f'&bdquo;Alles protokolliert. Letzter Lauf: {jetzt.strftime("%d.%m. %H:%M")}.&ldquo;', "ready", "Bereit"),
    ("&#127758;", "Viktor", "Welt-Stratege &middot; Nachrichten",
     f'&bdquo;{len(nachrichten)} relevante Schlagzeilen gesichtet. Thema heute: {themen_txt}.&ldquo;', "ready", "Bereit"),
    ("&#9878;", "Dr. Julian Winter", "Jurist &middot; Recht &amp; Steuern",
     '&bdquo;Ich uebernehme kuenftig Steuern und Rechtsfragen. Noch im Aufbau.&ldquo;', "soon", "In Vorbereitung"),
]
agent_html = ""
for ic, nm, role, last, scls, slabel in agenten:
    agent_html += f'''<div class="card"><div class="row1"><div class="ic">{ic}</div>
    <span class="status {scls}"><span class="dot"></span>{slabel}</span></div>
    <h3>{nm}</h3><div class="role">{role}</div>
    <div class="last"><b>Zuletzt:</b> {last}</div></div>'''

feed_items = [
    ("Th", jetzt.strftime("%H:%M") + " &middot; Theo",
     f'Modus {modus_label}. {len(ueber_liste)} von {len(ok)} Maerkten im Aufwaertstrend - ich ranke nach Staerke.'),
    ("Si", jetzt.strftime("%H:%M") + " &middot; Sina",
     ("Es gibt was zu tun: " + "; ".join(signale)) if signale else "Depot unveraendert - heute nichts zu tun."),
    ("Do", jetzt.strftime("%H:%M") + " &middot; Doro",
     f'Depot: {haltetext}.' + ('' if ONLINE else f' Vorschlag je ~{betrag} Euro pro Wert.')),
    ("Vi", jetzt.strftime("%H:%M") + " &middot; Viktor",
     f'Weltlage gesichtet: {len(nachrichten)} relevante Meldungen. Schwerpunkt: {themen_txt}.'),
    ("Mi", jetzt.strftime("%H:%M") + " &middot; Mira",
     f'Am naechsten an der Linie: {nah_txt}. Den beobachte ich.'),
]
feed_html = ""
for av, meta, txt in feed_items:
    feed_html += f'<div class="f"><div class="av">{av}</div><div><div class="fmeta">{meta}</div><div class="ftxt">{txt}</div></div></div>'

CSS = """
:root{--bg:#0d141d;--panel:#141d28;--panel2:#18232f;--line:#243342;--ink:#e7edf3;--muted:#8395a7;--dim:#5c6b7d;--green:#3ecf8e;--greenbg:rgba(62,207,142,.12);--red:#e5645a;--teal:#4bb6c9;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.45;padding:26px 34px 60px;max-width:1180px;margin:0 auto}
.accent{font-family:Georgia,serif;font-style:italic;color:var(--green)}
h1{font-size:26px;font-weight:600;margin-bottom:4px}
.sub{color:var(--dim);font-size:12px;margin-bottom:24px}
.brain{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:22px 24px;margin-bottom:28px;display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap}
.brain .orb{width:46px;height:46px;border-radius:12px;background:var(--greenbg);display:flex;align-items:center;justify-content:center;font-size:22px}
.brain h2{font-size:17px;font-weight:600}
.brain .bs{color:var(--dim);font-size:10.5px;letter-spacing:1px;text-transform:uppercase;margin-top:2px}
.brain p{color:var(--muted);font-size:13px;margin-top:10px;max-width:520px}
.stats{margin-left:auto;display:flex;gap:26px;text-align:center}
.stats .n{font-size:26px;font-weight:600}.stats .l{font-size:10px;letter-spacing:.6px;text-transform:uppercase;color:var(--dim);margin-top:2px}
.eyebrow{font-size:10.5px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dim);margin:0 0 14px;font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(255px,1fr));gap:14px;margin-bottom:32px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}
.card .row1{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.card .ic{width:34px;height:34px;border-radius:9px;background:var(--panel2);display:flex;align-items:center;justify-content:center;font-size:17px}
.status{font-size:10px;letter-spacing:.5px;text-transform:uppercase;padding:3px 8px;border-radius:20px;font-weight:600;display:inline-flex;align-items:center;gap:5px;background:var(--greenbg);color:var(--green)}
.status .dot{width:6px;height:6px;border-radius:50%;background:var(--green)}
.status.soon{background:rgba(131,149,167,.14);color:var(--muted)}.status.soon .dot{background:var(--muted)}
.card h3{font-size:15px;font-weight:600}
.card .role{font-size:10px;letter-spacing:.6px;text-transform:uppercase;color:var(--teal);margin:3px 0 10px}
.card .last{margin-top:6px;padding-top:11px;border-top:1px solid var(--line);font-size:11.5px;color:var(--dim)}
.card .last b{color:var(--muted)}
.sysgrid{display:grid;grid-template-columns:1fr 1fr 1.4fr;gap:14px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}
.tile h4{font-size:13px;font-weight:600;margin-bottom:6px}
.amp{display:flex;gap:12px;margin-top:10px}
.amp .m{flex:1;text-align:center;background:var(--panel2);border-radius:10px;padding:10px 4px}
.amp .m .dot{width:11px;height:11px;border-radius:50%;margin:0 auto 6px}
.amp .m .nm{font-size:12px;font-weight:600}.amp .m .st{font-size:10px;color:var(--dim);margin-top:2px}
.g .dot{background:var(--green);box-shadow:0 0 10px rgba(62,207,142,.5)}
.r .dot{background:var(--red);box-shadow:0 0 10px rgba(229,100,90,.5)}
.amp .m.held{box-shadow:inset 0 0 0 1px var(--green)}
.tile .todo{font-size:12.5px;color:var(--muted);margin-top:8px;line-height:1.7}
.feed .f{display:flex;gap:11px;padding:9px 0;border-bottom:1px solid var(--line)}
.feed .f:last-child{border-bottom:0}
.feed .av{width:26px;height:26px;border-radius:7px;background:var(--panel2);display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:var(--teal)}
.feed .fmeta{font-size:10px;color:var(--dim);margin-bottom:2px}.feed .ftxt{font-size:12px}
.news{margin-bottom:32px}
.nw{padding:9px 0;border-bottom:1px solid var(--line)}
.nw:last-child{border-bottom:0}
.nwt{font-size:12.5px;line-height:1.45}
.nwm{font-size:10px;color:var(--dim);margin-top:3px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.tag{background:rgba(75,182,201,.14);color:var(--teal);padding:1px 6px;border-radius:20px;font-weight:600;letter-spacing:.3px}
footer{margin-top:28px;color:var(--dim);font-size:11px;text-align:center}
@media(max-width:820px){.sysgrid{grid-template-columns:1fr}}
"""

html = ("<!DOCTYPE html><html lang='de'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Trading Brain</title><style>" + CSS + "</style></head><body>"
        f"<h1>{gruss}, <span class='accent'>Kilian</span>.</h1>"
        f"<div class='sub'>Trading Brain &middot; Lagecheck vom {jetzt.strftime('%d.%m.%Y %H:%M')}</div>"
        "<div class='brain'><div class='orb'>&#9670;</div><div>"
        f"<h2>Trading Brain</h2><div class='bs'>Modell 2.0 &middot; Momentum-Ranking &middot; Modus {modus_label}</div>"
        "<p>Rankt taeglich deine Maerkte nach Staerke und haelt die besten im Aufwaertstrend. Meldet, sobald sich dein Depot aendern soll.</p></div>"
        "<div class='stats'>"
        f"<div><div class='n' style='color:var(--green)'>{len(gehalten_liste)}/{len(ok)}</div><div class='l'>im Depot</div></div>"
        f"<div><div class='n'>{len(signale)}</div><div class='l'>Signale heute</div></div>"
        f"{wert_block}{gv_block}"
        "</div></div>"
        "<div class='eyebrow'>// Dein Team</div>"
        f"<div class='grid'>{agent_html}</div>"
        "<div class='eyebrow'>// Systeme &amp; Team-Funk</div>"
        "<div class='sysgrid'>"
        f"<div class='tile'><h4>&#128682; Markt-Ampel</h4><div class='amp'>{ampel}</div></div>"
        f"<div class='tile'><h4>&#9989; Heute zu tun</h4><div class='todo'>{tun}</div></div>"
        f"<div class='tile'><h4>&#128251; Team-Funk</h4><div class='feed'>{feed_html}</div></div>"
        "</div>"
        "<div class='eyebrow' style='margin-top:32px'>// Viktors Weltlage</div>"
        f"<div class='tile news'>{news_html}</div>"
        "<footer>Automatisch erzeugt von deinem trading_brain-Programm &middot; echte Kursdaten</footer>"
        "</body></html>")

with open(DASHBOARD_DATEI, "w", encoding="utf-8") as d:
    d.write(html)
print("  Dashboard gebaut:", DASHBOARD_DATEI)


# ======================================================================
#   PUSH ANS IPHONE  (kurze Meldung; bei echtem Signal laut & dringend)
# ======================================================================
if signale:
    sende_push(
        "⚠️ Trading-Signal – bitte handeln",
        "\n".join(signale) + f"\n\nStand: {jetzt.strftime('%d.%m. %H:%M')}",
        dringend=True,
    )
else:
    zusatz = f"Depotwert {d_wert} € ({d_gewinn:+d} € / {d_pct:+.1f}%).\n" if depot_zahlen else ""
    sende_push(
        "Trading Brain – Lagecheck",
        zusatz +
        f"Modus {modus_label}: {len(gehalten_liste)} Wert(e) im Depot ({haltetext}).\n"
        f"Am nächsten an der Linie: {nah_txt}.",
        dringend=False,
    )
print("=" * 58)
