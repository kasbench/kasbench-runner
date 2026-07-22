# Requirement 7: Collect Roundtrip Data

The purpose of this requirement is to add a new endpoint to collect and export roundtrip data from a benchmark run.

## POST /roundtrip/export

The following is example code from a different application.  This application needs to perform the same function.  It should take the same approach to executing the psql query shown in the example.  However, the results should be stored to S3 at `{s3bucket}/{runIdentifier}/{trialIdentifier}/roundtrip/trade_orders.json`

```python
def get_roundtrip_trade_results(bucket_name, trial, filename=None):
    command = 'kubectl exec svc/globeco-debug-tools -- psql -h globeco-trade-service-postgresql -U postgres -tAc "select json_agg(t) from (select sum(quantity_ordered) quantity_ordered, sum(quantity_placed) quantity_placed, sum(quantity_filled) quantity_filled from execution) t;"'
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    output = result.stdout.strip()
    print(f"Roundtrip trade results: {output}")
    if result.returncode != 0:
        print(f"Error executing command: {result.stderr}")
        raise RuntimeError(f"Command failed with return code {result.returncode}")  
    if not output.startswith("[") or not output.endswith("]"):
        raise ValueError(f"Unexpected output format: {output}")
    # sample output: [{"quantity_ordered":30210.00000000,"quantity_placed":30210.00000000,"quantity_filled":30165.00000000}]
    print(f"Saving {bucket_name}/{filename}")
    with tempfile.NamedTemporaryFile(mode='w+', delete=True) as tmp:
        tmp.write(output)
        tmp.flush()
        minio_client.fput_object(bucket_name, filename, tmp.name)
```