#!/usr/bin/env python3
# coding: utf-8
#
# otel-sst-quickstart.py
# © 2024 Cisco and/or its affiliates. All rights reserved.
#
# A companion setup script to automate the changes to Splunk Sustainability Toolkit to 
# allow for OpenTelemetry support
#
# v1.1 - 31-may-2024 - Added support to automate loading example files into splunk for 
# those that don't have an active OpenTelemetry pipeline to ingest from.
# v1.0 - 17-may-2024 - Initial release. sholl@cisco.com

# Install this dependency via 'pip3 install splunk-sdk'
import splunklib.client as client
import splunklib.results as results        
import urllib.request

from getpass import getpass
import os
from pathlib import Path
import json
import time
import sys

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
    if i['host'] == None:
        i['host'] = 'localhost'
        
    
    i['port'] = input('Enter your Splunk management port (usually 8089): ')
    if i['port'] == '8000':
        print('INFO: Port 8000 is usually the Splunk Web port to acces the UI, \
                and not the port used for the management API. \
                To validate, check what port your Universal Forwarders are sending to.')
        i['port'] = input('Enter your Splunk management port (usually 8089): ')
    if i['port'] == None:
        i['port'] = '8089'  
        
    i['username'] = input('Enter your Splunk username: ') 
    if i['username'] == None:
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
    apps = service.apps
    app_installed = False
    for app in apps:
        if app.name == app_name:
            app_installed = True
            print(f"App '{app_name}' is installed.")
    
    if not app_installed:
        apps = s.apps
        print(f'App {app_name} is not installed. Please navigate to \
        http(s)://[splunkhostname]/en-US/manager/search/appsremote?offset=0&count=20&order=relevance&query=sustainability \
        and install Sustainability Toolkit for Splunk.')
        print('Rerun his script once both Sustainability_Toolkit and TA-electricity-carbon-intensity are installed')
        sys.exit()

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
        for line in file:                
            s.post(
                '/services/receivers/simple',
                source=source,
                sourcetype=sourcetype,
                index=index,
                body=line.strip()
            )
    print(f'Wrote sample data from {file_path} to {index}.')

        
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

def _add_sample_data(i):
    '''Adds sample jsonl OTel data and associated electricty maps data from the same timeperiod
    to a splunk index named otel, when provided input for splunk authentication. Assumes sample file locations from git repo.'''

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
apps = s.apps
check_app(s,'Sustainability_Toolkit')
check_app(s,'TA-electricity-carbon-intensity')

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

#Update search macros that reference sample lookup to use lookup files. Uploading the lookup file needs
# to be manually done by the user.
rename_macro(s,'cmdb-lookup-name','cmdb-lookup-name-old')
create_macro(s,'cmdb-lookup-name','otel_sample_cmdb.csv')

rename_macro(s,'sites-lookup-name','sites-lookup-name-old')
create_macro(s,'sites-lookup-name','otel_sample_sites.csv')

input('\n***ACTION REQUIRED***\nYou must edit the lookup files to match hostnames to site information. \
See the splunk/lookups folder for examples. We have automated changing the search macros cmdb-lookup-name \
and sites-lookup-name that reference these files for you. Press enter when complete:')



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

    

