import logging
import pickle
import sys

from redis import Redis

from lib.consts import REDIS_DB, REDIS_TOKEN_KEY

_logger = logging.getLogger('REDIS')

redis_client = Redis(db=REDIS_DB)


def load_token_from_redis():
    """Load token info from Redis (pickled)."""
    token_bytes: bytes = redis_client.get(REDIS_TOKEN_KEY)
    if not token_bytes:
        logging.critical("No token found in Redis. Please run 'authorize.py' first.")
        sys.exit(1)
    try:
        return pickle.loads(token_bytes)
    except Exception as ex:
        logging.critical(f"Failed to load token from Redis: {ex}")
        sys.exit(1)


def save_token_to_redis(token_dict):
    """Save updated token info to Redis."""
    redis_client.set(REDIS_TOKEN_KEY, pickle.dumps(token_dict))
