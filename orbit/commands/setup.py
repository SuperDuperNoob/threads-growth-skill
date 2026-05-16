from __future__ import annotations
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from orbit.config import Config

app = typer.Typer(help="Connect your platforms")
console = Console()

PLATFORMS = ["LinkedIn", "YouTube", "Threads", "Facebook", "Substack"]


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
        console.print("You need a LinkedIn app with r_liteprofile and w_member_social scopes.")
        console.print("Create one at: https://www.linkedin.com/developers/apps")
        client_id = Prompt.ask("  Client ID")
        client_secret = Prompt.ask("  Client Secret", password=True)
        token = Prompt.ask("  Access Token (from OAuth flow)")
        author_urn = Prompt.ask("  Author URN (e.g. urn:li:person:abc123)")
        cfg.set("linkedin.client_id", client_id)
        cfg.set("linkedin.client_secret", client_secret)
        cfg.set("linkedin.access_token", token)
        cfg.set("linkedin.author_urn", author_urn)
        console.print("  [green]✓ LinkedIn configured[/green]")

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
        token = Prompt.ask("  Access Token")
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
