#!/usr/bin/env python3
# coding: utf-8
#
# otel-sst-quickstart.py
# © 2024 Cisco and/or its affiliates. All rights reserved.
#
# A companion setup script to automate the changes to Splunk Sustainability Toolkit to 
# allow for OpenTelemetry support
#
# v1.2 - 27-mar-2026 - Added: auto-upload lookup CSVs, timestamp normalization for 
# stale sample data, dashboard time picker defaults, dispatch time range fix,
# and automatic summarization backfill kickoff.
# v1.1 - 31-may-2024 - Added support to automate loading example files into splunk for 
# those that don't have an active OpenTelemetry pipeline to ingest from.
# v1.0 - 17-may-2024 - Initial release. sholl@cisco.com

# Install this dependency via 'pip3 install splunk-sdk'
import splunklib.client as client
import splunklib.results as results        
import urllib.request
import urllib.parse

from getpass import getpass
import os
from pathlib import Path
import json
import time
import sys
import datetime
import re
import copy

def _get_spl_from_file(filename):
    '''internal function to get the path where the spl file is located'''
    p = os.path.dirname(os.path.realpath('__file__'))
    path = Path(p)
    f = os.path.join(path.parent.absolute(),'splunk','spl',filename)
    with open(f, 'r') as file:
        d = file.read()
    return d

def _get_sample_data_path(filename):
    '''Internal function to get path of sample file data for loading in, if desired.'''
    p = os.path.dirname(os.path.realpath('__file__'))
    path = Path(p)
    f = os.path.join(path.parent.absolute(),'data',filename)
    return f

def get_input_for_auth():
    '''Collects input for Splunk server authentication from the user in CLI. 
    Returns a dict for splunk_auth().'''
    i = {
        "host": None,
        "port": None,
        "username": None,
        "password": None
    }    
    i['host'] = input('Enter your splunk IP or hostname: ')
    if not i['host']:
        i['host'] = 'localhost'
        
    
    i['port'] = input('Enter your Splunk management port (usually 8089): ')
    if i['port'] == '8000':
        print('INFO: Port 8000 is usually the Splunk Web port to acces the UI, \
                and not the port used for the management API. \
                To validate, check what port your Universal Forwarders are sending to.')
        i['port'] = input('Enter your Splunk management port (usually 8089): ')
    if not i['port']:
        i['port'] = '8089'  
        
    i['username'] = input('Enter your Splunk username: ')
    if not i['username']:
        i['username'] = 'admin' 
        
    while not i['password']:    
        i['password'] = getpass('Enter your Splunk password: ')    

    i['app'] = "search"

    return i

def splunk_auth(auth_input):
    '''Takes a dictionary of host, port, username, password, and app and returns an active splunk session.'''
    try:
        # Connect to Splunk
        service = client.connect(
            host = i['host'],
            port = i['port'],
            username = i['username'],
            password = i['password'],
            app = i['app'],
            owner = 'nobody'
        )
        print ('Info: Authenticated successfully to Splunk.')
    except Exception as e:
        print (e)
        print('Error: Could not authenticate to Splunk with the provided information. \
                Please check the input and retry.')
        raise
    return service

def create_macro(service, macro_name, definition):
    '''Adds a new search macro to Splunk, when provided an active splunk service session, 
    macro name, and macro definition.'''
    try:
        service.post('properties/macros', __stanza=macro_name)
        service.post(f'properties/macros/{macro_name}', definition=definition)
        print(f'Search macro {macro_name} has been created.')
    except:
        print(f'ERROR: Search macro {macro_name} could not be created.')
        raise

def rename_macro(service, macro_name_old, macro_name_new):
    '''Renames an existing search macro in Splunk, when provided an active splunk service session, 
    and the old & new macro names.'''
    try:
        definition = service.get(f'properties/macros/{macro_name_old}/definition')['body']
    except:
        print(f'ERROR: Could not find and get propertes of search macro {macro_name_old}. Rename was unsuccessful.')
        raise
    create_macro(service=service, macro_name=macro_name_new,definition=definition)
    #delete_macro(service=service,macro_name=macro_name_old)


def delete_macro(service, macro_name):
    '''Deletes an existing search macro in Splunk, when provided an active splunk service 
    session and the macro name.'''
    macro = service.confs['macros'][macro_name]
    try:
        macro.delete()
        print(f'Search macro {macro_name} has been deleted.')
    except:
        print(f'ERROR: Search macro {macro_name} could not be deleted.')

