# Requirement 5: Enhance Kubernetes initialization

1. The following steps must be added after Step 8 in function `install_cluster` in [kubernetes_manager.py](../src/kasbench_runner/services/kubernetes_manager.py).

- Execute the following command (or equivalent):
```bash
helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.8.2 -n envoy-gateway-system --create-namespace
# Wait for Envoy to become available
kubectl wait --timeout=5m -n envoy-gateway-system deployment/envoy-gateway --for=condition=Available
```

- Install Prometheus with the following (or equivalent):
```bash
# Add the official community repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts

# Download the latest chart listings
 helm repo update

# Install prometheus
helm install prometheus prometheus-community/prometheus -f https://raw.githubusercontent.com/kasbench/globeco-observability/v1.1.5/k8s_aws/values_prometheus.yaml -n monitoring
```
**Note**: the URL of the Prometheus values file above should be stored in configuration and easily changed.

- Install the OpenTelemetry Collector with the following (or equivalent):
```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
# Wait for it to be ready before installing the operator
kubectl wait --for=condition=Available deployment --all -n cert-manager --timeout=360s
kubectl apply -f https://github.com/open-telemetry/opentelemetry-operator/releases/latest/download/opentelemetry-operator.yaml
kubectl wait --for=condition=Available deployment/opentelemetry-operator-controller-manager -n opentelemetry-operator-system --timeout=360s
```



