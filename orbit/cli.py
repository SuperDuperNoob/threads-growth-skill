import typer
from orbit.commands import setup, sync, status, insights, draft
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


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    show_splash()
    if ctx.invoked_subcommand is None:
        # No subcommand — show help after splash
        import typer
        typer.echo(ctx.get_help())


if __name__ == "__main__":
    app()
