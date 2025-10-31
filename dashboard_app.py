# dashboard_app.py

import pandas as pd
import streamlit as st
import re
from datetime import datetime
import plotly.graph_objects as go
import io # Für den Download-Button

# --- Funktionen aus dem Originalcode (mit st.cache_data für Performance) ---

@st.cache_data(show_spinner="CSV wird eingelesen und Spalten analysiert...")
def load_and_clean_csv(uploaded_file):
    """
    Liest die hochgeladene CSV-Datei ein, erkennt Encoding/Trennzeichen
    und bereinigt die Spalten.
    """
    # 1. CSV laden (Angepasste Version für Streamlit File Uploader)
    encodings = ["utf-8-sig", "cp1252", "latin1"]
    seps = [";", ",", "\t"]
    df = None

    # Datei-Inhalt als Bytes lesen
    file_bytes = uploaded_file.getvalue()

    for enc in encodings:
        for sep in seps:
            try:
                # Versuch, die Datei aus dem In-Memory-Buffer zu lesen
                tmp = pd.read_csv(io.StringIO(file_bytes.decode(enc)), sep=sep)

                # Prüfen, ob genügend Spalten vorhanden sind (mind. 5)
                if tmp.shape[1] >= 5:
                    df = tmp
                    break
            except Exception:
                continue
        if df is not None:
            break

    if df is None:
        st.error("❌ CSV konnte nicht eingelesen werden – prüfe Trennzeichen oder Encoding.")
        return None

    # 2. Relevante Spalten finden und bereinigen
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

    # Sicherstellen, dass alle Schlüsselspalten gefunden wurden
    if not all([col_time, col_dev, col_msg, col_soll, col_ist]):
        st.error("❌ Eine oder mehrere benötigte Spalten (Zeit, Gerät, Meldung, Soll, Ist) wurden nicht gefunden.")
        return None

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
                # Versucht Format wie "23/10/25, 08:30:00, 000"
                return datetime.strptime(f"{parts[0]} {parts[1]}.{parts[2]}", "%y/%m/%d %H:%M:%S.%f")
        except:
            pass
        # Versucht Standard-Pandas-Konvertierung (Tag zuerst für europäische Formate)
        return pd.to_datetime(s, dayfirst=True, errors="coerce")

    df["timestamp"] = df["Datum/Zeit"].apply(parse_timestamp)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

    if df.empty:
        st.error("❌ Nach der Zeitbereinigung sind keine gültigen Daten mehr vorhanden. Prüfe das Zeitformat.")
        return None

    # 3. Gerät + Herd extrahieren
    def parse_device(dev):
        m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", str(dev))
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return str(dev), ""

    df[["device_type", "device_id"]] = df["Gerät"].apply(lambda x: pd.Series(parse_device(x)))

    def clean_device_type(row):
        device_type = str(row.device_type).strip()
        device_id = str(row.device_id).strip()
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

    # 4. Programmphasen bestimmen
    df["is_loaded"] = df["Meldung"].str.contains("Arbeitsprog", case=False, na=False)
    df["is_started"] = df["Meldung"].str.contains("Programm gestartet", case=False, na=False)
    df["is_ended"] = df["Meldung"].str.contains("Programmende|Programm beendet|Programm gestoppt", case=False, na=False)

    def extract_program_number(msg):
        msg_str = str(msg)
        m = re.search(r"P\s*(\d+)", msg_str, re.IGNORECASE)
        if m:
            return f"P{m.group(1)}"
        m = re.search(r"(?:Programm|Prog)\s+(\d+)", msg_str, re.IGNORECASE)
        if m:
            return f"P{m.group(1)}"
        return None

    df["prog_num"] = df["Meldung"].apply(extract_program_number)

    preheats = []
    runs = []
    for name, g in df.groupby("row_name"):
        g = g.sort_values("timestamp")
        t_load = t_start = prog_num = None
        for _, r in g.iterrows():
            t = r["timestamp"]
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
                prog_num = None

    return df, preheats, runs