def create_saved_search(service, search_name, search_query):
    '''Adds a new saved search to Splunk, when provided an active splunk service session, 
    search name, and SPL query.'''
    try:
        service.get(f'search')
        service.saved_searches.create(search_name, search_query)
        print(f'Saved search {search_name} has been created.')
    except:
        print(f'ERROR: Saved search {search_name} could not be created.')
        raise

def delete_saved_search(service, search_name):
    '''Deletes a  saved search in Splunk, when provided an active splunk service session, 
    and search name.'''    
    try:
        service.get(f'search')
        service.saved_searches.delete(search_name)
        print(f'Saved search {search_name} was deleted.')
    except:
        print(f'ERROR: Saved search {search_name} could not be deleted.')
        raise

def rename_saved_search(service, search_name_old, search_name_new):
    '''Renames an existing saved search in Splunk, when provided an active splunk 
    service session, and the old & new macro names'''
    try:
        service.get(f'search')
        search_query = service.saved_searches[search_name_old]['qualifiedSearch']
    except:
        print(f'ERROR: Could not find and extract details for {search_name_old}')
    create_saved_search(service=service,search_name=search_name_new,search_query=search_query)
    delete_saved_search(service, search_name_old)

def schedule_saved_search(service, search_name, cron):
    '''Edits the schedule for an existing saved search in Splunk, when provided an active splunk service session, 
    the search name, and the cron schedule.'''
    try:
        saved_search = service.saved_searches[search_name]
    except:
        print(f'ERROR: Could not find saved search: {search_name}')
        raise
    # Update the saved search with the new cron schedule
    try:
        kwargs = {
            "is_scheduled": True,
            "cron_schedule": "15 4 * * 6"
        }
        saved_search.update(**kwargs).refresh()
    except:
        print('ERROR: Failed to edit schedule for search {search_name}')

def check_app(service, app_name):
    '''Checks if a single app is installed. Returns True/False.'''
    for app in service.apps:
        if app.name == app_name:
            return True
    return False

def _get_splunkbase_token(username, password):
    '''Authenticates to splunkbase.splunk.com and returns a session token.
    Requires a splunk.com account (free to create at https://www.splunk.com/page/sign_up).'''
    import xml.etree.ElementTree as ET

    url = 'https://splunkbase.splunk.com/api/account:login/'
    data = urllib.parse.urlencode({
        'username': username,
        'password': password
    }).encode()
    req = urllib.request.Request(url, data=data)
    try:
        resp = urllib.request.urlopen(req)
        body = resp.read().decode()
        root = ET.fromstring(body)
        # Token is in <id> element within the feed
        token = root.find('.//{http://www.w3.org/2005/Atom}id')
        if token is not None and token.text:
            return token.text
        # Fallback: check for a direct token response
        return body.strip()
    except Exception as e:
        print(f'  ERROR: Could not authenticate to Splunkbase: {e}')
        return None

def install_app_from_splunkbase(service, app_name, splunkbase_id, splunkbase_token):
    '''Installs an app from Splunkbase using the REST API.
    Requires a valid Splunkbase session token.
    Returns True on success, False on failure.'''
    try:
        # The Splunk REST API installs Splunkbase apps via POST /services/apps/local
        # with the name parameter set to the Splunkbase package URL and auth token
        service.post('/services/apps/local',
                     name=f'https://splunkbase.splunk.com/app/{splunkbase_id}/',
                     auth=splunkbase_token,
                     update='true')
        print(f'  Installed {app_name} successfully.')
        return True
    except Exception as e:
        print(f'  ERROR installing {app_name}: {e}')
        return False

