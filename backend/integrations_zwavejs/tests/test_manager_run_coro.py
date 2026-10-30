"""Issue #124: ``_run_coro`` cancels a command that runs past its timeout and says so."""

from __future__ import annotations

import asyncio
import threading

from django.test import SimpleTestCase

from integrations_zwavejs.manager import ZwavejsCommandError, ZwavejsConnectionManager


class RunCoroTimeoutTests(SimpleTestCase):
    def setUp(self):
        self.manager = ZwavejsConnectionManager()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="test-zwavejs-loop", daemon=True)
        self.thread.start()
        self.manager._loop = self.loop
        self.addCleanup(self._stop_loop)

    def _stop_loop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)
        self.loop.close()

    def test_a_timeout_cancels_the_command_and_names_the_timeout(self):
        cancelled = threading.Event()

        async def slow_command():
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with self.assertRaises(ZwavejsCommandError) as ctx:
            self.manager._run_coro(slow_command(), timeout_seconds=0.05)

        self.assertEqual(str(ctx.exception), "Z-Wave JS command timed out after 0.05s")
        self.assertTrue(cancelled.wait(timeout=2), "the command never saw CancelledError")

    def test_a_timeout_error_from_the_command_itself_keeps_its_message(self):
        async def failing_command():
            raise TimeoutError("driver gave up")

        with self.assertRaises(ZwavejsCommandError) as ctx:
            self.manager._run_coro(failing_command(), timeout_seconds=2)

        self.assertEqual(str(ctx.exception), "driver gave up")

    def test_an_empty_timeout_error_from_the_command_still_says_it_timed_out(self):
        async def failing_command():
            raise TimeoutError()

        with self.assertRaises(ZwavejsCommandError) as ctx:
            self.manager._run_coro(failing_command(), timeout_seconds=2)

        self.assertEqual(str(ctx.exception), "Z-Wave JS command timed out")

    def test_a_command_that_finishes_in_time_returns_its_result(self):
        async def quick_command():
            return {"status": 255}

        self.assertEqual(self.manager._run_coro(quick_command(), timeout_seconds=2), {"status": 255})
