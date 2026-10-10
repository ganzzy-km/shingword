"""Explicit storage initialization/check, separate from HTTP server startup."""
import argparse
import json
import os
from app.storage import StorageBlocked, StorageGuard, initialize_storage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "check"])
    args = parser.parse_args()
    root, identity = os.getenv("GEULBIT_DATA_ROOT"), os.getenv("GEULBIT_VOLUME_ID")
    if not root:
        raise StorageBlocked("DATA_ROOT_REQUIRED")
    if args.command == "init":
        initialize_storage(root, identity)
    else:
        StorageGuard(root, identity).check(startup=True)
    print(json.dumps({"status": "PASS", "operation": args.command, "schema": "0001_initial"}))


if __name__ == "__main__":
    try:
        main()
    except StorageBlocked as error:
        print(json.dumps({"status": "BLOCKED", "code": error.code}))
        raise SystemExit(1)
