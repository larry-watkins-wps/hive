"""glia/launcher.py — Region container launcher (spec §E.2, §G.7).

Starts and stops region containers via the synchronous ``docker`` Python SDK.
The async glia supervisor wraps these calls in :func:`asyncio.to_thread`.

The launcher augments :meth:`RegionRegistry.docker_spec` with:

* environment variables for MQTT broker host, per-region MQTT password
  (``MQTT_PASSWORD_<UPPER_NAME>``), and ``ANTHROPIC_API_KEY`` — all pulled
  from ``os.environ`` by default (spec §F.4);
* resource caps per spec §G.7 — 1 CPU, 2 GiB memory, read-only root FS
  plus a tmpfs at ``/tmp``;
* a ``unless-stopped`` restart policy so Docker itself handles crash-loops.

Container names follow the plan convention ``hive-<name>`` (e.g.
``hive-amygdala``).  Note: spec §G.7 shows ``hive-region-<name>``; the plan
wins on naming since it appears in the Task 5.3 failing-test description.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import docker  # type: ignore[import-untyped]
from docker.errors import (  # type: ignore[import-untyped]
    APIError,
    ImageNotFound,
    NotFound,
)

from glia.registry import RegionRegistry

if TYPE_CHECKING:  # pragma: no cover
    from docker.models.containers import Container  # type: ignore[import-untyped]


class GliaError(Exception):
    """Glia-layer infrastructure failure (launch, stop, restart, query)."""


# Resource limits per spec §G.7:
#   --cpus 1.0            -> cpu_quota=100_000 at default cpu_period=100_000
#   --memory 2g           -> mem_limit="2g"
#   --memory-swap 2g      -> memswap_limit="2g"  (equal to mem_limit => no swap)
#   --read-only           -> read_only=True
#   --tmpfs /tmp          -> tmpfs={"/tmp": ""}
DEFAULT_RESOURCE_LIMITS: dict[str, Any] = {
    "cpu_quota": 100_000,
    "mem_limit": "2g",
    "memswap_limit": "2g",
    "read_only": True,
    "tmpfs": {"/tmp": ""},
}


class Launcher:
    """Starts and stops region containers via the docker SDK.

    All docker SDK calls are synchronous.  Async callers should wrap these
    via :func:`asyncio.to_thread`.
    """

    def __init__(
        self,
        registry: RegionRegistry,
        client: docker.DockerClient | None = None,
        *,
        broker_host: str = "broker",
        env_loader: Callable[[str], dict[str, str]] | None = None,
    ) -> None:
        self._registry = registry
        self._client = client if client is not None else docker.from_env()
        self._broker_host = broker_host
        self._env_loader = env_loader or self._default_env_loader

    # ------------------------------------------------------------------
    # Env helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_env_loader(region: str) -> dict[str, str]:
        """Pull region-specific MQTT password + global API key from env.

        Spec §F.4:
          * ``MQTT_PASSWORD_<UPPER_NAME>`` per region
          * ``ANTHROPIC_API_KEY`` global

        Missing values are tolerated in v0 (dev-mode broker may be open).
        """
        out: dict[str, str] = {}
        pwd = os.environ.get(f"MQTT_PASSWORD_{region.upper()}")
        if pwd:
            out["MQTT_PASSWORD"] = pwd
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            out["ANTHROPIC_API_KEY"] = api_key
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def launch_region(self, name: str) -> Container:
        """Start a region container.

        Returns the ``docker.models.containers.Container`` object.

        Note: not thread-safe against concurrent launches for the same region
        name; docker will return a name-conflict APIError which is surfaced as
        GliaError. Supervisor is responsible for serializing launches.

        Raises
        ------
        GliaError
            If the region is unknown, reserved, already running, or the
            docker SDK call fails (image missing, API error).
        """
        try:
            spec = self._registry.docker_spec(name)
        except KeyError as exc:
            raise GliaError(f"unknown region: {name}") from exc
        except ValueError as exc:
            raise GliaError(
                f"cannot launch reserved region: {name}: {exc}"
            ) from exc

        # Singleton enforcement — spec §G.9.  Refuse double-launch so we
        # don't fork duplicate brain regions.
        if self.is_running(name):
            raise GliaError(f"region already running: {name}")

        env = dict(spec["env"])
        env["MQTT_HOST"] = self._broker_host
        env.update(self._env_loader(name))

        try:
            container = self._client.containers.run(
                image=spec["image"],
                name=spec["name"],
                network=spec["network"],
                volumes=spec["volumes"],
                environment=env,
                detach=True,
                restart_policy={"Name": "unless-stopped"},
                **DEFAULT_RESOURCE_LIMITS,
            )
        except ImageNotFound as exc:
            raise GliaError(f"image not found for {name}: {exc}") from exc
        except APIError as exc:
            raise GliaError(f"docker API error launching {name}: {exc}") from exc

        return container

    def stop_region(self, name: str, *, timeout: int = 10) -> None:
        """Stop and remove the container for region ``name``.

        No-op if the container does not exist.  Wraps docker API errors
        in :class:`GliaError`.
        """
        container_name = f"hive-{name}"
        try:
            container = self._client.containers.get(container_name)
        except NotFound:
            return
        except APIError as exc:
            raise GliaError(f"docker API error looking up {name}: {exc}") from exc

        try:
            container.stop(timeout=timeout)
        except APIError as exc:
            raise GliaError(f"docker API error stopping {name}: {exc}") from exc
        try:
            container.remove()
        except NotFound:
            pass  # already removed between stop() and remove() — acceptable
        except APIError as exc:
            raise GliaError(f"docker API error removing {name}: {exc}") from exc

    def restart_region(self, name: str) -> Container:
        """Stop (if running) then launch the region.  Returns new container."""
        self.stop_region(name)
        return self.launch_region(name)

    def is_running(self, name: str) -> bool:
        """True iff a container named ``hive-<name>`` exists and is running."""
        container_name = f"hive-{name}"
        try:
            container = self._client.containers.get(container_name)
        except NotFound:
            return False
        except APIError as exc:
            raise GliaError(f"docker API error querying {name}: {exc}") from exc

        # Refresh to avoid stale cached status from a previous get().
        try:
            container.reload()
        except NotFound:
            return False
        except APIError as exc:
            raise GliaError(
                f"docker API error reloading {name}: {exc}"
            ) from exc
        return container.status == "running"
