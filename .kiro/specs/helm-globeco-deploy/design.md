# Design Document: Helm GlobeCo Deploy

## Overview

Replace the manifest-based GlobeCo deployment (step 4 in `initialize()`) with Helm chart installation. The new implementation runs three sequential Helm CLI commands via `asyncio.create_subprocess_exec`, reuses the existing error handling patterns, and adds configurable Helm parameters to `RunnerConfig`.

## Architecture

The change is localized to three files:

1. **`config.py`** — Add Helm-related configuration fields
2. **`initialize.py`** — Replace step 4 logic with a new `_install_helm_chart` function
3. **`errors.py`** — Add `HelmInstallError` exception class

The existing `_install_manifests` and `_execute_manifest_operations` functions remain in `initialize.py` marked as deprecated. No new service classes are introduced — the Helm install is a simple sequential subprocess workflow that fits naturally as a private helper function in the route module.

## Components

### RunnerConfig Additions

```python
# In config.py - add to RunnerConfig class

# Helm configuration
helm_install_timeout: int = 300
helm_repo_name: str = "globeco-repo"
helm_repo_url: str = "https://kasbench.github.io/globeco-helm"
helm_chart_name: str = "globeco"
helm_release_name: str = "globeco"
helm_namespace: str = "globeco"
```

The `helm_install_timeout` field is loaded from the `HELM_INSTALL_TIMEOUT` environment variable via pydantic-settings' standard mechanism (case-insensitive env var matching).

### HelmInstallError

```python
# In errors.py

class HelmInstallError(RunnerError):
    """Helm chart installation failure."""

    def __init__(self, command: str, stderr: str):
        super().__init__(
            error="helm_install_failed",
            message=f"Helm operation failed: {command}",
            command=command,
            stderr=stderr,
        )
```

### Helm Install Function

```python
# In initialize.py

async def _install_helm_chart(config: RunnerConfig) -> None:
    """Deploy GlobeCo via Helm chart install.

    Executes three commands sequentially:
    1. helm repo add {repo_name} {repo_url}
    2. helm repo update
    3. helm install {release} {repo_name}/{chart} --namespace {ns} --create-namespace --wait --timeout {t}s

    Raises:
        HelmInstallError: If any Helm command fails.
    """
    commands = [
        ["helm", "repo", "add", config.helm_repo_name, config.helm_repo_url],
        ["helm", "repo", "update"],
        [
            "helm", "install", config.helm_release_name,
            f"{config.helm_repo_name}/{config.helm_chart_name}",
            "--namespace", config.helm_namespace,
            "--create-namespace",
            "--wait",
            "--timeout", f"{config.helm_install_timeout}s",
        ],
    ]

    for cmd in commands:
        cmd_str = " ".join(cmd)
        logger.info("helm_command_start", command=cmd_str)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError:
            raise HelmInstallError(
                command=cmd_str,
                stderr="Helm CLI binary not found. Ensure helm is installed and on PATH.",
            )

        if proc.returncode != 0:
            error_output = stderr.decode().strip()
            logger.error(
                "helm_command_failed",
                command=cmd_str,
                exit_code=proc.returncode,
                stderr=error_output,
            )
            raise HelmInstallError(command=cmd_str, stderr=error_output)

        logger.info(
            "helm_command_success",
            command=cmd_str,
            stdout=stdout.decode()[:200],
        )
```

### Modified Step 4 in `initialize()`

```python
# Step 4: GlobeCo Helm install (Req 6)
if body.skip_manifest_install:
    logger.info("helm_install_skipped")
    state.globeco_installed = True
else:
    try:
        await _install_helm_chart(config)
        state.globeco_installed = True
    except HelmInstallError as exc:
        return build_error_response(
            error=exc.error,
            message=exc.message,
            status_code=500,
            **exc.context,
        )
    except Exception as exc:
        return build_error_response(
            error="helm_install_failed",
            message=str(exc),
            status_code=500,
            exception_class=type(exc).__name__,
        )
```

## Data Flow

```
POST /initialize
    │
    ├── Step 1-3: (unchanged)
    │
    ├── Step 4: Helm install
    │   ├── Check skip_manifest_install → skip if True
    │   ├── _install_helm_chart(config)
    │   │   ├── helm repo add ...
    │   │   ├── helm repo update
    │   │   └── helm install ... --wait --timeout Ns
    │   ├── On success → state.globeco_installed = True
    │   └── On failure → build_error_response()
    │
    └── Step 5-6: (unchanged)
```

## Error Handling

| Scenario | Error Type | HTTP Status |
|----------|-----------|-------------|
| Helm binary not found | `helm_install_failed` | 500 |
| `helm repo add` fails | `helm_install_failed` | 500 |
| `helm repo update` fails | `helm_install_failed` | 500 |
| `helm install` times out or fails | `helm_install_failed` | 500 |
| Unexpected exception | `helm_install_failed` | 500 |

All error responses include `command` and `stderr` context fields for diagnostics.

## Backward Compatibility

- `force_manifest_install` field remains in `InitializeRequest` but is silently ignored
- `skip_manifest_install` field continues to control whether step 4 runs
- `_install_manifests` and `_execute_manifest_operations` remain with `.. deprecated::` docstring markers
- `MANIFEST_REPOS` constant remains in `config.py` (referenced by deprecated functions)
- Response shape is unchanged for success cases

## Testing Strategy

- Unit tests mock `asyncio.create_subprocess_exec` to verify command construction and error handling
- Property tests validate command construction across config variations
- Integration tests (manual) verify actual Helm deployment on a real cluster

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Helm command construction includes all config values

*For any* valid `RunnerConfig` with non-empty `helm_repo_name`, `helm_repo_url`, `helm_chart_name`, `helm_release_name`, `helm_namespace`, and positive `helm_install_timeout`, the constructed Helm install command list SHALL contain the repo name, repo URL, chart reference, namespace, and timeout flag with the correct value.

**Validates: Requirements 1.3, 2.3, 5.1, 5.2, 5.3, 5.4, 5.5**

### Property 2: Helm config fields load from environment variables

*For any* valid string value assigned to `HELM_REPO_NAME`, `HELM_REPO_URL`, `HELM_CHART_NAME`, `HELM_RELEASE_NAME`, `HELM_NAMESPACE`, or valid positive integer assigned to `HELM_INSTALL_TIMEOUT`, the resulting `RunnerConfig` instance SHALL have those fields set to the provided values.

**Validates: Requirements 2.1, 5.1, 5.2, 5.3, 5.4, 5.5**

### Property 3: Non-zero exit codes produce error responses with correct structure

*For any* non-zero exit code and any stderr string, when a Helm subprocess returns that exit code, the resulting `HelmInstallError` SHALL contain error type `helm_install_failed`, the command string, and the stderr output.

**Validates: Requirements 3.1, 3.3**

### Property 4: force_manifest_install has no effect on Helm behavior

*For any* valid `InitializeRequest` where `skip_manifest_install` is False, the Helm commands executed SHALL be identical regardless of whether `force_manifest_install` is True or False.

**Validates: Requirements 4.3**
