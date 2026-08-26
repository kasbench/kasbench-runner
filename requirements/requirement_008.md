# Requirement 8: Save Kubernetes logs to S3

A new API endpoint /logs/{namesapace}/export should save all Kubernetes logs for all pods in the specified namespace to S3 with the `{s3bucket}/{runIdentifier}/{trialIdentifier}/logs/{namespace}/` prefix. It should include any pod with an available log regardless of status.  It should include completed or failed jobs.  It should include all containers with pods.  The name of the file should include the pod name and container (if a multi-container pod).  

Please also update the #README.md with details of this change.