from __future__ import annotations
import json
import threading
import webbrowser
import urllib.parse
import httpx
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from orbit.config import Config

app = typer.Typer(help="Connect your platforms")
console = Console()

PLATFORMS = ["LinkedIn", "YouTube", "Threads", "Facebook", "Substack", "Twitter", "Anthropic"]
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
        _setup_youtube(cfg)

    elif platform in ("threads", "facebook"):
        console.print("Threads and Facebook use the Meta Graph API.")
        console.print("Get the values at: https://developers.facebook.com/apps  →  App settings  →  Basic")
        console.print(
            "[dim]App ID + Secret let us inspect token expiry and auto-upgrade short-lived → "
            "long-lived (60 days). Token is required; the rest reuse stored values if you press Enter.[/dim]"
        )

        existing_app_id = cfg.get(f"{platform}.app_id") or ""
        existing_app_secret = cfg.get(f"{platform}.app_secret") or ""
        existing_user_id = cfg.get(f"{platform}.user_id") or ""

        token = Prompt.ask("  Access Token", password=True)
        app_id = Prompt.ask("  App ID", default=existing_app_id).strip()
        app_secret = Prompt.ask(
            f"  App Secret {'(press Enter to keep stored value)' if existing_app_secret else ''}",
            default=existing_app_secret,
            password=True,
        ).strip()
        user_id = Prompt.ask("  User/Page ID", default=existing_user_id).strip()

        # Store app credentials BEFORE inspecting — inspect_and_upgrade_token
        # reads them from config to do the long-lived-token exchange.
        if app_id:
            cfg.set(f"{platform}.app_id", app_id)
        if app_secret:
            cfg.set(f"{platform}.app_secret", app_secret)
        if user_id:
            cfg.set(f"{platform}.user_id", user_id)

        # Try to inspect + upgrade the token. Best-effort: if the inspect/exchange
        # fails, fall back to storing the raw token and let the user retry later.
        from orbit.platforms.meta_token import inspect_and_upgrade_token, TokenInfo
        try:
            info: TokenInfo = inspect_and_upgrade_token(token, platform)
            cfg.set(f"{platform}.access_token", info.token)
            if info.expires_at_iso:
                cfg.set(f"{platform}.token_expires_at", info.expires_at_iso)
            else:
                # Wipe any stale expiry from a previous token
                cfg.set(f"{platform}.token_expires_at", None)
            if info.upgraded:
                console.print(f"  [green]✓[/green] Upgraded to long-lived token, valid until {info.expires_at_iso}")
            elif info.expires_at_iso:
                console.print(f"  [green]✓[/green] Token valid until {info.expires_at_iso}")
            else:
                console.print(
                    f"  [green]✓[/green] {platform.title()} configured "
                    f"[dim](expiry unknown — likely app credentials missing or wrong)[/dim]"
                )
        except Exception as e:
            cfg.set(f"{platform}.access_token", token)
            console.print(f"  [green]✓[/green] {platform.title()} configured")
            console.print(f"  [yellow]⚠ Could not check/upgrade token expiry: {e}[/yellow]")

    elif platform == "substack":
        console.print("Substack has no public API. Orbit will draft content for manual publish.")
        pub_url = Prompt.ask("  Your publication URL (e.g. https://yourname.substack.com)")
        cfg.set("substack.publication_url", pub_url)
        console.print("  [green]✓ Substack configured (manual publish mode)[/green]")

    elif platform == "twitter":
        _setup_twitter(cfg)

    elif platform == "anthropic":
        console.print("  You need an Anthropic API key to generate drafts.")
        console.print("  Get one at: [cyan]https://console.anthropic.com/keys[/cyan]")
        key = Prompt.ask("  API Key", password=True)
        cfg.set("anthropic.api_key", key)
        console.print("  [green]✓ Anthropic configured[/green]")

    else:
        console.print(f"  [yellow]Unknown platform: {platform}[/yellow]")


