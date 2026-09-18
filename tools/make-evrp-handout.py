"""Build the copy of the eVRP callback spec that carries the real API key.

The spec in docs/ keeps a placeholder so it is safe to commit. This script produces a separate
handout with the key filled in, for sending to the eVRP team. The output file name matches a
.gitignore rule, so the key cannot be committed by accident.

    python3 tools/make-evrp-handout.py                 # asks for the key without echoing it
    THAISAUSAGE_API_KEY=... python3 tools/make-evrp-handout.py --out ~/Desktop

Rendering the PDF needs the same tools the other documents use: ruby for docs/render_pdf.rb and
Google Chrome for the print step. Without them the markdown is still written.
"""

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "eVRP_DO_Callback_Spec.md"
PLACEHOLDER = "<THAISAUSAGE_API_KEY>"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def api_key():
    key = os.environ.get("THAISAUSAGE_API_KEY")
    if not key:
        key = getpass.getpass("THAISAUSAGE_API_KEY (ไม่แสดงบนจอ): ").strip()
    if not key:
        raise SystemExit("ไม่ได้ใส่ key — ยกเลิก")
    if key.upper().startswith(("YOUR", "REPLACE", "XXX")):
        raise SystemExit("ค่าที่ใส่ดูเหมือน placeholder — ยกเลิก")
    return key


def render_pdf(markdown_path, pdf_path):
    html = markdown_path.with_suffix(".html")
    try:
        subprocess.run(["ruby", str(ROOT / "docs" / "render_pdf.rb"),
                        str(markdown_path), str(html)], check=True)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--print-to-pdf=%s" % pdf_path, "file://%s" % html],
                       check=True, capture_output=True)
        html.unlink(missing_ok=True)
        return True
    except (OSError, subprocess.CalledProcessError) as error:
        print("ข้ามการสร้าง PDF:", type(error).__name__, file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Build the eVRP handout carrying the API key")
    parser.add_argument("--out", default=str(Path.home() / "Desktop"))
    args = parser.parse_args()

    text = SOURCE.read_text(encoding="utf-8")
    if PLACEHOLDER not in text:
        raise SystemExit("ไม่พบ %s ใน %s" % (PLACEHOLDER, SOURCE))
    filled = text.replace(PLACEHOLDER, api_key())

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = out_dir / "eVRP_DO_Callback_Spec_with_key.md"
    markdown.write_text(filled, encoding="utf-8")
    print("เขียนแล้ว:", markdown)

    pdf = out_dir / "eVRP_DO_Callback_Spec_with_key.pdf"
    if render_pdf(markdown, pdf):
        print("เขียนแล้ว:", pdf)
    print("ไฟล์นี้มี API key จริง — ส่งให้ทีม eVRP ทางช่องทางที่ปลอดภัย และอย่า commit")


if __name__ == "__main__":
    main()
