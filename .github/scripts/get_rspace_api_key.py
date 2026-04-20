import os
import re
import sys
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

RSPACE_URL = os.getenv("RSPACE_URL")
RSPACE_USERNAME = os.getenv("RSPACE_USERNAME")
RSPACE_PASSWORD = os.getenv("RSPACE_PASSWORD")


def main():
    if not RSPACE_URL or not RSPACE_USERNAME or not RSPACE_PASSWORD:
        raise RuntimeError(
            "Missing required environment variables: RSPACE_URL, RSPACE_USERNAME, RSPACE_PASSWORD"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print("Step 1: Navigating to RSpace...", file=sys.stderr)
        page.goto(RSPACE_URL, wait_until="networkidle")

        print("Step 2: Logging in...", file=sys.stderr)
        page.get_by_role("textbox", name="User").fill(RSPACE_USERNAME)
        page.get_by_role("textbox", name="Password").fill(RSPACE_PASSWORD)
        page.get_by_role("button", name="Log in").click()
        
        # Wait for login to complete and redirect
        page.wait_for_load_state("networkidle")
        print("Step 3: Login successful, navigating to My RSpace...", file=sys.stderr)

        # Step 2: Navigate to Profile → Manage API Key
        page.get_by_role("link", name="My RSpace").click()
        page.wait_for_load_state("networkidle")
        
        print("Step 4: Looking for Generate/Regenerate key button...", file=sys.stderr)
        # Wait for the button to appear (either "Generate key" or "Regenerate key")
        page.wait_for_selector("a#apiKeyRegenerateBtn", timeout=10000)
        page.click("a#apiKeyRegenerateBtn")

        print("Step 5: Confirming password...", file=sys.stderr)
        dialog = page.get_by_role("dialog", name="Confirm password")
        dialog.wait_for()
        dialog.get_by_role("textbox", name="Please confirm your password").fill(RSPACE_PASSWORD)
        dialog.get_by_role("button", name="OK").click()
        dialog.wait_for(state="detached")

        
        print("Step 6: Waiting for key to be displayed...", file=sys.stderr)
        page.wait_for_load_state("networkidle")
        
        # Wait for the key to appear in the page
        page.wait_for_selector("#apiKeyInfo")
        
        # Extract the key from the displayed text
        # Format: "Key: {32-char-string}"
        key_locator = page.locator("div.api-menu__key")
        if key_locator.count() == 0:
            raise RuntimeError("Selector 'div.api-menu__key' not found on page — page structure may have changed")

        info_text = key_locator.inner_text()
        print(f"Key element text length: {len(info_text)}", file=sys.stderr)

        match = re.search(r"Key:\s*([A-Za-z0-9]{32})", info_text)
        if not match:
            raise RuntimeError(f"API key regex did not match for selector 'div.api-menu__key' — text length {len(info_text)}")

        api_key = match.group(1)
        print("Successfully extracted API key", file=sys.stderr)

        # Write to GITHUB_OUTPUT so the key never touches stdout/stderr.
        # Writing to GITHUB_OUTPUT is the standard GitHub Actions mechanism for passing
        # step outputs; the file is ephemeral and runner-scoped.
        github_output = os.getenv("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a") as f:
                f.write(f"rspace_api_key={api_key}\n")
        else:
            raise RuntimeError("GITHUB_OUTPUT is not set; refusing to emit API key to stdout.")

        browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error generating API key: {exc}", file=sys.stderr)
        sys.exit(1)