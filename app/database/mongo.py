from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.config import Settings
from app.models import (
    AdminRole,
    Role,
    Status,
    TaskStatus,
    TransactionType,
    WithdrawalStatus,
)

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MongoStore:
    """MongoDB access layer. Handlers only interact with this class."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: AsyncIOMotorClient | None = None
        self.db: AsyncIOMotorDatabase | None = None
        self._admin_ids: set[int] = set()
        self._owner_ids: set[int] = set(settings.owner_ids)

    async def connect(self) -> None:
        self.client = AsyncIOMotorClient(
            self.settings.mongodb_uri,
            serverSelectionTimeoutMS=10_000,
            connectTimeoutMS=10_000,
            uuidRepresentation="standard",
        )
        await self.client.admin.command("ping")
        self.db = self.client[self.settings.mongodb_db]
        await self._create_indexes()
        await self._sync_configured_owners()
        await self.refresh_admin_cache()
        logger.info("Connected to MongoDB database %s", self.settings.mongodb_db)

    async def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
            self.db = None

    def _collection(self, name: str) -> Any:
        if self.db is None:
            raise RuntimeError("MongoStore is not connected")
        return self.db[name]

    async def _create_indexes(self) -> None:
        users = self._collection("users")
        transactions = self._collection("transactions")
        withdrawals = self._collection("withdrawals")
        team_additions = self._collection("team_additions")
        tasks = self._collection("tasks")
        admins = self._collection("admins")
        admin_notifications = self._collection("admin_notifications")
        broadcasts = self._collection("broadcasts")

        await users.create_index("telegram_id", unique=True, name="uq_users_telegram_id")
        await users.create_index("custom_uid", unique=True, name="uq_users_custom_uid")
        await users.create_index([("status", 1), ("created_at", 1)])
        await users.create_index([("role", 1), ("status", 1)])

        await transactions.create_index(
            "transaction_id", unique=True, name="uq_transactions_id"
        )
        await transactions.create_index([("user_id", 1), ("timestamp", -1)])

        await withdrawals.create_index(
            "withdrawal_id", unique=True, name="uq_withdrawals_id"
        )
        await withdrawals.create_index([("status", 1), ("created_at", 1)])
        await withdrawals.create_index([("user_id", 1), ("created_at", -1)])

        await team_additions.create_index(
            "addition_id", unique=True, name="uq_team_additions_id"
        )
        await team_additions.create_index([("status", 1), ("created_at", 1)])
        await team_additions.create_index([("agent_id", 1), ("created_at", -1)])

        await tasks.create_index("task_id", unique=True, name="uq_tasks_id")
        await tasks.create_index([("status", 1), ("created_at", 1)])
        await tasks.create_index([("user_id", 1), ("created_at", -1)])
        await admins.create_index("telegram_id", unique=True, name="uq_admins_telegram_id")
        await admins.create_index([("role", 1), ("created_at", 1)])
        await admin_notifications.create_index(
            [("request_key", 1), ("status", 1), ("created_at", 1)]
        )
        await admin_notifications.create_index(
            [("chat_id", 1), ("message_id", 1)],
            unique=True,
            name="uq_admin_notification_message",
        )
        await broadcasts.create_index(
            "broadcast_id", unique=True, name="uq_broadcasts_id"
        )
        await broadcasts.create_index([("created_at", -1)])

    async def _sync_configured_owners(self) -> None:
        """Seed configured owners without removing database-managed admins."""
        now = utc_now()
        admins = self._collection("admins")
        for owner_id in self.settings.owner_ids:
            await admins.update_one(
                {"telegram_id": owner_id},
                {
                    "$set": {
                        "role": AdminRole.OWNER,
                        "updated_at": now,
                    },
                    "$setOnInsert": {"created_at": now, "added_by": None},
                },
                upsert=True,
            )

    async def refresh_admin_cache(self) -> None:
        rows = await self._collection("admins").find(
            {}, {"_id": 0, "telegram_id": 1, "role": 1}
        ).to_list(length=None)
        self._admin_ids = {int(row["telegram_id"]) for row in rows}
        self._owner_ids = {
            int(row["telegram_id"])
            for row in rows
            if row.get("role") == AdminRole.OWNER
        }
        # Keep the bot usable during a migration if the admins collection is
        # empty but the process was started with configured owners.
        self._admin_ids.update(self.settings.owner_ids)
        self._owner_ids.update(self.settings.owner_ids)

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self._admin_ids

    def is_owner(self, telegram_id: int) -> bool:
        return telegram_id in self._owner_ids

    async def list_admin_ids(self) -> list[int]:
        await self.refresh_admin_cache()
        return sorted(self._admin_ids)

    async def list_admins(self) -> list[dict[str, Any]]:
        cursor = self._collection("admins").find(
            {}, {"_id": 0}
        ).sort([("role", 1), ("created_at", 1)])
        return await cursor.to_list(length=None)

    async def add_admin(self, telegram_id: int, added_by: int) -> tuple[dict[str, Any] | None, str | None]:
        if telegram_id in self._owner_ids:
            return None, "That user is already an owner."
        now = utc_now()
        result = await self._collection("admins").find_one_and_update(
            {"telegram_id": telegram_id},
            {
                "$set": {"role": AdminRole.ADMIN, "updated_at": now},
                "$setOnInsert": {"created_at": now, "added_by": added_by},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        await self.refresh_admin_cache()
        return result, None

    async def remove_admin(self, telegram_id: int) -> tuple[bool, str | None]:
        if telegram_id in self._owner_ids:
            return False, "Owners cannot be removed from the admin panel."
        result = await self._collection("admins").delete_one(
            {"telegram_id": telegram_id, "role": AdminRole.ADMIN}
        )
        await self.refresh_admin_cache()
        if not result.deleted_count:
            return False, "That admin was not found."
        return True, None

    async def record_admin_notification(
        self,
        request_key: str,
        chat_id: int,
        message_id: int,
        content_type: str,
        content: str,
    ) -> None:
        await self._collection("admin_notifications").update_one(
            {"chat_id": chat_id, "message_id": message_id},
            {
                "$set": {
                    "request_key": request_key,
                    "content_type": content_type,
                    "content": content,
                    "status": "active",
                    "updated_at": utc_now(),
                },
                "$setOnInsert": {"created_at": utc_now()},
            },
            upsert=True,
        )

    async def list_active_admin_notifications(
        self, request_key: str
    ) -> list[dict[str, Any]]:
        cursor = self._collection("admin_notifications").find(
            {"request_key": request_key, "status": "active"},
            {"_id": 0},
        )
        return await cursor.to_list(length=None)

    async def resolve_admin_notification(
        self, chat_id: int, message_id: int, decision: str
    ) -> None:
        await self._collection("admin_notifications").update_one(
            {"chat_id": chat_id, "message_id": message_id},
            {
                "$set": {
                    "status": "resolved",
                    "decision": decision,
                    "resolved_at": utc_now(),
                }
            },
        )

    async def get_user(self, telegram_id: int) -> dict[str, Any] | None:
        return await self._collection("users").find_one({"telegram_id": telegram_id})

    async def find_user(self, query: str) -> dict[str, Any] | None:
        query = query.strip()
        if query.isdigit():
            user = await self._collection("users").find_one({"telegram_id": int(query)})
            if user:
                return user
        return await self._collection("users").find_one({"custom_uid": query})

    async def register_user(self, telegram_id: int, custom_uid: str) -> dict[str, Any]:
        """Create a pending user or restart a previously rejected registration."""
        now = utc_now()
        users = self._collection("users")
        existing_uid = await users.find_one(
            {"custom_uid": custom_uid, "telegram_id": {"$ne": telegram_id}}
        )
        if existing_uid:
            raise ValueError("That custom UID is already registered.")

        existing_user = await users.find_one({"telegram_id": telegram_id})
        if existing_user:
            if existing_user["status"] == Status.PENDING:
                raise ValueError("Your registration is already awaiting approval.")
            if existing_user["status"] == Status.APPROVED:
                return existing_user
            await users.update_one(
                {"telegram_id": telegram_id},
                {
                    "$set": {
                        "custom_uid": custom_uid,
                        "status": Status.PENDING,
                        "updated_at": now,
                    }
                },
            )
            return await self.get_user(telegram_id)  # type: ignore[return-value]

        document = {
            "telegram_id": telegram_id,
            "custom_uid": custom_uid,
            "role": Role.USER,
            "status": Status.PENDING,
            "balance": 0.0,
            "upline_agent": None,
            "created_at": now,
            "updated_at": now,
        }
        await users.insert_one(document)
        return document

    async def list_pending_users(self, skip: int, limit: int) -> list[dict[str, Any]]:
        cursor = (
            self._collection("users")
            .find({"status": Status.PENDING})
            .sort("created_at", 1)
            .skip(skip)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def count_pending_users(self) -> int:
        return await self._collection("users").count_documents({"status": Status.PENDING})

    async def list_users(self, skip: int, limit: int) -> list[dict[str, Any]]:
        # Rejected accounts are hidden from the All Users list (search still finds them).
        cursor = (
            self._collection("users")
            .find({"status": {"$ne": Status.REJECTED}}, {"_id": 0})
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def count_users(self) -> int:
        return await self._collection("users").count_documents(
            {"status": {"$ne": Status.REJECTED}}
        )

    async def list_agent_members(
        self, agent_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        cursor = (
            self._collection("users")
            .find({"upline_agent": agent_id}, {"_id": 0})
            .sort("created_at", -1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def set_user_status(
        self, telegram_id: int, status: Status
    ) -> dict[str, Any] | None:
        result = await self._collection("users").find_one_and_update(
            {"telegram_id": telegram_id, "status": Status.PENDING},
            {"$set": {"status": status, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return result

    async def list_transactions(self, telegram_id: int, limit: int = 10) -> list[dict[str, Any]]:
        cursor = (
            self._collection("transactions")
            .find({"user_id": telegram_id}, {"_id": 0})
            .sort("timestamp", -1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def create_transaction(
        self,
        user_id: int,
        amount: float,
        transaction_type: TransactionType,
        reason: str,
        balance_after: float | None = None,
    ) -> dict[str, Any]:
        transaction = {
            "transaction_id": uuid4().hex,
            "user_id": user_id,
            "amount": round(amount, 2),
            "type": transaction_type,
            "reason": reason,
            "timestamp": utc_now(),
        }
        if balance_after is not None:
            transaction["balance_after"] = round(balance_after, 2)
        await self._collection("transactions").insert_one(transaction)
        return transaction

    async def adjust_balance(
        self,
        telegram_id: int,
        amount: float,
        transaction_type: TransactionType,
        reason: str,
    ) -> dict[str, Any] | None:
        """Atomically update a wallet and write its transaction record."""
        delta = amount if transaction_type == TransactionType.CREDIT else -amount
        filter_query: dict[str, Any] = {"telegram_id": telegram_id}
        if delta < 0:
            filter_query["balance"] = {"$gte": abs(delta)}
        user = await self._collection("users").find_one_and_update(
            filter_query,
            {"$inc": {"balance": round(delta, 2)}, "$set": {"updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        if user is None:
            return None
        await self.create_transaction(
            telegram_id,
            amount,
            transaction_type,
            reason,
            balance_after=float(user["balance"]),
        )
        return await self.get_user(telegram_id)

    async def create_withdrawal(
        self,
        user_id: int,
        amount: float,
        payment_method: str,
        payment_photo_file_id: str | None = None,
    ) -> dict[str, Any]:
        withdrawal = {
            "withdrawal_id": uuid4().hex,
            "user_id": user_id,
            "amount": round(amount, 2),
            "payment_method": payment_method,
            "payment_photo_file_id": payment_photo_file_id,
            "status": WithdrawalStatus.PENDING,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        await self._collection("withdrawals").insert_one(withdrawal)
        return withdrawal

    async def get_withdrawal(self, withdrawal_id: str) -> dict[str, Any] | None:
        return await self._collection("withdrawals").find_one(
            {"withdrawal_id": withdrawal_id}
        )

    async def list_pending_withdrawals(
        self, skip: int, limit: int
    ) -> list[dict[str, Any]]:
        cursor = (
            self._collection("withdrawals")
            .find({"status": WithdrawalStatus.PENDING})
            .sort("created_at", 1)
            .skip(skip)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def count_pending_withdrawals(self) -> int:
        return await self._collection("withdrawals").count_documents(
            {"status": WithdrawalStatus.PENDING}
        )

    async def create_task_submission(
        self, user_id: int, description: str, proof_file_ids: list[str]
    ) -> dict[str, Any]:
        task = {
            "task_id": uuid4().hex,
            "user_id": user_id,
            "description": description,
            "proof_file_ids": proof_file_ids,
            "status": TaskStatus.PENDING,
            "reward_amount": 0.0,
            "reviewed_by": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        await self._collection("tasks").insert_one(task)
        return task

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        return await self._collection("tasks").find_one({"task_id": task_id})

    async def list_pending_tasks(self, skip: int, limit: int) -> list[dict[str, Any]]:
        cursor = (
            self._collection("tasks")
            .find({"status": TaskStatus.PENDING})
            .sort("created_at", 1)
            .skip(skip)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def count_pending_tasks(self) -> int:
        return await self._collection("tasks").count_documents(
            {"status": TaskStatus.PENDING}
        )

    async def list_user_tasks(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        cursor = (
            self._collection("tasks")
            .find({"user_id": user_id}, {"_id": 0})
            .sort("created_at", -1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def approve_task_with_reward(
        self, task_id: str, admin_id: int, amount: float
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Claim a pending task, credit its reward, and finalize approval."""
        task = await self._collection("tasks").find_one_and_update(
            {"task_id": task_id, "status": TaskStatus.PENDING},
            {
                "$set": {
                    "status": TaskStatus.PROCESSING,
                    "updated_at": utc_now(),
                    "reviewed_by": admin_id,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not task:
            return None, "This task is no longer pending."

        user = await self.adjust_balance(
            task["user_id"],
            amount,
            TransactionType.CREDIT,
            f"Task reward ({task_id[:8]})",
        )
        if not user:
            await self._collection("tasks").update_one(
                {"task_id": task_id, "status": TaskStatus.PROCESSING},
                {
                    "$set": {
                        "status": TaskStatus.PENDING,
                        "reviewed_by": None,
                        "updated_at": utc_now(),
                    }
                },
            )
            return None, "The submitting user no longer exists."

        updated = await self._collection("tasks").find_one_and_update(
            {"task_id": task_id, "status": TaskStatus.PROCESSING},
            {
                "$set": {
                    "status": TaskStatus.APPROVED,
                    "reward_amount": round(amount, 2),
                    "updated_at": utc_now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return updated, None

    async def reject_task(
        self, task_id: str, admin_id: int, reason: str = ""
    ) -> dict[str, Any] | None:
        return await self._collection("tasks").find_one_and_update(
            {"task_id": task_id, "status": TaskStatus.PENDING},
            {
                "$set": {
                    "status": TaskStatus.REJECTED,
                    "reviewed_by": admin_id,
                    "rejection_reason": reason[:500],
                    "updated_at": utc_now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )

    async def set_withdrawal_status(
        self, withdrawal_id: str, status: WithdrawalStatus
    ) -> dict[str, Any] | None:
        result = await self._collection("withdrawals").find_one_and_update(
            {"withdrawal_id": withdrawal_id, "status": WithdrawalStatus.PENDING},
            {"$set": {"status": status, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return result

    async def create_team_addition(
        self, agent_id: int, custom_uid: str, member_telegram_id: int
    ) -> dict[str, Any]:
        addition = {
            "addition_id": uuid4().hex,
            "agent_id": agent_id,
            "custom_uid": custom_uid,
            "member_telegram_id": member_telegram_id,
            "status": Status.PENDING,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        await self._collection("team_additions").insert_one(addition)
        return addition

    async def get_team_addition(self, addition_id: str) -> dict[str, Any] | None:
        return await self._collection("team_additions").find_one(
            {"addition_id": addition_id}
        )

    async def list_pending_team_additions(
        self, skip: int, limit: int
    ) -> list[dict[str, Any]]:
        cursor = (
            self._collection("team_additions")
            .find({"status": Status.PENDING})
            .sort("created_at", 1)
            .skip(skip)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def count_pending_team_additions(self) -> int:
        return await self._collection("team_additions").count_documents(
            {"status": Status.PENDING}
        )

    async def set_team_addition_status(
        self, addition_id: str, status: Status
    ) -> dict[str, Any] | None:
        return await self._collection("team_additions").find_one_and_update(
            {"addition_id": addition_id, "status": Status.PENDING},
            {"$set": {"status": status, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )

    async def approve_team_addition(
        self, addition_id: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Approve an addition and create its pending user atomically at app level."""
        addition = await self.get_team_addition(addition_id)
        if not addition or addition["status"] != Status.PENDING:
            return None, "This team request is no longer pending."
        if await self.get_user(addition["member_telegram_id"]):
            return None, "That Telegram user is already registered."
        if await self._collection("users").find_one({"custom_uid": addition["custom_uid"]}):
            return None, "That custom UID is already registered."

        now = utc_now()
        user = {
            "telegram_id": addition["member_telegram_id"],
            "custom_uid": addition["custom_uid"],
            "role": Role.USER,
            "status": Status.APPROVED,
            "balance": 0.0,
            "upline_agent": addition["agent_id"],
            "created_at": now,
            "updated_at": now,
        }
        await self._collection("users").insert_one(user)
        updated = await self.set_team_addition_status(addition_id, Status.APPROVED)
        if updated is None:
            return None, "The team request changed while it was being processed."
        return updated, None

    async def search_users(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        query = query.strip()
        if query.isdigit():
            cursor = self._collection("users").find({"telegram_id": int(query)}).limit(limit)
        else:
            cursor = self._collection("users").find(
                {"custom_uid": {"$regex": re.escape(query), "$options": "i"}}
            ).limit(limit)
        return await cursor.to_list(length=limit)

    async def set_role(self, telegram_id: int, role: Role) -> dict[str, Any] | None:
        return await self._collection("users").find_one_and_update(
            {"telegram_id": telegram_id},
            {"$set": {"role": role, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )

    # ------------------------------------------------------------------
    # Broadcasts
    # ------------------------------------------------------------------
    @staticmethod
    def _broadcast_filter(audience: str) -> dict[str, Any]:
        if audience == "approved":
            return {"status": Status.APPROVED}
        if audience == "agents":
            return {"status": Status.APPROVED, "role": Role.AGENT}
        if audience == "users":
            return {"status": Status.APPROVED, "role": Role.USER}
        if audience == "all":
            return {}
        raise ValueError(f"Unknown broadcast audience: {audience}")

    async def count_broadcast_recipients(self, audience: str) -> int:
        return await self._collection("users").count_documents(
            self._broadcast_filter(audience)
        )

    async def list_broadcast_recipient_ids(self, audience: str) -> list[int]:
        cursor = self._collection("users").find(
            self._broadcast_filter(audience), {"_id": 0, "telegram_id": 1}
        )
        rows = await cursor.to_list(length=None)
        return [int(row["telegram_id"]) for row in rows]

    async def create_broadcast(
        self,
        broadcast_id: str,
        created_by: int,
        audience: str,
        content_type: str,
        total: int,
    ) -> dict[str, Any]:
        document = {
            "broadcast_id": broadcast_id,
            "created_by": created_by,
            "audience": audience,
            "content_type": content_type,
            "total": total,
            "sent": 0,
            "blocked": 0,
            "failed": 0,
            "status": "Running",
            "created_at": utc_now(),
            "finished_at": None,
        }
        await self._collection("broadcasts").insert_one(document)
        return document

    async def finish_broadcast(
        self,
        broadcast_id: str,
        status: str,
        sent: int,
        blocked: int,
        failed: int,
    ) -> None:
        await self._collection("broadcasts").update_one(
            {"broadcast_id": broadcast_id},
            {
                "$set": {
                    "status": status,
                    "sent": sent,
                    "blocked": blocked,
                    "failed": failed,
                    "finished_at": utc_now(),
                }
            },
        )
