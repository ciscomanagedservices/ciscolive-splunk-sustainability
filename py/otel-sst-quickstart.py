#!/usr/bin/env python3
# coding: utf-8
#
# otel-sst-quickstart.py
# © 2024 Cisco and/or its affiliates. All rights reserved.
#
# A companion setup script to automate the changes to Splunk Sustainability Toolkit to
# allow for OpenTelemetry support
#
# v1.3 - 27-mar-2026 - Automated Electricity Maps API key config and sample lookup file upload.
# v1.2 - 27-mar-2026 - Added Splunkbase app check and automated install support.
# v1.1 - 31-may-2024 - Added support to automate loading example files into splunk for
# those that don't have an active OpenTelemetry pipeline to ingest from.
# v1.0 - 17-may-2024 - Initial release. sholl@cisco.com

# Install this dependency via 'pip3 install splunk-sdk'
import splunklib.client as client
import splunklib.results as results
import urllib.request
import urllib.parse
import urllib.error

from getpass import getpass
import os
from pathlib import Path
import json
import shutil
import sys


def _get_spl_from_file(filename):
    """internal function to get the path where the spl file is located"""
    p = os.path.dirname(os.path.realpath("__file__"))
    path = Path(p)
    f = os.path.join(path.parent.absolute(), "splunk", "spl", filename)
    with open(f, "r") as file:
        d = file.read()
    return d


def _get_sample_data_path(filename):
    """Internal function to get path of sample file data for loading in, if desired."""
    p = os.path.dirname(os.path.realpath("__file__"))
    path = Path(p)
    f = os.path.join(path.parent.absolute(), "data", filename)
    return f


def get_input_for_auth():
    """Collects input for Splunk server authentication from the user in CLI.
    Returns a dict for splunk_auth()."""
    i = {"host": None, "port": None, "username": None, "password": None}
    i["host"] = input("Enter your splunk IP or hostname: ").strip()
    if not i["host"]:
        i["host"] = "localhost"

    i["port"] = input("Enter your Splunk management port (usually 8089): ").strip()
    if i["port"] == "8000":
        print(
            "INFO: Port 8000 is usually the Splunk Web port to acces the UI, \
                and not the port used for the management API. \
                To validate, check what port your Universal Forwarders are sending to."
        )
        i["port"] = input("Enter your Splunk management port (usually 8089): ").strip()
    if not i["port"]:
        i["port"] = "8089"

    i["username"] = input("Enter your Splunk username: ").strip()
    if not i["username"]:
        i["username"] = "admin"

    while not i["password"]:
        i["password"] = getpass("Enter your Splunk password: ")

    i["app"] = "search"

    return i


def splunk_auth(auth_input):
    """Takes a dictionary of host, port, username, password, and app and returns an active splunk session."""
    try:
        # Connect to Splunk
        service = client.connect(
            host=i["host"],
            port=i["port"],
            username=i["username"],
            password=i["password"],
            app=i["app"],
            owner="nobody",
        )
        print("Info: Authenticated successfully to Splunk.")
    except Exception as e:
        print(e)
        print(
            "Error: Could not authenticate to Splunk with the provided information. \
                Please check the input and retry."
        )
        raise
    return service


def create_macro(service, macro_name, definition):
    """Adds a new search macro to Splunk, when provided an active splunk service session,
    macro name, and macro definition."""
    try:
        service.post("properties/macros", __stanza=macro_name)
        service.post(f"properties/macros/{macro_name}", definition=definition)
        print(f"Search macro {macro_name} has been created.")
    except:
        print(f"ERROR: Search macro {macro_name} could not be created.")
        raise


def rename_macro(service, macro_name_old, macro_name_new):
    """Renames an existing search macro in Splunk, when provided an active splunk service session,
    and the old & new macro names."""
    try:
        definition = service.get(f"properties/macros/{macro_name_old}/definition")[
            "body"
        ]
    except:
        print(
            f"ERROR: Could not find and get propertes of search macro {macro_name_old}. Rename was unsuccessful."
        )
        raise
    create_macro(service=service, macro_name=macro_name_new, definition=definition)
    # delete_macro(service=service,macro_name=macro_name_old)