def smart_sort_key(row_name):
    """Sortiert Geräte logisch: zuerst nach Typ, dann nach ID-Nummer, dann nach Herd"""
    parts = row_name.split(" - ")
    base = parts[0]
    herd = parts[1] if len(parts) > 1 else ""
    match = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", base)
    if match:
        device_type = match.group(1).strip().lower()
        device_id = match.group(2).strip()
    else:
        device_type = base.lower()
        device_id = ""
    if not device_type or device_type == "0" or device_type == "nan" or not device_id:
        return ("zzz_invalid", [9999], 9999)
    id_numbers = [int(x) if x.isdigit() else 0 for x in re.findall(r'\d+', device_id)]
    if not id_numbers:
        id_numbers = [9999]
    herd_match = re.search(r"Herd\s*(\d+)", herd)
    herd_num = int(herd_match.group(1)) if herd_match else 0
    return (device_type, id_numbers, herd_num)

def adjust_timestamp_to_cycle(ts, cycle_start_date):
    """Setzt den Zeitstempel in das 24h-Zyklus-Datum (22:00-22:00 Zyklus)"""
    # Wenn die Uhrzeit >= 22:00 ist, gehört sie zum Startdatum des Zyklus
    if ts.hour >= 22:
        return ts.replace(year=cycle_start_date.year, month=cycle_start_date.month, day=cycle_start_date.day)
    # Wenn die Uhrzeit < 22:00 ist, gehört sie zum nächsten Kalendertag des Zyklus
    else:
        next_day = cycle_start_date + pd.Timedelta(days=1)
        return ts.replace(year=next_day.year, month=next_day.month, day=next_day.day)

# --- Hauptfunktion zum Erstellen des Dashboards ---

