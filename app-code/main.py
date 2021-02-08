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
import ansible_runner, yaml, time
from datetime import datetime
from setup import bot_setup, influxdb_setup
from setup_alerts import alert_thresholds


# get configuration data
config = yaml.safe_load(open("credentials.yaml"))
influxdb_host = config['influxdb_host']
influxdb_port = config['influxdb_port']
influxdb_name = config['influxdb_name']
collector_interval = int(config['collector_interval'])
transceiver_update_interval = int(config['transceiver_update_interval'])


# setup bot and influxdb
bot_setup()
influxdb_setup()
client = InfluxDBClient(host=influxdb_host, port=influxdb_port, database=influxdb_name)


# loop to poll DOM data from devices every 60 seconds
i = -1
playbook_on_start_referencetime = datetime.utcnow()
while True:
    # to update transceiver information upon start and periodically as configured (~ every 24h if ansible_interval = 60 and transceiver_update_interval = 1440)
    i += 1
    if i % transceiver_update_interval == 0:
        mediatype_info = alert_thresholds()

    # ansible_runner to run the playbook specified as parameter and returns the result in an object
    r = ansible_runner.run(private_data_dir='/usr/src/app', playbook='playbook-show_int_transceiver.yaml')
    interface_list = []

    # the returned object includes different events that describe different stages of the playbook execution
    for event in r.events:

        # the event labeled "playbook_on_start" includes references to the most recent playbook execution
        if event['event'] == "playbook_on_start":
            created_string = event['created']
            created = datetime.strptime(created_string, '%Y-%m-%dT%H:%M:%S.%f')
            if created > playbook_on_start_referencetime:
                playbook_on_start_referencetime = created
                playbook_uuid_filter = event['event_data']['playbook_uuid']

        # the event labeled "runner_on_ok" includes the output of the command 'show interfaces transceiver' run in the playbook 'playbook-show_int_transceiver.yaml'
        if event['event'] == "runner_on_ok":
            playbook_uuid = event['event_data']['playbook_uuid']
            if playbook_uuid_filter == playbook_uuid:
                host = event['event_data']['host']

                cmd_line_output = event['event_data']['res']['stdout_lines'][0]
                for line in cmd_line_output[9:]:
                    x = ' '.join(line.split()).split(" ")

                    # get media type for host and interface
                    media_type = ''
                    for item in mediatype_info:
                        for hosts_listed in item['interfaces']:
                            if host == hosts_listed['host']:
                                for ints_listed in hosts_listed['interfaces']:
                                    if x[0] == ints_listed:
                                        media_type = item['media_type']
                    if media_type == '': # get threshold data if data cannot be found in existing list
                        mediatype_info = alert_thresholds()

                    # store DOM data and host info in dict
                    data = {
                        'host': host,
                        'interface': x[0],
                        'media_type': media_type,
                        'temperature': float(x[1]),
                        'voltage': float(x[2]),
                        'current': float(x[3]),
                        'optical tx power': float(x[4]),
                        'optical rx power': float(x[5])
                    }
                    interface_list.append(data)

    # prepare data to write to influxdb
    json_body = {}
    series = []
    total_records = 0
    for item in interface_list: 
        json_body = {
            "measurement": "dom_statistics",
            "tags": {
                "host": item["host"],
                "interface": item["interface"],
                "media_type": item["media_type"]
            },
            "time": datetime.utcnow(),
            "fields": item
        }
        series.append(json_body)
        total_records = total_records + 1

    # write to influxdb
    print("Write points: {0}".format(total_records))
    s = client.write_points(series)
    print('Successfully written to InfluxDB: ' + str(s))

    # pause the script for x seconds, represents the polling interval
    time.sleep(collector_interval)