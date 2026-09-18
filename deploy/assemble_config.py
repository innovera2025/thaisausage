"""Rebuild the deployed configuration from the two files that are kept in git.

The running configuration lives at config/local.json on the VPS and is not tracked, because it is
edited in place. Its two halves are tracked: config/production.json holds the settings and the
reviewed SQL, config/do-write-template.json holds the ERP DO column mapping. This command puts
them back together, which is what a rebuilt server needs.

    python3 deploy/assemble_config.py                      # writes config/local.json
    python3 deploy/assemble_config.py --check              # compares instead of writing
    python3 deploy/assemble_config.py --enable-do-write    # callback writes DO into ERP itself

Credentials are never involved: both files name environment variables, and the values come from
the deployment environment.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def assemble(enable_do_write=False):
    config = json.loads((ROOT / "config" / "production.json").read_text(encoding="utf-8"))
    template = json.loads((ROOT / "config" / "do-write-template.json").read_text(encoding="utf-8"))
    do_write = template["do_write"]
    # Writing stays off unless it is asked for here, so a restored server cannot start writing
    # into ERP on its own.
    do_write["enabled"] = bool(enable_do_write)
    config["do_write"] = do_write
    return config


def main():
    parser = argparse.ArgumentParser(description="Rebuild config/local.json from the tracked halves")
    parser.add_argument("--out", default=str(ROOT / "config" / "local.json"))
    parser.add_argument("--check", action="store_true", help="report differences instead of writing")
    parser.add_argument("--enable-do-write", action="store_true",
                        help="let the eVRP callback write DO into ERP without an operator")
    args = parser.parse_args()

    config = assemble(args.enable_do_write)
    out = Path(args.out)

    if args.check:
        if not out.exists():
            raise SystemExit("%s ยังไม่มี — รันโดยไม่ใส่ --check เพื่อสร้าง" % out)
        current = json.loads(out.read_text(encoding="utf-8"))
        if current == config:
            print("ตรงกับที่เก็บไว้ใน git ทุกค่า")
            return
        keys = sorted(set(current) | set(config))
        for key in keys:
            if current.get(key) != config.get(key):
                print("ต่างกันที่:", key)
        raise SystemExit("config ที่ใช้อยู่ไม่ตรงกับ git — ตรวจก่อนว่าฝั่งไหนถูก")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("เขียนแล้ว:", out)
    print("header %d คอลัมน์ · detail %d คอลัมน์ · เขียน DO อัตโนมัติ: %s"
          % (len(config["do_write"]["header_columns"]), len(config["do_write"]["detail_columns"]),
             "เปิด" if config["do_write"]["enabled"] else "ปิด"))


if __name__ == "__main__":
    main()
