# Requirements Document

## Introduction

Enhance the Kubernetes cluster initialization workflow in `KubernetesManager.install_cluster` by adding three new infrastructure installation steps after the existing Step 8 (EBS CSI driver). These steps install Envoy Gateway, Prometheus (with a configurable values file URL), and the OpenTelemetry Collector (via cert-manager and the OTel operator). Each step follows the existing async subprocess pattern with error handling and structured logging.

## Glossary

- **KubernetesManager**: The service class responsible for orchestrating Kubernetes cluster installation and configuration.
- **RunnerConfig**: The pydantic-settings configuration class that loads environment variables with defaults.
- **KubernetesError**: The error raised when a Kubernetes installation step fails.
- **Envoy_Gateway**: An API gateway for Kubernetes based on the Envoy proxy, installed via Helm OCI chart.
- **Prometheus**: A monitoring and alerting toolkit installed via Helm chart with a configurable values file.
- **OpenTelemetry_Collector**: A telemetry data collection component installed via the OpenTelemetry Operator, which requires cert-manager as a prerequisite.
- **Helm**: A Kubernetes package manager used to install and manage charts.
- **cert-manager**: A Kubernetes add-on that automates TLS certificate management, required by the OpenTelemetry Operator.

## Requirements

### Requirement 1: Install Envoy Gateway

**User Story:** As a platform operator, I want Envoy Gateway installed during cluster initialization, so that the cluster has an API gateway ready for service traffic routing.

#### Acceptance Criteria

1. WHEN the install_cluster method reaches Step 9, THE KubernetesManager SHALL execute a Helm install command to deploy Envoy Gateway version v1.8.2 into the envoy-gateway-system namespace, creating the namespace if it does not exist.
2. WHEN the Envoy Gateway Helm install completes successfully, THE KubernetesManager SHALL wait up to 5 minutes for the envoy-gateway deployment in envoy-gateway-system to become Available.
3. IF the Envoy Gateway Helm install command returns a non-zero exit code, THEN THE KubernetesManager SHALL raise a KubernetesError with step name, command, and error output.
4. IF the Envoy Gateway readiness wait times out or fails, THEN THE KubernetesManager SHALL raise a KubernetesError with step name, command, and error output.
5. WHEN the Envoy Gateway installation and readiness check succeed, THE KubernetesManager SHALL log a success event using structured logging.

### Requirement 2: Install Prometheus

**User Story:** As a platform operator, I want Prometheus installed during cluster initialization with a configurable values file, so that monitoring is available and the configuration can be updated without code changes.

#### Acceptance Criteria

1. THE RunnerConfig SHALL include a `prometheus_values_url` field with a default value of `https://raw.githubusercontent.com/kasbench/globeco-observability/v1.1.5/k8s_aws/values_prometheus.yaml`, loadable from an environment variable.
2. WHEN the install_cluster method reaches Step 10, THE KubernetesManager SHALL add the prometheus-community Helm repository and update Helm repositories.
3. WHEN Helm repositories are updated, THE KubernetesManager SHALL install the prometheus chart from prometheus-community into the monitoring namespace using the values file URL from configuration.
4. IF the Helm repo add, repo update, or chart install command returns a non-zero exit code, THEN THE KubernetesManager SHALL raise a KubernetesError with step name, command, and error output.
5. WHEN the Prometheus installation succeeds, THE KubernetesManager SHALL log a success event using structured logging.

### Requirement 3: Install OpenTelemetry Collector

**User Story:** As a platform operator, I want the OpenTelemetry Collector operator installed during cluster initialization, so that telemetry collection infrastructure is ready for application instrumentation.

#### Acceptance Criteria

1. WHEN the install_cluster method reaches Step 11, THE KubernetesManager SHALL apply the cert-manager manifest from the latest release URL.
2. WHEN the cert-manager manifest is applied, THE KubernetesManager SHALL wait up to 360 seconds for all deployments in the cert-manager namespace to become Available.
3. WHEN cert-manager is ready, THE KubernetesManager SHALL apply the OpenTelemetry Operator manifest from the latest release URL.
4. WHEN the OpenTelemetry Operator manifest is applied, THE KubernetesManager SHALL wait up to 360 seconds for the opentelemetry-operator-controller-manager deployment in the opentelemetry-operator-system namespace to become Available.
5. IF any command in the OpenTelemetry Collector installation sequence returns a non-zero exit code or times out, THEN THE KubernetesManager SHALL raise a KubernetesError with step name, command, and error output.
6. WHEN the OpenTelemetry Collector installation completes successfully, THE KubernetesManager SHALL log a success event using structured logging.

### Requirement 4: Step Ordering and Integration

**User Story:** As a platform operator, I want the new installation steps executed in the correct order after existing steps, so that dependencies between components are respected.

#### Acceptance Criteria

1. THE KubernetesManager SHALL execute Step 9 (Envoy Gateway) after Step 8 (EBS CSI) completes successfully.
2. THE KubernetesManager SHALL execute Step 10 (Prometheus) after Step 9 (Envoy Gateway) completes successfully.
3. THE KubernetesManager SHALL execute Step 11 (OpenTelemetry Collector) after Step 10 (Prometheus) completes successfully.
4. WHEN all eleven steps complete successfully, THE KubernetesManager SHALL log the overall kubernetes_install_completed event.
5. IF any step fails, THEN THE KubernetesManager SHALL halt the installation sequence and propagate the error without executing subsequent steps.
