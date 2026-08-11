# Using and Hooking MLflow into the AmSC MLflow Server with ROSE aaS

Use the following imports to connect MLflow to the AmSC MLflow server.

## 1. Add the Patch

Place this patch at the top of your code and invoke it as well (already provided in the amsc.py):

```python
# Inject X-Api-Key into all MLflow REST calls
def enable_amsc_x_api_key():

    import mlflow.utils.rest_utils as rest_utils
    api_key = os.environ["AM_SC_API_KEY"]
    if api_key:
        _orig = rest_utils.http_request
        def patched(host_creds, endpoint, method, *args, **kwargs):
            h = dict(kwargs.get("headers") or kwargs.get("extra_headers") or {})
            h["X-Api-Key"] = api_key
            kwargs["headers" if "headers" in kwargs else "extra_headers"] = h
            return _orig(host_creds, endpoint, method, *args, **kwargs)
        rest_utils.http_request = patched


enable_amsc_x_api_key()  
```

---

## 2. Export Environment Variables

Use this guide to obtain your API key:

* [Get your API key here](https://docs.google.com/document/d/1tLFdhAa6ymWV-LqHMWkwNzjmiX7klSmMkUNgAWUgGMU/edit?usp=sharing)

Then export the following environment variables:

```bash
export AM_SC_API_KEY="YOUR_AMSC_API_KEY"
export MLFLOW_TRACKING_URI="https://mlflow.american-science-cloud.org"
```

---

## 3. Run Your Example

Now run your example above and verify that the runs appear in the MLflow server.
