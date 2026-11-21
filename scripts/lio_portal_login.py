#!/usr/bin/env python3
"""Sign in to the Lio / Soony Supplier Portal and print the landing page text.

Reads LIO_PROJECT_WEBSITE, LIO_PROJECT_WEBSITE_USERNAME and
LIO_PROJECT_WEBSITE_PASSWORD from the .env file in the repo root.

Requires Playwright:  pip install playwright && playwright install chromium

Usage:  python scripts/lio_portal_login.py [--screenshot PATH]
"""
import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path):
    env = {}
    for line in path.read_text().splitlines():
        match = re.match(r'(\w+)="(.*)"\s*$', line)
        if match:
            env[match.group(1)] = match.group(2)
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--screenshot", help="save a full-page screenshot here")
    args = parser.parse_args()

    env = load_env(ENV_FILE)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(env["LIO_PROJECT_WEBSITE"], wait_until="networkidle")
        page.fill("#name", env["LIO_PROJECT_WEBSITE_USERNAME"])
        page.fill("#password", env["LIO_PROJECT_WEBSITE_PASSWORD"])
        page.click("button[type=submit]")
        try:
            page.wait_for_url("**/app**", timeout=15000)
        except Exception:
            pass
        page.wait_for_load_state("networkidle")

        logged_in = "/login" not in page.url
        print("URL:", page.url)
        print(page.inner_text("body"))
        if args.screenshot:
            page.screenshot(path=args.screenshot, full_page=True)
        browser.close()

    if not logged_in:
        sys.exit("Login failed: still on the sign-in page.")


if __name__ == "__main__":
    main()
