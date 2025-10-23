import json
import logging

import keyring
import keyring.errors

log = logging.getLogger(__name__)

SERVICE_NAME = "pupil_labs.neon_player"
KEYS_LIST_KEY = "_NEON_PLAYER_SECRET_KEYS_"


def get_secret(key_name: str) -> str | None:
    try:
        return keyring.get_password(SERVICE_NAME, key_name)
    except keyring.errors.KeyringError as e:
        log.warning(f"Could not retrieve secret '{key_name}': {e}")
        return None


def set_secret(key_name: str, secret_value: str):
    try:
        keyring.set_password(SERVICE_NAME, key_name, secret_value)
        _add_to_keys_list(key_name)
    except keyring.errors.KeyringError:
        log.exception(f"Could not save secret '{key_name}':")


def delete_secret(key_name: str):
    try:
        keyring.delete_password(SERVICE_NAME, key_name)
        _remove_from_keys_list(key_name)
    except keyring.errors.KeyringError:
        log.exception(f"Could not delete secret '{key_name}':")


def list_secret_keys() -> list[str]:
    try:
        keys_json = keyring.get_password(SERVICE_NAME, KEYS_LIST_KEY)
        if keys_json:
            return json.loads(keys_json)
    except keyring.errors.KeyringError as e:
        log.warning(f"Could not list secret keys: {e}")
    return []


def _add_to_keys_list(key_name: str):
    keys = list_secret_keys()
    if key_name not in keys:
        keys.append(key_name)
        _save_keys_list(keys)


def _remove_from_keys_list(key_name: str):
    keys = list_secret_keys()
    if key_name in keys:
        keys.remove(key_name)
        _save_keys_list(keys)


def _save_keys_list(keys: list[str]):
    try:
        keys_json = json.dumps(keys)
        keyring.set_password(SERVICE_NAME, KEYS_LIST_KEY, keys_json)
    except keyring.errors.KeyringError:
        log.exception("Could not save keys list:")
