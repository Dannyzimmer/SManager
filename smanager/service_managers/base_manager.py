"""
Base class for all simple service managers.
Defines the interface and common functionality for managing a single service.
"""

from abc import abstractmethod
from ..datatypes import ServiceStatus
from ..events import ManagerEvent, ManagerEventDispatcher
import subprocess

class BaseManager:
    def __init__(self, config, event_dispatcher: ManagerEventDispatcher | None = None):
        self.config = config
        self.event_dispatcher = event_dispatcher

    def on(self, callback, event_name: str | None = None):
        """Register an event callback for this manager."""
        if self.event_dispatcher is None:
            self.event_dispatcher = ManagerEventDispatcher()
        self.event_dispatcher.on(callback, event_name)

    def off(self, callback, event_name: str | None = None):
        """Unregister an event callback from this manager."""
        if self.event_dispatcher is None:
            return
        self.event_dispatcher.off(callback, event_name)

    def _emit_event(
        self,
        *,
        scope: str,
        action: str,
        phase: str,
        service_id: str | None = None,
        group_name: str | None = None,
        dependency_name: str | None = None,
        message: str | None = None,
        payload: dict | None = None,
        error: BaseException | None = None,
    ) -> None:
        if self.event_dispatcher is None:
            return
        self.event_dispatcher.emit(
            ManagerEvent(
                name=f"{scope}.{action}.{phase}",
                scope=scope,
                action=action,
                phase=phase,
                source=self.__class__.__name__,
                service_id=service_id,
                group_name=group_name,
                dependency_name=dependency_name,
                message=message,
                payload=payload or {},
                error=error,
            )
        )

    def subprocess_run(self, command: list) -> subprocess.CompletedProcess:
        """Helper method to run a subprocess command and handle errors.

        Failures are normalised to RuntimeError so callers (and the CLI) never
        surface a raw traceback from a subprocess.
        """
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            return result
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or e.stdout or "").strip()
            raise RuntimeError(
                f"Command failed ({' '.join(command)}): "
                f"{detail or f'exit code {e.returncode}'}"
            ) from e
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Command not found: {command[0]}"
            ) from e

    @abstractmethod
    def start(self):
        """Start the service."""
        raise NotImplementedError("Start method must be implemented by subclasses.")

    @abstractmethod
    def stop(self):
        """Stop the service."""
        raise NotImplementedError("Stop method must be implemented by subclasses.")

    def restart(self):
        """Restart the service."""
        self._emit_event(
            scope="service",
            action="restart",
            phase="before",
            service_id=self.get_id(),
        )
        try:
            self.stop()
            self.start()
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="restart",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="restart",
            phase="after",
            service_id=self.get_id(),
        )

    def update(self, dry_run: bool = False):
        """Update the service to the latest available version."""
        raise NotImplementedError("Update method must be implemented by subclasses.")

    @abstractmethod
    def status(self)-> ServiceStatus:
        """Check the status of the service."""
        raise NotImplementedError("Status method must be implemented by subclasses.")
    
    @abstractmethod
    def enable(self):
        """Enable the service to be managed (start, stop, restart)."""
        raise NotImplementedError("Enable method must be implemented by subclasses.")
    
    @abstractmethod
    def disable(self):
        """Disable the service from being managed (start, stop, restart)."""
        raise NotImplementedError("Disable method must be implemented by subclasses.")
    
    @abstractmethod
    def get_groups(self):
        """Get the groups associated with this service."""
        raise NotImplementedError("get_groups method must be implemented by subclasses.")
    
    @abstractmethod
    def get_dependencies(self):
        """Get the dependencies of this service."""
        raise NotImplementedError("get_dependencies method must be implemented by subclasses.")
    
    @abstractmethod
    def get_id(self):
        """Get the unique identifier of this service."""
        raise NotImplementedError("get_id method must be implemented by subclasses.")
    
    @abstractmethod
    def is_active(self):
        """Check if the service is active."""
        raise NotImplementedError("is_active method must be implemented by subclasses.")
    