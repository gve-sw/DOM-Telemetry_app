'''
Copyright (c) 2021 Cisco and/or its affiliates.

This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at

               https://developer.cisco.com/docs/licenses

All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.
'''


from influxdb import InfluxDBClient
import yaml, time, requests


# get configuration data
config = yaml.safe_load(open("credentials.yaml"))
heroku_username = config['heroku_username']
heroku_password = config['heroku_password']
heroku_region = config['heroku_region']
heroku_sourceblob_version = config['heroku_sourceblob_version']
heroku_sourceblob_url = config['heroku_sourceblob_url'] + '/tarball/' + heroku_sourceblob_version
webex_bot_token = config['webex_bot_token']
webex_room_id = config['webex_room_id']
influxdb_host = config['influxdb_host']
influxdb_port = config['influxdb_port']
influxdb_name = config['influxdb_name']
grafana_user = config['grafana_user']
grafana_password = config['grafana_password']
grafana_notificationchannel = config['grafana_notificationchannel']
grafana_notificationchannel_reminder = config['grafana_notificationchannel_reminder']
grafana_host = config['grafana_host']
grafana_port = config['grafana_port']


# connect to influxdb and create database
def influxdb_setup():
    time.sleep(5)

    # connect to influxdb
    client = InfluxDBClient(host=influxdb_host, port=influxdb_port)

    # check if DB already exists, and create if it does not
    existing_dbs = client.get_list_database()
    dom_exists = False
    for db in existing_dbs:
        if db['name'] == influxdb_name:
            dom_exists = True
            print('InfluxDB database already exists')
            break
    if dom_exists == False:
        client.create_database(influxdb_name)
        print('InfluxDB database created')

    return


# push Webex bot to Heroku and configure on Grafana
def bot_setup():
    print('Bot Setup starting')

    # provide basic information for heroku API calls
    heroku_base_url = 'https://api.heroku.com'
    heroku_headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/vnd.heroku+json; version=3'
    }

    # get heroku access token and update headers
    token_request = requests.post(heroku_base_url + '/oauth/authorizations', headers=heroku_headers, auth=(heroku_username, heroku_password))
    print('-H token_request: ' + str(token_request.status_code))
    token = token_request.json()['access_token']['token']
    heroku_headers['Authorization'] = 'Bearer ' + token

    # check if bot is already deployed on heroku and make sure the dyno is up and running
    deployed_apps = requests.get(heroku_base_url + '/apps', headers=heroku_headers)
    print('-H deployed_apps: ' + str(deployed_apps.status_code))
    heroku_deployed = False
    apps_deployed = []
    for app in deployed_apps.json():
        app_name = app['name']
        heroku_url = app['web_url']
        last_update = app['updated_at']
        get_build = requests.get(heroku_base_url + '/apps/' + app_name + '/builds', headers=heroku_headers)
        print('-H get_source_blob: ' + str(get_build.status_code))
        for build in get_build.json():
            if build['source_blob']['url'] == heroku_sourceblob_url:
                app_data = {
                    "name": app_name,
                    "url": heroku_url,
                    "last_updated": last_update
                }
                apps_deployed.append(app_data)
    if len(apps_deployed) != 0:
        heroku_deployed = True
        if len(apps_deployed) == 1:
            app_name = apps_deployed[0]['name']
            heroku_url = apps_deployed[0]['url']
            print('-H app already deployed at ' + heroku_url)
        else: # if there are multiple apps deployed with the same source_blob, the app that was last updated is used
            updated_times = []
            for item in apps_deployed:
                updated_times.append(item['last_updated'])
            most_recent = max(updated_times)
            for item in apps_deployed:
                if item['last_updated'] == most_recent:
                    app_name = item['name']
                    heroku_url = item['url']
                    print('-H multiple apps already deployed, using last updated app at ' + heroku_url)
                    break
        # check if dyno of app is up, restart otherwise
        while True:
            dyno_status = requests.get(heroku_base_url + '/apps/' + app_name + '/dynos/web.1/', headers=heroku_headers)
            dyno_status_value = dyno_status.json()['state']
            print('-H dyno_status: ' + str(dyno_status.status_code) + ', status: ' + dyno_status_value)
            # restart dyno if not up
            if dyno_status_value == 'up':
                print('-H dyno up and running')
                break
            else:
                dynorestart = requests.delete(heroku_base_url + '/apps/' + app_name + '/dynos', headers=heroku_headers)
                print('-H dynorestart: ' + str(dynorestart.status_code))
                time.sleep(10)

    # provide basic information for grafana API calls
    grafana_base_url = 'http://' + grafana_host + ':' + str(grafana_port) + '/api/alert-notifications'
    grafana_headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }

    # check if webhook for bot app is already configured on Grafana
    time.sleep(20) # pause script to wait for grafana container to be setup and responsive
    notification_channels = requests.get(grafana_base_url, headers=grafana_headers, auth=(grafana_user, grafana_password))
    print('-G notification_channels: ' + str(notification_channels.status_code))
    grafana_configured = False
    for notification_channel in notification_channels.json():
        if notification_channel['type'] == 'webhook':
            if notification_channel['uid'] == grafana_notificationchannel:
                grafana_configured = True
                grafana_webhookURL = notification_channel['settings']['url']
                print('-G notification channel already configured, webhook at ' + grafana_webhookURL)
                break

    # take actions based on whether heroku and grafana are already set up
    if heroku_deployed == True and grafana_configured == True:
        if heroku_url != grafana_webhookURL: # if the heroku url and grafana configured url are not the same, it must be updated (no update needed otherwise9
            grafana_config(heroku_url, 'update')
    elif heroku_deployed == True and grafana_configured == False:
        grafana_config(heroku_url, 'create')
    elif heroku_deployed == False:
        heroku_url = heroku_deploy(token)
        if grafana_configured == True:
            grafana_config(heroku_url, 'update')
        elif grafana_configured == False:
            grafana_config(heroku_url, 'create')

    print('Bot Setup finished')
    return