def _setup_youtube(cfg: Config) -> None:
    default_path = str(Path.home() / "Downloads")
    console.print("  Drop your OAuth client secret JSON file from Google Cloud Console.")
    console.print("  Create one at: [cyan]https://console.cloud.google.com/apis/credentials[/cyan]")
    secret_path = Prompt.ask(
        "  Path to client_secret_*.json",
        default=str(Path.home() / "Downloads" / "client_secret.json"),
    )
    secret_file = Path(secret_path).expanduser()
    if not secret_file.exists():
        console.print(f"  [red]✗ File not found: {secret_file}[/red]")
        return

    try:
        raw = json.loads(secret_file.read_text())
        creds = raw.get("installed") or raw.get("web")
        if not creds:
            console.print("  [red]✗ Unexpected JSON format — expected 'installed' or 'web' key.[/red]")
            return
        client_id = creds["client_id"]
        client_secret = creds["client_secret"]
    except Exception as e:
        console.print(f"  [red]✗ Could not parse JSON: {e}[/red]")
        return

    # Build OAuth URL — request both Data API + Analytics API scopes so we can
    # both list videos and pull traffic-source / engagement reports.
    scope = (
        "https://www.googleapis.com/auth/youtube.readonly "
        "https://www.googleapis.com/auth/yt-analytics.readonly"
    )
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": _REDIRECT_URI,
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
    })
    auth_url = f"https://accounts.google.com/o/oauth2/auth?{params}"

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
                self.wfile.write(b"<html><body><h2>&#10007; Authorization failed</h2></body></html>")

        def log_message(self, *args): pass

    server = HTTPServer(("localhost", _CALLBACK_PORT), CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.daemon = True
    thread.start()

    console.print("\n  Opening browser for YouTube authorization...")
    webbrowser.open(auth_url)
    console.print("  [dim]Waiting for you to authorize in the browser...[/dim]")

    thread.join(timeout=120)
    server.server_close()

    if "error" in code_holder:
        console.print(f"  [red]✗ Authorization failed: {code_holder['error']}[/red]")
        return

    if "code" not in code_holder:
        console.print("  [red]✗ Timed out waiting for authorization.[/red]")
        return

    # Exchange code for tokens
    console.print("  Exchanging code for access token...")
    try:
        resp = httpx.post(
            "https://oauth2.googleapis.com/token",
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
        token_data = resp.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        if not access_token:
            console.print(f"  [red]✗ No access token in response: {resp.text}[/red]")
            return
    except Exception as e:
        console.print(f"  [red]✗ Token exchange failed: {e}[/red]")
        return

    # Fetch channel ID
    console.print("  Fetching your YouTube channel ID...")
    try:
        me = httpx.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "id,snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        me.raise_for_status()
        items = me.json().get("items", [])
        if not items:
            console.print("  [yellow]⚠ No channel found for this account.[/yellow]")
            channel_id = Prompt.ask("  Enter Channel ID manually (e.g. UCxxxxxxxxxxxxxxxx)")
        else:
            channel_id = items[0]["id"]
            channel_title = items[0].get("snippet", {}).get("title", channel_id)
            console.print(f"  Found channel: [cyan]{channel_title}[/cyan] ({channel_id})")
    except Exception as e:
        console.print(f"  [yellow]⚠ Could not fetch channel: {e}[/yellow]")
        channel_id = Prompt.ask("  Enter Channel ID manually (e.g. UCxxxxxxxxxxxxxxxx)")

    cfg.set("youtube.client_id", client_id)
    cfg.set("youtube.client_secret", client_secret)
    cfg.set("youtube.access_token", access_token)
    if refresh_token:
        cfg.set("youtube.refresh_token", refresh_token)
    cfg.set("youtube.channel_id", channel_id)
    console.print("  [green]✓ YouTube configured[/green]")


def _setup_twitter(cfg: Config) -> None:
    console.print("  Orbit uses your browser cookies to fetch your X bookmarks.")
    console.print("  [bold]Step 1:[/bold] Install the [cyan]'Get cookies.txt LOCALLY'[/cyan] Chrome extension")
    console.print("          Search for it at: [cyan]https://chrome.google.com/webstore[/cyan]")
    console.print("  [bold]Step 2:[/bold] Go to [cyan]https://x.com[/cyan] while logged in")
    console.print("  [bold]Step 3:[/bold] Click the extension icon → [cyan]Export as Netscape format[/cyan]")
    console.print("  [bold]Step 4:[/bold] Save the file somewhere (e.g. ~/Downloads/x_cookies.txt)\n")

    # Auto-detect cookies file in Downloads
    downloads = Path.home() / "Downloads"
    candidates = []
    if downloads.is_dir():
        candidates = sorted(downloads.glob("*cookies*"), key=lambda p: p.stat().st_mtime, reverse=True)

    if candidates:
        cookies_file = candidates[0]
        console.print(f"  [green]Auto-detected:[/green] {cookies_file}")
        console.print("  [dim]Press Enter to use it, or type a different path.[/dim]")
        override = Prompt.ask("  Path", default="").strip()
        if override:
            cookies_file = Path(override).expanduser()
    else:
        raw = Prompt.ask("  Path to cookies.txt file", default="~/Downloads/x_cookies.txt")
        cookies_file = Path(raw).expanduser()

    if not cookies_file.exists():
        console.print(f"  [red]✗ File not found: {cookies_file}[/red]")
        return

    # Validate required cookies are present
    required = {"ct0", "auth_token"}
    found = set()
    for line in cookies_file.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.strip().split("\t")
        if len(parts) >= 7:
            found.add(parts[5])
    missing = required - found
    if missing:
        console.print(f"  [red]✗ Cookie file is missing required fields: {', '.join(sorted(missing))}[/red]")
        console.print("  [dim]Export fresh cookies from x.com and try again.[/dim]")
        return

    cfg.set("twitter.cookies_path", str(cookies_file))
    console.print("  [green]✓ Twitter/X configured (bookmark sync enabled)[/green]")


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