def delete_macro(service, macro_name):
    """Deletes an existing search macro in Splunk, when provided an active splunk service
    session and the macro name."""
    macro = service.confs["macros"][macro_name]
    try:
        macro.delete()
        print(f"Search macro {macro_name} has been deleted.")
    except:
        print(f"ERROR: Search macro {macro_name} could not be deleted.")


def create_saved_search(service, search_name, search_query):
    """Adds a new saved search to Splunk, when provided an active splunk service session,
    search name, and SPL query."""
    try:
        service.get(f"search")
        service.saved_searches.create(search_name, search_query)
        print(f"Saved search {search_name} has been created.")
    except:
        print(f"ERROR: Saved search {search_name} could not be created.")
        raise


def delete_saved_search(service, search_name):
    """Deletes a  saved search in Splunk, when provided an active splunk service session,
    and search name."""
    try:
        service.get(f"search")
        service.saved_searches.delete(search_name)
        print(f"Saved search {search_name} was deleted.")
    except:
        print(f"ERROR: Saved search {search_name} could not be deleted.")
        raise


def rename_saved_search(service, search_name_old, search_name_new):
    """Renames an existing saved search in Splunk, when provided an active splunk
    service session, and the old & new macro names"""
    try:
        service.get(f"search")
        search_query = service.saved_searches[search_name_old]["qualifiedSearch"]
    except:
        print(f"ERROR: Could not find and extract details for {search_name_old}")
    create_saved_search(
        service=service, search_name=search_name_new, search_query=search_query
    )
    delete_saved_search(service, search_name_old)


def schedule_saved_search(service, search_name, cron):
    """Edits the schedule for an existing saved search in Splunk, when provided an active splunk service session,
    the search name, and the cron schedule."""
    try:
        saved_search = service.saved_searches[search_name]
    except:
        print(f"ERROR: Could not find saved search: {search_name}")
        raise
    # Update the saved search with the new cron schedule
    try:
        kwargs = {"is_scheduled": True, "cron_schedule": "15 4 * * 6"}
        saved_search.update(**kwargs).refresh()
    except:
        print("ERROR: Failed to edit schedule for search {search_name}")


def splunkbase_auth(service, sb_username, sb_password):
    """Authenticates to Splunkbase via Splunk's proxied login endpoint
    (apps/remote/login) and returns a session token.

    Using Splunk's proxy avoids having to parse the raw Splunkbase Atom XML
    directly. The proxy returns a clean <sessionKey> element.
    Raises RuntimeError on failure."""
    try:
        resp = service.post(
            "apps/remote/login",
            headers=[("Content-Type", "application/x-www-form-urlencoded")],
            username=sb_username,
            password=sb_password,
        )
        # Response XML: <response><sessionKey>TOKEN</sessionKey></response>
        import re

        body = (
            resp["body"].read().decode("utf-8")
            if hasattr(resp["body"], "read")
            else str(resp["body"])
        )
        m = re.search(r"<sessionKey>([^<]+)</sessionKey>", body)
        if not m:
            raise ValueError("No <sessionKey> found in Splunkbase login response.")
        return m.group(1)
    except Exception as e:
        raise RuntimeError(f"Splunkbase authentication failed: {e}") from e


def install_app_from_splunkbase(service, folder_name, splunkbase_token):
    """Installs a Splunkbase app via Splunk's proxied remote install endpoint.

    Uses the app's folder name (e.g. 'Sustainability_Toolkit') in the endpoint
    path apps/remote/entriesbyid/<folder_name>, with auth=<token> and
    action=install. This is how Splunk Web itself installs apps."""
    try:
        service.post(
            f"apps/remote/entriesbyid/{folder_name}",
            headers=[("Content-Type", "application/x-www-form-urlencoded")],
            auth=splunkbase_token,
            action="install",
        )
    except Exception as e:
        raise RuntimeError(f"Install failed for app '{folder_name}': {e}") from e


