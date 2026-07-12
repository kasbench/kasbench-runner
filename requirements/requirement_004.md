# Requirement 4: Preliminary auditing enhancements


1. Implement a "wait for rollout" capability that waits for a named Kubernetes deployment to be rolled in a named namespace.  It should accept a deployment name, namespace, and timeout (at minimum).  You may use the following as an imperfect example:

```python
def wait_for_rollout(deployment, namespace, timeout_seconds=300, sleep_seconds=10, verbose=True):
    """
    Wait for a Deployment rollout to complete, similar to `kubectl rollout status`.
    """
    start_time = time.time()
    name = deployment.name

    # The following line is required.  Refresh alone does not work.  Might just be timing.
    deployment = list(kr8s.get("Deployment", name, namespace=namespace))[0]

    while True:
        if time.time() - start_time > timeout_seconds:
            raise TimeoutError(f"Timed out waiting for deployment '{name}' to roll out.")

        retries = 3
        for i in range(retries):
            try:
                deployment.refresh()  # Refresh the object from the API
            except Exception as e:
                if i == retries - 1:
                    raise(e)
                print(f"Exception in waiting for deployment: {e}.  Retrying")
                time.sleep(15)
        status = deployment.status or {}
        conditions = {c["type"]: c for c in status.get("conditions", [])}

        progressing = conditions.get("Progressing", {})
        available = conditions.get("Available", {})

        # Print a status line for debugging
        updated = status.get("updatedReplicas", 0)
        ready = status.get("readyReplicas", 0)
        desired = deployment.spec.get("replicas", 0)
        if verbose:
            print(f"Waiting for rollout of {name}: {ready}/{desired} ready, {updated} updated")

        # Success: progressing=True, available=True, and all replicas ready
        if (progressing.get("status") == "True" and progressing.get("reason") == "NewReplicaSetAvailable"
            and available.get("status") == "True"
            and ready == desired):
            if verbose:
                print(f"Deployment '{name}' successfully rolled out.")
            return

        # Failure case (like kubectl does)
        if progressing.get("status") == "False" and progressing.get("reason") == "ProgressDeadlineExceeded":
            raise RuntimeError(f"Rollout of deployment '{name}' failed: ProgressDeadlineExceeded")

        time.sleep(sleep_seconds)
```

Unlike in the example above, the code should recognize scenarios in which the deployment will never be successful without intervention and raise an appropriate exception.


2. Implement a "wait for all rollouts" functionality, which takes a list of deployments (with namespace) and a timeout, It should either returns silently (if all deployments have rolled out) or throws an exception.  The timeout is the maximum time for the entire function to wait, not the timeout for each individual deployment.


