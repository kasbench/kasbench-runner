# Implementation Plan: Enhance Kubernetes Initialization

## Overview

Add three new infrastructure installation steps (Envoy Gateway, Prometheus, OpenTelemetry Collector) to `KubernetesManager.install_cluster`, following the existing `_install_ebs_csi` async subprocess pattern. Add a configurable `prometheus_values_url` to `RunnerConfig`.

## Tasks

- [x] 1. Add `prometheus_values_url` config field to RunnerConfig
  - Add `prometheus_values_url: str = "https://raw.githubusercontent.com/kasbench/globeco-observability/v1.1.5/k8s_aws/values_prometheus.yaml"` field to `RunnerConfig` in `src/kasbench_runner/config.py`
  - Pydantic-settings will automatically load from `PROMETHEUS_VALUES_URL` env var
  - _Requirements: 2.1_

- [x] 2. Add `_install_envoy_gateway` method and call in `install_cluster`
  - Add `prometheus_values_url: str` parameter to `KubernetesManager.__init__` with the default URL, store as `self._prometheus_values_url`
  - Implement `_install_envoy_gateway()` following `_install_ebs_csi` pattern:
    - Command 1: `helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.8.2 -n envoy-gateway-system --create-namespace`
    - Command 2: `kubectl wait --timeout=5m -n envoy-gateway-system deployment/envoy-gateway --for=condition=Available`
    - Raise `KubernetesError` on non-zero exit code with step `"install_envoy_gateway"`
    - Log `envoy_gateway_installed` on success
  - Call `await self._install_envoy_gateway()` in `install_cluster` after Step 8
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 4.1_

- [x] 3. Add `_install_prometheus` method and call in `install_cluster`
  - Implement `_install_prometheus()` following `_install_ebs_csi` pattern:
    - Command 1: `helm repo add prometheus-community https://prometheus-community.github.io/helm-charts && helm repo update`
    - Command 2: `helm install prometheus prometheus-community/prometheus -f {self._prometheus_values_url} -n monitoring`
    - Raise `KubernetesError` on non-zero exit code with step `"install_prometheus"`
    - Log `prometheus_installed` on success
  - Call `await self._install_prometheus()` after `_install_envoy_gateway()` in `install_cluster`
  - _Requirements: 2.2, 2.3, 2.4, 2.5, 4.2_

- [x] 4. Add `_install_otel_collector` method and call in `install_cluster`
  - Implement `_install_otel_collector()` following `_install_ebs_csi` pattern:
    - Command 1: `kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml`
    - Command 2: `kubectl wait --for=condition=Available deployment --all -n cert-manager --timeout=360s`
    - Command 3: `kubectl apply -f https://github.com/open-telemetry/opentelemetry-operator/releases/latest/download/opentelemetry-operator.yaml`
    - Command 4: `kubectl wait --for=condition=Available deployment/opentelemetry-operator-controller-manager -n opentelemetry-operator-system --timeout=360s`
    - Raise `KubernetesError` on non-zero exit code with step `"install_otel_collector"`
    - Log `otel_collector_installed` on success
  - Call `await self._install_otel_collector()` after `_install_prometheus()` in `install_cluster`
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.3_

- [x] 5. Checkpoint - Verify implementation compiles
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 6. Add unit tests for the three new methods
  - Mock `asyncio.create_subprocess_exec` to return controlled exit codes and stderr
  - Test `_install_envoy_gateway`: happy path (exit 0 → no error, success logged) and failure path (non-zero → KubernetesError raised with correct step/command/output)
  - Test `_install_prometheus`: happy path and failure path for both repo-add and chart-install commands
  - Test `_install_otel_collector`: happy path and failure at each of the 4 sub-commands
  - Test that `install_cluster` calls the 3 new methods in order after Step 8
  - _Requirements: 1.3, 1.4, 1.5, 2.4, 2.5, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 7. Update module docstring requirements list
  - Update the docstring at the top of `kubernetes_manager.py` to include the new requirement numbers (5.1–5.5 or however they are numbered in requirement_005.md)
  - _Requirements: 4.4_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The implementation language is Python (matching existing codebase)
- All new methods follow the exact pattern of `_install_ebs_csi` for consistency
- The `prometheus_values_url` parameter on `__init__` keeps the class testable without requiring a full RunnerConfig instance