def check_apps(service, host):
    '''Checks all required and optional Splunk apps, reports status, and offers
    to auto-install missing apps from Splunkbase. Exits if required apps cannot
    be installed.'''

    # App definitions: (internal_name, display_name, splunkbase_id, required)
    app_list = [
        ('Sustainability_Toolkit',                  'Sustainability Toolkit for Splunk',    '6343',  True),
        ('TA-electricity-carbon-intensity',          'Splunk Add-on for Electricity Carbon Intensity', '7089', True),
        ('lookup_editor',                           'Splunk App for Lookup File Editing',   '1724',  False),
        ('Splunk_MCP_Server',                       'Splunk MCP Server',                    '7582',  False),
        ('Splunk_ML_Toolkit',                       'Machine Learning Toolkit',             '2890',  False),
        ('Splunk_SA_Scientific_Python_linux_x86_64', 'Python for Scientific Computing',     '2882',  False),
    ]

    print('\n--- Checking installed Splunk apps ---')
    missing_required = []
    missing_optional = []
    all_missing = []

    for app_id, display_name, splunkbase_id, required in app_list:
        installed = check_app(service, app_id)
        req_label = 'required' if required else 'optional'
        icon = '  [OK]  ' if installed else '  [  ]  '
        print(f'{icon} {display_name} ({req_label})')
        if not installed:
            url = f'https://splunkbase.splunk.com/app/{splunkbase_id}'
            print(f'          Install from: {url}')
            entry = (app_id, display_name, splunkbase_id)
            all_missing.append(entry)
            if required:
                missing_required.append(entry)
            else:
                missing_optional.append(entry)

    if not all_missing:
        print('\nAll apps are installed.')
        print()
        return

    # Offer to auto-install missing apps
    print(f'\n{len(all_missing)} app(s) are not installed:')
    for app_id, display_name, splunkbase_id in all_missing:
        req = '(REQUIRED)' if any(a[0] == app_id for a in missing_required) else '(optional)'
        print(f'  - {display_name} {req}')

    auto_install = input('\nWould you like this script to install the missing app(s) automatically?\n'
                         'This requires a splunk.com account (free). (y/n): ')

    if auto_install.lower() in ('y', 'yes'):
        print('\nSplunkbase authentication required.')
        print('If you do not have a splunk.com account, create one at: https://www.splunk.com/page/sign_up')
        sb_user = input('Enter your splunk.com username (email): ')
        sb_pass = getpass('Enter your splunk.com password: ')

        token = _get_splunkbase_token(sb_user, sb_pass)
        if not token:
            print('ERROR: Could not authenticate to Splunkbase. Install apps manually and re-run.')
            if missing_required:
                sys.exit(1)
        else:
            print('  Authenticated to Splunkbase successfully.\n')
            install_failures = []
            for app_id, display_name, splunkbase_id in all_missing:
                print(f'  Installing {display_name}...')
                success = install_app_from_splunkbase(service, display_name, splunkbase_id, token)
                if not success:
                    install_failures.append((app_id, display_name, splunkbase_id))

            if install_failures:
                failed_required = [f for f in install_failures if any(r[0] == f[0] for r in missing_required)]
                print(f'\nWARNING: {len(install_failures)} app(s) failed to install:')
                for app_id, display_name, splunkbase_id in install_failures:
                    print(f'  - {display_name}: https://splunkbase.splunk.com/app/{splunkbase_id}')

                if failed_required:
                    manage_url = f'http://{host}:8000/en-US/manager/search/appsremote'
                    print(f'\nRequired apps failed to install. Install them manually from:')
                    print(f'  {manage_url}')
                    print('Then re-run this script.')
                    sys.exit(1)
                else:
                    print('Only optional apps failed. Continuing...')
            else:
                print('\nAll missing apps installed successfully!')
    else:
        # User declined auto-install
        if missing_required:
            manage_url = f'http://{host}:8000/en-US/manager/search/appsremote'
            print(f'\nERROR: {len(missing_required)} required app(s) must be installed before continuing:')
            for app_id, display_name, splunkbase_id in missing_required:
                print(f'  - {display_name}: https://splunkbase.splunk.com/app/{splunkbase_id}')
            print(f'\nInstall from Splunk Web: {manage_url}')
            print('Then re-run this script.')
            sys.exit(1)

        if missing_optional:
            proceed = input(f'\n{len(missing_optional)} optional app(s) not installed. Continue without them? (y/n): ')
            if proceed.lower() not in ('y', 'yes', ''):
                sys.exit(0)

    print()

def update_saved_search(service, saved_search_name, properties):
    '''Updates an existing saved_search, given existing authenticated splunk service, the search name, 
    and a properties dict for the attributes to change.'''
    try:
        saved_search = service.saved_searches[saved_search_name]
        saved_search.update(**properties).refresh()
        print(f"Saved search '{saved_search_name}' updated successfully.")
        
    except KeyError:
        print(f"Saved search '{saved_search_name}' not found.")
        
    except Exception as e:
        print(f"An error occurred: {e}")

def create_index(service, index_name, index_type='event'):
    '''creates an index, when provided an splunk service session, index name, and index type'''
    try:
        if index_name in service.indexes:
            print(f"The index '{index_name}' already exists.")
            return

        params = {'name': index_name}
        if index_type == 'metric':
            params['datatype'] = 'metric'

        service.indexes.create(**params)
        print(f"Index '{index_name}' of type '{index_type}' created successfully.")
    except Exception as e:
        print(f"An error occurred while creating the index: {e}")

