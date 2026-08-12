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
JOURNAL_DATEI = os.path.join(HIER, "journal.json")

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


# ======================================================================
#   KI-ANBINDUNG - die Agenten formulieren ihre Meldungen selbst
# ======================================================================
# Ohne Schluessel laeuft alles wie bisher weiter (feste Texte).
def _lies_ki_schluessel():
    aus_umgebung = os.environ.get("ANTHROPIC_API_KEY")
    if aus_umgebung:
        return aus_umgebung.strip()
    pfad = os.path.join(HIER, "brain_geheim.json")
    if os.path.exists(pfad):
        try:
            return json.load(open(pfad, encoding="utf-8")).get("anthropic_api_key", "")
        except Exception:
            return ""
    return ""


KI_SCHLUESSEL = _lies_ki_schluessel()
KI_AN = bool(KI_SCHLUESSEL)
KI_MODELL = "claude-opus-5"

# ---- Stimmen vorproduzieren (damit auch die Online-Version echt klingt) ----
def _lies_stimm_schluessel():
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"].strip()
    pfad = os.path.join(HIER, "brain_geheim.json")
    if os.path.exists(pfad):
        try:
            return json.load(open(pfad, encoding="utf-8")).get("openai_api_key", "")
        except Exception:
            return ""
    return ""


STIMM_SCHLUESSEL = _lies_stimm_schluessel()
STIMMEN_ORDNER = os.path.join(HIER, "stimmen")

# Stimme + Tempo + Regieanweisung je Agent (gleich wie im Agenten-Server)
OPENAI_STIMMEN = {
    "Theo":   ("echo",    1.15, "Sprich ruhig und sachlich, aber zuegig - wie ein erfahrener Analyst."),
    "Sina":   ("sage",    1.19, "Du bist eine junge, wache Frau. Sprich mit heller, klarer, eindeutig weiblicher Stimme - aufmerksam und bestimmt, du meldest etwas Wichtiges."),
    "Doro":   ("shimmer", 1.11, "Sprich freundlich, warm und gelassen, wie eine hilfsbereite Kollegin."),
    "Rico":   ("onyx",    1.07, "Sprich tief und ernst, mit ruhigem Nachdruck - du warnst."),
    "Mira":   ("coral",   1.21, "Sprich lebhaft, hell und neugierig - als haettest du etwas entdeckt."),
    "Clara":  ("nova",  1.0, "Du bist eine Frau mittleren Alters. Sprich mit klarer, warmer, eindeutig weiblicher Stimme - ruhig und bedaechtig, mit Pausen, wie eine Archivarin, die sorgfaeltig Protokoll fuehrt."),
    "Viktor": ("fable",   1.17, "Sprich klar, flott und sachlich wie ein Nachrichtensprecher."),
    "Winter": ("ash",     1.09,  "Sprich seriös, praezise und wuerdevoll, wie ein erfahrener Jurist."),
    "Georg":  ("verse",   1.18, "Du bist ein wacher, offensiver Mann, der Chancen wittert. Sprich schnell, lebendig und mit Spannung in der Stimme - wie jemand, der gerade etwas Interessantes entdeckt hat."),
}


def erzeuge_stimmdatei(agent, text):
    """Laesst OpenAI den Satz sprechen und legt ihn als MP3 ab."""
    if not STIMM_SCHLUESSEL or agent not in OPENAI_STIMMEN:
        return False
    stimme, tempo, anweisung = OPENAI_STIMMEN[agent]
    try:
        a = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {STIMM_SCHLUESSEL}"},
            json={"model": "gpt-4o-mini-tts", "voice": stimme, "input": text[:4000],
                  "instructions": anweisung + " Sprich auf Deutsch, natuerlich, lebendig und in zuegigem Tempo - nicht schleppend und nicht abgelesen.",
                  "speed": tempo, "response_format": "mp3"}, timeout=60)
        if a.status_code != 200:
            return False
        os.makedirs(STIMMEN_ORDNER, exist_ok=True)
        with open(os.path.join(STIMMEN_ORDNER, f"{agent}.mp3"), "wb") as d:
            d.write(a.content)
        return True
    except Exception:
        return False

# Wer ist wer? Diese Beschreibungen geben den Agenten ihren Charakter.
TEAM_CHARAKTER = """Du schreibst die Meldungen fuer Kilians Trading-Team. Jeder
Agent hat einen eigenen Charakter und spricht in der Ich-Form, auf Deutsch:

- Theo (Trend-Waechter): ruhig, sachlich, beobachtet Trends. Nennt Zahlen.
- Sina (Signalgeberin): wach, direkt, meldet Handlungsbedarf. Bei Signalen dringlich.
- Doro (Depot-Verwalterin): freundlich, gelassen, spricht ueber Geld und Bestand.
- Rico (Risiko-Waechter): vorsichtig, warnend, mahnt zur Umsicht. Etwas knapp.
- Mira (Markt-Beobachterin): neugierig, vorausschauend, sieht was sich anbahnt.
- Clara (Chronistin): bedaechtig, ordnend, spricht ueber Aufzeichnungen.
- Viktor (Welt-Stratege): nachrichtensprecher-artig, ordnet Weltlage ein.
- Winter (Dr. Julian Winter, Jurist): seriös, praezise, Steuern und Recht.

Regeln:
- Ein bis zwei Saetze pro Agent. Natuerlich gesprochen, nicht steif.
- Immer in der Ich-Form, mit Bezug auf die konkreten Zahlen der Lage.
- Keine Anlageberatung, keine Kursprognosen, kein "du solltest kaufen".
- Kein Markdown, keine Anfuehrungszeichen, keine Emojis."""

# ---- Georg der Gambler: sucht Zusammenhaenge zwischen Weltlage und Aktien ----
GEORG_AUFTRAG = """Du bist Georg, genannt "der Gambler" - der offensivste Kopf in
Kilians Trading-Team. Waehrend die anderen das disziplinierte Trendmodell huten,
ist dein Job: aus der aktuellen Nachrichtenlage ableiten, welche Branchen und
welche einzelnen Aktien gerade in Bewegung kommen koennten.

Du denkst in Ursache und Wirkung: Eskalation in einem Konflikt -> Ruestung
(Rheinmetall, Hensoldt, Thales). Mehr KI-Rechenleistung gefragt -> Chips und
Energie (Nvidia, ASML, Siemens Energy). Zinssenkung -> Wachstumswerte und Krypto.
Lieferkette gestoert -> Rohstoffe und Logistik.

Deine Regeln:
- Melde dich NUR, wenn es heute wirklich einen Auslöser in den Schlagzeilen gibt.
  Ist nichts Handfestes dabei, sag das ehrlich und knapp.
- Nenne konkrete Unternehmen mit Namen, damit Kilian weiss, wovon du sprichst.
- Du gibst KEINE Kaufempfehlung und keine Kursprognose. Du zeigst den
  Zusammenhang und sagst dazu, was dagegen spricht - jede Wette hat zwei Seiten.
- Sag immer klar, wie spekulativ die Sache ist.
- Du sprichst - kein Markdown, keine Aufzaehlungszeichen, keine Emojis."""

