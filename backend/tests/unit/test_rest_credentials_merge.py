from dte.sources.loader import _merge_rest_credentials


def test_unauthenticated_http_connection_adds_no_auth():
    # An Airflow http connection with no login/password maps to auth={};
    # dlt reads any auth dict as bearer and fails on the missing token.
    cfg = _merge_rest_credentials({"client": {"base_url": "https://x"}},
                                  {"auth": {}, "headers": {"Accept": "a/b"}})
    assert "auth" not in cfg["client"]
    assert cfg["client"]["headers"] == {"Accept": "a/b"}
