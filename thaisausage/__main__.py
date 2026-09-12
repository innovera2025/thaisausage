import argparse
import threading
import time

from .api import create_server
from .config import load_config
from .connectors import ERPConnector, VRPConnector
from .sqlserver import SQLServerConnector
from .service import IntegrationService


def main():
    parser = argparse.ArgumentParser(description="Thaisausage ERP integration API")
    parser.add_argument("--config", default="config/local.json")
    args = parser.parse_args()
    config = load_config(args.config)
    service = IntegrationService(config["database"], config["dry_run"],
                                 VRPConnector(config["vrp"]), ERPConnector(config["erp"]))
    server = create_server(config, service)
    scheduler_stop = threading.Event()
    sqlserver = SQLServerConnector(config.get("sqlserver", {}))
    def sweep_loop():
        interval = int(config.get("sync", {}).get("interval_seconds", 60))
        while not scheduler_stop.wait(interval):
            if not config.get("sync", {}).get("enabled", False):
                continue
            try:
                service.sweep_hooks(sqlserver)
            except Exception:
                pass
    scheduler = threading.Thread(target=sweep_loop, name="sql-sweep", daemon=True)
    scheduler.start()
    print("Thaisausage API http://%s:%s dry_run=%s" % (config["host"], server.server_port, config["dry_run"]), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler_stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
