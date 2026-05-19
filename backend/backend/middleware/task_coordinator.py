"""
Worker-safe background task coordinator.
Usa MongoDB come lock distribuito per garantire che solo 1 worker
esegua i task periodici (WAN probe, cleanup, ecc.).
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger("task_coordinator")

WORKER_ID = f"{os.getpid()}"
LOCK_TTL_SECONDS = 120  # Lock scade dopo 2 minuti (failsafe)


class TaskCoordinator:
    """Coordina background tasks tra multi-worker usando MongoDB locks."""

    def __init__(self):
        self._db = None
        self._tasks = {}

    def _get_db(self):
        if self._db is None:
            try:
                from database import db
                self._db = db
            except Exception:
                pass
        return self._db

    async def acquire_lock(self, task_name: str) -> bool:
        """Prova ad acquisire il lock per un task. True se acquisito."""
        db = self._get_db()
        if db is None:
            return True  # Single-worker fallback

        now = time.time()
        try:
            result = await db.task_locks.find_one_and_update(
                {
                    "task": task_name,
                    "$or": [
                        {"locked_until": {"$lt": now}},  # Lock scaduto
                        {"locked_until": {"$exists": False}},
                    ]
                },
                {
                    "$set": {
                        "task": task_name,
                        "worker_id": WORKER_ID,
                        "locked_at": now,
                        "locked_until": now + LOCK_TTL_SECONDS,
                    }
                },
                upsert=True,
                return_document=True,
            )
            return result and result.get("worker_id") == WORKER_ID
        except Exception as e:
            logger.debug(f"Lock acquire fallback: {e}")
            return True  # Fallback: permetti l'esecuzione

    async def release_lock(self, task_name: str):
        """Rilascia il lock di un task."""
        db = self._get_db()
        if db is None:
            return
        try:
            await db.task_locks.update_one(
                {"task": task_name, "worker_id": WORKER_ID},
                {"$set": {"locked_until": 0}}
            )
        except Exception:
            pass

    async def run_periodic(self, task_name: str, func, interval_seconds: int):
        """Esegue un task periodico con lock distribuito."""
        while True:
            try:
                if await self.acquire_lock(task_name):
                    try:
                        await func()
                    finally:
                        await self.release_lock(task_name)
                else:
                    logger.debug(f"Task {task_name} in esecuzione su altro worker, skip")
            except Exception as e:
                logger.error(f"Task {task_name} error: {e}")
            await asyncio.sleep(interval_seconds)

    def schedule(self, task_name: str, func, interval_seconds: int):
        """Registra un task periodico. Va chiamato nello startup."""
        if task_name not in self._tasks:
            task = asyncio.create_task(self.run_periodic(task_name, func, interval_seconds))
            self._tasks[task_name] = task
            logger.info(f"Scheduled task '{task_name}' every {interval_seconds}s (worker {WORKER_ID})")


# Singleton
coordinator = TaskCoordinator()
