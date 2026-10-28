"""Regenerate the README screenshots (SVG) from the demo. Run: python docs/make_screenshots.py"""
import argparse
import io
import os
import sys
from pathlib import Path

from rich.console import Console

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from homekeeper import cli, db  # noqa: E402

OUT = ROOT / "docs" / "img"


def shot(name, title, fn):
    cli.console = Console(record=True, width=112, file=io.StringIO(), force_terminal=True)
    fn()
    cli.console.save_svg(str(OUT / f"{name}.svg"), title=title)


if __name__ == "__main__":
    os.chdir(ROOT)
    shot("scan", "homekeeper demo  (review queue)", lambda: cli.cmd_demo(None, argparse.Namespace(home="homekeeper_demo")))
    con = db.connect()
    shot("dashboard", "homekeeper", lambda: cli.cmd_dash(con, argparse.Namespace(days=30)))
    shot("show", "homekeeper show 1", lambda: cli.cmd_show(con, argparse.Namespace(product="1", howto=False)))
    shot("net", "homekeeper net report", lambda: cli.cmd_net(con, argparse.Namespace(action="report")))
    shot("warranty", "homekeeper warranty", lambda: cli.cmd_warranty(con, argparse.Namespace()))
    print("saved to", OUT)
