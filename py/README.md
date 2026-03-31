# otel-sst-quickstart.py

A setup script that configures the [Splunk Sustainability Toolkit](https://splunkbase.splunk.com/app/6343) to accept OpenTelemetry (OTel) metrics data and optionally connects an AI assistant (OpenCode or Claude Desktop) to your sustainability data via the Splunk MCP Server.

---

## What the script does — step by step

This section is written for users who want to understand exactly what the script does before running it. Nothing happens silently; every action is either shown on screen or prompted for confirmation first.

---

### Before it does anything: dependency check

**What:** Checks whether the `splunk-sdk` Python package is installed. If it is missing, runs `pip install splunk-sdk` automatically.

**Why:** The script uses the Splunk SDK to talk to Splunk's REST API. Without it, nothing else can run.

**What it touches:** Your local Python environment only. No Splunk changes at this point.

---

### Step 0: Authenticate to Splunk

**What:** Prompts for your Splunk server address, management port, username, and password. Establishes an authenticated session using the Splunk SDK.

**Prompts:**
- Splunk IP or hostname (default: `127.0.0.1`)
- Management port (default: `8089`)
- Username (default: `admin`)
- Password (hidden input, no default — required)

**What it touches:** Nothing is written yet. This step only opens a connection to verify your credentials.

> The management port (`8089`) is Splunk's REST API port — it is separate from the web UI port (`8000`). The script warns you if you accidentally enter `8000`.

---

### Step 0b: MCP Server prompt

**What:** Asks whether you want to install the optional Splunk MCP Server app. Your answer determines whether that app is added to the install checklist in the next step.

**Prompt:** `Do you want to install and set up the Splunk MCP Server? (y/n)`

**What it touches:** Nothing yet — this only affects which apps are checked for in the next step.

---

### Step 0c: App check and optional auto-install

**What:** Checks which of the following apps are installed in your Splunk instance:

| App | Required? |
|-----|-----------|
| Sustainability Toolkit for Splunk | Yes |
| Splunk Add-on for Electricity Carbon Intensity | Yes |
| Splunk App for Lookup File Editing | No (recommended) |
| Machine Learning Toolkit | No (recommended) |
| Python for Scientific Computing | No (recommended) |
| Splunk MCP Server | No (only if you said yes above) |

If any apps are missing, you are offered the option to install them automatically. Auto-install requires a free [splunk.com](https://splunk.com) account and uses Splunk's own proxied Splunkbase install endpoint (the same mechanism Splunk Web uses when you click "Install" in the app browser).

**If you decline auto-install:** Required apps will cause the script to exit with instructions to install manually. Optional apps are skipped with a Splunkbase URL printed for reference.

**What it touches on Splunk:** Installs apps into `/opt/splunk/etc/apps/` if you confirm. No other changes.

---

### Step 1: Create indexes

**What:** Creates the following four Splunk indexes if they do not already exist:

| Index | Type | Purpose |
|-------|------|---------|
| `otel` | Event | Raw OpenTelemetry JSON metrics from your infrastructure |
| `electricity_carbon_intensity` | Event | Electricity grid carbon intensity data from Electricity Maps |
| `sustainability_toolkit_summary_asset_metrics` | Metric | Summarized per-asset CO2e and power metrics |
| `sustainability_toolkit_summary_electricity_metrics` | Metric | Summarized per-zone electricity carbon intensity metrics |

**Idempotent:** If an index already exists, it is left unchanged and a message is printed.

**What it touches on Splunk:** Index definitions only (equivalent to Settings > Indexes in the UI).

---

### Step 1b: Sample data (optional)

**What:** Asks whether you want to load example OpenTelemetry data from a Cisco Intersight environment. This is for users who do not yet have a live OTel pipeline sending data to Splunk.

**Prompt:** `Do you want to load the example data? (y/n)`

If yes, a second prompt confirms you are running the script on the Splunk server itself (required because the script writes files to the local filesystem):

**Prompt:** `Are you running this script directly on the Splunk server? (y/n)`

If you answer no to the server check, the script exits cleanly with instructions to re-run from the server.

**If sample data already exists** in the `otel` index (i.e., you are re-running the script), you are warned and asked to confirm before loading again to avoid duplicate events.

**What it does when you confirm:**
1. Reads `data/otelcol-export.jsonl` from the repo — a snapshot of OTel power/CPU metrics
2. Reads `data/emaps-export.jsonl` from the repo — a snapshot of Electricity Maps carbon intensity data
3. Rebases all timestamps in both files so the data ends at the current time (not the original capture date in 2024)
4. Writes the rebased data to a temporary file and posts it to Splunk via the REST receiver endpoint
5. Deletes the temporary file when done

**What it touches on Splunk:** Events posted to `otel` and `electricity_carbon_intensity` indexes.

**What it touches on the filesystem:** Writes a temporary `.jsonl` file under the system temp directory (`/tmp`), deleted immediately after posting.

---

### Step 2: Configure Electricity Maps

**What:** Configures the Splunk Add-on for Electricity Carbon Intensity to collect live grid carbon intensity data from the [Electricity Maps API](https://api.electricitymap.org/).

**Prompts:**
- Your Electricity Maps API key
- Whether you want to see the full list of available zone codes
- Which zone codes to collect data from (e.g. `CH,DE,PL`)

**What it does:**
1. Stores your API key in Splunk's encrypted credential store via the TA's REST handler (equivalent to configuring an account in the add-on's setup UI)
2. Creates or updates an `inputs.conf` stanza to collect data from your chosen zones every hour (interval: `3600` seconds) into the `electricity_carbon_intensity` index

**What it touches on Splunk:** A credential entry in the TA's account store and an input definition in `inputs.conf` for the `TA-electricity-carbon-intensity` app.

---

### Step 2b: props.conf for sample data (only if sample data was loaded)

**What:** Writes a `MAX_DAYS_HENCE = 14` setting to the local `props.conf` for the `EM:carbonintensity` sourcetype.

**Why:** Splunk rejects events with timestamps more than 2 days in the future by default. The sample data timestamps are rebased to the current time, but floating-point rounding can push a small number of events slightly beyond 2 days ahead. This setting extends that window to 14 days to prevent silent timestamp clamping.

**What it touches on the filesystem:** Writes (or merges into) `/opt/splunk/etc/apps/TA-electricity-carbon-intensity/local/props.conf`. Uses Python's `configparser` to merge only the `[EM:carbonintensity]` stanza — it does not overwrite any other settings in the file.

---

### Step 3–5: Update search macros

**What:** Creates or updates four SPL search macros in the Sustainability Toolkit app that control how the dashboards query your data:

| Macro | What it does |
|-------|-------------|
| `cmdb-lookup-name` | Points dashboards to the CMDB lookup file (`otel_sample_cmdb.csv`) |
| `sites-lookup-name` | Points dashboards to the sites lookup file (`otel_sample_sites.csv`) |
| `power-otel` | SPL subquery that reads power metrics from the `otel` index |
| `power-asset-location` | SPL subquery that joins asset power with site/location data |
| `electricity-carbon-intensity` | SPL subquery that reads grid carbon intensity from the summary index |
| `electricity-carbon-intensity-for-assets` | SPL subquery that joins asset power with grid carbon intensity to calculate CO2e |

For each macro, the script:
1. Renames the existing macro to `<name>-old` (preserving the original as a backup)
2. Creates a new macro with the updated SPL definition

**Idempotent:** If the `-old` backup already exists (re-run), the rename is skipped silently. If the macro already exists, its definition is updated in place.

**What it touches on Splunk:** Search macro definitions in `macros.conf` for the `Sustainability_Toolkit` app only.

---

### Step 5b: Copy lookup CSV files (only if sample data was loaded)

**What:** Copies two CSV lookup files from the repo into the Sustainability Toolkit's lookups directory:

| File | Contents |
|------|----------|
| `otel_sample_cmdb.csv` | Sample CMDB — one row per asset with hostname, site, country, embodied CO2e, and hardware lifetime |
| `otel_sample_sites.csv` | Sample site list — one row per site with grid zone codes, electricity cost source, lat/lon |

**Idempotent:** If the file already exists at the destination (e.g. you have edited it), it is left unchanged and a message is printed.

**What it touches on the filesystem:** Copies files to `/opt/splunk/etc/apps/Sustainability_Toolkit/lookups/`.

**What it touches on Splunk:** Registers `transforms.conf` lookup definitions so the `lookup` and `inputlookup` SPL commands can find the CSV files by name.

---

### Step 6: Update summarization saved searches

**What:** Updates two existing scheduled saved searches that aggregate raw OTel and electricity data into the metric summary indexes used by the dashboards:

| Saved Search | Schedule | What it produces |
|---|---|---|
| `Summarize Asset CO2e & kW V1.0` | Every hour at :23 | Per-asset CO2e and power data in `sustainability_toolkit_summary_asset_metrics` |
| `Summarize Electricity CO2e/kWh V1.0` | Every hour at :24 | Per-zone grid carbon intensity in `sustainability_toolkit_summary_electricity_metrics` |

The script updates the SPL query and cron schedule for each search. It does not delete or recreate them.

**What it touches on Splunk:** SPL and schedule for two saved searches in the `Sustainability_Toolkit` app.

---

### Step 7: Immediately trigger the summary searches

**What:** Dispatches both summary searches immediately (rather than waiting up to an hour for the next scheduled run) so the dashboards have data as soon as setup completes. Polls until each search finishes, printing progress every 5 seconds.

**What it touches on Splunk:** Creates and runs two ad-hoc search jobs. Results are written to the metric summary indexes. No configuration is changed.

---

### Step 8: Write opencode.json

**What:** Writes (or overwrites) `opencode.json` in the repo root using the Splunk host, port, username, and password you entered at the start.

**What it does:** `opencode.json` tells OpenCode how to launch the `splunk_mcp_proxy.py` bridge script and which Splunk instance to connect to. The file is always written so it stays in sync with whatever credentials you used.

**What it touches on the filesystem:** Writes `opencode.json` one directory above `py/` (the repo root).

---

### Step 9: Auto-install OpenCode

**What:** Checks whether the `opencode` command is available on the PATH. If not, installs it:

1. Checks for `node` and `npm`
2. If either is missing, runs `apt-get install -y nodejs npm`
3. Runs `npm install -g opencode-ai`
4. Verifies the install succeeded

If OpenCode is already installed, this step is skipped entirely.

**What it touches on the system:** May install system packages (`nodejs`, `npm`) and a global npm package (`opencode-ai`). Requires root/sudo privileges for the `apt-get` step.

---

## Prerequisites

- Python 3.7 or later
- Network access to your Splunk management port (default: `8089`)
- A Splunk admin account
- To load sample data or copy lookup files: must be run **directly on the Splunk server** (not over SSH from another machine)
- To auto-install apps: a free [splunk.com](https://splunk.com) account
- To configure Electricity Maps: a free or paid [Electricity Maps API key](https://api.electricitymap.org/)

---

## Usage

```
cd /path/to/ciscolive-splunk-sustainability
./py/otel-sst-quickstart.py
```

Or explicitly with Python:

```
python3 py/otel-sst-quickstart.py
```

The script is fully interactive — it will prompt you for everything it needs and will not make irreversible changes without asking first.

---

## Re-running the script

The script is designed to be re-run safely (idempotent):

- Indexes that already exist are left unchanged
- Macros that already exist are updated in place
- Lookup files that already exist are not overwritten
- `props.conf` changes are merged, not overwritten
- If sample data already exists in the `otel` index, you are warned and asked to confirm before reloading
- `opencode.json` is always overwritten with the credentials from the current run

---

## What the script does NOT do

- It does not delete any existing data
- It does not modify Splunk's authentication or user accounts
- It does not change Splunk's network configuration or ports
- It does not modify any Splunk app other than `Sustainability_Toolkit` and `TA-electricity-carbon-intensity`
- It does not transmit your Splunk credentials anywhere other than your own Splunk instance
- It does not make any outbound network calls other than:
  - To your Splunk management port
  - To `api.electricitymap.org` (only to fetch the list of zones if you request it)
  - To `splunkbase.splunk.com` (only if you choose auto-install apps)
  - To `npmjs.com` / the npm registry (only if OpenCode needs to be installed)

---

## After setup: using OpenCode to query your sustainability data

Once the script completes, OpenCode is configured to query your Splunk sustainability data using natural language. Five tools are available:

| Tool | Example questions |
|------|------------------|
| `get_asset_co2e` | "Which server emits the most carbon?" |
| `get_asset_embodied_vs_operational_co2e` | "Is our carbon footprint dominated by manufacturing or electricity use?" |
| `get_electricity_carbon_intensity` | "Which of our data center locations has the cleanest electricity grid?" |
| `get_site_co2e_summary` | "How do our three data center sites compare in total carbon emissions?" |
| `get_co2e_savings_potential` | "How much CO2e could we save by moving our Poland workloads to Switzerland?" |

To use OpenCode:

```bash
cd /path/to/ciscolive-splunk-sustainability
opencode
```

OpenCode picks up `opencode.json` automatically from the current directory and connects to your Splunk MCP Server.

---

## If you did not load sample data

The dashboards require two lookup CSV files to be populated with your own infrastructure data before they will show results:

**`/opt/splunk/etc/apps/Sustainability_Toolkit/lookups/otel_sample_cmdb.csv`**

One row per OTel asset. Required columns:

| Column | Description |
|--------|-------------|
| Asset IP | Hostname or IP matching what your OTel collector reports |
| Site | Site name (must match `otel_sample_sites.csv`) |
| Country | Country name |
| Location | Location description |
| Application | Application or workload name |
| Embodied CO2e | Total manufacturing CO2e in kg for this hardware |
| Years Lifetime | Expected hardware lifetime in years (used to amortize embodied CO2e) |

**`/opt/splunk/etc/apps/Sustainability_Toolkit/lookups/otel_sample_sites.csv`**

One row per site. Required columns:

| Column | Description |
|--------|-------------|
| Site | Site name (must match CMDB) |
| Electricity CO2e per kWh Source | Electricity Maps zone name |
| Electricity CO2e per kWh Source Location Code | Electricity Maps zone code (e.g. `PL`, `CH`, `DE`) |
| Electricity Cost Source | Electricity cost data source label |
| Latitude | Site latitude |
| Longitude | Site longitude |

You can edit these files directly on the server or use the Splunk App for Lookup File Editing in the Splunk web UI. After populating the files, re-trigger the two summary searches from Settings > Searches, Reports and Alerts.

---

## Version history

| Version | Date | Changes |
|---------|------|---------|
| v1.9 | 31-Mar-2026 | Auto-install OpenCode (and Node.js/npm if needed) if not on PATH |
| v1.8 | 31-Mar-2026 | Write `opencode.json` from user-supplied Splunk credentials |
| v1.7 | 31-Mar-2026 | Auto-install missing Python dependencies; print dashboard URL on completion |
| v1.6 | 30-Mar-2026 | Dispatch both summary searches immediately after setup |
| v1.5 | 30-Mar-2026 | Write `MAX_DAYS_HENCE=14` to `TA-electricity-carbon-intensity` props.conf |
| v1.4 | 27-Mar-2026 | Fix `__file__` path bug, add lookup transforms.conf registration, fix power-otel SPL |
| v1.3 | 27-Mar-2026 | Automated Electricity Maps API key config and sample lookup file upload |
| v1.2 | 27-Mar-2026 | Added Splunkbase app check and automated install support |
| v1.1 | 31-May-2024 | Added support for loading example OTel data |
| v1.0 | 17-May-2024 | Initial release |
