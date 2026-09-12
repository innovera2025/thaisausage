import json
import os
from pathlib import Path


def load_dotenv(path=".env"):
    """Load a small dotenv subset without adding a runtime dependency."""
    dotenv = Path(path)
    if not dotenv.exists():
        return
    for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key or key.startswith("#"):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_config(path):
    load_dotenv()
    with open(path, encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config.get("dry_run"), bool):
        raise ValueError("dry_run must explicitly be true or false")
    if not os.environ.get(config["api_key_env"]):
        raise ValueError("Set the environment variable named by api_key_env")
    if not config["dry_run"] and not os.environ.get(config["vrp"]["token_env"]):
        raise ValueError("Live mode requires the VRP token environment variable")
    Path(config["database"]).parent.mkdir(parents=True, exist_ok=True)
    return config
