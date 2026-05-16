import typer
from orbit.commands import setup, sync

app = typer.Typer(help="Orbit — content flywheel CLI")
app.add_typer(setup.app, name="setup")
app.add_typer(sync.app, name="sync")

if __name__ == "__main__":
    app()