GEORG_SCHEMA = {
    "type": "object",
    "properties": {
        "auslöser": {"type": "boolean"},
        "meldung": {"type": "string"},
        "thema": {"type": "string"},
        "werte": {"type": "array", "items": {"type": "string"}},
        "dagegen": {"type": "string"},
        "hitze": {"type": "string", "enum": ["kalt", "lauwarm", "heiss", "gluehend"]},
    },
    "required": ["auslöser", "meldung", "thema", "werte", "dagegen", "hitze"],
    "additionalProperties": False,
}


def frage_georg(schlagzeilen, lage):
    """Laesst Georg die Nachrichtenlage auf heisse Eisen abklopfen."""
    if not KI_AN or not schlagzeilen:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=KI_SCHLUESSEL)
        zeilen = "\n".join(f"- {n['titel']} ({n['quelle']})" for n in schlagzeilen[:18])
        a = client.messages.create(
            model=KI_MODELL, max_tokens=1200, system=GEORG_AUFTRAG,
            output_config={"effort": "low", "format": {
                "type": "json_schema", "schema": GEORG_SCHEMA}},
            messages=[{"role": "user", "content":
                       f"Heutige Schlagzeilen:\n{zeilen}\n\n"
                       f"Kilians Depot-Lage:\n{lage}\n\n"
                       f"Siehst du heute ein heisses Eisen? "
                       f"'auslöser' ist wahr, wenn es wirklich etwas Konkretes gibt. "
                       f"'meldung' ist dein gesprochener Satz an Kilian (2-3 Saetze). "
                       f"'hitze' schaetzt ein, wie spekulativ die Sache ist."}],
        )
        text = next(b.text for b in a.content if b.type == "text")
        kosten = (a.usage.input_tokens * 5 + a.usage.output_tokens * 25) / 1_000_000
        print(f"  Georg: Nachrichtenlage geprueft (~{kosten:.3f} USD)")
        return json.loads(text)
    except Exception as fehler:
        print("  Georg nicht erreichbar:", str(fehler)[:80])
        return None


AGENTEN_SCHEMA = {
    "type": "object",
    "properties": {name: {"type": "string"} for name in
                   ["Theo", "Sina", "Doro", "Rico", "Mira", "Clara", "Viktor", "Winter"]},
    "required": ["Theo", "Sina", "Doro", "Rico", "Mira", "Clara", "Viktor", "Winter"],
    "additionalProperties": False,
}


def frage_ki(lage_text):
    """Laesst die Agenten ihre Meldungen selbst formulieren.
    Gibt ein dict {Name: Satz} zurueck - oder None, wenn etwas schiefgeht."""
    if not KI_AN:
        return None
    # Bei Netzproblemen (z.B. WLAN noch im Ruhezustand) kurz warten und neu versuchen
    import time
    for versuch in range(1, 4):
        try:
            import socket
            socket.gethostbyname("api.anthropic.com")
            break
        except Exception:
            if versuch < 3:
                print(f"  Warte auf Internet ... ({versuch})")
                time.sleep(versuch * 20)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=KI_SCHLUESSEL)
        antwort = client.messages.create(
            model=KI_MODELL,
            max_tokens=1500,
            system=TEAM_CHARAKTER,
            output_config={"effort": "low", "format": {
                "type": "json_schema", "schema": AGENTEN_SCHEMA}},
            messages=[{"role": "user", "content":
                       f"Die heutige Lage:\n\n{lage_text}\n\n"
                       f"Schreibe fuer jeden Agenten seine Meldung."}],
        )
        text = next(b.text for b in antwort.content if b.type == "text")
        saetze = json.loads(text)
        kosten = (antwort.usage.input_tokens * 5 + antwort.usage.output_tokens * 25) / 1_000_000
        print(f"  KI: Agenten haben selbst formuliert (~{kosten:.3f} USD)")
        return saetze
    except Exception as fehler:
        print("  KI nicht erreichbar, nutze feste Texte:", str(fehler)[:90])
        return None


def sende_push(titel, text, dringend=False):
    """Schickt eine Benachrichtigung an dein iPhone (ntfy).
    Versucht es mehrfach - z.B. wenn das WLAN nach dem Ruhezustand noch schlaeft."""
    if not NTFY_AN:
        return
    import time
    for versuch in range(1, 5):          # bis zu 4 Versuche ueber ~2 Minuten
        try:
            requests.post(
                f"https://ntfy.sh/{NTFY_KANAL}",
                data=text.encode("utf-8"),
                headers={
                    "Title": titel.encode("utf-8"),
                    "Priority": "urgent" if dringend else "default",
                    "Tags": "rotating_light" if dringend else "chart_with_upwards_trend",
                },
                timeout=20,
            )
            print(f"  Push ans iPhone gesendet.{'' if versuch == 1 else f' (Versuch {versuch})'}")
            return
        except Exception as fehler:
            if versuch < 4:
                print(f"  Kein Netz - neuer Versuch in {versuch * 20} Sekunden ...")
                time.sleep(versuch * 20)
            else:
                print("  Push endgueltig nicht gesendet:", str(fehler)[:80])


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
#   CLARA - Chronistin: schreibt jeden Lauf mit (Grundlage fuer die Kurve)
# ======================================================================
def lies_journal():
    if not os.path.exists(JOURNAL_DATEI):
        return []
    try:
        return json.load(open(JOURNAL_DATEI, encoding="utf-8"))
    except Exception:
        return []


