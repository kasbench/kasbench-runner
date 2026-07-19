# Requirement 6: Switch to the GlobeCo Helm Repo

## Introduction

The current method of deploying GlobeCo by pulling individual manifests from GitHub has turned out to be unstable.  Repeated high-frequency calls periodically trigger GitHub's anti-scraping technology.  Instead, we will deploy GlobeCo using Helm, which only requires a single download per benchmark run.  This document lists the changes required to switch from individual manifest downloads to Helm.

## Requirements

- In the `initialize` function in `initialize.py`, replace step 4 (" Step 4: Manifest install (Req 5.1–5.13)") with the following (or an equivalent):

```bash
helm repo add globeco-repo https://kasbench.github.io/globeco-helm
helm repo update
helm install globeco globeco-repo/globeco --namespace globeco --create-namespace --wait
```

- For now, we will leave the `shutdown` function in `shutdown.py` unchanged.  In the future, we may replace it with Helm uninstall.  In testing thus far, Helm's uninstall has not freed up PVCs, which is the main goal of the shutdown API.