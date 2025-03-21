import argparse
import json
import logging
import math
import os
import sys
import time
import traceback
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt
from requests_oauthlib import OAuth2Session

from lib.redis import load_token_from_redis, save_token_to_redis

MQTT_BROKER_HOST = os.getenv('MQTT_BROKER_HOST')
MQTT_BROKER_PORT = int(os.getenv('MQTT_BROKER_PORT', 1883))
MQTT_CLIENT_ID = os.getenv('MQTT_CLIENT_ID', 'fitbit-extra')
MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', '')
MQTT_TOPIC_PREFIX = os.getenv('MQTT_TOPIC_PREFIX', 'fitbit-extra')

HEART_RATE_API_URI = 'https://api.fitbit.com/1/user/-/activities/heart/date/{start_date}/{end_date}/{detail_level}/time/{start_time}/{end_time}.json'

# Fitbit allows 150 calls per hour.
SLEEP_MINUTES = math.ceil(150 / 60)

logging.basicConfig(level=logging.INFO)

client = mqtt.Client(client_id=MQTT_CLIENT_ID)
if MQTT_USERNAME and MQTT_PASSWORD:
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
client.will_set(MQTT_TOPIC_PREFIX + '/status', payload='Offline', qos=1, retain=True)


def get_oauth_session():
    """
    Returns an OAuth2Session configured with stored token and automatic refresh.
    """
    token_dict = load_token_from_redis()
    session = OAuth2Session(
        client_id=token_dict.get('client_id', ''),
        token=token_dict,
        auto_refresh_url='https://api.fitbit.com/oauth2/token',
        auto_refresh_kwargs={
            'client_id': token_dict.get('client_id', ''),
        },
        token_updater=save_token_to_redis,
    )
    return session


def fetch_heart_rate_data(oauth_session, start_datetime, end_datetime, detail_level):
    start_date = start_datetime.strftime('%Y-%m-%d')
    end_date = end_datetime.strftime('%Y-%m-%d')
    start_time = start_datetime.strftime('%H:%M')
    end_time = end_datetime.strftime('%H:%M')

    url = HEART_RATE_API_URI.format(
        start_date=start_date,
        end_date=end_date,
        detail_level=detail_level,
        start_time=start_time,
        end_time=end_time,
    )

    response = oauth_session.get(url)

    if response.status_code != 200:
        logging.info(
            f'Failed to fetch heart rate data: {response.status_code}\n{response.headers}\n{response.text}'
        )
        response.raise_for_status()

    return response.json()


def publish(topic: str, msg: str, attributes: dict = None):
    topic_expanded = MQTT_TOPIC_PREFIX + '/' + topic
    retries = 10
    for i in range(retries):
        result = client.publish(topic_expanded, msg)
        if attributes:
            client.publish(topic_expanded + '/attributes', json.dumps(attributes))
        status = result[0]
        if status == 0:
            logging.info(f'Sent {msg} to topic {topic_expanded}')
            return
        else:
            logging.warning(
                f'Failed to send message to topic {topic_expanded}: {result}. '
                f'Retry {i + 1}/{retries}'
            )
            time.sleep(10)
    logging.error(f'Failed to send message to topic {topic_expanded}.')


def do_fetch(oauth_session, detail_level):
    end_datetime = datetime.now()
    start_datetime = end_datetime - timedelta(hours=23)

    try:
        data = fetch_heart_rate_data(oauth_session, start_datetime, end_datetime, detail_level)
    except:
        logging.critical(f'Error fetching heart rate data:\n{traceback.format_exc()}')
        sys.exit(1)

    if data and 'activities-heart-intraday' in data:
        heart_data = data['activities-heart-intraday'].get('dataset', [])
        if heart_data:
            latest = heart_data[-1]
            timestamp = latest.get('time')
            value = latest.get('value')
            if not timestamp or not value:
                logging.critical(f'Data/time is empty: {timestamp}:{value}')
                return None, None
            return timestamp, value
        else:
            logging.info(f'No intraday data found in: {data}')
    return None, None


def main(args):
    client.connect(MQTT_BROKER_HOST, port=MQTT_BROKER_PORT)
    client.loop_start()

    topic_name = 'fitbit-extra-heart-rate'
    if args.person_name:
        topic_name = f'{args.person_name}-{topic_name}'

    # Initialize our OAuth session
    oauth_session = get_oauth_session()

    while True:
        timestamp_str, hr_value = do_fetch(oauth_session, args.detail_level)
        logging.info(f'Latest data: {hr_value} BPM at {timestamp_str}')
        if hr_value is not None:
            publish(topic_name, str(hr_value))
        logging.info(f'Sleeping {SLEEP_MINUTES} minutes...')
        time.sleep(SLEEP_MINUTES * 60)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--person-name', help='Name of this person.')
    parser.add_argument('--detail-level', choices=['1sec', '1min', '5min'], default='5min', help='The detail level.')
    args = parser.parse_args()
    main(args)
