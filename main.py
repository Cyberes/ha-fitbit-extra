import argparse
import json
import logging
import math
import os
import pickle
import sys
import time
import traceback
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt
import requests
from dateparser import parse
from redis import Redis

from lib.consts import REDIS_DB, REDIS_TOKEN_KEY

TOKEN_URL = "https://api.fitbit.com/oauth2/token"
HEART_RATE_API_URL = "https://api.fitbit.com/1/user/-/activities/heart/date/{start_date}/{end_date}/1min/time/{start_time}/{end_time}.json"
SLEEP_MINUTES = math.floor(150 / 60)

redis = Redis(db=REDIS_DB)
logging.basicConfig(level=logging.INFO)

MQTT_BROKER_HOST = os.getenv('MQTT_BROKER_HOST')
MQTT_BROKER_PORT = int(os.getenv('MQTT_BROKER_PORT', 1883))
MQTT_CLIENT_ID = os.getenv('MQTT_CLIENT_ID', 'fitbit-extra')
MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', '')
MQTT_TOPIC_PREFIX = os.getenv('MQTT_TOPIC_PREFIX', 'fitbit-extra')

client = mqtt.Client(client_id=MQTT_CLIENT_ID)
if MQTT_USERNAME and MQTT_PASSWORD:
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
client.will_set(MQTT_TOPIC_PREFIX + '/status', payload='Offline', qos=1, retain=True)
client.connect(MQTT_BROKER_HOST, port=MQTT_BROKER_PORT)
client.loop_start()


def get_tokens():
    token_data = redis.hgetall(REDIS_TOKEN_KEY)
    if not token_data:
        logging.critical("No tokens found. Please run 'authorize.py' first.")
        exit(1)
    tokens = {k.decode('utf-8'): v.decode('utf-8') for k, v in token_data.items()}
    return tokens


def refresh_access_token(refresh_token):
    tokens = get_tokens()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": tokens.get('client_id'),
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    response = requests.post(TOKEN_URL, data=data, headers=headers)
    if response.status_code != 200:
        print(f"Failed to refresh access token: {response.status_code} {response.text}")
        exit(1)

    token_data = response.json()
    print("Access token refreshed successfully.")

    # Calculate new expiry time
    expires_in = token_data.get("expires_in")  # in seconds
    expires_at = int(datetime.now().timestamp()) + expires_in

    # Update tokens in Redis
    updated_tokens = {
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token", refresh_token),
        "expires_at": expires_at,
        "scope": token_data.get("scope"),
        "token_type": token_data.get("token_type"),
        "user_id": token_data.get("user_id"),
    }

    redis.hset(REDIS_TOKEN_KEY, mapping=updated_tokens)
    return updated_tokens


def get_valid_access_token():
    tokens = get_tokens()
    current_time = int(datetime.now().timestamp())
    if int(tokens["expires_at"]) <= current_time:
        print("Access token expired. Refreshing...")
        tokens = refresh_access_token(tokens["refresh_token"])
    return tokens["access_token"]


def fetch_heart_rate_data(access_token, start_datetime, end_datetime):
    start_date = start_datetime.strftime("%Y-%m-%d")
    end_date = end_datetime.strftime("%Y-%m-%d")
    start_time = start_datetime.strftime("%H:%M")
    end_time = end_datetime.strftime("%H:%M")

    url = HEART_RATE_API_URL.format(start_date=start_date, end_date=end_date, start_time=start_time, end_time=end_time)
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        logging.info(f'Failed to fetch heart rate data: {response.status_code}\n{response.headers}\n{response.text}')
        response.raise_for_status()
    else:
        return response.json()


def publish(topic: str, msg: str, attributes: dict = None):
    topic_expanded = MQTT_TOPIC_PREFIX + '/' + topic
    retries = 10
    for i in range(retries):  # retry
        result = client.publish(topic_expanded, msg)
        if attributes:
            client.publish(topic_expanded + '/attributes', json.dumps(attributes))
        status = result[0]
        if status == 0:
            logging.info(f'Sent {msg} to topic {topic_expanded}')
            return
        else:
            logging.warning(f'Failed to send message to topic {topic_expanded}: {result}. Retry {i + 1}/{retries}')
            time.sleep(10)
    logging.error(f'Failed to send message to topic {topic_expanded}.')


def do_fetch():
    access_token = get_valid_access_token()

    end_datetime_redis: bytes = redis.get('fitbit_end_datetime')
    now = datetime.now()
    if not end_datetime_redis:
        end_datetime = now
    else:
        end_datetime = pickle.loads(end_datetime_redis)
    redis.set('fitbit_end_datetime', pickle.dumps(now))

    start_datetime = end_datetime - timedelta(hours=23)

    logging.info(f"Fetching heart rate data from {start_datetime} to {end_datetime}...")

    try:
        data = fetch_heart_rate_data(access_token, start_datetime, end_datetime)
    except:
        logging.critical(f"Error fetching heart rate data: {traceback.format_exc()}")
        sys.exit(1)

    if data and "activities-heart-intraday" in data:
        heart_data = data["activities-heart-intraday"].get("dataset", [])
        if heart_data:
            latest = heart_data[-1]
            timestamp = latest.get('time')
            value = latest.get('value')
            if not timestamp or not value:
                logging.critical(f"Data and/or time is empty: {timestamp}:{value}")
                return None, None
            return parse(timestamp), value
        else:
            logging.info(f'Failed to retrieve heart rate data or no data available:\n{data}')
    return None, None


def main(args):
    topic_name = 'fitbit-extra-heart-rate'
    if args.person_name:
        topic_name = f'{args.person_name}-{topic_name}'

    while True:
        latest_timestamp_redis: bytes = redis.get('fitbit_latest_timestamp')
        latest_timestamp = None
        if latest_timestamp_redis:
            latest_timestamp = pickle.loads(latest_timestamp_redis)

        timestamp, hr_value = do_fetch()
        redis.set('fitbit_latest_timestamp', pickle.dumps(timestamp))

        if latest_timestamp is None or latest_timestamp < timestamp:
            publish(topic_name, hr_value)

        time.sleep(SLEEP_MINUTES * 1000)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--person-name', help='Name of this person.')
    args = parser.parse_args()
    main(args)
