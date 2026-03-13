import logging
from abc import ABC, abstractmethod

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskDispatcher(ABC):
    @abstractmethod
    def dispatch(self, task_name: str, args: list, queue: str, timeout: int = 600) -> object:
        """Send a task and block until it completes. Returns the task result."""


class CeleryTaskDispatcher(TaskDispatcher):
    def __init__(self, celery_app):
        self._app = celery_app

    def dispatch(self, task_name: str, args: list, queue: str, timeout: int = 600) -> object:
        task = self._app.send_task(task_name, args=args, queue=queue)
        logger.info(f"Dispatched {task_name} as {task.id}, waiting up to {timeout}s")
        result = task.get(timeout=timeout)
        logger.info(f"Task {task.id} finished: {result}")
        return result


class FakeTaskDispatcher(TaskDispatcher):
    """
    Drop-in for unit / integration tests.

    Usage:
        dispatcher = FakeTaskDispatcher({
            "screenshot": {"status": "ok", "count": 3},
            "transcribe": {"status": "ok"},
        })
    """

    def __init__(self, results: dict[str, object] | None = None):
        self._results = results or {}
        self.calls: list[dict] = []          # inspect in tests

    def dispatch(self, task_name: str, args: list, queue: str, timeout: int = 600) -> object:
        self.calls.append({"task": task_name, "args": args, "queue": queue})
        if task_name not in self._results:
            raise ValueError(f"FakeTaskDispatcher: no result configured for '{task_name}'")
        return self._results[task_name]