def edit_config(service,config,stanza,settings):
    '''Edits a .conf file in the app that the service is authenticated to. 
    Reqires an authenticated splunk service, config file name, stanza ([header] in the config) 
    and a dict of the parameters to change.'''

    conf_endpoint = service.confs[config]

    try:
        if stanza in conf_endpoint:
            stanza = conf_endpoint[stanza]
        else:
            stanza = conf_endpoint.create(stanza)
    
        for key, value in settings.items():
            stanza.update(**{key: value}).refresh()
        print(f"Configuration parameters updated successfully for {config}.")
        
    except Exception as e:
        print(f"An error occurred while updating the configuration: {e}")

def change_credential(service, username, realm, new_password):
    '''Changes a stored credential in splunk when given a authenticated service, username, realm, and new password.'''
    try:
        storage_passwords = s.storage_passwords
        service.storage_passwords.create(password=new_password, username=username, realm=realm)
        print(f"Password for username: {username} in realm: {realm} changed successfully.")
    
    except Exception as e:
        print(f"An error occurred while retrieving the credentials: {e}")

def post_data_to_index(service, file_path, index, sourcetype, source):
    '''Posts data payload to an existing index'''

    with open(file_path, 'r') as file:
        lines = file.readlines()
        total = len(lines)
        print(f'Posting {total} events to {index}...', end='', flush=True)

        for i, line in enumerate(lines, 1):
            service.post(
                '/services/receivers/simple',
                source=source,
                sourcetype=sourcetype,
                index=index,
                body=line.strip()
            )
            # Show progress every 1000 lines
            if i % 1000 == 0:
                print(f'\rPosting {total} events to {index}... {i}/{total} ({i*100//total}%)', end='', flush=True)

        print(f'\rWrote {total} events from {file_path} to {index}.')

        
def create_input(service,file_path,index,sourcetype):  
    '''creates an input type of monitor, when specified an active splunk sevice, 
    file path, index name, and sourcetype'''
    input_type = 'monitor' #hardcoded
    parameters = {
        'index': index,
        'sourcetype': sourcetype
    }
    try:
        data_input = service.inputs.create(file_path, input_type, **parameters)
        print(f"Data input for {file_path} created successfully into index {parameters['index']}.")
    except Exception as e:
        print(f"An error occurred creating the data input for {file_path}: {e}")

def _get_lookup_csv_path(filename):
    '''Internal function to get path of lookup CSV files.'''
    p = os.path.dirname(os.path.realpath('__file__'))
    path = Path(p)
    f = os.path.join(path.parent.absolute(),'splunk','lookups',filename)
    return f