def schreibe_journal(eintraege, neuer):
    """Ein Eintrag pro Tag - ein spaeterer Lauf ersetzt den frueheren."""
    tag = neuer["tag"]
    eintraege = [e for e in eintraege if e.get("tag") != tag]
    eintraege.append(neuer)
    eintraege.sort(key=lambda e: e["tag"])
    eintraege = eintraege[-400:]              # gut zwei Jahre aufheben
    try:
        json.dump(eintraege, open(JOURNAL_DATEI, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception as f:
        print("  Journal nicht gespeichert:", f)
    return eintraege


def baue_kurve(punkte, breite=260, hoehe=52):
    """Kleine Linie (SVG) aus einer Zahlenreihe - fuer die Wertentwicklung."""
    if len(punkte) < 2:
        return ""
    tief, hoch = min(punkte), max(punkte)
    spanne = (hoch - tief) or 1
    schritt = breite / (len(punkte) - 1)
    stellen = " ".join(
        f"{i * schritt:.1f},{hoehe - 4 - (p - tief) / spanne * (hoehe - 8):.1f}"
        for i, p in enumerate(punkte))
    farbe = "var(--green)" if punkte[-1] >= punkte[0] else "var(--red)"
    return (f'<svg viewBox="0 0 {breite} {hoehe}" preserveAspectRatio="none" '
            f'style="width:100%;height:{hoehe}px;overflow:visible">'
            f'<polyline points="{stellen}" fill="none" stroke="{farbe}" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg>')


# ======================================================================
#   DR. JULIAN WINTER - Jurist: schaetzt die Steuer auf Kursgewinne
# ======================================================================
# Deutschland: 25 % Abgeltungssteuer + 5,5 % Soli darauf = 26,375 %.
# Aktien-ETFs sind zu 30 % teilfreigestellt -> nur 70 % des Gewinns zaehlen.
# Sparerpauschbetrag: 1.000 EUR Gewinn pro Jahr bleiben steuerfrei (Einzelperson).
STEUERSATZ = 0.26375
TEILFREISTELLUNG = 0.30
SPARERPAUSCHBETRAG = 1000


def schaetze_steuer(gewinn_eur, schon_genutzt=0):
    """Was bliebe nach Steuern, wenn du jetzt alles mit Gewinn verkaufst?"""
    if gewinn_eur <= 0:
        return 0.0, max(0, SPARERPAUSCHBETRAG - schon_genutzt)
    steuerpflichtig = gewinn_eur * (1 - TEILFREISTELLUNG)
    frei = max(0, SPARERPAUSCHBETRAG - schon_genutzt)
    zu_versteuern = max(0, steuerpflichtig - frei)
    return zu_versteuern * STEUERSATZ, max(0, frei - steuerpflichtig)


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


# Welches Thema betrifft welchen deiner Maerkte?
THEMA_TRIFFT = {
    "Zinsen":     ["S&P Tech", "Gold", "Bitcoin", "Ethereum"],
    "Politik":    ["DAX"],
    "Geopolitik": ["Gold", "DAX"],
    "Krypto":     ["Bitcoin", "Ethereum"],
    "Tech":       ["S&P Tech"],
    "DAX":        ["DAX"],
}


def bewerte_nachrichten(nachrichten):
    """Ordnet jeder Schlagzeile Themen zu und merkt an, welche Maerkte betroffen sind."""
    for n in nachrichten:
        klein = n["titel"].lower()
        n["themen"] = sorted({th for th, woerter in THEMEN.items()
                              if any(w in klein for w in woerter)})
        betroffen = set()
        for th in n["themen"]:
            betroffen.update(m for m in THEMA_TRIFFT.get(th, []) if m in MAERKTE)
        n["betrifft"] = sorted(betroffen)
    relevant = [n for n in nachrichten if n["themen"]]
    # Zuerst, was deine gehaltenen Werte betrifft; dann nach Anzahl Treffer.
    relevant.sort(key=lambda n: (len(n["betrifft"]), len(n["themen"])), reverse=True)
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
    # Betrifft die Meldung etwas, das du haeltst? Dann hervorheben.
    marken = ""
    for m in n["betrifft"]:
        klasse = "trifft depot" if m in gehalten_namen else "trifft"
        marken += f'<span class="{klasse}">{m}</span>'
    titel = html_mod.escape(n["titel"])[:120]
    news_html += (f'<div class="nw"><div class="nwt">{titel}</div>'
                  f'<div class="nwm">{n["quelle"]}{tags}{marken}</div></div>')
if not news_html:
    news_html = '<div class="nw"><div class="nwt">Keine Schlagzeilen abrufbar.</div></div>'
betroffen_depot = {m for n in nachrichten[:6] for m in n["betrifft"] if m in gehalten_namen}
hinweis = (f'<div class="dinfo">Betrifft dein Depot: {", ".join(sorted(betroffen_depot))}</div>'
           if betroffen_depot else "")
viktor_details = f'<div class="dtitel">Aktuelle Schlagzeilen</div>{news_html}{hinweis}'

# Echtes Depot bewerten (Wert, Gewinn/Verlust in Euro)
depot_zahlen = None if ONLINE else rechne_depot()   # online: keine Euro-Betraege zeigen
if depot_zahlen:
    d_wert, d_inv, d_gewinn, d_pct = depot_zahlen
    gv_farbe = "var(--green)" if d_gewinn >= 0 else "var(--red)"
    doro_txt = f'&bdquo;Depotwert {d_wert} &euro; &middot; {d_gewinn:+d} &euro; ({d_pct:+.1f}%) seit Kauf.&ldquo;'
    wert_block = f"<div><div class='n'>{d_wert}&euro;</div><div class='l'>Depotwert</div></div>"
    gv_block = f"<div><div class='n' style='color:{gv_farbe}'>{d_gewinn:+d}&euro;</div><div class='l'>Gewinn/Verlust</div></div>"
else:
    d_wert = d_gewinn = d_pct = None
    if ONLINE:
        doro_txt = f'&bdquo;Modus {modus_label}: {len(gehalten_liste)} Wert(e) im Depot. Betraege bleiben privat.&ldquo;'
        wert_block = f"<div><div class='n'>{MODUS_ANZAHL.get(MODUS, 2)}</div><div class='l'>Plaetze</div></div>"
    else:
        doro_txt = f'&bdquo;Modus {modus_label}: ich halte {len(gehalten_liste)} Wert(e), je ~{betrag} &euro;.&ldquo;'
        wert_block = f"<div><div class='n'>{kapital_txt}&euro;</div><div class='l'>Kapital</div></div>"
    gv_block = ""

# Theos Detailbereich: Rangliste nach Staerke - wer waere als naechstes dran?
rang = sorted(ok, key=lambda e: e["momentum"], reverse=True)
theo_details = '<div class="dtitel">Rangliste nach Staerke</div>'
for platz, e in enumerate(rang, 1):
    if e["gehalten"]:
        lage, lfarbe = "im Depot", "var(--green)"
    elif e["ueber"]:
        lage, lfarbe = "im Trend, wartet", "var(--teal)"
    else:
        lage, lfarbe = f"unter der Linie ({e['abstand']:+.1f}%)", "var(--dim)"
    theo_details += (
        f'<div class="rang"><span class="rnr">{platz}</span>'
        f'<span class="rnm">{e["markt"]}</span>'
        f'<span class="rmom">{e["momentum"]:+.1f}%</span>'
        f'<span class="rlage" style="color:{lfarbe}">{lage}</span></div>')

# Clara: diesen Lauf ins Journal schreiben (Grundlage fuer die Kurve)
journal = lies_journal()
eintrag = {
    "tag": jetzt.strftime("%Y-%m-%d"),
    "zeit": jetzt.strftime("%H:%M"),
    "modus": MODUS,
    "gehalten": sorted(gehalten_namen),
    "signale": signale,
    "maerkte": {e["markt"]: {"kurs": e["kurs"], "abstand": e["abstand"],
                             "momentum": e["momentum"], "gehalten": e["gehalten"]}
                for e in ok},
}
if depot_zahlen:
    eintrag["depot"] = {"wert": d_wert, "investiert": d_inv, "gewinn": d_gewinn, "prozent": d_pct}
journal = schreibe_journal(journal, eintrag)
print(f"  Clara: Journal-Eintrag {len(journal)} gespeichert.")

# Kurve der Wertentwicklung (nur wo echte Depotwerte vorliegen)
werte_reihe = [e["depot"]["wert"] for e in journal if e.get("depot")]
kurve_html = baue_kurve(werte_reihe)
tage_gefuehrt = len(journal)
if len(werte_reihe) >= 2:
    seit_start = werte_reihe[-1] - werte_reihe[0]
    kurve_info = f"{len(werte_reihe)} Tage aufgezeichnet &middot; {seit_start:+d} &euro; seit Beginn"
else:
    kurve_info = f"{tage_gefuehrt} Tag(e) aufgezeichnet &middot; Kurve entsteht ab dem 2. Tag"

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

# Dr. Julian Winter: Steuerlage einschaetzen
if depot_zahlen and d_gewinn is not None:
    steuer, rest_frei = schaetze_steuer(d_gewinn)
    if d_gewinn <= 0:
        julian_txt = (f'&bdquo;Aktuell {d_gewinn:+d} &euro; &ndash; kein steuerbarer Gewinn. '
                      f'Freibetrag {SPARERPAUSCHBETRAG} &euro; unangetastet.&ldquo;')
    elif steuer <= 0:
        julian_txt = (f'&bdquo;Gewinn {d_gewinn:+d} &euro; liegt im Freibetrag. '
                      f'Verkauf waere heute steuerfrei; noch {rest_frei:.0f} &euro; Puffer.&ldquo;')
    else:
        julian_txt = (f'&bdquo;Bei Verkauf heute: rund {steuer:.0f} &euro; Steuer auf {d_gewinn} &euro; Gewinn '
                      f'(nach Teilfreistellung).&ldquo;')
else:
    julian_txt = ('&bdquo;Aktien-ETFs: 26,375 % auf 70 % des Gewinns, '
                  f'{SPARERPAUSCHBETRAG} &euro; pro Jahr steuerfrei.&ldquo;')

sina_txt = (f'&bdquo;{len(signale)} Depot-Aenderung(en) heute &ndash; bitte handeln!&ldquo;'
            if signale else '&bdquo;Depot unveraendert &ndash; ich bleibe wachsam.&ldquo;')
rico_txt = ('&bdquo;Modus Offensiv &ndash; groessere Schwankungen sind eingeplant. Augen auf.&ldquo;'
            if MODUS == "offensiv" else '&bdquo;Risiko im Griff &ndash; Gewichtung ausgewogen.&ldquo;')
# Claras Detailbereich: die Wertentwicklungs-Kurve (nur lokal, enthaelt Euro)
clara_details = ""
if not ONLINE and kurve_html:
    clara_details = (f'<div class="dtitel">Wertentwicklung</div>{kurve_html}'
                     f'<div class="dinfo">{kurve_info}</div>')

# Aufbau je Agent: (Symbol, Name, Rolle, Meldung, Status, Statustext, Detailbereich)
sina_details = f'<div class="dtitel">Heute zu tun</div><div class="todo">{tun}</div>'

# ---- Die Agenten formulieren ihre Meldungen selbst (falls KI angebunden) ----
lage_fuer_ki = [f"Modus: {modus_label} (haelt die {anzahl} staerksten im Aufwaertstrend)"]
for e in ok:
    lage_fuer_ki.append(
        f"- {e['markt']}: Kurs {e['kurs']}, {'ueber' if e['ueber'] else 'unter'} der "
        f"200-Tage-Linie ({e['abstand']:+.1f}%), Momentum {e['momentum']:+.1f}%"
        f"{', IM DEPOT' if e['gehalten'] else ''}")
lage_fuer_ki.append("Signale heute: " + ("; ".join(signale) if signale else "keine, Depot unveraendert"))
if depot_zahlen:
    lage_fuer_ki.append(f"Depotwert {d_wert} Euro, Gewinn/Verlust {d_gewinn:+d} Euro ({d_pct:+.1f}%)")
    _steuer, _frei = schaetze_steuer(d_gewinn)
    lage_fuer_ki.append(f"Steuer bei Verkauf heute: {_steuer:.0f} Euro, Freibetrag-Rest {_frei:.0f} Euro")
lage_fuer_ki.append(f"Journal: {tage_gefuehrt} Tag(e) aufgezeichnet")
lage_fuer_ki.append(f"Naechster an der Linie: {nah_txt}")
if nachrichten:
    lage_fuer_ki.append("Schlagzeilen: " + " | ".join(n["titel"] for n in nachrichten[:4]))
    if betroffen_depot:
        lage_fuer_ki.append("Davon betrifft dein Depot: " + ", ".join(sorted(betroffen_depot)))

ki_saetze = frage_ki("\n".join(lage_fuer_ki))

# Georg prueft die Nachrichtenlage auf heisse Eisen
georg = frage_georg(nachrichten, "\n".join(lage_fuer_ki))
if georg:
    georg_txt = "&bdquo;" + html_mod.escape(georg.get("meldung", "").strip()) + "&ldquo;"
    if georg.get("auslöser"):
        farbe = {"gluehend": "var(--red)", "heiss": "#e8a33d",
                 "lauwarm": "var(--teal)", "kalt": "var(--dim)"}.get(georg.get("hitze"), "var(--teal)")
        werte = "".join(f'<span class="tag">{html_mod.escape(w)}</span>'
                        for w in georg.get("werte", [])[:6])
        georg_details = (
            f'<div class="dtitel">Heisses Eisen &middot; '
            f'<span style="color:{farbe}">{html_mod.escape(georg.get("hitze","")).upper()}</span></div>'
            f'<div style="font-size:12.5px;line-height:1.5;margin-bottom:8px">'
            f'{html_mod.escape(georg.get("thema",""))}</div>'
            f'<div class="nwm" style="margin-bottom:10px">{werte}</div>'
            f'<div class="dtitel">Was dagegen spricht</div>'
            f'<div style="font-size:12px;color:var(--muted);line-height:1.5">'
            f'{html_mod.escape(georg.get("dagegen",""))}</div>')
        georg_status, georg_label = "ready", "Witterung"
    else:
        georg_details = ('<div class="dinfo">Heute kein Auslöser in den Schlagzeilen. '
                         'Georg meldet sich nur, wenn wirklich etwas in Bewegung kommt.</div>')
        georg_status, georg_label = "soon", "Ruhig"
else:
    georg_txt = '&bdquo;Ich halte die Augen offen, komme aber gerade nicht an die Nachrichten.&ldquo;'
    georg_details, georg_status, georg_label = "", "soon", "Ruhig"


def meldung(name, standard):
    """Nimmt den KI-Satz, wenn vorhanden - sonst den festen Text."""
    if ki_saetze and ki_saetze.get(name):
        return "&bdquo;" + html_mod.escape(ki_saetze[name].strip()) + "&ldquo;"
    return standard


# Stimmen als Dateien vorproduzieren, damit sie ueberall klingen -
# auch online, wo der Agenten-Server nicht erreichbar ist.
stimmen_da = set()
if STIMM_SCHLUESSEL:
    for _name in OPENAI_STIMMEN:
        # Georgs Meldung entsteht getrennt von den uebrigen Agenten
        _text = (georg or {}).get("meldung", "") if _name == "Georg" \
            else (ki_saetze or {}).get(_name, "")
        if _text and erzeuge_stimmdatei(_name, _text.strip()):
            stimmen_da.add(_name)
    if stimmen_da:
        print(f"  Stimmen vorproduziert: {len(stimmen_da)} Agenten "
              f"(~{len(stimmen_da) * 0.005:.2f} USD)")


# Jeder Agent bekommt eine eigene Stimme + Sprechweise (Tempo, Tonhoehe).
# Faellt eine Stimme aus, greift die naechste in der Liste.
STIMMEN = {
    "Theo":    ("Reed",    0.98, 0.95),   # ruhig, sachlich
    "Sina":    ("Sandy",   1.10, 1.10),   # wach, aufmerksam
    "Doro":    ("Shelley", 1.00, 1.02),   # freundlich, gelassen
    "Rico":    ("Rocko",   0.92, 0.85),   # tief, warnend
    "Mira":    ("Flo",     1.05, 1.08),   # neugierig
    "Clara":   ("Grandma", 0.95, 1.00),   # bedaechtig, erzaehlend
    "Viktor":  ("Eddy",    1.02, 0.92),   # nachrichtensprecher-artig
    "Winter":  ("Grandpa", 0.90, 0.88),   # aelter, seriös - der Jurist
    "Georg":   ("Rocko",   1.10, 1.02),   # offensiv, wach - der Gambler
}

agenten = [
    ("&#128200;", "Theo", "Trend-Waechter &middot; taeglich",
     meldung("Theo", f'&bdquo;{len(ueber_liste)} von {len(ok)} Maerkten im Aufwaertstrend. Ich ranke sie nach Staerke.&ldquo;'),
     "ready", "Bereit", f'<div class="dtitel">Markt-Ampel</div><div class="amp">{ampel}</div>{theo_details}'),
    ("&#128276;", "Sina", "Signalgeberin &middot; bei Depot-Aenderung",
     meldung("Sina", sina_txt), "ready", "Bereit", sina_details),
    ("&#128188;", "Doro", "Depot-Verwalterin &middot; laufend",
     meldung("Doro", doro_txt), "ready", "Bereit", ""),
    ("&#128737;", "Rico", "Risiko-Waechter &middot; Veto",
     meldung("Rico", rico_txt), "ready", "Bereit", ""),
    ("&#128301;", "Mira", "Markt-Beobachterin &middot; Fruehwarnung",
     meldung("Mira", f'&bdquo;Am naechsten an der Linie: {nah_txt}. Den beobachte ich genau.&ldquo;'),
     "ready", "Bereit", ""),
    ("&#128221;", "Clara", "Chronistin &middot; Journal",
     meldung("Clara", f'&bdquo;{tage_gefuehrt} Tag(e) im Journal. Letzter Eintrag: {jetzt.strftime("%d.%m. %H:%M")}.&ldquo;'),
     "ready", "Bereit", clara_details),
    ("&#127758;", "Viktor", "Welt-Stratege &middot; Nachrichten",
     meldung("Viktor", f'&bdquo;{len(nachrichten)} relevante Schlagzeilen gesichtet. Thema heute: {themen_txt}.&ldquo;'),
     "ready", "Bereit", viktor_details),
    ("&#9878;", "Dr. Julian Winter", "Jurist &middot; Recht &amp; Steuern",
     meldung("Winter", julian_txt), "ready", "Bereit", ""),
    ("&#127922;", "Georg", "Der Gambler &middot; heisse Eisen",
     georg_txt, georg_status, georg_label, georg_details),
]
agent_html = ""
for ic, nm, role, last, scls, slabel, details in agenten:
    breit = ""                             # alle Agenten gleich gross
    detail_html = f'<div class="details">{details}</div>' if details else ""
    kurz = nm.split()[-1] if nm.startswith("Dr.") else nm     # "Winter" statt "Dr. Julian Winter"
    # Notizfeld: du kannst jedem Agenten etwas hinterlassen (wird im Browser gemerkt)
    notiz_html = (f'<div class="notiz"><div class="nlist" id="nl-{kurz}"></div>'
                  f'<div class="nrow">'
                  f'<button class="mic" title="Nachricht einsprechen" '
                  f'onclick="diktat(this,\'{kurz}\')">&#127908;</button>'
                  f'<input class="nin" id="ni-{kurz}" '
                  f'placeholder="Sprich oder tippe an {kurz} ..." '
                  f'onkeydown="if(event.key===\'Enter\')notiz(\'{kurz}\')">'
                  f'<button class="nbtn" onclick="notiz(\'{kurz}\')">Senden</button></div></div>')
    # Text zum Vorlesen aufbereiten - klingt so natuerlicher
    gesprochen = re.sub(r"<[^>]+>", "", last)
    gesprochen = html_mod.unescape(gesprochen)
    for weg, hin in [("„", ""), ("“", ""), ("–", ","), ("&", " und "), ("%", " Prozent"),
                     ("€", " Euro"), ("ue", "ü"), ("ae", "ä"), ("oe", "ö")]:
        gesprochen = gesprochen.replace(weg, hin)
    gesprochen = re.sub(r"\s+", " ", gesprochen).replace("'", "").strip()
    stimme, tempo, hoehe = STIMMEN.get(kurz, ("", 1.0, 1.0))
    agent_html += f'''<div class="card{breit}"><div class="row1"><div class="ic">{ic}</div>
    <span class="status {scls}"><span class="dot"></span>{slabel}</span></div>
    <h3>{nm}<button class="vor" title="Vorlesen lassen" data-agent="{kurz}"
      onclick="sprich(this,'{gesprochen}','{stimme}',{tempo},{hoehe},'{kurz}')">&#128266;</button></h3><div class="role">{role}</div>
    <div class="last"><b>Zuletzt:</b> {last}</div>{detail_html}{notiz_html}</div>'''

feed_items = [
    ("Th", jetzt.strftime("%H:%M") + " &middot; Theo",
     f'Modus {modus_label}. {len(ueber_liste)} von {len(ok)} Maerkten im Aufwaertstrend - ich ranke nach Staerke.'),
    ("Si", jetzt.strftime("%H:%M") + " &middot; Sina",
     ("Es gibt was zu tun: " + "; ".join(signale)) if signale else "Depot unveraendert - heute nichts zu tun."),
    ("Do", jetzt.strftime("%H:%M") + " &middot; Doro",
     f'Depot: {haltetext}.' + ('' if ONLINE else f' Vorschlag je ~{betrag} Euro pro Wert.')),
    ("Cl", jetzt.strftime("%H:%M") + " &middot; Clara",
     f'Eintrag {tage_gefuehrt} ins Journal geschrieben. Ich sammle deine Historie.'),
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
.brain .orb{width:52px;height:52px;border-radius:13px;background:var(--greenbg);display:flex;align-items:center;justify-content:center;color:var(--green);font-size:22px;flex-shrink:0;overflow:hidden}
.brain .orb img,.brain .orb svg{width:34px;height:34px;object-fit:contain}
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
.card h3{font-size:22px;font-weight:700;letter-spacing:-.2px;display:flex;align-items:center;gap:8px}
.card .role{font-size:10px;letter-spacing:.6px;text-transform:uppercase;color:var(--teal);margin:4px 0 11px}
.vor{background:none;border:0;color:var(--dim);cursor:pointer;font-size:15px;padding:2px 4px;line-height:1;border-radius:6px}
.vor:hover{color:var(--teal);background:var(--panel2)}
.vor.aktiv{color:var(--green)}
.teamzeile{display:flex;align-items:center;gap:14px;margin:0 0 14px;flex-wrap:wrap}
.briefbtn{margin-left:auto;background:var(--greenbg);color:var(--green);border:0;border-radius:20px;
padding:6px 14px;font-size:11.5px;font-weight:600;font-family:inherit;cursor:pointer}
.briefbtn:hover{background:rgba(62,207,142,.2)}
.briefbtn.aktiv{background:var(--green);color:var(--bg)}
.card .last{margin-top:6px;padding-top:11px;border-top:1px solid var(--line);font-size:11.5px;color:var(--dim)}
.card .last b{color:var(--muted)}
.sysgrid{display:grid;grid-template-columns:1fr 1fr 1.4fr;gap:14px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}
.tile h4{font-size:13px;font-weight:600;margin-bottom:6px}
.amp{display:grid;grid-template-columns:repeat(5,1fr);gap:5px;margin:8px 0 4px}
.amp .m{text-align:center;background:var(--panel2);border-radius:8px;padding:7px 2px;min-width:0}
.amp .m .dot{width:8px;height:8px;border-radius:50%;margin:0 auto 4px}
.amp .m .nm{font-size:9.5px;font-weight:600;line-height:1.2;word-break:break-word}
.amp .m .st{font-size:8.5px;color:var(--dim);margin-top:2px;line-height:1.2}
.g .dot{background:var(--green);box-shadow:0 0 10px rgba(62,207,142,.5)}
.r .dot{background:var(--red);box-shadow:0 0 10px rgba(229,100,90,.5)}
.amp .m.held{box-shadow:inset 0 0 0 1px var(--green)}
.tile .todo{font-size:12.5px;color:var(--muted);margin-top:8px;line-height:1.7}
.feed .f{display:flex;gap:11px;padding:9px 0;border-bottom:1px solid var(--line)}
.feed .f:last-child{border-bottom:0}
.feed .av{width:26px;height:26px;border-radius:7px;background:var(--panel2);display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:var(--teal)}
.feed .fmeta{font-size:10px;color:var(--dim);margin-bottom:2px}.feed .ftxt{font-size:12px}
/* Alle Agenten gleich gross - gleiches Raster, gleiche Hoehe */
.grid{grid-template-columns:repeat(auto-fill,minmax(330px,1fr));align-items:stretch;gap:14px}
.card{display:flex;flex-direction:column;height:440px}
.card .details{flex:1;min-height:0;overflow-y:auto}
.card .notiz{margin-top:auto;flex-shrink:0}
.card .details::-webkit-scrollbar{width:5px}
.card .details::-webkit-scrollbar-thumb{background:var(--line);border-radius:3px}
@media(max-width:700px){.card{height:auto;min-height:340px}}
.details{margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}
.dtitel{font-size:10px;letter-spacing:.6px;text-transform:uppercase;color:var(--dim);margin-bottom:7px;font-weight:600}
.dinfo{font-size:10.5px;color:var(--dim);margin-top:4px}
.nw{padding:8px 0;border-bottom:1px solid var(--line)}
.nw:last-child{border-bottom:0;padding-bottom:0}
.nwt{font-size:12.5px;line-height:1.45}
.nwm{font-size:10px;color:var(--dim);margin-top:3px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.tag{background:rgba(75,182,201,.14);color:var(--teal);padding:1px 6px;border-radius:20px;font-weight:600;letter-spacing:.3px}
.trifft{background:rgba(131,149,167,.16);color:var(--muted);padding:1px 6px;border-radius:20px;font-weight:600}
.trifft.depot{background:var(--greenbg);color:var(--green)}
.rang{display:flex;align-items:center;gap:9px;padding:6px 0;border-bottom:1px solid var(--line);font-size:12px}
.rang:last-child{border-bottom:0}
.rnr{width:16px;color:var(--dim);font-size:10.5px}
.rnm{font-weight:600;min-width:74px}
.rmom{color:var(--muted);min-width:52px;text-align:right;font-variant-numeric:tabular-nums}
.rlage{font-size:10.5px;margin-left:auto}
.notiz{margin-top:12px;padding-top:11px;border-top:1px solid var(--line)}
.nlist{margin-bottom:7px}
.nmsg{font-size:11.5px;color:var(--muted);background:var(--panel2);border-radius:8px;padding:6px 9px;margin-bottom:5px;display:flex;gap:8px;align-items:flex-start}
.nmsg time{color:var(--dim);font-size:9.5px;white-space:nowrap;margin-left:auto}
.nmsg.agent{background:var(--greenbg);color:var(--ink);border-left:2px solid var(--green)}
.nmsg.denkt{opacity:.65;font-style:italic}
.nlist{max-height:230px;overflow-y:auto}
.nrow{display:flex;gap:6px}
.nin{flex:1;background:var(--panel2);border:1px solid var(--line);border-radius:8px;color:var(--ink);
padding:7px 10px;font-size:11.5px;font-family:inherit;min-width:0}
.nin::placeholder{color:var(--dim)}
.nin:focus{outline:none;border-color:var(--teal)}
.nbtn{background:var(--greenbg);color:var(--green);border:0;border-radius:8px;padding:7px 12px;
font-size:11.5px;font-weight:600;font-family:inherit;cursor:pointer}
.nbtn:hover{background:rgba(62,207,142,.2)}
.mic{background:var(--panel2);border:1px solid var(--line);border-radius:8px;color:var(--muted);
padding:6px 10px;font-size:14px;cursor:pointer;line-height:1;flex-shrink:0}
.mic:hover{border-color:var(--teal);color:var(--teal)}
.mic.aktiv{background:var(--red);border-color:var(--red);color:#fff;animation:puls 1.1s ease-in-out infinite}
@keyframes puls{0%,100%{opacity:1}50%{opacity:.55}}
@media(max-width:600px){.card.weit{grid-column:span 1}}
footer{margin-top:28px;color:var(--dim);font-size:11px;text-align:center}
@media(max-width:820px){.sysgrid{grid-template-columns:1fr}}
"""

# Notizen bleiben im Browser gespeichert (auch nach dem naechsten Lauf).
NOTIZ_SKRIPT = """<script>
var STIMMEN=__STIMMEN__;
var VORPRODUZIERT=__VORPRODUZIERT__;
var AUDIO=__AUDIO__;      /* Stimmen direkt in dieser Datei - laeuft ueberall */
function notizen(){try{return JSON.parse(localStorage.getItem('tb_notizen')||'{}')}catch(e){return {}}}
function zeige(wer){
  var box=document.getElementById('nl-'+wer); if(!box)return;
  var alle=(notizen()[wer]||[]).slice(-6);
  box.innerHTML=alle.map(function(n){
    var k=(n.von==='agent')?'nmsg agent':'nmsg';
    return '<div class="'+k+'"><span>'+n.text.replace(/[<>&]/g,'')+'</span><time>'+n.zeit+'</time></div>';
  }).join('');
  box.scrollTop=box.scrollHeight;
}
function merke(wer,text,von){
  var alle=notizen(); alle[wer]=alle[wer]||[];
  var d=new Date();
  alle[wer].push({text:text, von:von||'ich',
    zeit:('0'+d.getDate()).slice(-2)+'.'+('0'+(d.getMonth()+1)).slice(-2)+'. '
    +('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)});
  alle[wer]=alle[wer].slice(-20);
  localStorage.setItem('tb_notizen',JSON.stringify(alle));
  zeige(wer);
}
function notiz(wer){
  var feld=document.getElementById('ni-'+wer); if(!feld)return;
  var text=feld.value.trim(); if(!text)return;
  merke(wer,text,'ich');
  feld.value='';
  frageAgent(wer,text);
}
/* --- Dialog: die Frage an den Agenten-Server auf deinem Mac schicken --- */
function frageAgent(wer,text){
  var box=document.getElementById('nl-'+wer); if(!box)return;
  var warte=document.createElement('div');
  warte.className='nmsg agent denkt';
  warte.innerHTML='<span>'+wer+' denkt nach ...</span>';
  box.appendChild(warte);
  fetch('http://localhost:8765',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({agent:wer,frage:text})})
   .then(function(r){return r.json()})
   .then(function(d){
     warte.remove();
     var antwort=(d && d.antwort) ? d.antwort : 'Ich konnte gerade nicht antworten.';
     merke(wer,antwort,'agent');
     var s=STIMMEN[wer]||['',1,1];
     sprich(null,antwort,s[0],s[1],s[2],wer);
   })
   .catch(function(){
     warte.remove();
     merke(wer,'Ich bin gerade nicht erreichbar - starte den Agenten-Server auf deinem Mac (python3 agenten_server.py), dann antworte ich dir.','agent');
   });
}
document.querySelectorAll('.nlist').forEach(function(b){zeige(b.id.slice(3))});

/* --- Sprachausgabe: jeder Agent hat seine eigene Stimme --- */
function findeStimme(wunsch){
  var s=window.speechSynthesis.getVoices();
  var de=s.filter(function(v){return v.lang.indexOf('de')===0});
  if(wunsch){var t=de.find(function(v){return v.name.indexOf(wunsch)===0}); if(t)return t;}
  return de[0]||null;
}
function stoppAlles(){
  if('speechSynthesis' in window)window.speechSynthesis.cancel();
  if(LAUFENDES_AUDIO){try{LAUFENDES_AUDIO.pause()}catch(e){} LAUFENDES_AUDIO=null}
  document.querySelectorAll('.vor.aktiv,.briefbtn.aktiv').forEach(function(b){b.classList.remove('aktiv')});
}
/* Echte Stimme vom Agenten-Server holen (OpenAI). Klappt das nicht,
   nimmt sprichMac() die eingebaute Mac-Stimme. */
var LAUFENDES_AUDIO=null;
function sprich(knopf,text,stimme,tempo,hoehe,wer){
  var lief=knopf && knopf.classList.contains('aktiv');
  stoppAlles();
  if(lief)return;
  if(knopf)knopf.classList.add('aktiv');
  var name=wer||(knopf?knopf.getAttribute('data-agent'):null);
  function fertig(){ if(knopf)knopf.classList.remove('aktiv') }
  function spieleDatei(){
    /* Vorproduzierte Stimme (funktioniert auch online) */
    if(!name||VORPRODUZIERT.indexOf(name)<0){ sprichMac(knopf,text,stimme,tempo,hoehe); return }
    var audio=new Audio(AUDIO[name]||('stimmen/'+name+'.mp3'));
    LAUFENDES_AUDIO=audio;
    audio.onended=fertig;
    audio.onerror=function(){ sprichMac(knopf,text,stimme,tempo,hoehe) };
    audio.play().catch(function(){ sprichMac(knopf,text,stimme,tempo,hoehe) });
  }
  if(name && location.protocol.indexOf('http')===0){
    /* Zuerst die Live-Stimme vom Agenten-Server versuchen */
    fetch('/stimme',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({agent:name,text:text})})
     .then(function(r){ if(r.status!==200)throw 0; return r.blob() })
     .then(function(b){
       var audio=new Audio(URL.createObjectURL(b));
       LAUFENDES_AUDIO=audio; audio.onended=fertig; audio.onerror=fertig;
       audio.play();
     })
     .catch(spieleDatei);
    return;
  }
  spieleDatei();
}
function sprichMac(knopf,text,stimme,tempo,hoehe){
  if(!('speechSynthesis' in window)){if(knopf)knopf.classList.remove('aktiv');return}
  var a=new SpeechSynthesisUtterance(text);
  a.lang='de-DE'; a.rate=tempo||1; a.pitch=hoehe||1;
  var st=findeStimme(stimme); if(st)a.voice=st;
  if(knopf){knopf.classList.add('aktiv');
    a.onend=function(){knopf.classList.remove('aktiv')};
    a.onerror=function(){knopf.classList.remove('aktiv')};}
  window.speechSynthesis.speak(a);
}
/* Lagebericht: jeder Agent spricht nacheinander mit SEINER Stimme */
function briefing(knopf){
  if(!('speechSynthesis' in window))return;
  var lief=knopf.classList.contains('aktiv');
  stoppAlles();
  if(lief)return;
  knopf.classList.add('aktiv');
  var teile=[];
  document.querySelectorAll('.card h3 .vor').forEach(function(b){
    var m=b.getAttribute('onclick').match(/sprich\\(this,'([^']*)','([^']*)',([\\d.]+),([\\d.]+),'([^']*)'\\)/);
    if(m)teile.push({text:m[1],stimme:m[2],tempo:parseFloat(m[3]),hoehe:parseFloat(m[4]),wer:m[5]});
  });
  var i=0;
  function weiter(){
    if(i>=teile.length||!knopf.classList.contains('aktiv')){knopf.classList.remove('aktiv');return}
    var t=teile[i++];
    /* Echte Stimme versuchen, sonst Mac-Stimme */
    if(location.protocol.indexOf('http')===0){
      fetch('/stimme',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({agent:t.wer,text:t.text})})
       .then(function(r){ if(r.status!==200)throw 0; return r.blob() })
       .then(function(b){
         var audio=new Audio(URL.createObjectURL(b));
         LAUFENDES_AUDIO=audio; audio.onended=weiter; audio.onerror=weiter; audio.play();
       })
       .catch(function(){ dateiStueck(t) });
    } else { dateiStueck(t) }
  }
  function dateiStueck(t){
    if(VORPRODUZIERT.indexOf(t.wer)<0){ macStueck(t); return }
    var audio=new Audio(AUDIO[t.wer]||('stimmen/'+t.wer+'.mp3'));
    LAUFENDES_AUDIO=audio; audio.onended=weiter;
    audio.onerror=function(){ macStueck(t) };
    audio.play().catch(function(){ macStueck(t) });
  }
  function macStueck(t){
    var a=new SpeechSynthesisUtterance(t.text);
    a.lang='de-DE'; a.rate=t.tempo; a.pitch=t.hoehe;
    var st=findeStimme(t.stimme); if(st)a.voice=st;
    a.onend=weiter; a.onerror=weiter;
    window.speechSynthesis.speak(a);
  }
  weiter();
}
if('speechSynthesis' in window){window.speechSynthesis.onvoiceschanged=function(){}}

/* --- Spracheingabe: Nachricht einsprechen statt tippen --- */
var Erkennung = window.SpeechRecognition || window.webkitSpeechRecognition;
function diktat(knopf,wer){
  if(!Erkennung){alert('Spracheingabe braucht Safari oder Chrome.');return}
  var feld=document.getElementById('ni-'+wer); if(!feld)return;
  if(knopf.classList.contains('aktiv')){if(knopf._r)knopf._r.stop();return}
  var r=new Erkennung();
  r.lang='de-DE'; r.interimResults=true; r.continuous=false;
  knopf.classList.add('aktiv'); knopf._r=r;
  r.onresult=function(e){
    var t='';
    for(var i=0;i<e.results.length;i++)t+=e.results[i][0].transcript;
    feld.value=t;
  };
  r.onend=function(){knopf.classList.remove('aktiv'); if(feld.value.trim())notiz(wer)};
  r.onerror=function(){knopf.classList.remove('aktiv')};
  r.start();
}
</script>"""

# Dein Logo - als Vektorgrafik, damit es in jeder Groesse scharf bleibt.
# Dein Logo: liegt es als Datei neben diesem Programm, wird es eingebettet.
# Sonst erscheint das schlichte Rauten-Zeichen.
def lies_logo():
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo.svg"):
        pfad = os.path.join(HIER, name)
        if os.path.exists(pfad):
            if name.endswith(".svg"):
                return open(pfad, encoding="utf-8").read()
            import base64, mimetypes
            typ = mimetypes.guess_type(pfad)[0] or "image/png"
            b64 = base64.b64encode(open(pfad, "rb").read()).decode("ascii")
            return f"<img src='data:{typ};base64,{b64}' alt='Logo'>"
    return "&#9670;"


LOGO = lies_logo()


def eingebettete_stimmen():
    """Packt die vorproduzierten Stimmen direkt in die Dashboard-Datei,
    damit sie ueberall funktionieren - auch online, ohne Extra-Ordner."""
    import base64
    audio = {}
    if not os.path.isdir(STIMMEN_ORDNER):
        return audio
    for name in OPENAI_STIMMEN:
        pfad = os.path.join(STIMMEN_ORDNER, f"{name}.mp3")
        if os.path.exists(pfad):
            b64 = base64.b64encode(open(pfad, "rb").read()).decode("ascii")
            audio[name] = "data:audio/mpeg;base64," + b64
    return audio

html = ("<!DOCTYPE html><html lang='de'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Trading Brain</title><style>" + CSS + "</style></head><body>"
        f"<h1>{gruss}, <span class='accent'>Kilian</span>.</h1>"
        f"<div class='sub'>Trading Brain &middot; Lagecheck vom {jetzt.strftime('%d.%m.%Y %H:%M')}</div>"
        "<div class='brain'><div class='orb'>" + LOGO + "</div><div>"
        f"<h2>Trading Brain</h2><div class='bs'>Modell 2.0 &middot; Momentum-Ranking &middot; Modus {modus_label}</div>"
        "<p>Rankt taeglich deine Maerkte nach Staerke und haelt die besten im Aufwaertstrend. Meldet, sobald sich dein Depot aendern soll.</p></div>"
        "<div class='stats'>"
        f"<div><div class='n' style='color:var(--green)'>{len(gehalten_liste)}/{len(ok)}</div><div class='l'>im Depot</div></div>"
        f"<div><div class='n'>{len(signale)}</div><div class='l'>Signale heute</div></div>"
        f"{wert_block}{gv_block}"
        "</div></div>"
        "<div class='teamzeile'><div class='eyebrow' style='margin:0'>// Dein Team</div>"
        "<button class='briefbtn' onclick='briefing(this)'>&#128266; Lagebericht anhoeren</button></div>"
        f"<div class='grid'>{agent_html}</div>"
        "<div class='eyebrow'>// Team-Funk</div>"
        f"<div class='tile'><div class='feed'>{feed_html}</div></div>"
        "<footer>Automatisch erzeugt von deinem trading_brain-Programm &middot; echte Kursdaten</footer>"
        + NOTIZ_SKRIPT.replace("__STIMMEN__", json.dumps(STIMMEN))
                      .replace("__VORPRODUZIERT__", json.dumps(sorted(stimmen_da)))
                      .replace("__AUDIO__", json.dumps(eingebettete_stimmen())) +
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
