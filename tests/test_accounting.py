"""Regression tests exercise the patched upstream functions in the runtime image."""

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from litellm.proxy.db.db_spend_update_writer import DBSpendUpdateWriter
from litellm.proxy.utils import ProxyUpdateSpend

ENTITIES = ("user", "end_user", "key", "team", "team_member", "org", "tag", "agent")


def spend_batch():
    return {f"{name}_list_transactions": {} for name in ENTITIES}


class RecordingDB:
    def __init__(self):
        self.commits = []
        self.failures = []
        self.attempts = 0

    @asynccontextmanager
    async def tx(self, **kwargs):
        self.attempts += 1
        pending = []
        db = self

        class Transaction:
            @asynccontextmanager
            async def batch_(self):
                yield self

            def __getattr__(self, table):
                def write(**kwargs):
                    pending.append((table, kwargs))

                return SimpleNamespace(upsert=write, update_many=write)

        yield Transaction()
        if db.failures:
            raise db.failures.pop(0)
        self.commits.append(pending)


class AccountingOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_opposing_arrival_orders_take_end_user_locks_in_same_order(self):
        orders = []
        for entries in ({"b": 2, "a": 1}, {"a": 1, "b": 2}):
            db = RecordingDB()
            await ProxyUpdateSpend.update_end_user_spend(
                n_retry_times=0,
                prisma_client=SimpleNamespace(db=db),
                proxy_logging_obj=AsyncMock(),
                end_user_list_transactions=entries,
            )
            orders.append([data["where"]["user_id"] for _, data in db.commits[0]])
        self.assertEqual(orders, [["a", "b"], ["a", "b"]])

    async def test_each_aggregate_table_has_consistent_lock_order(self):
        db = RecordingDB()
        batch = spend_batch()
        for entity in ENTITIES:
            batch[f"{entity}_list_transactions"] = {"b": 2, "a": 1}
        batch["team_member_list_transactions"] = {
            "team_id::b::user_id::b": 2,
            "team_id::a::user_id::a": 1,
        }
        writer = DBSpendUpdateWriter.__new__(DBSpendUpdateWriter)
        await writer._commit_spend_updates_to_db(
            prisma_client=SimpleNamespace(db=db),
            n_retry_times=0,
            proxy_logging_obj=None,
            db_spend_update_transactions=batch,
        )
        self.assertEqual(len(db.commits), 8)
        for transaction in db.commits:
            self.assertEqual(
                [next(iter(data["where"].values())) for _, data in transaction],
                ["a", "b"],
            )
