import argparse
import logging
import threading

from .api import create_server
from .config import load_config
from .connectors import ERPConnector, VRPConnector
from .do_writer import DOWriter
from .sqlserver import SQLServerConnector
from .service import IntegrationService


logger = logging.getLogger(__name__)


def run_sweep_cycle(config, service, sqlserver):
    """Run one scheduled cycle, or nothing at all while sync is disabled.

    Only per-state counts are logged: never an order, a payload or a driver message.
    """
    if not config.get("sync", {}).get("enabled", False):
        return None
    results = service.sweep_approved_orders(sqlserver)
    summary = {}
    for result in results:
        summary[result["state"]] = summary.get(result["state"], 0) + 1
    logger.info("scheduled sweep cycle finished: orders=%d %s", len(results), sorted(summary.items()))
    return results


def main():
    parser = argparse.ArgumentParser(description="Thaisausage ERP integration API")
    parser.add_argument("--config", default="config/local.json")
    args = parser.parse_args()
    config = load_config(args.config)
    service = IntegrationService(config["database"], config["dry_run"],
                                 VRPConnector(config["vrp"]), ERPConnector(config["erp"]))
    scheduler_stop = threading.Event()
    sqlserver = SQLServerConnector(config.get("sqlserver", {}))
    do_writer = DOWriter(config.get("do_write", {}))
    server = create_server(config, service, do_writer=do_writer)
    def sweep_loop():
        interval = int(config.get("sync", {}).get("interval_seconds", 60))
        while not scheduler_stop.is_set():
            scheduler_stop.wait(interval)
            if scheduler_stop.is_set():
                break
            try:
                run_sweep_cycle(config, service, sqlserver)
            except Exception as error:
                # Driver messages can carry connection details, so only the class name is logged.
                logger.error("scheduled SO sweep cycle failed: %s", type(error).__name__)
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