def check_and_install_apps(service, app_specs):
    """Checks whether required/optional apps are installed. If any are missing, offers
    to install them automatically via Splunkbase.

    app_specs is a list of dicts:
        {
            "display_name": "Sustainability Toolkit for Splunk",
            "folder_name":  "Sustainability_Toolkit",   # internal app name in Splunk
            "splunkbase_id": 6343,                       # numeric Splunkbase app ID
            "required": True
        }

    Returns True if all required apps are present after the check (and any installs),
    False otherwise.
    """
    installed_names = {app.name for app in service.apps}

    missing = []
    print("\n--- Checking installed Splunk apps ---")
    for spec in app_specs:
        label = spec["display_name"]
        req_label = "(required)" if spec["required"] else "(optional)"
        if spec["folder_name"] in installed_names:
            print(f"  [OK]   {label} {req_label}")
        else:
            print(f"  [  ]   {label} {req_label}")
            if not spec["required"]:
                print(
                    f"          Install from: https://splunkbase.splunk.com/app/{spec['splunkbase_id']}"
                )
            missing.append(spec)

    if not missing:
        return True

    missing_required = [s for s in missing if s["required"]]
    print(f"\n{len(missing)} app(s) are not installed:")
    for spec in missing:
        req_label = "(REQUIRED)" if spec["required"] else "(optional)"
        print(f"  - {spec['display_name']} {req_label}")

    answer = input(
        "\nWould you like this script to install the missing app(s) automatically?\n"
        "This requires a splunk.com account (free). (y/n): "
    )
    if answer.strip().lower() not in ("y", "yes"):
        if missing_required:
            print("\nRequired apps are not installed. Install them manually from:")
            print(f"  http://{i['host']}:8000/en-US/manager/search/appsremote")
            print("Then re-run this script.")
            return False
        return True

    print("\nSplunkbase authentication required.")
    print(
        "If you do not have a splunk.com account, create one at: https://www.splunk.com/page/sign_up"
    )
    sb_username = input("Enter your splunk.com username (email): ")
    sb_password = getpass("Enter your splunk.com password: ")

    try:
        sb_token = splunkbase_auth(service, sb_username, sb_password)
        print("  Authenticated to Splunkbase successfully.")
    except RuntimeError as e:
        print(f"  ERROR: {e}")
        print("  Could not authenticate to Splunkbase. Install apps manually from:")
        print(f"  http://{i['host']}:8000/en-US/manager/search/appsremote")
        return False if missing_required else True

    failed = []
    for spec in missing:
        print(f"\n  Installing {spec['display_name']}...")
        try:
            install_app_from_splunkbase(service, spec["folder_name"], sb_token)
            print(f"  Installed {spec['display_name']} successfully.")
        except RuntimeError as e:
            print(f"  ERROR installing {spec['display_name']}: {e}")
            failed.append(spec)

    failed_required = [s for s in failed if s["required"]]
    if failed:
        print(f"\nWARNING: {len(failed)} app(s) failed to install:")
        for spec in failed:
            print(
                f"  - {spec['display_name']}: https://splunkbase.splunk.com/app/{spec['splunkbase_id']}"
            )

    if failed_required:
        print("\nRequired apps failed to install. Install them manually from:")
        print(f"  http://{i['host']}:8000/en-US/manager/search/appsremote")
        print("Then re-run this script.")
        return False

    return True


