import argparse

from .api import create_server
from .config import load_config
from .connectors import ERPConnector, VRPConnector
from .service import IntegrationService


def main():
    parser = argparse.ArgumentParser(description="Thaisausage ERP integration API")
    parser.add_argument("--config", default="config/local.json")
    args = parser.parse_args()
    config = load_config(args.config)
    service = IntegrationService(config["database"], config["dry_run"],
                                 VRPConnector(config["vrp"]), ERPConnector(config["erp"]))
    server = create_server(config, service)
    print("Thaisausage API http://%s:%s dry_run=%s" % (config["host"], server.server_port, config["dry_run"]), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
