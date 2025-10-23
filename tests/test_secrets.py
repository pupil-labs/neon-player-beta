import json
import unittest

import keyring
from keyring.backends.memory import Keyring

from pupil_labs.neon_player import secrets


class TestSecrets(unittest.TestCase):
    def setUp(self):
        # Use an in-memory keyring for testing
        self.keyring = Keyring()
        keyring.set_keyring(self.keyring)
        secrets.SERVICE_NAME = "pupil_labs.neon_player.testing"

    def tearDown(self):
        # Clean up the test keyring
        try:
            keys = json.loads(
                self.keyring.get_password(secrets.SERVICE_NAME, secrets.KEYS_LIST_KEY)
            )
            for key in keys:
                self.keyring.delete_password(secrets.SERVICE_NAME, key)
            self.keyring.delete_password(secrets.SERVICE_NAME, secrets.KEYS_LIST_KEY)
        except (TypeError, keyring.errors.PasswordDeleteError):
            pass

    def test_set_and_get_secret(self):
        secrets.set_secret("my_secret", "my_value")
        self.assertEqual(secrets.get_secret("my_secret"), "my_value")

    def test_get_nonexistent_secret(self):
        self.assertIsNone(secrets.get_secret("nonexistent_secret"))

    def test_delete_secret(self):
        secrets.set_secret("to_be_deleted", "some_value")
        self.assertIsNotNone(secrets.get_secret("to_be_deleted"))
        secrets.delete_secret("to_be_deleted")
        self.assertIsNone(secrets.get_secret("to_be_deleted"))

    def test_list_secret_keys(self):
        self.assertEqual(secrets.list_secret_keys(), [])
        secrets.set_secret("key1", "value1")
        secrets.set_secret("key2", "value2")
        self.assertCountEqual(secrets.list_secret_keys(), ["key1", "key2"])
        secrets.delete_secret("key1")
        self.assertCountEqual(secrets.list_secret_keys(), ["key2"])


if __name__ == "__main__":
    unittest.main()
