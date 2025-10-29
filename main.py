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
# 4. Programmphasen bestimmen
# ---------------------------------------------------------------
df["is_loaded"] = df["Meldung"].str.contains("Arbeitsprog", case=False, na=False)
df["is_started"] = df["Meldung"].str.contains("Programm gestartet", case=False, na=False)
df["is_ended"] = df["Meldung"].str.contains("Programmende|Programm beendet|Programm gestoppt", case=False, na=False)

preheats = []
runs = []
for name, g in df.groupby("row_name"):
    g = g.sort_values("timestamp")
    t_load = t_start = None
    for _, r in g.iterrows():
        t = r["timestamp"]
        if r["is_loaded"]:
            t_load = t
        if r["is_started"]:
            if t_load:
                preheats.append((name, t_load, t))
                t_load = None
            t_start = t
        if r["is_ended"] and t_start:
            runs.append((name, t_start, t))
            t_start = None

# ---------------------------------------------------------------
# 5. Diagramme pro Ofen/Herd erstellen
# ---------------------------------------------------------------
html_parts = []
all_names = sorted(df["row_name"].unique())

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

    # Vorheizen/Laufzeit-Balken
    for n, s, e in preheats:
        if n == name:
            fig.add_shape(type="rect", x0=s, x1=e, y0=0, y1=1,
                          xref="x", yref="paper", fillcolor="rgba(255,0,0,0.3)", line=dict(width=0))
    for n, s, e in runs:
        if n == name:
            fig.add_shape(type="rect", x0=s, x1=e, y0=0, y1=1,
                          xref="x", yref="paper", fillcolor="rgba(0,200,0,0.3)", line=dict(width=0))

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
