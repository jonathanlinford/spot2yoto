"""Click CLI entry point for spot2yoto."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from spot2yoto import ui
from spot2yoto.config import (
    create_default_config,
    load_config,
    save_config,
)
from spot2yoto.exceptions import ConfigError, Spot2YotoError
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


def _resolve_config_path(ctx: click.Context) -> Path | None:
    raw = ctx.obj.get("config_path")
    return Path(raw) if raw else None


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
            _resolve_config_path(ctx)
        )
    except ConfigError:
        config = AppConfig()

    client_id = config.yoto.client_id
    ui.status("Requesting device code from Yoto...", "key")
    device = request_device_code(client_id)

    ui.auth_panel(
        device["verification_uri_complete"],
        device["user_code"],
    )

    ui.info("Waiting for authorization...")

    interval = device.get("interval", 5)
    tokens = poll_for_token(client_id, device["device_code"], interval=interval)
    save_tokens(tokens, account_name=name)
    ui.success(f"Yoto account '{name}' authenticated! Tokens saved.")


@auth.command("spotify")
@click.pass_context
def auth_spotify(ctx: click.Context) -> None:
    """Configure Spotify API credentials and authorize."""
    config_path = _resolve_config_path(ctx)
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

    ui.info("Spotify will display an authorization URL below.")
    ui.info("Open it in your browser, authorize, then paste the redirect URL back here.")

    from spot2yoto.spotify import get_spotify_client

    sp = get_spotify_client(config.spotify.client_id, config.spotify.client_secret)
    user = sp.me()
    ui.success(f"Spotify authorized as: {user['display_name']}")


@auth.command("clear")
@click.option("--service", type=click.Choice(["spotify", "yoto"]), required=True, help="Service to clear auth for")
@click.option("--account", "account_name", default="default", help="Yoto account name (for yoto service)")
@click.pass_context
def auth_clear(ctx: click.Context, service: str, account_name: str) -> None:
    """Clear saved authentication tokens."""
    if service == "spotify":
        from spot2yoto.spotify import CACHE_PATH

        if CACHE_PATH.exists():
            CACHE_PATH.unlink()
            ui.success("Spotify auth cache cleared.")
        else:
            ui.info("No Spotify auth cache found.")
    elif service == "yoto":
        from spot2yoto.yoto_auth import _token_path

        path = _token_path(account_name)
        if path.exists():
            path.unlink()
            ui.success(f"Yoto tokens cleared for account '{account_name}'.")
        else:
            ui.info(f"No Yoto tokens found for account '{account_name}'.")


@auth.command("status")
@click.pass_context
def auth_status(ctx: click.Context) -> None:
    """Show authentication status."""
    accounts = list_accounts()
    if not accounts:
        ui.info("Yoto: not authenticated")
    else:
        for name in accounts:
            tokens = load_tokens(account_name=name)
            if tokens:
                status_str = "expired" if tokens.is_expired else "valid"
                if tokens.is_expired:
                    ui.warning(f"Yoto ({name}): {status_str}")
                else:
                    ui.success(f"Yoto ({name}): {status_str}")
            else:
                ui.error(f"Yoto ({name}): invalid token file")

    try:
        config = load_config(
            _resolve_config_path(ctx)
        )
        has_spotify = bool(config.spotify.client_id and config.spotify.client_secret)
        if has_spotify:
            ui.success(f"Spotify: configured")
        else:
            ui.info(f"Spotify: not configured")
    except ConfigError:
        ui.info("Spotify: no config file")


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
        _resolve_config_path(ctx)
    )
    accounts = [account_name] if account_name else list_accounts()
    if not accounts:
        ui.warning("No Yoto accounts found. Run 'spot2yoto auth yoto' first.")
        return

    for name in accounts:
        if len(accounts) > 1:
            ui.info(f"\n=== Account: {name} ===")
        tokens = ensure_valid_token(config.yoto.client_id, account_name=name)
        with YotoClient(tokens, client_id=config.yoto.client_id, account_name=name) as yoto:
            card_list = yoto.list_myo_cards()
        if not card_list:
            ui.info("No MYO cards found.")
            continue
        table_data = []
        for card in card_list:
            has_spotify = "spotify.com/playlist" in card.description
            table_data.append({
                "card_id": card.card_id,
                "title": card.title or "(untitled)",
                "has_spotify": has_spotify,
            })
        ui.cards_table(table_data)


@cards.command("show")
@click.argument("card_id")
@click.option("--account", "account_name", default="default", help="Yoto account name (default: default)")
@click.pass_context
def cards_show(ctx: click.Context, card_id: str, account_name: str) -> None:
    """Show details for a card."""
    config = load_config(
        _resolve_config_path(ctx)
    )
    tokens = ensure_valid_token(config.yoto.client_id, account_name=account_name)
    with YotoClient(tokens, client_id=config.yoto.client_id, account_name=account_name) as yoto:
        data = yoto.get_card(card_id)
    click.echo(json.dumps(data, indent=2))


# ---- config group ----


@cli.group("config")
def config_group() -> None:
    """Manage configuration."""


@config_group.command("init")
@click.pass_context
def config_init(ctx: click.Context) -> None:
    """Create default config file."""
    config_path = _resolve_config_path(ctx)
    try:
        path = create_default_config(config_path)
        ui.success(f"Config created at {path}")
        ui.info("Edit it to add your Spotify credentials.")
    except ConfigError as e:
        ui.error(str(e))
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
        _resolve_config_path(ctx)
    )
    verbose = ctx.obj["verbose"]

    from spot2yoto.sync import sync_all

    accounts = [account_name] if account_name else list_accounts()
    if not accounts:
        ui.warning("No Yoto accounts found. Run 'spot2yoto auth yoto' first.")
        sys.exit(1)

    total_all = 0
    failures_all = 0
    for name in accounts:
        if len(accounts) > 1:
            ui.info(f"\n=== Account: {name} ===")
        tokens = ensure_valid_token(config.yoto.client_id, account_name=name)
        try:
            with YotoClient(tokens, client_id=config.yoto.client_id, account_name=name) as yoto, StateDB() as db:
                total, failures = sync_all(config, yoto, db, dry_run=dry_run, verbose=verbose, force=force)
                total_all += total
                failures_all += failures
        except Spot2YotoError as e:
            ui.error(str(e))
            sys.exit(1)

    if total_all == 0:
        sys.exit(0)
    if failures_all:
        ui.error(f"\n{failures_all}/{total_all} mapping(s) failed.")
        sys.exit(1 if failures_all < total_all else 2)


# ---- status ----


@cli.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Show sync state."""
    with StateDB() as db:
        card_states = db.get_all_card_states()
    if not card_states:
        ui.info("No sync history found.")
        return
    ui.status_table(card_states)