def check_app(service, app_name):
    apps = service.apps
    app_installed = False
    for app in apps:
        if app.name == app_name:
            app_installed = True
            print(f"App '{app_name}' is installed.")

    if not app_installed:
        apps = s.apps
        print(
            f"App {app_name} is not installed. Please navigate to \
        http(s)://[splunkhostname]/en-US/manager/search/appsremote?offset=0&count=20&order=relevance&query=sustainability \
        and install Sustainability Toolkit for Splunk."
        )
        print(
            "Rerun his script once both Sustainability_Toolkit and TA-electricity-carbon-intensity are installed"
        )
        sys.exit()


def update_saved_search(service, saved_search_name, properties):
    """Updates an existing saved_search, given existing authenticated splunk service, the search name,
    and a properties dict for the attributes to change."""
    try:
        saved_search = service.saved_searches[saved_search_name]
        saved_search.update(**properties).refresh()
        print(f"Saved search '{saved_search_name}' updated successfully.")

    except KeyError:
        print(f"Saved search '{saved_search_name}' not found.")

    except Exception as e:
        print(f"An error occurred: {e}")


def create_index(service, index_name, index_type="event"):
    """creates an index, when provided an splunk service session, index name, and index type"""
    try:
        if index_name in service.indexes:
            print(f"The index '{index_name}' already exists.")
            return

        params = {"name": index_name}
        if index_type == "metric":
            params["datatype"] = "metric"

        service.indexes.create(**params)
        print(f"Index '{index_name}' of type '{index_type}' created successfully.")
    except Exception as e:
        print(f"An error occurred while creating the index: {e}")


def edit_config(service, config, stanza, settings):
    """Edits a .conf file in the app that the service is authenticated to.
    Reqires an authenticated splunk service, config file name, stanza ([header] in the config)
    and a dict of the parameters to change."""

    try:
        conf_endpoint = service.confs[config]
    except KeyError:
        # Conf file doesn't exist yet - create it via direct REST POST
        service.post(f"configs/conf-{config}", name=stanza)
        conf_endpoint = service.confs[config]

    try:
        if stanza in conf_endpoint:
            stanza_obj = conf_endpoint[stanza]
        else:
            stanza_obj = conf_endpoint.create(stanza)

        for key, value in settings.items():
            stanza_obj.update(**{key: value}).refresh()
        print(f"Configuration parameters updated successfully for {config}.")

    except Exception as e:
        print(f"An error occurred while updating the configuration: {e}")


def change_credential(service, username, realm, new_password):
    """Changes a stored credential in splunk when given a authenticated service, username, realm, and new password."""
    try:
        storage_passwords = s.storage_passwords
        service.storage_passwords.create(
            password=new_password, username=username, realm=realm
        )
        print(
            f"Password for username: {username} in realm: {realm} changed successfully."
        )

    except Exception as e:
        print(f"An error occurred while retrieving the credentials: {e}")


def post_data_to_index(service, file_path, index, sourcetype, source):
    """Posts data payload to an existing index"""

    with open(file_path, "r") as file:
        lines = file.readlines()
        total = len(lines)
        print(f"Posting {total} events to {index}...", end="", flush=True)

        for i, line in enumerate(lines, 1):
            service.post(
                "/services/receivers/simple",
                source=source,
                sourcetype=sourcetype,
                index=index,
                body=line.strip(),
            )
            # Show progress every 1000 lines
            if i % 1000 == 0:
                print(
                    f"\rPosting {total} events to {index}... {i}/{total} ({i * 100 // total}%)",
                    end="",
                    flush=True,
                )

        print(f"\rWrote {total} events from {file_path} to {index}.")


def create_input(service, file_path, index, sourcetype):
    """creates an input type of monitor, when specified an active splunk sevice,
    file path, index name, and sourcetype"""
    input_type = "monitor"  # hardcoded
    parameters = {"index": index, "sourcetype": sourcetype}
    try:
        data_input = service.inputs.create(file_path, input_type, **parameters)
        print(
            f"Data input for {file_path} created successfully into index {parameters['index']}."
        )
    except Exception as e:
        print(f"An error occurred creating the data input for {file_path}: {e}")


