import typer
from rich.console import Console
from rich.prompt import Prompt

from orbit.commands import discover, draft, drafts, insights, interview, linkedin_import, repurpose, setup, sync, status, youtube
from orbit.commands.splash import show_splash

app = typer.Typer(
    help="Orbit — content flywheel CLI",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(setup.app, name="setup")
app.add_typer(sync.app, name="sync")
app.add_typer(status.app, name="status")
app.add_typer(insights.app, name="insights")
app.add_typer(draft.app, name="draft")
app.add_typer(draft.app, name="threads")  # alias: `orbit threads` is the same as `orbit draft`
app.add_typer(drafts.app, name="drafts")  # `orbit drafts list/show/publish`
app.add_typer(discover.app, name="discover")  # `orbit discover` finds candidates from your For You feed
app.add_typer(interview.app, name="interview")  # `orbit interview` turns your experiments into drafts
app.add_typer(repurpose.app, name="repurpose")  # `orbit repurpose` turns YouTube videos into drafts
app.add_typer(youtube.app, name="youtube")  # `orbit youtube new/list/show/check` — Jeff-Sue-style checklist
app.add_typer(linkedin_import.app, name="linkedin")  # `orbit linkedin import analytics/shares`

console = Console()

_MENU = [
    ("draft",     "✍  Generate Threads drafts from your X bookmarks"),
    ("discover",  "🔭  Find AI content from your For You feed"),
    ("interview", "🎙  Turn your own experiments + teaching into drafts"),
    ("repurpose", "📼  Turn your YouTube videos into Threads drafts"),
    ("youtube",   "🎬  Plan a new YouTube video with the checklist"),
    ("sync",      "🔄  Sync latest metrics from connected platforms"),
    ("insights",  "📊  Analyze your content performance"),
    ("status",    "🔌  Show platform connection status"),
    ("setup",     "⚙  Connect a platform"),
]


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    show_splash()
    if ctx.invoked_subcommand is not None:
        return

    # Interactive menu
    console.print("\n[bold]What do you want to do?[/bold]\n")
    for i, (_, label) in enumerate(_MENU, 1):
        console.print(f"  [{i}] {label}")
    console.print()

    raw = Prompt.ask("Choose", default="1")
    try:
        idx = int(raw.strip()) - 1
        if not (0 <= idx < len(_MENU)):
            raise ValueError
    except ValueError:
        console.print("[yellow]Invalid choice.[/yellow]")
        raise typer.Exit(1)

    command = _MENU[idx][0]

    # Re-invoke through the Typer app so Option/Argument defaults get resolved
    # properly. Calling the @app.callback functions directly leaves typer.Option
    # sentinels (OptionInfo) in place of real values, which then explode when
    # passed to e.g. SQLite (ProgrammingError: type 'OptionInfo' is not supported).
    if command == "setup":
        platform = Prompt.ask("  Which platform? (linkedin/youtube/threads/twitter/anthropic)")
        argv = ["setup", "--platform", platform.lower()]
    elif command == "youtube":
        # youtube is a sub-app with no default; ask which action
        console.print("  [1] Start a new video checklist")
        console.print("  [2] List existing checklists")
        console.print("  [3] Show a specific checklist")
        sub = Prompt.ask("  Choose", default="1").strip()
        if sub == "2":
            argv = ["youtube", "list"]
        elif sub == "3":
            cid = Prompt.ask("  Checklist id")
            argv = ["youtube", "show", cid.strip()]
        else:
            title = Prompt.ask("  Working title for the video")
            argv = ["youtube", "new", title.strip()]
    else:
        argv = [command]

    # standalone_mode=False prevents Click from calling sys.exit on completion,
    # so the menu loop returns cleanly.
    app(argv, standalone_mode=False)


if __name__ == "__main__":
    app()
