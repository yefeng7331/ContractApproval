"""Internal CNY estimate ledger; no provider calls or public mutation API."""

import json
from contextlib import contextmanager

from backend.auth import AuthStore
from backend.errors import ApiError


LIMIT_MICROYUAN = 50_000_000


def _integer(value, maximum=10**12):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("Expected a bounded nonnegative integer")
    return value


def estimate(input_tokens, output_tokens, input_rate, output_rate):
    """Rates: integer microyuan per million tokens; round total upward."""
    values = [input_tokens, output_tokens, input_rate, output_rate]
    for value in values:
        _integer(value)
    return (input_tokens * input_rate + output_tokens * output_rate + 999_999) // 1_000_000


class ModelBudgetStore:
    def __init__(self, auth_store: AuthStore):
        self.auth_store = auth_store

    def initialize(self):
        with self.auth_store.lock, self.auth_store.connection:
            self.auth_store.connection.executescript("""
                CREATE TABLE IF NOT EXISTS model_budget_entries (
                    call_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL,
                    quote_json TEXT NOT NULL,
                    reserved_microyuan INTEGER NOT NULL CHECK(reserved_microyuan > 0),
                    state TEXT NOT NULL CHECK(state IN ('reserved','unknown','settled','rejected')),
                    estimated_microyuan INTEGER,
                    usage_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id,document_version) REFERENCES document_versions(task_id,version)
                );
            """)

    @contextmanager
    def _transaction(self):
        with self.auth_store.lock:
            connection = self.auth_store.connection
            nested = connection.in_transaction
            connection.execute("SAVEPOINT model_budget" if nested else "BEGIN IMMEDIATE")
            try:
                yield connection
                if nested:
                    connection.execute("RELEASE model_budget")
                else:
                    connection.commit()
            except BaseException:
                if nested:
                    connection.execute("ROLLBACK TO model_budget")
                    connection.execute("RELEASE model_budget")
                else:
                    connection.rollback()
                raise

    def summary(self):
        with self.auth_store.lock:
            row = self.auth_store.connection.execute("""
                SELECT COALESCE(SUM(CASE WHEN state='settled' THEN estimated_microyuan ELSE 0 END),0),
                    COALESCE(SUM(CASE WHEN state IN ('reserved','unknown') THEN reserved_microyuan ELSE 0 END),0)
                FROM model_budget_entries
            """).fetchone()
            return {"limit_microyuan": LIMIT_MICROYUAN, "estimated_microyuan": row[0],
                    "held_microyuan": row[1],
                    "available_microyuan": max(0, LIMIT_MICROYUAN - row[0] - row[1])}

    def reserve(self, call_id, task_id, document_version, *, model, price_reference,
                input_tokens, max_output_tokens, input_rate, output_rate,
                reservation_microyuan=None, input_reference=None):
        """Persist a quote before dispatch. created=True identifies a fresh reservation.

        Caller supplies token estimates, frozen rates and optionally a larger
        reservation. This component does not establish prices or call consent.
        """
        for value in (call_id, model, price_reference):
            if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                raise ValueError("Missing or oversized call/price identity")
        _integer(document_version)
        amount = estimate(input_tokens, max_output_tokens, input_rate, output_rate)
        if not 0 < amount <= 10**15:
            raise ValueError("Reservation must be positive and bounded")
        quote_data = dict(model=model, price_reference=price_reference,
            input_tokens=input_tokens, max_output_tokens=max_output_tokens,
            input_rate=input_rate, output_rate=output_rate)
        if reservation_microyuan is not None:
            _integer(reservation_microyuan, 10**15)
            if reservation_microyuan < amount:
                raise ValueError("Reservation cannot be below the token estimate")
            amount = reservation_microyuan
            quote_data['reservation_microyuan'] = amount
        if input_reference is not None:
            if not isinstance(input_reference, str) or not input_reference.strip() or len(input_reference) > 1000:
                raise ValueError("Missing or oversized token estimate reference")
            quote_data['input_reference'] = input_reference
        quote = json.dumps(quote_data, sort_keys=True)
        with self._transaction() as connection:
            old = connection.execute("SELECT * FROM model_budget_entries WHERE call_id=?", (call_id,)).fetchone()
            if old is not None:
                if (old['task_id'], old['document_version'], old['quote_json']) != (task_id, document_version, quote):
                    raise ApiError(409, "BUDGET_CALL_CONFLICT", "调用标识已用于其他请求")
                return {"created": False, **dict(old)}
            task = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None:
                raise ApiError(404, "TASK_NOT_FOUND", "任务不存在")
            if task['current_document_version'] != document_version or task['machine_status'] != 'reviewing':
                raise ApiError(409, "BUDGET_TASK_NOT_READY", "任务版本或状态不允许预留")
            balance = self.summary()
            accepted = balance['estimated_microyuan'] + balance['held_microyuan'] + amount <= LIMIT_MICROYUAN
            state = 'reserved' if accepted else 'rejected'
            now = self.auth_store._clock().isoformat()
            connection.execute("""INSERT INTO model_budget_entries
                (call_id,task_id,document_version,quote_json,reserved_microyuan,state,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)""", (call_id, task_id, document_version, quote, amount, state, now, now))
            if not accepted:
                connection.execute("""UPDATE tasks SET machine_status='blocked', blocked_code='BUDGET_LIMIT',
                    blocked_reason='模型调用预留将超过50元演示预算', recovery_action='budget_decision'
                    WHERE id=?""", (task_id,))
            return {"created": accepted, **dict(connection.execute(
                "SELECT * FROM model_budget_entries WHERE call_id=?", (call_id,)).fetchone())}

    def settle(self, call_id, *, input_tokens=None, output_tokens=None):
        """Unknown usage keeps the reservation; known usage uses the frozen quote.

        No timeout expiry: a crash after dispatch cannot prove the call was free.
        """
        unknown = input_tokens is None and output_tokens is None
        if not unknown:
            _integer(input_tokens)
            _integer(output_tokens)
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM model_budget_entries WHERE call_id=?", (call_id,)).fetchone()
            if row is None:
                raise ApiError(404, "BUDGET_CALL_NOT_FOUND", "调用记录不存在")
            if row['state'] == 'rejected':
                raise ApiError(409, "BUDGET_CALL_REJECTED", "被预算拒绝的调用不能结算")
            usage = None if unknown else json.dumps([input_tokens, output_tokens])
            if row['state'] == 'settled':
                if usage != row['usage_json']:
                    raise ApiError(409, "BUDGET_USAGE_CONFLICT", "已结算用量不能覆盖")
                return dict(row)
            quote = json.loads(row['quote_json'])
            amount = None if unknown else estimate(input_tokens, output_tokens, quote['input_rate'], quote['output_rate'])
            # ponytail: integer microyuan ledger; add provider reconciliation only with verified billing evidence.
            if amount is not None and amount > 10**15:
                raise ValueError("Settlement exceeds supported amount")
            connection.execute("""UPDATE model_budget_entries SET state=?, estimated_microyuan=?, usage_json=?,
                updated_at=? WHERE call_id=?""", ('unknown' if unknown else 'settled', amount, usage,
                self.auth_store._clock().isoformat(), call_id))
            return dict(connection.execute("SELECT * FROM model_budget_entries WHERE call_id=?", (call_id,)).fetchone())