def grafana_config(webhook_url, action):

    # provide basic information for grafana API calls
    grafana_base_url = 'http://' + grafana_host + ':' + str(grafana_port) + '/api/alert-notifications'
    grafana_headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }

    # describe notification channel
    payload = {
        "uid": grafana_notificationchannel,
        "name": grafana_notificationchannel,
        "type": "webhook",
        "sendReminder": True,
        "frequency": grafana_notificationchannel_reminder,
        "settings": {
            "autoResolve": True,
            "httpMethod": "POST",
            "severity": "critical",
            "uploadImage": False,
            "url": webhook_url,
            "username": ""
        }
    }
    # either update or create notification channel
    if action == 'update':
        update_webhook_url = requests.put(grafana_base_url + '/uid/' + grafana_notificationchannel, json=payload, headers=grafana_headers, auth=(grafana_user, grafana_password))
        print('-G update_webhook_url: ' + str(update_webhook_url.status_code))
        if update_webhook_url.status_code == 200:
            print('-G notification channel updated with webhook url ' + webhook_url)
    elif action == 'create':
        create_admin_notification_channel = requests.post(grafana_base_url, json=payload, headers=grafana_headers, auth=(grafana_user, grafana_password))
        print('-G create_admin_notification_channel: ' + str(create_admin_notification_channel.status_code))
        if create_admin_notification_channel.status_code == 200:
            print('-G notification channel created with webhook url ' + webhook_url)

    return


def heroku_deploy(token):
    # provide basic information for heroku API calls
    heroku_base_url = 'https://api.heroku.com'
    heroku_headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/vnd.heroku+json; version=3',
        'Authorization': 'Bearer ' + token
    }

    payload_appsetup = {
        "app": {
            "region": heroku_region
        },
        "source_blob": {
            "url": heroku_sourceblob_url,
            "version": heroku_sourceblob_version
        }
    }
    appsetup = requests.post(heroku_base_url + '/app-setups', headers=heroku_headers, json=payload_appsetup)
    print('-H appsetup_request: ' + str(appsetup.status_code))
    appsetup_id = appsetup.json()['id']
    app_name = appsetup.json()['app']['name']

    # poll status until app is successfully setup
    while True:
        time.sleep(5)
        appsetup_status = requests.get(heroku_base_url + '/app-setups/' + appsetup_id, headers=heroku_headers)
        print('-H appsetup_status: ' + str(appsetup_status.status_code))
        appsetup_status_value = appsetup_status.json()['status']
        if appsetup_status_value == "succeeded":
            app_url = appsetup_status.json()['resolved_success_url']
            print('-H app deployed at ' + app_url)
            break
        elif appsetup_status_value == "failed":
            failure_message = appsetup_status.json()['failure_message']
            print('-H deployment failed: ' + str(failure_message))
            print('-G notification channel can therefore not be configured')
            return

    # configure config vars on app
    payload_configvars = {
        "WT_BOT_TOKEN": webex_bot_token,
        "WT_ROOM_ID": webex_room_id
    }
    configvars = requests.patch(heroku_base_url + '/apps/' + app_name + '/config-vars', headers=heroku_headers, json=payload_configvars)
    print('-H configvars_request: ' + str(configvars.status_code))
    if configvars.status_code == 200:
        # restart dyno
        dynorestart = requests.delete(heroku_base_url + '/apps/' + app_name + '/dynos', headers=heroku_headers)
        print('-H dynorestart: ' + str(dynorestart.status_code))
        while True:
            time.sleep(10)
            dyno_status = requests.get(heroku_base_url + '/apps/' + app_name + '/dynos/web.1/', headers=heroku_headers)
            dyno_status_value = dyno_status.json()['state']
            print('-H dyno_status: ' + str(dyno_status.status_code) + ', status: ' + dyno_status_value)
            if dyno_status_value == "up":
                print('-H dyno up and running')
                print("-H Webex bot successfully deployed on Heroku and running (for application logs, go to the Heroku dashboard, or if the Heroku CLI is installed, issue the command 'heroku logs -- tail -a " + app_name + "')")
                break

    return app_url