@st.cache_data(show_spinner="Dashboard wird gerendert...")
def create_dashboard_html(df, preheats, runs):
    """Erstellt den vollständigen HTML-Code des Dashboards."""

    # 4.5. 24h-Zyklus-Basiszeitpunkt bestimmen
    earliest_timestamp = df["timestamp"].min()
    start_time_base = earliest_timestamp.replace(hour=22, minute=0, second=0, microsecond=0)

    if earliest_timestamp.hour < 22:
        cycle_start = start_time_base - pd.Timedelta(days=1)
    else:
        cycle_start = start_time_base

    cycle_end = cycle_start + pd.Timedelta(hours=24)
    cycle_start_date_only = cycle_start.normalize() # Nur das Datum des Zyklusstarts

    st.info(f"🔗 **Analysierter 24h-Zeitraum:** {cycle_start.strftime('%d.%m. %H:%M')} bis {cycle_end.strftime('%d.%m. %H:%M')}")

    # 5. Diagramme pro Ofen/Herd erstellen
    html_parts = []
    all_names = sorted(df["row_name"].unique(), key=smart_sort_key)
    x_range_start = cycle_start
    x_range_end = cycle_end
    Y_AXIS_MAX = 350
    Y_AXIS_MIN = 0
    DUMMY_TEMP = -10

    for name in all_names:
        subset = df[df["row_name"] == name].copy()
        if subset.empty:
            continue

        # NEU: Zeitstempel-Anpassung
        subset["timestamp"] = subset["timestamp"].apply(
            lambda ts: adjust_timestamp_to_cycle(ts, cycle_start_date_only)
        )

        subset["Ist °C"] = pd.to_numeric(subset["Ist °C"].astype(str).str.replace(",", "."), errors="coerce")
        subset["Soll °C"] = pd.to_numeric(subset["Soll °C"].astype(str).str.replace(",", "."), errors="coerce")

        # FIKTIVE DATENPUNKTE HINZUFÜGEN, UM ACHSE ZU ERZWINGEN (X und Y)
        dummy_data = {
            "timestamp": [x_range_start, x_range_end],
            "Ist °C": [DUMMY_TEMP, DUMMY_TEMP],
            "Soll °C": [DUMMY_TEMP, DUMMY_TEMP],
            "Gerät": [subset["Gerät"].iloc[0]] * 2 if not subset["Gerät"].empty else ["DUMMY"]*2,
            "row_name": [name] * 2
        }
        dummy_df = pd.DataFrame(dummy_data)
        subset = pd.concat([subset, dummy_df], ignore_index=True)
        subset = subset.sort_values("timestamp").reset_index(drop=True)

        # Plotly-Figur erstellen
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
            s_adj = adjust_timestamp_to_cycle(s, cycle_start_date_only)
            e_adj = adjust_timestamp_to_cycle(e, cycle_start_date_only)

            if n == name:
                fig.add_shape(type="rect", x0=s_adj, x1=e_adj, y0=0, y1=1,
                              xref="x", yref="paper", fillcolor="rgba(255,0,0,0.3)", line=dict(width=0))

        for item in runs:
            n = item[0]
            s = item[1]
            e = item[2]
            prog_num = item[3] if len(item) > 3 else None

            s_adj = adjust_timestamp_to_cycle(s, cycle_start_date_only)
            e_adj = adjust_timestamp_to_cycle(e, cycle_start_date_only)

            if n == name:
                # Grünes Rechteck für Programm-Run
                fig.add_shape(type="rect", x0=s_adj, x1=e_adj, y0=0, y1=1,
                              xref="x", yref="paper", fillcolor="rgba(0,200,0,0.3)", line=dict(width=0))

                # Programmnummer als Text-Annotation
                if prog_num:
                    mid_time = s_adj + (e_adj - s_adj) / 2
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
            legend=dict(orientation="h", y=-0.25),
            xaxis=dict(
                type='date',
                tickformat="%H:%M",
                ticklabelmode="period",
                dtick=3600000 * 2 # Ticks alle 2 Stunden
            ),
            yaxis=dict(
                range=[Y_AXIS_MIN, Y_AXIS_MAX],
                dtick=50 # Ticks alle 50 Grad
            )
        )

        # Plotly JS für jedes Diagramm in HTML-Teil
        html_parts.append(fig.to_html(full_html=False, include_plotlyjs='cdn'))

    # 6. Gesamtes Dashboard schreiben
    separator = "\n<hr style='margin:40px 0;'>\n"
    joined_html = separator.join(html_parts)

    html_content = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>Ofen-Dashboard</title>
    </head>
    <body style="font-family:Arial; margin:20px;">
        <h1>Ofen-Dashboard</h1>
        <p>Vorheizen = Rot | Laufzeit = Grün | Ist/Soll-Temperatur = Linien</p>
        {joined_html}
    </body>
    </html>
    """
    return html_content


# --- Streamlit UI ---

st.set_page_config(page_title="Ofen-Dashboard Generator", layout="wide")

st.title("🔥 Ofen-Dashboard Generator")
st.markdown("Lade deine **Ofenauswertung.csv** hoch, um eine interaktive Visualisierung deiner Ofen- und Programmphasen über einen 24-Stunden-Zyklus (22:00 - 22:00 Uhr) zu erhalten.")

uploaded_file = st.file_uploader(
    "1. CSV-Datei per Drag & Drop hochladen",
    type="csv",
    help="Bitte wähle die 'Ofenauswertung.csv' Datei aus."
)

if uploaded_file is not None:
    # 2. Daten laden und vorbereiten
    result = load_and_clean_csv(uploaded_file)

    if result is not None:
        df, preheats, runs = result

        # 3. Dashboard generieren
        with st.spinner("Generiere Dashboard... ⏳"):
            html_output = create_dashboard_html(df, preheats, runs)

        st.success("✅ Dashboard erfolgreich generiert!")

        # 4. Download-Button anzeigen
        st.download_button(
            label="Dashboard (ofen_dashboard.html) herunterladen",
            data=html_output,
            file_name="ofen_dashboard.html",
            mime="text/html"
        )

        # Optional: Vorschau im Browser
        with st.expander("Dashboard-Vorschau anzeigen"):
            # Streamlit kann HTML anzeigen, was die Diagramme hier darstellt
            # Dies ist eine vereinfachte Vorschau, das vollständige HTML wird heruntergeladen
            st.components.v1.html(html_output, height=800, scrolling=True)