def _normalize_timestamps(data_dir):
    '''Checks if sample data is older than 30 days, and if so, shifts all timestamps
    so that the most recent timestamp in each file aligns with the current time.
    Operates on the data files in-place (overwrites them).
    Returns True if normalization was performed, False otherwise.'''

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    thirty_days_ago = now_utc - datetime.timedelta(days=30)

    # --- Analyze OTel data timestamps ---
    otel_path = os.path.join(data_dir, 'otelcol-export.jsonl')
    emaps_path = os.path.join(data_dir, 'emaps-export.jsonl')

    if not os.path.exists(otel_path) or not os.path.exists(emaps_path):
        print('WARNING: Sample data files not found. Skipping timestamp normalization.')
        return False

    # Find the max timestamp in OTel data
    max_otel_nano = 0
    with open(otel_path) as f:
        for line in f:
            d = json.loads(line)
            for rm in d.get('resourceMetrics', []):
                for sm in rm.get('scopeMetrics', []):
                    for m in sm.get('metrics', []):
                        for dp in m.get('gauge', {}).get('dataPoints', []):
                            for field in ['startTimeUnixNano', 'timeUnixNano']:
                                val = dp.get(field)
                                if val and int(val) > max_otel_nano:
                                    max_otel_nano = int(val)

    if max_otel_nano == 0:
        print('WARNING: No timestamps found in OTel data. Skipping normalization.')
        return False

    max_otel_dt = datetime.datetime.fromtimestamp(max_otel_nano / 1e9, tz=datetime.timezone.utc)
    print(f'  Most recent OTel data timestamp: {max_otel_dt.strftime("%Y-%m-%d %H:%M:%S UTC")}')

    if max_otel_dt >= thirty_days_ago:
        print('  Data is less than 30 days old. No normalization needed.')
        return False

    age_days = (now_utc - max_otel_dt).days
    print(f'  Data is {age_days} days old (>30 days). Normalizing timestamps to current time...')

    # Calculate offset: shift so max timestamp becomes "now"
    offset_nano = int((now_utc - max_otel_dt).total_seconds() * 1e9)

    # --- Normalize OTel data ---
    print(f'  Normalizing {otel_path}...')
    normalized_otel = []
    with open(otel_path) as f:
        for line in f:
            d = json.loads(line)
            for rm in d.get('resourceMetrics', []):
                for sm in rm.get('scopeMetrics', []):
                    for m in sm.get('metrics', []):
                        for dp in m.get('gauge', {}).get('dataPoints', []):
                            for field in ['startTimeUnixNano', 'timeUnixNano']:
                                if field in dp:
                                    dp[field] = str(int(dp[field]) + offset_nano)
            normalized_otel.append(json.dumps(d))

    with open(otel_path, 'w') as f:
        for line in normalized_otel:
            f.write(line + '\n')
    print(f'  Normalized {len(normalized_otel)} OTel events.')

    # --- Normalize emaps data ---
    # emaps uses ISO 8601 datetime strings in 'datetime', 'updatedAt', 'createdAt'
    offset_td = datetime.timedelta(seconds=offset_nano / 1e9)
    iso_fields = ['datetime', 'updatedAt', 'createdAt']
    iso_formats = [
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S.%f%z',
    ]

    def shift_iso(val, offset):
        '''Shift an ISO 8601 datetime string by an offset timedelta.'''
        for fmt in iso_formats:
            try:
                dt = datetime.datetime.strptime(val, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                new_dt = dt + offset
                # Preserve original format
                if '.' in val:
                    return new_dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{new_dt.microsecond:03d}' + 'Z'
                else:
                    return new_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            except ValueError:
                continue
        return val  # Return unchanged if no format matched

    print(f'  Normalizing {emaps_path}...')
    normalized_emaps = []
    with open(emaps_path) as f:
        for line in f:
            d = json.loads(line)
            for field in iso_fields:
                if field in d and d[field]:
                    d[field] = shift_iso(d[field], offset_td)
            normalized_emaps.append(json.dumps(d))

    with open(emaps_path, 'w') as f:
        for line in normalized_emaps:
            f.write(line + '\n')
    print(f'  Normalized {len(normalized_emaps)} emaps events.')

    # Verify
    new_max_dt = datetime.datetime.fromtimestamp((max_otel_nano + offset_nano) / 1e9, tz=datetime.timezone.utc)
    print(f'  New most recent OTel timestamp: {new_max_dt.strftime("%Y-%m-%d %H:%M:%S UTC")}')
    return True

def upload_lookup_csvs(service):
    '''Uploads the otel_sample_cmdb.csv and otel_sample_sites.csv lookup files
    to Splunk via outputlookup SPL, and ensures lookup definitions exist in transforms.conf.'''

    lookup_files = {
        'otel_sample_cmdb.csv': {
            'fields': ['Asset IP', 'Site', 'Country', 'Location', 'Application', 'Embodied CO2e', 'Years Lifetime'],
            'delimiter': ','
        },
        'otel_sample_sites.csv': {
            'fields': ['Site', 'Electricity CO2e per kWh Source', 'Electricity CO2e per kWh Source Location Code',
                       'Electricity Cost Source', 'Latitude', 'Longitude'],
            'delimiter': ','
        }
    }

    for filename, meta in lookup_files.items():
        # Create lookup definition in transforms.conf
        lookup_name = filename.replace('.csv', '')
        try:
            service.post('properties/transforms', __stanza=lookup_name)
            service.post(f'properties/transforms/{lookup_name}', filename=filename)
            print(f'  Created lookup definition: {lookup_name}')
        except Exception as e:
            if 'already exists' in str(e).lower():
                print(f'  Lookup definition {lookup_name} already exists.')
            else:
                print(f'  Note: lookup definition {lookup_name} may already exist ({e})')

        # Read the CSV from repo and upload via outputlookup
        csv_path = _get_lookup_csv_path(filename)
        if not os.path.exists(csv_path):
            print(f'  WARNING: {csv_path} not found. Skipping upload for {filename}.')
            continue

        with open(csv_path, 'r') as f:
            lines = f.readlines()

        # Parse CSV into SPL makeresults + outputlookup
        header = lines[0].strip().split(',')
        data_rows = [l.strip() for l in lines[1:] if l.strip()]

        # Build SPL using makeresults + eval + outputlookup
        # Join rows with semicolons, then split in SPL
        rows_str = ';'.join(data_rows)
        spl = f'| makeresults count=1\n'
        spl += f'| eval data="{rows_str}"\n'
        spl += f'| eval data=split(data,";")\n'
        spl += f'| mvexpand data\n'
        spl += f'| eval cols=split(data,",")\n'

        for idx, col in enumerate(header):
            spl += f'| eval "{col}"=mvindex(cols,{idx})\n'

        spl += f'| fields - _time data cols\n'
        spl += f'| outputlookup {filename}'

        try:
            service.jobs.oneshot(spl)
            print(f'  Uploaded lookup data: {filename} ({len(data_rows)} rows)')
        except Exception as e:
            print(f'  ERROR uploading {filename}: {e}')

def update_dashboard_timepicker(service, dashboard_name, earliest='0', latest='now'):
    '''Updates the default time picker in a Splunk dashboard XML to use the specified
    earliest/latest values. This replaces the <default> block inside <input type="time"> elements.'''
    try:
        # Fetch current dashboard XML
        resp = service.get(f'/servicesNS/nobody/Sustainability_Toolkit/data/ui/views/{dashboard_name}',
                           output_mode='json')
        body = json.loads(resp['body'].read())
        xml_data = body['entry'][0]['content']['eai:data']

        # Replace the default time range in time input elements
        old_pattern = r'(<input[^>]*type="time"[^>]*>\s*<label>[^<]*</label>\s*<default>\s*<earliest>)[^<]*(</earliest>\s*<latest>)[^<]*(</latest>\s*</default>)'
        new_repl = f'\\1{earliest}\\2{latest}\\3'
        new_xml = re.sub(old_pattern, new_repl, xml_data)

        if new_xml == xml_data:
            print(f'  Dashboard {dashboard_name}: no time picker changes needed.')
            return

        # Update the dashboard
        service.post(f'/servicesNS/nobody/Sustainability_Toolkit/data/ui/views/{dashboard_name}',
                     **{'eai:data': new_xml})
        print(f'  Dashboard {dashboard_name}: time picker default updated to earliest={earliest}, latest={latest}.')

    except Exception as e:
        print(f'  ERROR updating dashboard {dashboard_name}: {e}')

def dispatch_saved_search(service, search_name, earliest='0', latest='now'):
    '''Dispatches a saved search with an overridden time range and waits for completion.
    Returns the result count, or -1 on error.'''
    try:
        saved_search = service.saved_searches[search_name]
        job = saved_search.dispatch(**{
            'dispatch.earliest_time': earliest,
            'dispatch.latest_time': latest,
            'force_dispatch': True
        })
        print(f'  Dispatched \'{search_name}\' (SID: {job.sid})')
        while not job.is_done():
            time.sleep(2)
            job.refresh()
        job.refresh()
        result_count = int(job['resultCount'])
        run_duration = job['runDuration']
        print(f'  Completed: {result_count} results in {run_duration}s')
        return result_count
    except KeyError:
        print(f'  ERROR: Saved search \'{search_name}\' not found.')
        return -1
    except Exception as e:
        print(f'  ERROR dispatching \'{search_name}\': {e}')
        return -1

def _add_sample_data(i):
    '''Adds sample jsonl OTel data and associated electricty maps data from the same timeperiod
    to a splunk index named otel, when provided input for splunk authentication. Assumes sample file locations from git repo.
    
    If the sample data is older than 30 days, timestamps are automatically normalized
    to align with the current date before loading.'''

    # Check if timestamps need normalization
    p = os.path.dirname(os.path.realpath('__file__'))
    data_dir = os.path.join(Path(p).parent.absolute(), 'data')
    _normalize_timestamps(data_dir)

    #Add example emaps historical data aligned to the sample file
    f = _get_sample_data_path('emaps-export.jsonl')    
    i['app'] = 'TA-electricity-carbon-intensity'
    s = splunk_auth(i)
    post_data_to_index(service=s, file_path=f, index='electricity_carbon_intensity', sourcetype='EM:carbonintensity', 
                        source='electricity_maps_carbon_intensity_latest')

    #Add example OTel JSON
    f = _get_sample_data_path('otelcol-export.jsonl')
    i['app'] = 'Sustainability_Toolkit'
    s = splunk_auth(i)
    post_data_to_index(service=s, file_path=f, index='otel', sourcetype='_json', source='otelcol-export.json')

##########################################################################################################

#Authenticate to splunk
i = get_input_for_auth()
s = splunk_auth(i)

#Check that apps are installed
check_apps(s, i['host'])

#Change to the sustainability app context
i['app'] = 'Sustainability_Toolkit'
s = splunk_auth(i)

# Step 1 - Ensure the right indexes are created
create_index(s, 'otel', index_type='event')
create_index(s, 'electricity_carbon_intensity', index_type='event')
create_index(s, 'sustainability_toolkit_summary_asset_metrics', index_type='metric')
create_index(s, 'sustainability_toolkit_summary_electricity_metrics', index_type='metric')

# Step 1b - See if the user wants the cold snapshot sample OTel data loaded in
# Note: this script needs to be run on the splunk server itself to place a file, 
# otherwise creating the data file will fail and you will have to copy it manually.

load_data = input('\nIf you do not have an active OpenTelemetry data pipeline yet, we can load example \
OpenTelemetry data from Cisco Intersight into a splunk index for you. \
\n\nDo you want to load the example data? (y/n): ')

if load_data.lower() == 'y' or load_data.lower() == 'yes':
    _add_sample_data(i)

#################################

# Step 2 - Configure Electricity Maps

'''Conf ta_electricity_carbon_intensity_add_on_for_splunk_account is not created until the first account is added, and
Adding new conf files from REST is not supported. This step must be done manually.'''

print('Switching to the carbon intensity app context.')
i['app'] = 'TA-electricity-carbon-intensity'
s = splunk_auth(i)

url = f"http(s)://{i['host']}:8000/en-US/app/TA-electricity-carbon-intensity/configuration"

print(f'\n***ACTION REQUIRED***\nPlease navigate to this URL, click Add, and provision your electrictymaps API account, \
then return back here:\n{url}\n\nUse the following information:\n Electricity Maps Account name: \
electricitymaps\n Base Product URL: https://api.electricitymap.org/v3\n API Key: [your API key]')

time.sleep(5)
input('\nOnce you complete this step return to this window and hit enter to proceed with the automation: ')

answer = input('Do you already know the name of your electricitymaps zones? If not, we can show \
you the options here by saying no (y/n): ')

if answer.lower()=='n' or answer.lower()=='no':
    z = urllib.request.urlopen("https://api.electricitymap.org/v3/zones").read()
    print(json.loads(z))

my_zones= input('Enter the electricitymaps zones you want to collect data from, in a comma separated \
format. See above for the full list of zones (e.g. CH,DE,PL,US-CAR-DUK,US-CAL-LDWP): ')

# Configure collection of latest data every hour.
config = 'inputs'
stanza = 'electricity_maps_carbon_intensity_latest://electricitymapslatest'
settings = {
    "electricity_maps_account": 'electricitymaps',
    "interval": '3600',
    "zone_s_": my_zones,
    "index": 'electricity_carbon_intensity'
}

edit_config(s,config,stanza,settings)

print('Switching back to the Sustainability Toolkit app context')
i['app'] = 'Sustainability_Toolkit'
s = splunk_auth(i)

#################################################

#Update search macros that reference sample lookup to use otel lookup files.
rename_macro(s,'cmdb-lookup-name','cmdb-lookup-name-old')
create_macro(s,'cmdb-lookup-name','otel_sample_cmdb.csv')

rename_macro(s,'sites-lookup-name','sites-lookup-name-old')
create_macro(s,'sites-lookup-name','otel_sample_sites.csv')

# Prompt user to auto-upload lookup CSVs or do it manually
upload_lookups = input('\nThe search macros cmdb-lookup-name and sites-lookup-name have been updated to \
reference otel_sample_cmdb.csv and otel_sample_sites.csv.\n\nWould you like this script to automatically \
upload the lookup CSV files from the repo to Splunk? (y/n): ')

if upload_lookups.lower() in ('y', 'yes'):
    print('Uploading lookup CSV files...')
    upload_lookup_csvs(s)
else:
    input('\n***ACTION REQUIRED***\nYou must upload the lookup files to match hostnames to site information. \\\nSee the splunk/lookups folder for the CSV files. Press enter when complete:')



# Step 3 - Create power-otel search macro
d = _get_spl_from_file('power-otel.txt')
create_macro(s,'power-otel',d)


# Step 4 - Modify power-asset-location to look at otel data
d = _get_spl_from_file('power-asset-location.txt')
rename_macro(s,'power-asset-location','power-asset-location-old')
create_macro(s,'power-asset-location',d)

# Step 4a - Modify electricity-carbon-intensity to remove time summarization
d = _get_spl_from_file('electricity-carbon-intensity.txt')
rename_macro(s,'electricity-carbon-intensity','electricity-carbon-intensity-old')
create_macro(s,'electricity-carbon-intensity',d)


# Step 5 - Modify Carbon Intensity macro
rename_macro(s,'electricity-carbon-intensity-for-assets','electricity-carbon-intensity-for-assets-old')
d = _get_spl_from_file('electricity-carbon-intensity-for-assets.txt')
create_macro(s,'electricity-carbon-intensity-for-assets',d)


# Step 6 - Edit summarization for Summarize Asset CO2e & kW V1.0
d = _get_spl_from_file('Summarize Asset CO2e & kW V1.0.txt')
p = {
    "is_scheduled": True,
    "cron_schedule": "23 * * * *",    
    "search": d,
    "description": "Modified to support OTel",
}
#rename_saved_search(s,'Summarize Asset CO2e & kW V1.0','Summarize Asset CO2e & kW V1.0-old')
update_saved_search(s, 'Summarize Asset CO2e & kW V1.0', p)


# Step 7 - Uncomment mcollect in Summarize Electricity CO2e/kWh
d = _get_spl_from_file('Summarize Electricity CO2e_kWh V1.0.txt')
p = {
    "is_scheduled": True,
    "cron_schedule": "24 * * * *",
    "search": d
}
#rename_saved_search(s,'Summarize Asset CO2e & kW V1.0','Summarize Asset CO2e & kW V1.0-old')
update_saved_search(s, 'Summarize Electricity CO2e/kWh V1.0', p)


# Step 8 - Update dashboard time picker defaults to All-time
# The default -30d@d time range won't show historical/sample data from the past.
# Changing to earliest=0 (All time) so dashboards always render available data.
print('\n--- Step 8: Updating dashboard time picker defaults to All-time ---')
for dashboard in ['coe_amp_energy', 'coe__energy_trends']:
    update_dashboard_timepicker(s, dashboard, earliest='0', latest='now')


# Step 9 - Update dispatch time range for summarization saved searches
# The default dispatch.earliest_time of -24h@h won't reach older/sample data.
# Setting to 0 (all time) so summarization covers all available data.
print('\n--- Step 9: Updating dispatch time range for summarization searches ---')
for ss_name in ['Summarize Asset CO2e & kW V1.0', 'Summarize Electricity CO2e/kWh V1.0']:
    try:
        saved_search = s.saved_searches[ss_name]
        saved_search.update(**{
            'dispatch.earliest_time': '0',
            'dispatch.latest_time': 'now'
        }).refresh()
        print(f'  Updated \'{ss_name}\' dispatch time range to earliest=0, latest=now.')
    except KeyError:
        print(f'  ERROR: Saved search \'{ss_name}\' not found.')
    except Exception as e:
        print(f'  ERROR updating \'{ss_name}\': {e}')


# Step 10 - Kick off summarization searches to backfill metric indexes
# The metric indexes won't have data until the summarization searches run.
# Dispatching them now so the dashboards show results immediately.
print('\n--- Step 10: Running summarization searches to populate metric indexes ---')
print('This may take a minute...')

print('\nRunning Summarize Electricity CO2e/kWh V1.0...')
elec_count = dispatch_saved_search(s, 'Summarize Electricity CO2e/kWh V1.0', earliest='0', latest='now')

print('\nRunning Summarize Asset CO2e & kW V1.0...')
asset_count = dispatch_saved_search(s, 'Summarize Asset CO2e & kW V1.0', earliest='0', latest='now')

if asset_count > 0 and elec_count > 0:
    print('\nSummarization complete! Both metric indexes have been populated.')
elif asset_count == 0 or elec_count == 0:
    print('\nWARNING: One or more summarization searches returned 0 results.')
    print('Check that sample data was loaded correctly and lookup files are in place.')
else:
    print('\nERROR: Summarization searches failed. Check Splunk logs for details.')

print(f'\n{"="*70}')
print('Setup complete! Navigate to your dashboard:')
print(f'  http://{i["host"]}:8000/en-US/app/Sustainability_Toolkit/coe_amp_energy')
print(f'{"="*70}')

