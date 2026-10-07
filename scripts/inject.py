#!/usr/bin/env python3
"""Manual failure injection:  python scripts/inject.py payment-service latency [intensity]   |   python scripts/inject.py reset"""
import json, sys, urllib.request

API = "http://localhost:8080"
def post(path, body=None):
    req = urllib.request.Request(API + path, method="POST", data=json.dumps(body or {}).encode(), headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read())

if sys.argv[1:] == ["reset"]:
    print(post("/api/chaos/reset"))
elif len(sys.argv) >= 3:
    body = {"service": sys.argv[1], "type": sys.argv[2]}
    if len(sys.argv) > 3:
        body["intensity"] = float(sys.argv[3])
    print(post("/api/chaos", body))
else:
    sys.exit(__doc__)
