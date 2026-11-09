"""The schema check passes only once every shipped migration is applied."""

import unittest
from contextlib import redirect_stdout
from io import StringIO

from litellm_gateway.schema_check import shipped_migrations, wait_for_schema

SHIPPED = {"001_init", "002_add_column"}


def check(*results, timeout_s=1):
    reads = iter(results)

    def read_applied():
        result = next(reads)
        if isinstance(result, Exception):
            raise result
        return result

    with redirect_stdout(StringIO()):
        return wait_for_schema(read_applied, SHIPPED, timeout_s, interval_s=0)


class SchemaCheckTests(unittest.TestCase):
    def test_ready_when_every_shipped_migration_is_applied(self):
        self.assertTrue(check(SHIPPED))

    def test_newer_database_is_ready(self):
        self.assertTrue(check(SHIPPED | {"003_from_newer_release"}))

    def test_waits_through_pending_migrations_and_outages(self):
        self.assertTrue(check({"001_init"}, ConnectionError("down"), SHIPPED))

    def test_gives_up_when_still_behind(self):
        self.assertFalse(check({"001_init"}, timeout_s=0))

    def test_image_ships_migrations(self):
        self.assertTrue(shipped_migrations())


if __name__ == "__main__":
    unittest.main()
