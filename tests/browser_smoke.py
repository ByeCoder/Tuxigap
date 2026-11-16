"""Optional real-browser check using synthetic data only. Run with the browser extra."""

from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
from threading import Thread
import secrets

from playwright.sync_api import sync_playwright

from tuxigap.config import Config
from tuxigap.dashboard import make_handler
from tuxigap.demo import populate


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "demo.sqlite3"
        populate(path)
        token = secrets.token_urlsafe(32)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(Config("0:demo", database=str(path)), token)
        )
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1080})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")
                page.locator("#token").fill(token)
                page.locator("#loginForm button").click()
                page.locator("#workspace").wait_for(state="visible")
                page.locator("#stats").filter(has_text="Messages").wait_for()
                output = Path("browser-artifacts")
                output.mkdir(exist_ok=True)
                page.screenshot(path=str(output / "dashboard-en.png"), full_page=True)
                for code, direction in [
                    ("he", "rtl"),
                    ("fa", "rtl"),
                    ("ar", "rtl"),
                    ("zh", "ltr"),
                    ("ru", "ltr"),
                    ("en", "ltr"),
                ]:
                    page.locator("#uiLanguage").select_option(code)
                    page.wait_for_function(
                        "([lang,dir])=>document.documentElement.lang===lang&&document.documentElement.dir===dir",
                        arg=[code, direction],
                    )
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth+2"), (
                    "Mobile layout overflow"
                )
                page.screenshot(path=str(output / "dashboard-mobile.png"), full_page=True)
                page.locator("#logout").click()
                page.locator("#login").wait_for(state="visible")
                assert not errors, errors
                browser.close()
                print(
                    "Browser checks passed: sign-in, analytics, language/RTL switching, mobile width, sign-out."
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