def _rebase_otel_timestamps(src_path, offset_ns):
    """Returns a list of JSON strings with all OTel nanosecond timestamps
    shifted forward by offset_ns nanoseconds."""
    rebased = []
    with open(src_path, "r") as f:
        for line in f:
            d = json.loads(line)
            for rm in d.get("resourceMetrics", []):
                for sm in rm.get("scopeMetrics", []):
                    for m in sm.get("metrics", []):
                        for pt in m.get("gauge", {}).get("dataPoints", []):
                            for field in ("startTimeUnixNano", "timeUnixNano"):
                                if field in pt:
                                    pt[field] = str(int(pt[field]) + offset_ns)
            rebased.append(json.dumps(d))
    return rebased


def _rebase_emaps_timestamps(src_path, offset_seconds):
    """Returns a list of JSON strings with emaps datetime/updatedAt fields
    shifted forward by offset_seconds seconds."""
    import datetime

    rebased = []
    with open(src_path, "r") as f:
        for line in f:
            d = json.loads(line)
            for field in ("datetime", "updatedAt"):
                if field in d:
                    ts = datetime.datetime.fromisoformat(
                        d[field].replace("Z", "+00:00")
                    )
                    ts += datetime.timedelta(seconds=offset_seconds)
                    d[field] = (
                        ts.strftime("%Y-%m-%dT%H:%M:%S.")
                        + f"{ts.microsecond // 1000:03d}Z"
                    )
            rebased.append(json.dumps(d))
    return rebased


def _add_sample_data(i):
    """Adds sample jsonl OTel data and associated electricity maps data,
    with all timestamps rebased so the end of the dataset lands at the
    current time. Assumes sample file locations from git repo."""
    import datetime, tempfile, os

    # Compute offset: shift data so OTel max timestamp (2024-05-22 16:00:28 UTC)
    # lands at the current time.
    data_end_utc = datetime.datetime(
        2024, 5, 22, 16, 0, 28, tzinfo=datetime.timezone.utc
    )
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    offset_seconds = (now_utc - data_end_utc).total_seconds()
    offset_ns = int(offset_seconds * 1_000_000_000)
    print(
        f"Rebasing sample data timestamps by {offset_seconds / 86400:.1f} days to current time..."
    )

    # Add example emaps historical data with rebased timestamps
    src = _get_sample_data_path("emaps-export.jsonl")
    rebased_lines = _rebase_emaps_timestamps(src, offset_seconds)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
        tmp.write("\n".join(rebased_lines))
        tmp_emaps = tmp.name
    try:
        i["app"] = "TA-electricity-carbon-intensity"
        s = splunk_auth(i)
        post_data_to_index(
            service=s,
            file_path=tmp_emaps,
            index="electricity_carbon_intensity",
            sourcetype="EM:carbonintensity",
            source="electricity_maps_carbon_intensity_latest",
        )
    finally:
        os.unlink(tmp_emaps)

    # Add example OTel JSON with rebased timestamps
    src = _get_sample_data_path("otelcol-export.jsonl")
    rebased_lines = _rebase_otel_timestamps(src, offset_ns)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
        tmp.write("\n".join(rebased_lines))
        tmp_otel = tmp.name
    try:
        i["app"] = "Sustainability_Toolkit"
        s = splunk_auth(i)
        post_data_to_index(
            service=s,
            file_path=tmp_otel,
            index="otel",
            sourcetype="_json",
            source="otelcol-export.json",
        )
    finally:
        os.unlink(tmp_otel)


##########################################################################################################

# Authenticate to splunk
i = get_input_for_auth()
s = splunk_auth(i)

