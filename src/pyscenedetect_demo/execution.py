"""Application-owned background work and independent progress subscribers."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class BackgroundExecutor:
    def __init__(self, concurrency=1):
        self._slots = asyncio.Semaphore(concurrency)
        self._tasks = {}
        self._closing = False

    def contains(self, key):
        return key in self._tasks

    def submit(self, key, operation):
        """Claim a key before yielding, preventing duplicate starts while queued."""
        if self._closing:
            raise RuntimeError("Application is shutting down")
        if key in self._tasks:
            return False

        async def run():
            try:
                async with self._slots:
                    await operation()
            except Exception:
                logger.exception("Background operation %s failed", key)
            finally:
                self._tasks.pop(key, None)

        self._tasks[key] = asyncio.create_task(run(), name=key)
        return True

    async def call(self, key, operation):
        """Await tracked work without letting a disconnected caller cancel it."""
        outcome = asyncio.get_running_loop().create_future()
        # Observe failures even if the HTTP caller has already disconnected.
        outcome.add_done_callback(lambda future: None if future.cancelled() else future.exception())

        async def work():
            try:
                result = await operation()
            except Exception as exc:
                outcome.set_exception(exc)
            else:
                outcome.set_result(result)

        if not self.submit(key, work):
            raise ValueError("Wait for the current operation to finish")
        return await asyncio.shield(outcome)

    async def close(self):
        # Do not cancel a coroutine while its media-processing thread still writes.
        # Drain tracked work before repositories are saved or the loop is closed.
        self._closing = True
        if self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)


class EventHub:
    def __init__(self):
        self._subscribers = defaultdict(set)

    def subscribe(self, key):
        queue = asyncio.Queue(maxsize=128)
        self._subscribers[key].add(queue)
        return queue

    def unsubscribe(self, key, queue):
        subscribers = self._subscribers.get(key)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(key, None)

    def publish(self, key, event):
        for queue in tuple(self._subscribers.get(key, ())):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def remove(self, key):
        self.publish(key, None)
        self._subscribers.pop(key, None)
