"""Network as Code — CLI.

Subcommands:
  build   render templates + fragments tot configs/generated/<device>-baseline.xml
  list    toon devices uit inventory.db                                  [Quanah]
  show    device-detail + laatste deploy-status                          [Quanah]
  run     haal baseline van GitHub, voer NETCONF-deploy uit              [Quanah]
  log     chronologisch overzicht van deploys                            [Quanah]
"""
from __future__ import annotations
import click

from . import builder


@click.group(help="Network as Code — IOS-XE baseline-deployment via NETCONF.")
def cli():
    pass


@cli.command(name="build")
@click.argument("device")
def cmd_build(device):
    """Render baseline-XML voor DEVICE (bv. R1)."""
    path = builder.build(device)
    click.echo(f"Baseline geschreven naar {path.relative_to(builder.ROOT)}")


@cli.command(name="list")
def cmd_list():
    """Toon alle devices uit inventory.db."""
    raise click.ClickException("Nog te implementeren door Quanah.")


@cli.command(name="show")
@click.argument("device")
def cmd_show(device):
    """Toon device-detail + laatste deploy-status."""
    raise click.ClickException("Nog te implementeren door Quanah.")


@cli.command(name="run")
@click.argument("device")
def cmd_run(device):
    """Voer NETCONF-deploy uit op DEVICE."""
    raise click.ClickException("Nog te implementeren door Quanah.")


@cli.command(name="log")
@click.argument("device")
def cmd_log(device):
    """Toon deploy-historie voor DEVICE."""
    raise click.ClickException("Nog te implementeren door Quanah.")


if __name__ == "__main__":
    cli()
