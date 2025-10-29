# Ofen-Dashboard: alle Öfen/Herde untereinander mit Gantt + Temperatur
# Vollständig funktionierende Version mit eingebettetem Plotly-JS
# ---------------------------------------------------------------
# Voraussetzung: pip install pandas plotly

import pandas as pd
import re
from datetime import datetime
import plotly.graph_objects as go

# ---------------------------------------------------------------
# 1. CSV laden
# ---------------------------------------------------------------
file_path = "Ofenauswertung.csv"

# Automatisch Encoding und Trennzeichen erkennen
encodings = ["utf-8-sig", "cp1252", "latin1"]
seps = [";", ",", "\t"]
df = None
for enc in encodings:
    for sep in seps:
        try:
            tmp = pd.read_csv(file_path, sep=sep, encoding=enc)
            if tmp.shape[1] > 4:
                df = tmp
                break
        except Exception:
            continue
    if df is not None:
        break

if df is None:
    raise Exception("❌ CSV konnte nicht eingelesen werden – prüfe Trennzeichen oder Encoding.")

# ---------------------------------------------------------------
# 2. Relevante Spalten finden und bereinigen
# ---------------------------------------------------------------
def find_col(keys):
    for c in df.columns:
        if any(k.lower() in c.lower() for k in keys):
            return c
    return None

col_time = find_col(["Datum", "Zeit"])
col_dev = find_col(["Ger", "Gerät", "Ger„t"])
col_msg = find_col(["Meld"])
col_soll = find_col(["Soll"])
col_ist = find_col(["Ist"])

df = df.rename(columns={
    col_time: "Datum/Zeit",
    col_dev: "Gerät",
    col_msg: "Meldung",
    col_soll: "Soll °C",
    col_ist: "Ist °C"
})

# Zeitparsing
def parse_timestamp(s):
    s = str(s)
    try:
        parts = s.split(",")
        if len(parts) >= 3:
            return datetime.strptime(f"{parts[0]} {parts[1]}.{parts[2]}", "%y/%m/%d %H:%M:%S.%f")
    except:
        pass
    return pd.to_datetime(s, dayfirst=True, errors="coerce")

df["timestamp"] = df["Datum/Zeit"].apply(parse_timestamp)
df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

# ---------------------------------------------------------------
# 3. Gerät + Herd extrahieren
# ---------------------------------------------------------------
def parse_device(dev):
    m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", str(dev))
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return str(dev), ""

df[["device_type", "device_id"]] = df["Gerät"].apply(lambda x: pd.Series(parse_device(x)))

# Bereinigung: Geräte ohne Namen aber mit ID automatisch als MIWE gateway setzen
def clean_device_type(row):
    device_type = str(row.device_type).strip()
    device_id = str(row.device_id).strip()
    
    # Wenn kein Name aber ID im Format "X/Y" vorhanden ist -> MIWE gateway
    if (not device_type or device_type == "0" or device_type == "nan") and device_id and "/" in device_id:
        return "MIWE gateway"
    return device_type

df["device_type"] = df.apply(clean_device_type, axis=1)

def extract_herd(msg):
    m = re.search(r"Herd\s*([0-9]+)", str(msg))
    return f"Herd {m.group(1)}" if m else None

df["herd"] = df["Meldung"].apply(extract_herd)

def make_row_name(row):
    if "miwe ideal tc" in str(row.device_type).lower():
        return f"{row.device_type} ({row.device_id}) - {row.herd or 'kein Herd'}"
    return f"{row.device_type} ({row.device_id})"

df["row_name"] = df.apply(make_row_name, axis=1)

# ---------------------------------------------------------------
# 4. Programmphasen bestimmen + Programmnummern extrahieren
# ---------------------------------------------------------------
df["is_loaded"] = df["Meldung"].str.contains("Arbeitsprog", case=False, na=False)
df["is_started"] = df["Meldung"].str.contains("Programm gestartet", case=False, na=False)
df["is_ended"] = df["Meldung"].str.contains("Programmende|Programm beendet|Programm gestoppt", case=False, na=False)

# Funktion: Programmnummer aus Meldung extrahieren (z.B. "P1", "Programm 123" -> "P123")
def extract_program_number(msg):
    msg_str = str(msg)
    # Suche nach "P" gefolgt von Ziffern
    m = re.search(r"P\s*(\d+)", msg_str, re.IGNORECASE)
    if m:
        return f"P{m.group(1)}"
    # Alternativ: "Programm 123" oder "Prog 123"
    m = re.search(r"(?:Programm|Prog)\s+(\d+)", msg_str, re.IGNORECASE)
    if m:
        return f"P{m.group(1)}"
    return None

df["prog_num"] = df["Meldung"].apply(extract_program_number)

preheats = []
runs = []  # jetzt: (name, start, end, prog_num)
for name, g in df.groupby("row_name"):
    g = g.sort_values("timestamp")
    t_load = t_start = prog_num = None
    for _, r in g.iterrows():
        t = r["timestamp"]
        # Programmnummer merken, wenn vorhanden
        if r["prog_num"]:
            prog_num = r["prog_num"]
        
        if r["is_loaded"]:
            t_load = t
        if r["is_started"]:
            if t_load:
                preheats.append((name, t_load, t))
                t_load = None
            t_start = t
        if r["is_ended"] and t_start:
            runs.append((name, t_start, t, prog_num))
            t_start = None
            prog_num = None  # Reset für nächsten Run