3. Implement a snapshot functionality, using the following approach
- The snapshot takes an argument called `phase`.  Phase can either be "pre" or "post", for a pre- or post-benchmark snapshot.
- All files are stored in S3.  All filenames described below are prefixed with: `{s3bucket}/{runIdentifier}/{trialIdentifier}/snapshot/{phase}`, where s3Bucket, runIdentifier, and trialIndentifier are values passed at initialization.  
- Use the following to understand what should be collected in the snapshot.  Use the subdirectory and file names shown in the script, but store in S3 with the filename prefix given above (`{s3bucket}/{runIdentifier}/{trialIdentifier}/snapshot/{phase}`).  Note that errors are expected and must be tolerated for three of the statements below (vpa.yaml, keda.yaml, and gateway-api.yaml).  Errors may be reported in the logs but should not cause the snapshot to fail.  Note that this sample code is for reference.  The functionality may be built using Python functions and the `k8rs` library to be consistent with the rest of the code.
```bash
#!/usr/bin/env bash
set -Eeuo pipefail

PHASE="${1:?Usage: $0 pre|post}"
RUN_ID="${RUN_ID:?RUN_ID must be set}"
TRIAL_ID="${TRIAL_ID:?TRIAL_ID must be set}"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="snapshot-${RUN_ID}-${TRIAL_ID}-${PHASE}-${TIMESTAMP}"

mkdir -p "${OUT}"/{metadata,resources,descriptions,events,raw}

run() {
    local name="$1"
    shift

    {
        printf '# collected_at=%s\n' "$(date --iso-8601=seconds)"
        printf '# command='
        printf '%q ' "$@"
        printf '\n'
        "$@"
    } >"${OUT}/${name}" 2>&1 || true
}

run metadata/date.txt date --iso-8601=seconds
run metadata/kubectl-version.yaml kubectl version -o yaml
run metadata/context.txt kubectl config current-context
run metadata/cluster-info.txt kubectl cluster-info

run resources/nodes.yaml \
    kubectl get nodes -o yaml
run descriptions/nodes.txt \
    kubectl describe nodes
run resources/pods.yaml \
    kubectl get pods -A -o yaml
run resources/pods-wide.txt \
    kubectl get pods -A -o wide
run descriptions/pods.txt \
    kubectl describe pods -A

run resources/workloads.yaml \
    kubectl get deployments,statefulsets,daemonsets,replicasets,jobs,cronjobs \
    -A -o yaml

run resources/autoscaling.yaml \
    kubectl get hpa -A -o yaml

run resources/network.yaml \
    kubectl get services,endpoints,endpointslices,ingresses,networkpolicies \
    -A -o yaml

run resources/storage.yaml \
    kubectl get pvc,pv,storageclass,volumeattachments -A -o yaml

run resources/policies.yaml \
    kubectl get resourcequotas,limitranges,poddisruptionbudgets \
    -A -o yaml

run resources/configmaps.yaml \
    kubectl get configmaps -A -o yaml

run resources/webhooks.yaml \
    kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations \
    -o yaml

run events/all.yaml \
    kubectl events -A -o yaml
run events/warnings.yaml \
    kubectl events -A --types=Warning -o yaml

run raw/readyz.txt \
    kubectl get --raw '/readyz?verbose'
run raw/livez.txt \
    kubectl get --raw '/livez?verbose'
run raw/node-metrics.json \
    kubectl get --raw '/apis/metrics.k8s.io/v1beta1/nodes'
run raw/pod-metrics.json \
    kubectl get --raw '/apis/metrics.k8s.io/v1beta1/pods'

# Optional CRDs. Failure is deliberately tolerated by run().
run resources/vpa.yaml \
    kubectl get vpa -A -o yaml
run resources/keda.yaml \
    kubectl get scaledobjects,scaledjobs,triggerauthentications,clustertriggerauthentications \
    -A -o yaml
run resources/gateway-api.yaml \
    kubectl get gateways,gatewayclasses,httproutes,grpcroutes \
    -A -o yaml

kubectl api-resources -o wide >"${OUT}/metadata/api-resources.txt"

find "${OUT}" -type f -print0 |
    sort -z |
    xargs -0 sha256sum >"${OUT}/SHA256SUMS"

tar -czf "${OUT}.tar.gz" "${OUT}"
sha256sum "${OUT}.tar.gz" >"${OUT}.tar.gz.sha256"
```

4. Implement a wait for rollout API that takes a deployment name, namespace, and timeout as parameters, using the function built in requirement 1.

5. Implement a wait for all rollouts API that takes a timeout as a parameter.  It should wait for a configurable list of deployments to be ready, using the function built in requirement 2.  The default list of deployments is:

```text
NAMESPACE NAME
elasticsearch elasticsearch
globeco globeco-allocation-service
globeco globeco-confirmation-service
globeco globeco-debug-tools
globeco globeco-execution-service
globeco globeco-fix-engine
globeco globeco-order-generation-service
globeco globeco-order-service
globeco globeco-portfolio-accounting-service
globeco globeco-portfolio-management-portal
globeco globeco-portfolio-service
globeco globeco-postgres-exporter-trade-service
globeco globeco-pricing-service
globeco globeco-security-service
globeco globeco-trade-service
kube-system coredns
kube-system metrics-server
monitoring prometheus-kube-state-metrics
monitorong prometheus-prometheus-pushgateway
monitoring prometheus-server
monitoring pushgateway
monitoring otel-collector
observability jaeger
opentelemetry-operator-system opentelemetry-operator-controller-manager
```