# Check that required (and optional) apps are installed, offering auto-install if not
REQUIRED_APPS = [
    {
        "display_name": "Sustainability Toolkit for Splunk",
        "folder_name": "Sustainability_Toolkit",
        "splunkbase_id": 6343,
        "required": True,
    },
    {
        "display_name": "Splunk Add-on for Electricity Carbon Intensity",
        "folder_name": "TA-electricity-carbon-intensity",
        "splunkbase_id": 7089,
        "required": True,
    },
    {
        "display_name": "Splunk App for Lookup File Editing",
        "folder_name": "lookup_editor",
        "splunkbase_id": 1724,
        "required": False,
    },
    {
        "display_name": "Splunk MCP Server",
        "folder_name": "Splunk_MCP_Server",
        "splunkbase_id": 7582,
        "required": False,
    },
    {
        "display_name": "Machine Learning Toolkit",
        "folder_name": "Splunk_ML_Toolkit",
        "splunkbase_id": 2890,
        "required": False,
    },
    {
        "display_name": "Python for Scientific Computing",
        # Splunkbase installs a platform-specific folder; check for the linux x86_64 variant.
        # On other platforms this may be Splunk_SA_Scientific_Python_darwin_x86_64 etc.
        "folder_name": "Splunk_SA_Scientific_Python_linux_x86_64",
        "splunkbase_id": 2882,
        "required": False,
    },
]

if not check_and_install_apps(s, REQUIRED_APPS):
    sys.exit(1)

# Change to the sustainability app context
i["app"] = "Sustainability_Toolkit"
s = splunk_auth(i)

# Step 1 - Ensure the right indexes are created
create_index(s, "otel", index_type="event")
create_index(s, "electricity_carbon_intensity", index_type="event")
create_index(s, "sustainability_toolkit_summary_asset_metrics", index_type="metric")
create_index(
    s, "sustainability_toolkit_summary_electricity_metrics", index_type="metric"
)

# Step 1b - See if the user wants the cold snapshot sample OTel data loaded in
# Note: this script needs to be run on the splunk server itself to place a file,
# otherwise creating the data file will fail and you will have to copy it manually.

load_data = input(
    "\nIf you do not have an active OpenTelemetry data pipeline yet, we can load example \
OpenTelemetry data from Cisco Intersight into a splunk index for you. \
\n\nDo you want to load the example data? (y/n): "
)

if load_data.lower() == "y" or load_data.lower() == "yes":
    _add_sample_data(i)

#################################

# Step 2 - Configure Electricity Maps

print("Switching to the carbon intensity app context.")
i["app"] = "TA-electricity-carbon-intensity"
s = splunk_auth(i)

emaps_api_key = input(
    "\nEnter your Electricity Maps API key (get one at https://api.electricitymap.org/): "
).strip()

while not emaps_api_key:
    emaps_api_key = input(
        "API key cannot be empty. Enter your Electricity Maps API key: "
    ).strip()

# Write the account credentials directly into the TA conf.
# The stanza 'electricitymaps' is pre-created by the TA; update it in-place.
edit_config(
    s,
    "ta_electricity_carbon_intensity_add_on_for_splunk_account",
    "electricitymaps",
    {
        "username": "https://api.electricitymap.org/v3",
        "password": emaps_api_key,
    },
)
print("Electricity Maps API account configured successfully.")

answer = input(
    "Do you already know the name of your electricitymaps zones? If not, we can show \
you the options here by saying no (y/n): "
)

if answer.lower() == "n" or answer.lower() == "no":
    z = urllib.request.urlopen("https://api.electricitymap.org/v3/zones").read()
    print(json.loads(z))

my_zones = input(
    "Enter the electricitymaps zones you want to collect data from, in a comma separated \
format. See above for the full list of zones (e.g. CH,DE,PL,US-CAR-DUK,US-CAL-LDWP): "
)

# Configure collection of latest data every hour.
config = "inputs"
stanza = "electricity_maps_carbon_intensity_latest://electricitymapslatest"
settings = {
    "electricity_maps_account": "electricitymaps",
    "interval": "3600",
    "zone_s_": my_zones,
    "index": "electricity_carbon_intensity",
}

edit_config(s, config, stanza, settings)

