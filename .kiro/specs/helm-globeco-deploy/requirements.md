# Requirements Document

## Introduction

Replace the GlobeCo manifest-based deployment (step 4 of `initialize()`) with a Helm-based deployment. The current approach downloads individual manifests from GitHub, which triggers anti-scraping protections under repeated high-frequency calls. Helm consolidates this into a single chart install, improving reliability.

## Glossary

- **Runner**: The KASBench Benchmark Runner FastAPI application
- **Helm_Installer**: The component responsible for executing Helm CLI commands to deploy GlobeCo
- **RunnerConfig**: The pydantic-settings configuration class holding all environment-variable-driven settings
- **InitializeRequest**: The Pydantic model representing the POST /initialize request body
- **GlobeCo**: The suite of microservices deployed into the `globeco` Kubernetes namespace

## Requirements

### Requirement 1

**User Story:** As a benchmark operator, I want GlobeCo deployed via Helm instead of individual manifest downloads, so that initialization is reliable and not blocked by GitHub rate limiting.

#### Acceptance Criteria

1. WHEN step 4 of initialize executes and `skip_manifest_install` is False, THE Helm_Installer SHALL run `helm repo add globeco-repo https://kasbench.github.io/globeco-helm`
2. WHEN the Helm repo has been added, THE Helm_Installer SHALL run `helm repo update`
3. WHEN the repo is updated, THE Helm_Installer SHALL run `helm install globeco globeco-repo/globeco --namespace globeco --create-namespace --wait` with a configurable timeout
4. WHEN the Helm install completes successfully, THE Runner SHALL set `state.globeco_installed = True`
5. WHEN `skip_manifest_install` is True in the request, THE Runner SHALL skip the Helm install and set `state.globeco_installed = True`

### Requirement 2

**User Story:** As a benchmark operator, I want the Helm install timeout to be configurable, so that I can adjust it for clusters with varying startup times.

#### Acceptance Criteria

1. THE RunnerConfig SHALL expose a `helm_install_timeout` field loaded from the `HELM_INSTALL_TIMEOUT` environment variable
2. WHEN `HELM_INSTALL_TIMEOUT` is not set, THE RunnerConfig SHALL default `helm_install_timeout` to 300 seconds
3. WHEN the Helm install command is constructed, THE Helm_Installer SHALL append `--timeout {helm_install_timeout}s` to the command

### Requirement 3

**User Story:** As a benchmark operator, I want clear error responses when Helm installation fails, so that I can diagnose deployment issues.

#### Acceptance Criteria

1. IF a Helm CLI command returns a non-zero exit code, THEN THE Runner SHALL return an error response with error type `helm_install_failed`, the failing command, and stderr output
2. IF the Helm CLI binary is not found on the system, THEN THE Runner SHALL return an error response with error type `helm_install_failed` and a message indicating Helm is not installed
3. WHEN the Helm install fails, THE Runner SHALL NOT set `state.globeco_installed = True`

### Requirement 4

**User Story:** As a maintainer, I want the old manifest install functions preserved but deprecated, so that the codebase remains backward-compatible during transition.

#### Acceptance Criteria

1. THE Runner SHALL retain the `_install_manifests` function with a deprecation warning in its docstring
2. THE Runner SHALL retain the `_execute_manifest_operations` function with a deprecation warning in its docstring
3. THE InitializeRequest SHALL retain the `force_manifest_install` field but THE Runner SHALL ignore its value during Helm installation

### Requirement 5

**User Story:** As a benchmark operator, I want Helm repository and chart details configurable, so that I can point to alternative charts if needed.

#### Acceptance Criteria

1. THE RunnerConfig SHALL expose a `helm_repo_name` field defaulting to `globeco-repo`
2. THE RunnerConfig SHALL expose a `helm_repo_url` field defaulting to `https://kasbench.github.io/globeco-helm`
3. THE RunnerConfig SHALL expose a `helm_chart_name` field defaulting to `globeco`
4. THE RunnerConfig SHALL expose a `helm_release_name` field defaulting to `globeco`
5. THE RunnerConfig SHALL expose a `helm_namespace` field defaulting to `globeco`
