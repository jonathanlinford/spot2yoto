"""Click CLI entry point for spot2yoto."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from spot2yoto.config import (
    create_default_config,
    load_config,
    save_config,
)
from spot2yoto.exceptions import ConfigError
from spot2yoto.models import AppConfig
from spot2yoto.state import StateDB
from spot2yoto.yoto_auth import (
    ensure_valid_token,
    list_accounts,
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
@click.argument("name", default="default")
@click.pass_context
def auth_yoto(ctx: click.Context, name: str) -> None:
    """Authenticate with Yoto via device code flow.

    NAME is the account name (default: "default"). Use different names
    to authenticate multiple Yoto accounts.
    """
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
    save_tokens(tokens, account_name=name)
    click.echo(f"Yoto account '{name}' authenticated! Tokens saved.")


@auth.command("spotify")
@click.pass_context
def auth_spotify(ctx: click.Context) -> None:
    """Configure Spotify API credentials and authorize."""
    config_path = Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
    try:
        config = load_config(config_path)
    except ConfigError:
        config = AppConfig()

    if not config.spotify.client_id or not config.spotify.client_secret:
        client_id = click.prompt("Spotify Client ID")
        client_secret = click.prompt("Spotify Client Secret")
        config.spotify.client_id = client_id
        config.spotify.client_secret = client_secret
        save_config(config, config_path)

    click.echo("Opening browser for Spotify authorization...")

    from spot2yoto.spotify import get_spotify_client

    sp = get_spotify_client(config.spotify.client_id, config.spotify.client_secret)
    user = sp.me()
    click.echo(f"Spotify authorized as: {user['display_name']}")


@auth.command("status")
@click.pass_context
def auth_status(ctx: click.Context) -> None:
    """Show authentication status."""
    accounts = list_accounts()
    if not accounts:
        click.echo("Yoto: not authenticated")
    else:
        for name in accounts:
            tokens = load_tokens(account_name=name)
            if tokens:
                status = "expired" if tokens.is_expired else "valid"
                click.echo(f"Yoto ({name}): {status}")
            else:
                click.echo(f"Yoto ({name}): invalid token file")

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
@click.option("--account", "account_name", default=None, help="Yoto account name (default: all)")
@click.pass_context
def cards_list(ctx: click.Context, account_name: str | None) -> None:
    """List your MYO cards."""
    config = load_config(
        Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
    )
    accounts = [account_name] if account_name else list_accounts()
    if not accounts:
        click.echo("No Yoto accounts found. Run 'spot2yoto auth yoto' first.")
        return

    for name in accounts:
        if len(accounts) > 1:
            click.echo(f"\n=== Account: {name} ===")
        tokens = ensure_valid_token(config.yoto.client_id, account_name=name)
        with YotoClient(tokens, client_id=config.yoto.client_id, account_name=name) as yoto:
            card_list = yoto.list_myo_cards()
        if not card_list:
            click.echo("No MYO cards found.")
            continue
        for card in card_list:
            spotify = ""
            if "spotify.com/playlist" in card.description:
                spotify = "  [has spotify link]"
            click.echo(f"  {card.card_id}  {card.title or '(untitled)'}{spotify}")


@cards.command("show")
@click.argument("card_id")
@click.option("--account", "account_name", default="default", help="Yoto account name (default: default)")
@click.pass_context
def cards_show(ctx: click.Context, card_id: str, account_name: str) -> None:
    """Show details for a card."""
    config = load_config(
        Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
    )
    tokens = ensure_valid_token(config.yoto.client_id, account_name=account_name)
    with YotoClient(tokens, client_id=config.yoto.client_id, account_name=account_name) as yoto:
        data = yoto.get_card(card_id)
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
        click.echo("Edit it to add your Spotify credentials.")
    except ConfigError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


# ---- sync ----


@cli.command("sync")
@click.option("--account", "account_name", default=None, help="Sync a specific Yoto account (default: all)")
@click.option("--dry-run", is_flag=True, help="Preview changes without syncing")
@click.option("--force", is_flag=True, help="Force re-sync even if playlist snapshot unchanged")
@click.pass_context
def sync_cmd(ctx: click.Context, account_name: str | None, dry_run: bool, force: bool) -> None:
    """Discover MYO cards with Spotify links and sync them."""
    config = load_config(
        Path(ctx.obj["config_path"]) if ctx.obj["config_path"] else None
    )
    verbose = ctx.obj["verbose"]

    from spot2yoto.sync import sync_all

    accounts = [account_name] if account_name else list_accounts()
    if not accounts:
        click.echo("No Yoto accounts found. Run 'spot2yoto auth yoto' first.")
        sys.exit(1)

    total_all = 0
    failures_all = 0
    for name in accounts:
        if len(accounts) > 1:
            click.echo(f"\n=== Account: {name} ===")
        tokens = ensure_valid_token(config.yoto.client_id, account_name=name)
        with YotoClient(tokens, client_id=config.yoto.client_id, account_name=name) as yoto, StateDB() as db:
            total, failures = sync_all(config, yoto, db, dry_run=dry_run, verbose=verbose, force=force)
            total_all += total
            failures_all += failures

    if total_all == 0:
        sys.exit(0)
    if failures_all:
        click.echo(f"\n{failures_all}/{total_all} mapping(s) failed.", err=True)
        sys.exit(1 if failures_all < total_all else 2)


# ---- status ----


@cli.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Show sync state."""
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