print("Switching back to the Sustainability Toolkit app context")
i["app"] = "Sustainability_Toolkit"
s = splunk_auth(i)

#################################################

# Update search macros that reference sample lookup to use lookup files, and optionally
# auto-copy the sample CSVs into the app's lookups directory.
rename_macro(s, "cmdb-lookup-name", "cmdb-lookup-name-old")
create_macro(s, "cmdb-lookup-name", "otel_sample_cmdb.csv")

rename_macro(s, "sites-lookup-name", "sites-lookup-name-old")
create_macro(s, "sites-lookup-name", "otel_sample_sites.csv")

load_lookups = (
    input(
        "\nWould you like to load the sample lookup files (otel_sample_cmdb.csv and otel_sample_sites.csv)? "
        "These map hostnames to site and asset information. (y/n): "
    )
    .strip()
    .lower()
)

if load_lookups in ("y", "yes"):
    _lookup_src_dir = (
        Path(os.path.dirname(os.path.realpath("__file__"))).parent
        / "splunk"
        / "lookups"
    )
    _lookup_dst_dir = Path("/opt/splunk/etc/apps/Sustainability_Toolkit/lookups")
    _lookup_dst_dir.mkdir(parents=True, exist_ok=True)
    for _csv in ("otel_sample_cmdb.csv", "otel_sample_sites.csv"):
        _src = _lookup_src_dir / _csv
        _dst = _lookup_dst_dir / _csv
        shutil.copy(str(_src), str(_dst))
        print(f"Copied {_csv} to {_dst}")
    print("Sample lookup files loaded. Edit them to match your environment as needed.")
else:
    print(
        "Skipping lookup file copy. To load them manually, copy otel_sample_cmdb.csv and "
        "otel_sample_sites.csv from the splunk/lookups folder to "
        "/opt/splunk/etc/apps/Sustainability_Toolkit/lookups/"
    )


# Step 3 - Create power-otel search macro
d = _get_spl_from_file("power-otel.txt")
create_macro(s, "power-otel", d)


# Step 4 - Modify power-asset-location to look at otel data
d = _get_spl_from_file("power-asset-location.txt")
rename_macro(s, "power-asset-location", "power-asset-location-old")
create_macro(s, "power-asset-location", d)

# Step 4a - Modify electricity-carbon-intensity to remove time summarization
d = _get_spl_from_file("electricity-carbon-intensity.txt")
rename_macro(s, "electricity-carbon-intensity", "electricity-carbon-intensity-old")
create_macro(s, "electricity-carbon-intensity", d)


# Step 5 - Modify Carbon Intensity macro
rename_macro(
    s,
    "electricity-carbon-intensity-for-assets",
    "electricity-carbon-intensity-for-assets-old",
)
d = _get_spl_from_file("electricity-carbon-intensity-for-assets.txt")
create_macro(s, "electricity-carbon-intensity-for-assets", d)


# Step 6 - Edit summarization for Summarize Asset CO2e & kW V1.0
d = _get_spl_from_file("Summarize Asset CO2e & kW V1.0.txt")
p = {
    "is_scheduled": True,
    "cron_schedule": "23 * * * *",
    "search": d,
    "description": "Modified to support OTel",
}
# rename_saved_search(s,'Summarize Asset CO2e & kW V1.0','Summarize Asset CO2e & kW V1.0-old')
update_saved_search(s, "Summarize Asset CO2e & kW V1.0", p)


# Step 7 - Uncomment mcollect in Summarize Electricity CO2e/kWh
d = _get_spl_from_file("Summarize Electricity CO2e_kWh V1.0.txt")
p = {"is_scheduled": True, "cron_schedule": "24 * * * *", "search": d}
# rename_saved_search(s,'Summarize Asset CO2e & kW V1.0','Summarize Asset CO2e & kW V1.0-old')
update_saved_search(s, "Summarize Electricity CO2e/kWh V1.0", p)
