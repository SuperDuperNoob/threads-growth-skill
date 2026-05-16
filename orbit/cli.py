import typer
from orbit.commands import setup, sync, status

app = typer.Typer(help="Orbit — content flywheel CLI")
app.add_typer(setup.app, name="setup")
app.add_typer(sync.app, name="sync")
app.add_typer(status.app, name="status")

if __name__ == "__main__":
    app()