# ---------------------------------------------------------------
# 5. Diagramme pro Ofen/Herd erstellen
# ---------------------------------------------------------------
# Bessere Sortierung: Nach Gerätetyp und ID, dann Herd
def smart_sort_key(row_name):
    """Sortiert Geräte logisch: zuerst nach Typ, dann nach ID-Nummer, dann nach Herd"""
    # Parse row_name: z.B. "MIWE gateway (2/1)" oder "MIWE ideal TC (1/1) - Herd 1"
    parts = row_name.split(" - ")
    base = parts[0]  # z.B. "MIWE ideal TC (1/1)"
    herd = parts[1] if len(parts) > 1 else ""
    
    # Extrahiere Gerätetyp und ID
    match = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", base)
    if match:
        device_type = match.group(1).strip().lower()
        device_id = match.group(2).strip()
    else:
        device_type = base.lower()
        device_id = ""
    
    # Filtere ungültige/leere Geräte ans Ende
    if not device_type or device_type == "0" or device_type == "nan" or not device_id:
        return ("zzz_invalid", [9999], 9999)
    
    # Extrahiere Zahlen aus device_id für numerische Sortierung (z.B. "2/1" -> [2, 1])
    id_numbers = [int(x) if x.isdigit() else 0 for x in re.findall(r'\d+', device_id)]
    if not id_numbers:
        id_numbers = [9999]  # Geräte ohne Nummer ans Ende
    
    # Extrahiere Herd-Nummer falls vorhanden
    herd_match = re.search(r"Herd\s*(\d+)", herd)
    herd_num = int(herd_match.group(1)) if herd_match else 0
    
    # Sortierung: (Gerätetyp, ID-Zahlen, Herd-Nummer)
    return (device_type, id_numbers, herd_num)

html_parts = []
all_names = sorted(df["row_name"].unique(), key=smart_sort_key)

# Debug: Zeige die Reihenfolge
print(f"\n📋 Geräte-Reihenfolge im Dashboard ({len(all_names)} Geräte):")
for i, name in enumerate(all_names, 1):
    print(f"  {i}. {name}")
print()

for name in all_names:
    subset = df[df["row_name"] == name].copy()
    if subset.empty:
        continue

    subset["Ist °C"] = pd.to_numeric(subset["Ist °C"].astype(str).str.replace(",", "."), errors="coerce")
    subset["Soll °C"] = pd.to_numeric(subset["Soll °C"].astype(str).str.replace(",", "."), errors="coerce")

    fig = go.Figure()

    # Temperaturkurven
    if subset["Ist °C"].notna().any():
        fig.add_trace(go.Scatter(
            x=subset["timestamp"], y=subset["Ist °C"],
            mode="lines", name="Ist °C", line=dict(color="orange", width=2)
        ))

    if subset["Soll °C"].notna().any():
        fig.add_trace(go.Scatter(
            x=subset["timestamp"], y=subset["Soll °C"],
            mode="lines", name="Soll °C", line=dict(color="blue", dash="dot", width=1.5)
        ))

    # Vorheizen/Laufzeit-Balken + Programmnummer-Annotations
    for n, s, e in preheats:
        if n == name:
            fig.add_shape(type="rect", x0=s, x1=e, y0=0, y1=1,
                          xref="x", yref="paper", fillcolor="rgba(255,0,0,0.3)", line=dict(width=0))
    
    for item in runs:
        n = item[0]
        s = item[1]
        e = item[2]
        prog_num = item[3] if len(item) > 3 else None
        
        if n == name:
            # Grünes Rechteck für Programm-Run
            fig.add_shape(type="rect", x0=s, x1=e, y0=0, y1=1,
                          xref="x", yref="paper", fillcolor="rgba(0,200,0,0.3)", line=dict(width=0))
            
            # Programmnummer als Text-Annotation in der Mitte des Rechtecks
            if prog_num:
                mid_time = s + (e - s) / 2
                fig.add_annotation(
                    x=mid_time,
                    y=0.95,
                    yref="paper",
                    text=f"<b>{prog_num}</b>",
                    showarrow=False,
                    font=dict(size=14, color="darkgreen"),
                    bgcolor="rgba(255,255,255,0.7)",
                    bordercolor="darkgreen",
                    borderwidth=1,
                    borderpad=3
                )

    fig.update_layout(
        title=f"{name}",
        xaxis_title="Zeit",
        yaxis_title="Temperatur °C",
        height=350,
        margin=dict(l=80, r=30, t=50, b=40),
        template="plotly_white",
        legend=dict(orientation="h", y=-0.25)
    )

    # Hier wird jetzt das vollständige Plotly-JS eingebettet
    html_parts.append(fig.to_html(full_html=False, include_plotlyjs='cdn'))

# ---------------------------------------------------------------
# 6. Gesamtes Dashboard schreiben
# ---------------------------------------------------------------
html_content = """
<html>
<head>
    <meta charset="utf-8">
    <title>Ofen-Dashboard</title>
</head>
<body style="font-family:Arial; margin:20px;">
    <h1>Ofen-Dashboard</h1>
    <p>Vorheizen = Rot | Laufzeit = Grün | Ist/Soll-Temperatur = Linien</p>
    {}
</body>
</html>
""".format("\n<hr style='margin:40px 0;'>\n".join(html_parts))

output_path = "ofen_dashboard.html"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"✅ Dashboard erstellt: {output_path}")
print("👉 Datei kann jetzt direkt lokal im Browser geöffnet werden (Doppelklick).")
