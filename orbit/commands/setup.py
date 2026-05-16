from __future__ import annotations
import threading
import webbrowser
import urllib.parse
import httpx
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from orbit.config import Config

app = typer.Typer(help="Connect your platforms")
console = Console()

PLATFORMS = ["LinkedIn", "YouTube", "Threads", "Facebook", "Substack"]
_CALLBACK_PORT = 8080
_REDIRECT_URI = f"http://localhost:{_CALLBACK_PORT}"


@app.callback(invoke_without_command=True)
def setup(
    platform: Optional[str] = typer.Option(
        None, "--platform", "-p", help="Re-configure one platform"
    ),
) -> None:
    cfg = Config()

    if platform:
        _setup_platform(cfg, platform.lower())
        return

    console.print("\n[bold]Welcome to Orbit.[/bold] Let's connect your platforms.\n")

    choices = []
    for p in PLATFORMS:
        if Confirm.ask(f"  Connect [cyan]{p}[/cyan]?", default=True):
            choices.append(p.lower())

    console.print()
    for p in choices:
        _setup_platform(cfg, p)

    console.print(
        "\n[bold green]Setup complete.[/bold green] "
        "Run [cyan]orbit sync[/cyan] to pull your existing post history.\n"
    )


def _setup_platform(cfg: Config, platform: str) -> None:
    console.print(f"\n[bold cyan][{platform.upper()}][/bold cyan]")

    if platform == "linkedin":
        _setup_linkedin(cfg)

    elif platform == "youtube":
        console.print("You need a YouTube Data API v3 key from Google Cloud Console.")
        console.print("Create one at: https://console.cloud.google.com/apis/credentials")
        api_key = Prompt.ask("  API Key", password=True)
        channel_id = Prompt.ask("  Channel ID (e.g. UCxxxxxxxxxxxxxxxx)")
        cfg.set("youtube.api_key", api_key)
        cfg.set("youtube.channel_id", channel_id)
        console.print("  [green]✓ YouTube configured[/green]")

    elif platform in ("threads", "facebook"):
        console.print("Threads and Facebook use the Meta Graph API.")
        console.print("Create an app at: https://developers.facebook.com/apps")
        token = Prompt.ask("  Access Token", password=True)
        user_id = Prompt.ask("  User/Page ID")
        cfg.set(f"{platform}.access_token", token)
        cfg.set(f"{platform}.user_id", user_id)
        console.print(f"  [green]✓ {platform.title()} configured[/green]")

    elif platform == "substack":
        console.print("Substack has no public API. Orbit will draft content for manual publish.")
        pub_url = Prompt.ask("  Your publication URL (e.g. https://yourname.substack.com)")
        cfg.set("substack.publication_url", pub_url)
        console.print("  [green]✓ Substack configured (manual publish mode)[/green]")

    else:
        console.print(f"  [yellow]Unknown platform: {platform}[/yellow]")


def _setup_linkedin(cfg: Config) -> None:
    console.print("  You'll need a LinkedIn Developer app (free).")
    console.print("  Create one at: [cyan]https://www.linkedin.com/developers/apps[/cyan]")
    console.print(f"  Add this as an authorized redirect URL in your app: [cyan]{_REDIRECT_URI}[/cyan]\n")

    client_id = Prompt.ask("  Client ID")
    client_secret = Prompt.ask("  Client Secret", password=True)

    # Build OAuth URL
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": _REDIRECT_URI,
        "scope": "openid profile email w_member_social",
    })
    auth_url = f"https://www.linkedin.com/oauth/v2/authorization?{params}"

    # Start local callback server in a thread
    code_holder: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" in qs:
                code_holder["code"] = qs["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:sans-serif;padding:40px'>"
                    b"<h2>&#10003; Authorized!</h2>"
                    b"<p>You can close this tab and return to your terminal.</p>"
                    b"</body></html>"
                )
            elif "error" in qs:
                code_holder["error"] = qs.get("error_description", ["Unknown error"])[0]
                self.send_response(400)
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:sans-serif;padding:40px'>"
                    b"<h2>&#10007; Authorization failed</h2>"
                    b"<p>Check your terminal for details.</p>"
                    b"</body></html>"
                )

        def log_message(self, *args): pass

    server = HTTPServer(("localhost", _CALLBACK_PORT), CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.daemon = True
    thread.start()

    console.print("\n  Opening browser for LinkedIn authorization...")
    webbrowser.open(auth_url)
    console.print("  [dim]Waiting for you to authorize in the browser...[/dim]")

    thread.join(timeout=120)
    server.server_close()

    if "error" in code_holder:
        console.print(f"  [red]✗ Authorization failed: {code_holder['error']}[/red]")
        console.print("  [dim]Check that your app has the correct scopes approved.[/dim]")
        return

    if "code" not in code_holder:
        console.print("  [red]✗ Timed out waiting for authorization.[/red]")
        return

    # Exchange code for token
    console.print("  Exchanging code for access token...")
    try:
        resp = httpx.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code_holder["code"],
                "redirect_uri": _REDIRECT_URI,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if not token:
            console.print(f"  [red]✗ No token in response: {resp.text}[/red]")
            return
    except Exception as e:
        console.print(f"  [red]✗ Token exchange failed: {e}[/red]")
        return

    # Fetch author URN via OpenID userinfo endpoint
    console.print("  Fetching your profile URN...")
    try:
        me = httpx.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        me.raise_for_status()
        person_id = me.json().get("sub", "")
        author_urn = f"urn:li:person:{person_id}"
    except Exception as e:
        console.print(f"  [yellow]⚠ Could not fetch profile URN: {e}[/yellow]")
        author_urn = Prompt.ask("  Enter Author URN manually (e.g. urn:li:person:abc123)")

    cfg.set("linkedin.client_id", client_id)
    cfg.set("linkedin.client_secret", client_secret)
    cfg.set("linkedin.access_token", token)
    cfg.set("linkedin.author_urn", author_urn)

    console.print(f"  [green]✓ LinkedIn configured[/green] ({author_urn})")
