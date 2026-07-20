# Implementation Plan: Helm GlobeCo Deploy

## Overview

Replace the manifest-based GlobeCo deployment in step 4 of `initialize()` with Helm chart installation. Add Helm config fields to `RunnerConfig`, create a `HelmInstallError` exception, implement the `_install_helm_chart` helper, rewire step 4, and deprecate old manifest functions.

## Tasks

- [x] 1. Add HelmInstallError to errors.py
  - [x] 1.1 Add `HelmInstallError` class inheriting from `RunnerError`
    - Constructor takes `command: str` and `stderr: str`
    - Sets `error="helm_install_failed"` and includes command/stderr in context
    - _Requirements: 3.1, 3.2_

- [x] 2. Add Helm configuration fields to RunnerConfig
  - [x] 2.1 Add Helm fields to `RunnerConfig` in `config.py`
    - `helm_install_timeout: int = 300`
    - `helm_repo_name: str = "globeco-repo"`
    - `helm_repo_url: str = "https://kasbench.github.io/globeco-helm"`
    - `helm_chart_name: str = "globeco"`
    - `helm_release_name: str = "globeco"`
    - `helm_namespace: str = "globeco"`
    - _Requirements: 2.1, 2.2, 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ]* 2.2 Write property test for Helm config loading
    - **Property 2: Helm config fields load from environment variables**
    - **Validates: Requirements 2.1, 5.1, 5.2, 5.3, 5.4, 5.5**

- [x] 3. Implement `_install_helm_chart` helper in initialize.py
  - [x] 3.1 Add `_install_helm_chart(config: RunnerConfig) -> None` async function
    - Constructs three commands: `helm repo add`, `helm repo update`, `helm install`
    - Uses `asyncio.create_subprocess_exec` for each command
    - Catches `FileNotFoundError` for missing Helm binary
    - Raises `HelmInstallError` on non-zero exit code
    - Logs start/success/failure for each command via structlog
    - Appends `--timeout {helm_install_timeout}s` to install command
    - _Requirements: 1.1, 1.2, 1.3, 2.3, 3.1, 3.2_

  - [ ]* 3.2 Write property test for Helm command construction
    - **Property 1: Helm command construction includes all config values**
    - **Validates: Requirements 1.3, 2.3, 5.1, 5.2, 5.3, 5.4, 5.5**

  - [ ]* 3.3 Write property test for error response structure
    - **Property 3: Non-zero exit codes produce error responses with correct structure**
    - **Validates: Requirements 3.1, 3.3**

- [x] 4. Rewire step 4 in `initialize()` to use Helm
  - [x] 4.1 Replace step 4 body with Helm install logic
    - Keep `skip_manifest_install` check (skip → log + set state)
    - Call `_install_helm_chart(config)` instead of `_install_manifests(body, config)`
    - Catch `HelmInstallError` and generic `Exception`, return via `build_error_response()`
    - Set `state.globeco_installed = True` on success
    - Remove `manifest_errors` variable and related response logic
    - Update step 4 comment to reference Req 6
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.1, 3.3_

  - [x] 4.2 Update imports in initialize.py
    - Add import for `HelmInstallError`
    - Remove unused imports: `httpx`, `ManifestError`, `MANIFEST_REPOS`, `parse_manifest_list`, `ManifestOperation`
    - _Requirements: 1.1_

  - [ ]* 4.3 Write property test for force_manifest_install ignored
    - **Property 4: force_manifest_install has no effect on Helm behavior**
    - **Validates: Requirements 4.3**

- [x] 5. Deprecate old manifest functions
  - [x] 5.1 Add deprecation notices to `_install_manifests` and `_execute_manifest_operations`
    - Add `.. deprecated::` to each docstring
    - Add note: "Retained for backward compatibility. Use _install_helm_chart instead."
    - Do NOT delete the functions
    - _Requirements: 4.1, 4.2_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Clean up response shape
  - [x] 7.1 Remove `manifest_errors` from initialize response
    - The Helm install either succeeds or raises — no partial error accumulation
    - Remove the `if manifest_errors:` block and `manifest_errors` variable
    - Response body remains `{"message": "Initialization complete", "status": "not-started"}`
    - _Requirements: 1.4_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The `force_manifest_install` field stays in the request model for backward compatibility but is silently ignored
- The `MANIFEST_REPOS` constant in config.py is retained since the deprecated functions reference it
- Shutdown function remains unchanged per requirement_006.md
- Property tests use hypothesis for generation; mock `asyncio.create_subprocess_exec` to avoid real subprocess calls
