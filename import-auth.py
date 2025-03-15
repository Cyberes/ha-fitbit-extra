#!/usr/bin/env python3

import json
import sys

import redis

from lib.consts import REDIS_DB, REDIS_TOKEN_KEY


def import_token_info():
    print("Please paste the token_info JSON:")
    token_info_json = input()

    try:
        token_info = json.loads(token_info_json)
    except json.JSONDecodeError:
        print("Invalid JSON format. Please try again.")
        sys.exit(1)

    # Store tokens in Redis
    r = redis.Redis(db=REDIS_DB)
    r.hset(REDIS_TOKEN_KEY, mapping=token_info)
    print(f"Token info imported and stored in Redis under key '{REDIS_TOKEN_KEY}'")


if __name__ == "__main__":
    import_token_info()
