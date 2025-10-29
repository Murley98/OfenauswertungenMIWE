# Ofen-Dashboard

## Overview

This is a Python-based oven monitoring dashboard that processes CSV data from industrial ovens/furnaces and generates interactive visualizations. The application reads operational data (timestamps, device names, status messages, temperature setpoints and actual values) and creates Gantt charts combined with temperature trend lines using Plotly. The dashboard displays preheat phases (red), runtime phases (green), and temperature curves for multiple ovens simultaneously.

**Primary Purpose**: Visualize oven operational status and temperature data for industrial monitoring and analysis.

**Core Functionality**:
- CSV data parsing with automatic encoding/delimiter detection
- Time-series data extraction and transformation
- Multi-device Gantt chart generation with temperature overlays
- Static HTML dashboard output

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Type
**Standalone Python Script** - Single-file application that processes data and generates static HTML output. No web server, database, or persistent storage required.

### Data Processing Architecture

**CSV Input Processing**:
- **Problem**: CSV files may have varying encodings (UTF-8, CP1252, Latin1) and delimiters (semicolon, comma, tab)
- **Solution**: Iterative detection loop testing multiple encoding/delimiter combinations
- **Rationale**: Handles real-world data from different industrial systems without manual configuration

**Column Mapping Strategy**:
- **Problem**: CSV column names may vary (e.g., "Gerät" vs "Ger„t" due to encoding issues)
- **Solution**: Fuzzy column matching using substring search with multiple keywords
- **Implementation**: `find_col()` function searches for columns using keyword lists
- **Pros**: Robust against minor variations in column naming
- **Cons**: May match incorrect columns if naming is ambiguous

### Visualization Architecture

**Charting Library**: Plotly Graph Objects
- **Choice**: Plotly for interactive JavaScript-based charts
- **Alternatives Considered**: Matplotlib (static images), Chart.js (more manual JavaScript)
- **Rationale**: Plotly provides interactive features (zoom, pan, hover) with Python-friendly API
- **Deployment**: Uses Plotly CDN (v3.1.1) for rendering, no local dependencies

**Chart Structure**:
- Gantt chart implementation using horizontal bar traces
- Temperature data overlaid as line traces on secondary y-axis
- Color coding: Red for preheat phases, Green for runtime phases
- Each device gets its own subplot/chart

**Output Format**:
- **Problem**: Need standalone, shareable dashboard
- **Solution**: Static HTML file with embedded Plotly JavaScript
- **Files Generated**: 
  - `ofen_dashboard.html` (main dashboard)
  - `tmp_charts/chart_*.html` (individual chart fragments)
- **Pros**: No server required, easy to share and archive
- **Cons**: Not real-time, requires regeneration for updates

### Data Flow

1. **Load CSV** → Detect encoding and delimiter
2. **Parse & Clean** → Identify columns, rename for standardization
3. **Transform** → Extract timestamps, device names, status messages, temperature values
4. **Generate Charts** → Create Plotly figures for each device
5. **Export HTML** → Write standalone HTML file with embedded charts

### File Structure

```
/
├── main.py                    # Main application script
├── Ofenauswertung.csv        # Input data file (expected)
├── ofen_dashboard.html       # Generated dashboard output
└── tmp_charts/               # Individual chart HTML fragments
    ├── chart_0.html
    ├── chart_1.html
    └── ...
```

## External Dependencies

### Python Libraries

**pandas** - Data manipulation and CSV parsing
- Purpose: Load, clean, and transform tabular data
- Core operations: CSV reading, column renaming, data filtering

**plotly** - Interactive chart generation
- Purpose: Create Gantt charts and temperature line graphs
- Module used: `plotly.graph_objects`
- Specific features: Bar traces (Gantt), Scatter traces (temperature lines)

**datetime** (stdlib) - Timestamp parsing and manipulation
- Purpose: Convert string timestamps to datetime objects

**re** (stdlib) - Regular expressions
- Purpose: Pattern matching for data extraction (likely message parsing)

### External Services

**Plotly CDN** - `https://cdn.plot.ly/plotly-3.1.1.min.js`
- Purpose: JavaScript library for rendering interactive charts in browser
- Integrity hash: `sha256-HUEFyfiTnZJxCxur99FjbKYTvKSzwDaD3/x5TqHpFu4=`
- Note: Charts will not render without internet connection

### Data Sources

**Input CSV File** - `Ofenauswertung.csv`
- Expected columns (flexible naming):
  - Date/Time column (Datum, Zeit)
  - Device column (Gerät, Ger)
  - Message/Status column (Meld)
  - Setpoint temperature (Soll)
  - Actual temperature (Ist)
- Encoding: UTF-8-SIG, CP1252, or Latin1
- Delimiter: Semicolon, comma, or tab
- Source: Industrial oven monitoring system (external)

### No Database

This application does not use any database system. All data processing is done in-memory using pandas DataFrames.

### No Authentication

No user authentication or authorization mechanisms. This is a standalone data processing tool.