"""Click CLI entry point for spot2yoto."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from spot2yoto.config import (
    create_default_config,
    get_config_path,
    load_config,
    save_config,
)
from spot2yoto.exceptions import AuthError, ConfigError, Spot2YotoError
from spot2yoto.models import AppConfig, MappingConfig
from spot2yoto.state import StateDB
from spot2yoto.yoto_auth import (
    ensure_valid_token,
    load_tokens,
    poll_for_token,
    request_device_code,
    save_tokens,
)
from spot2yoto.yoto_client import YotoClient


@click.group()
@click.option("--config", "config_path", default=None, help="Path to config file")
@click.option("-v", "--verbose", is_flag=True, help="Verbose output")
@click.option("-q", "--quiet", is_flag=True, help="Suppress non-error output")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None, verbose: bool, quiet: bool) -> None:
    """spot2yoto — Sync Spotify playlists to Yoto MYO cards."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet


# ---- auth group ----


@cli.group()
def auth() -> None:
    """Manage authentication."""


@auth.command("yoto")
@click.pass_context
def auth_yoto(ctx: click.Context) -> None:
    """Authenticate with Yoto via device code flow."""
    try:
        config = load_config(
            Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
        )
    except ConfigError:
        config = AppConfig()

    client_id = config.yoto.client_id
    click.echo("Requesting device code from Yoto...")
    device = request_device_code(client_id)

    click.echo()
    click.echo("Open this URL in your browser to authorize:")
    click.echo(f"  {device['verification_uri_complete']}")
    click.echo()
    click.echo(f"Or go to {device['verification_uri']} and enter code: {device['user_code']}")
    click.echo()
    click.echo("Waiting for authorization...")

    interval = device.get("interval", 5)
    tokens = poll_for_token(client_id, device["device_code"], interval=interval)
    save_tokens(tokens)
    click.echo("Yoto authentication successful! Tokens saved.")


@auth.command("spotify")
@click.pass_context
def auth_spotify(ctx: click.Context) -> None:
    """Configure Spotify API credentials."""
    config_path = Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
    try:
        config = load_config(config_path)
    except ConfigError:
        config = AppConfig()

    client_id = click.prompt("Spotify Client ID", default=config.spotify.client_id or "")
    client_secret = click.prompt("Spotify Client Secret", default=config.spotify.client_secret or "")

    config.spotify.client_id = client_id
    config.spotify.client_secret = client_secret
    save_config(config, config_path)
    click.echo("Spotify credentials saved to config.")


@auth.command("status")
@click.pass_context
def auth_status(ctx: click.Context) -> None:
    """Show authentication status."""
    # Yoto
    tokens = load_tokens()
    if tokens:
        status = "expired" if tokens.is_expired else "valid"
        click.echo(f"Yoto: {status}")
    else:
        click.echo("Yoto: not authenticated")

    # Spotify
    try:
        config = load_config(
            Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
        )
        has_spotify = bool(config.spotify.client_id and config.spotify.client_secret)
        click.echo(f"Spotify: {'configured' if has_spotify else 'not configured'}")
    except ConfigError:
        click.echo("Spotify: no config file")


# ---- cards group ----


@cli.group()
def cards() -> None:
    """Manage Yoto cards."""


@cards.command("list")
@click.pass_context
def cards_list(ctx: click.Context) -> None:
    """List your MYO cards."""
    config = load_config(
        Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
    )
    tokens = ensure_valid_token(config.yoto.client_id)
    with YotoClient(tokens) as yoto:
        card_list = yoto.list_cards()
    if not card_list:
        click.echo("No cards found.")
        return
    for card in card_list:
        click.echo(f"  {card.card_id}  {card.title or '(untitled)'}")


@cards.command("show")
@click.argument("card_id")
@click.pass_context
def cards_show(ctx: click.Context, card_id: str) -> None:
    """Show details for a card."""
    config = load_config(
        Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
    )
    tokens = ensure_valid_token(config.yoto.client_id)
    with YotoClient(tokens) as yoto:
        data = yoto.get_card(card_id)
    # Pretty-print the raw JSON
    import json

    click.echo(json.dumps(data, indent=2))


# ---- config group ----


@cli.group("config")
def config_group() -> None:
    """Manage configuration."""


@config_group.command("init")
@click.pass_context
def config_init(ctx: click.Context) -> None:
    """Create default config file."""
    config_path = Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
    try:
        path = create_default_config(config_path)
        click.echo(f"Config created at {path}")
        click.echo("Edit it to add your Spotify credentials and playlist mappings.")
    except ConfigError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


# ---- sync group ----


@cli.group()
def sync() -> None:
    """Sync playlists to Yoto cards."""


@sync.command("all")
@click.option("--dry-run", is_flag=True, help="Preview changes without syncing")
@click.pass_context
def sync_all_cmd(ctx: click.Context, dry_run: bool) -> None:
    """Sync all configured mappings."""
    config = load_config(
        Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
    )
    tokens = ensure_valid_token(config.yoto.client_id)
    verbose = ctx.obj["verbose"]

    from spot2yoto.sync import sync_all

    with YotoClient(tokens) as yoto, StateDB() as db:
        failures = sync_all(config, yoto, db, dry_run=dry_run, verbose=verbose)

    if failures:
        click.echo(f"\n{failures} mapping(s) failed.", err=True)
        sys.exit(1 if failures < len(config.mappings) else 2)


@sync.command("one")
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Preview changes without syncing")
@click.pass_context
def sync_one_cmd(ctx: click.Context, name: str, dry_run: bool) -> None:
    """Sync a single mapping by name."""
    config = load_config(
        Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
    )
    mapping = next((m for m in config.mappings if m.name == name), None)
    if not mapping:
        click.echo(f"Mapping '{name}' not found in config.", err=True)
        sys.exit(2)

    tokens = ensure_valid_token(config.yoto.client_id)
    verbose = ctx.obj["verbose"]

    from spot2yoto.sync import sync_mapping

    with YotoClient(tokens) as yoto, StateDB() as db:
        try:
            ok = sync_mapping(mapping, config, yoto, db, dry_run=dry_run, verbose=verbose)
            if not ok:
                sys.exit(1)
        except Spot2YotoError as e:
            click.echo(f"ERROR: {e}", err=True)
            sys.exit(2)


# ---- status ----


@cli.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Show sync state for all mappings."""
    with StateDB() as db:
        card_states = db.get_all_card_states()
    if not card_states:
        click.echo("No sync history found.")
        return
    for cs in card_states:
        click.echo(
            f"  {cs['mapping_name']}: "
            f"last synced {cs['last_synced_at']}, "
            f"snapshot {cs['playlist_snapshot_id'][:12]}..."
        )
