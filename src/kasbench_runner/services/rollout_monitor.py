"""Kubernetes Deployment rollout monitor.

Polls Kubernetes Deployments via kr8s until rollout completes, times out,
or encounters an unrecoverable condition. Supports single-deployment and
batch-deployment modes with configurable timeouts, retry logic for transient
API errors, and early termination on unrecoverable conditions.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9
"""

import asyncio
import time
from dataclasses import dataclass

import kr8s
import structlog

from kasbench_runner.errors import (
    DeploymentNotFoundError,
    KubernetesApiError,
    RolloutTimeoutError,
    RolloutUnrecoverableError,
)

logger = structlog.get_logger()


@dataclass(frozen=True)
class DeploymentSpec:
    """Identifies a Kubernetes Deployment to monitor."""

    name: str
    namespace: str


class RolloutMonitor:
    """Monitors Kubernetes Deployment rollouts via kr8s."""

    POLL_INTERVAL: int = 10  # seconds
    RETRY_LIMIT: int = 3
    RETRY_DELAY: int = 15  # seconds

    UNRECOVERABLE_POD_CONDITIONS: set[str] = {
        "CrashLoopBackOff",
        "ImagePullBackOff",
        "ErrImagePull",
        "InvalidImageName",
        "CreateContainerConfigError",
    }

    async def wait_for_rollout(
        self,
        deployment_name: str,
        namespace: str,
        timeout_seconds: int,
    ) -> float:
        """Wait for a single deployment rollout to complete.

        Polls the deployment every POLL_INTERVAL seconds, checking for success,
        unrecoverable conditions, and pod-level failures.

        Args:
            deployment_name: Name of the Deployment resource.
            namespace: Kubernetes namespace.
            timeout_seconds: Maximum wait time in seconds.

        Returns:
            Elapsed time in seconds.

        Raises:
            DeploymentNotFoundError: Deployment does not exist.
            RolloutTimeoutError: Timeout elapsed before completion.
            RolloutUnrecoverableError: Terminal condition detected.
            KubernetesApiError: API unreachable after retries.
        """
        start = time.monotonic()

        while True:
            elapsed = time.monotonic() - start

            if elapsed >= timeout_seconds:
                raise RolloutTimeoutError(
                    deployment_name=deployment_name,
                    namespace=namespace,
                    elapsed_seconds=elapsed,
                )

            # Fetch the deployment with transient error retries
            deployment = await self._fetch_deployment_with_retry(
                deployment_name, namespace
            )

            # Check deployment-level unrecoverable condition
            status = deployment.status
            conditions = status.get("conditions", [])
            unrecoverable_reason = self._check_unrecoverable_deployment_condition(
                conditions
            )
            if unrecoverable_reason:
                raise RolloutUnrecoverableError(
                    deployment_name=deployment_name,
                    namespace=namespace,
                    reason=unrecoverable_reason,
                )

            # Check pod-level unrecoverable conditions
            pod_failure = await self._check_pod_conditions(
                deployment_name, namespace
            )
            if pod_failure:
                pod_name, condition = pod_failure
                raise RolloutUnrecoverableError(
                    deployment_name=deployment_name,
                    namespace=namespace,
                    reason=condition,
                    pod_name=pod_name,
                )

            # Check success
            if self._is_rollout_complete(status, deployment.spec):
                elapsed = time.monotonic() - start
                logger.info(
                    "rollout_complete",
                    deployment=deployment_name,
                    namespace=namespace,
                    elapsed_seconds=round(elapsed, 1),
                )
                return elapsed

            # Log progress
            ready_replicas = status.get("readyReplicas", 0) or 0
            desired_replicas = deployment.spec.get("replicas", 0) or 0
            logger.info(
                "rollout_progress",
                deployment=deployment_name,
                namespace=namespace,
                ready_replicas=ready_replicas,
                desired_replicas=desired_replicas,
                elapsed_seconds=round(elapsed, 1),
            )

            await asyncio.sleep(self.POLL_INTERVAL)

    async def wait_for_all_rollouts(
        self,
        deployments: list[DeploymentSpec],
        timeout_seconds: int,
    ) -> None:
        """Wait for multiple deployments concurrently under a shared timeout.

        Args:
            deployments: List of DeploymentSpec instances to monitor.
            timeout_seconds: Maximum wall-clock time for the entire batch.

        Raises:
            RolloutTimeoutError: Timeout with list of incomplete deployments.
            RolloutUnrecoverableError: Any deployment hit terminal condition.
            KubernetesApiError: API unreachable after retries.
        """
        if not deployments:
            return

        tasks = [
            asyncio.create_task(
                self.wait_for_rollout(d.name, d.namespace, timeout_seconds)
            )
            for d in deployments
        ]

        done, pending = await asyncio.wait(
            tasks, timeout=timeout_seconds, return_when=asyncio.FIRST_EXCEPTION
        )

        # Check for exceptions in done tasks
        for task in done:
            if task.exception():
                # Cancel all pending
                for p in pending:
                    p.cancel()
                # Await cancelled tasks to suppress warnings
                for p in pending:
                    try:
                        await p
                    except (asyncio.CancelledError, Exception):
                        pass
                raise task.exception()

        # If pending remain, timeout occurred
        if pending:
            for p in pending:
                p.cancel()
            for p in pending:
                try:
                    await p
                except (asyncio.CancelledError, Exception):
                    pass
            # Determine which deployments are incomplete
            incomplete = [
                deployments[i]
                for i, t in enumerate(tasks)
                if t in pending
            ]
            incomplete_names = [
                f"{d.namespace}/{d.name}" for d in incomplete
            ]
            raise RolloutTimeoutError(
                deployment_name=incomplete_names[0] if incomplete_names else "unknown",
                namespace="batch",
                elapsed_seconds=timeout_seconds,
            )

    def _is_rollout_complete(self, status: dict, spec: dict) -> bool:
        """Check if deployment meets success criteria.

        Success requires:
        - updatedReplicas == replicas
        - readyReplicas == replicas
        - Progressing condition reason == "NewReplicaSetAvailable"

        Args:
            status: The deployment's .status dict.
            spec: The deployment's .spec dict.

        Returns:
            True if rollout is complete, False otherwise.
        """
        replicas = spec.get("replicas", 0)
        if replicas is None or replicas == 0:
            return False

        updated_replicas = status.get("updatedReplicas", 0) or 0
        ready_replicas = status.get("readyReplicas", 0) or 0

        if updated_replicas != replicas:
            return False
        if ready_replicas != replicas:
            return False

        # Check Progressing condition reason
        conditions = status.get("conditions", [])
        for cond in conditions:
            if cond.get("type") == "Progressing":
                if cond.get("reason") == "NewReplicaSetAvailable":
                    return True
                return False

        # If no Progressing condition exists, not complete
        return False

    def _check_unrecoverable_deployment_condition(
        self, conditions: list[dict]
    ) -> str | None:
        """Check deployment conditions for unrecoverable state.

        Looks for Progressing condition with status "False" and reason
        "ProgressDeadlineExceeded".

        Args:
            conditions: List of condition dicts from deployment status.

        Returns:
            The unrecoverable reason string if found, else None.
        """
        for cond in conditions:
            if cond.get("type") == "Progressing" and cond.get("status") == "False":
                if cond.get("reason") == "ProgressDeadlineExceeded":
                    return cond["reason"]
        return None

    async def _check_pod_conditions(
        self, deployment_name: str, namespace: str
    ) -> tuple[str, str] | None:
        """Check pods owned by the deployment for unrecoverable states.

        Queries pods with the label selector app={deployment_name} and checks
        container statuses for known unrecoverable conditions.

        Args:
            deployment_name: Name of the deployment.
            namespace: Kubernetes namespace.

        Returns:
            Tuple of (pod_name, condition) if an unrecoverable state is found,
            else None.
        """
        try:
            api = await kr8s.asyncio.api()
            pods = [
                pod
                async for pod in api.get(
                    "pods",
                    namespace=namespace,
                    label_selector=f"app={deployment_name}",
                )
            ]
        except Exception as exc:
            logger.warning(
                "pod_condition_check_failed",
                deployment=deployment_name,
                namespace=namespace,
                error=str(exc),
            )
            return None

        for pod in pods:
            pod_name = pod.name
            container_statuses = pod.status.get("containerStatuses", [])
            init_container_statuses = pod.status.get("initContainerStatuses", [])

            for container_status in container_statuses + init_container_statuses:
                waiting = container_status.get("state", {}).get("waiting", {})
                reason = waiting.get("reason", "")
                if reason in self.UNRECOVERABLE_POD_CONDITIONS:
                    return (pod_name, reason)

        return None

    async def _fetch_deployment_with_retry(
        self, deployment_name: str, namespace: str
    ) -> object:
        """Fetch deployment from K8s API with transient error retries.

        Retries up to RETRY_LIMIT times with RETRY_DELAY seconds between
        attempts for connection errors, timeouts, and HTTP 5xx responses.

        Args:
            deployment_name: Name of the deployment.
            namespace: Kubernetes namespace.

        Returns:
            The kr8s Deployment object.

        Raises:
            DeploymentNotFoundError: If the deployment does not exist.
            KubernetesApiError: If all retries are exhausted.
        """
        for attempt in range(self.RETRY_LIMIT + 1):
            try:
                api = await kr8s.asyncio.api()
                deployments = [
                    dep
                    async for dep in api.get(
                        "deployments", deployment_name, namespace=namespace
                    )
                ]

                # kr8s returns an empty list when a specific named resource is not found
                if not deployments:
                    raise DeploymentNotFoundError(
                        deployment_name=deployment_name,
                        namespace=namespace,
                    )

                return deployments[0]

            except DeploymentNotFoundError:
                raise

            except kr8s.NotFoundError:
                raise DeploymentNotFoundError(
                    deployment_name=deployment_name,
                    namespace=namespace,
                )

            except (
                ConnectionError,
                TimeoutError,
                OSError,
                kr8s.APITimeoutError,
                kr8s.ServerError,
            ) as exc:
                # Transient errors: connection issues, timeouts, HTTP 5xx
                # kr8s.ServerError covers HTTP 5xx responses
                if attempt == self.RETRY_LIMIT:
                    raise KubernetesApiError(message=str(exc)) from exc

                logger.warning(
                    "kubernetes_api_retry",
                    deployment=deployment_name,
                    namespace=namespace,
                    retry_attempt=attempt + 1,
                    max_retries=self.RETRY_LIMIT,
                    error=str(exc),
                )

                await asyncio.sleep(self.RETRY_DELAY)

            except Exception as exc:
                # Non-transient, non-retryable error — propagate immediately
                raise KubernetesApiError(message=str(exc)) from exc

        # Should not reach here, but safety net
        raise KubernetesApiError(
            message=f"Failed to fetch deployment {namespace}/{deployment_name} after retries"
        )
