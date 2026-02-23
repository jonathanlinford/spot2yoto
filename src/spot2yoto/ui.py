"""Rich-powered UI helpers for spot2yoto CLI output.

All output flows through click.echo() so Click's CliRunner captures it
in tests. In a real TTY, output includes ANSI colors; otherwise plain
text with emoji preserved.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

import click
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# ---- Emoji constants ----

EMOJI = {
    "scan": "\U0001f50d",      # 🔍
    "found": "\U0001f4cb",     # 📋
    "sync": "\U0001f504",      # 🔄
    "check": "\u2705",         # ✅
    "warn": "\u26a0\ufe0f",    # ⚠️
    "error": "\u274c",         # ❌
    "download": "\u2b07\ufe0f",# ⬇️
    "upload": "\u2b06\ufe0f",  # ⬆️
    "skip": "\u23ed\ufe0f",    # ⏭️
    "music": "\U0001f3b5",     # 🎵
    "card": "\U0001f0cf",      # 🃏
    "key": "\U0001f511",       # 🔑
    "art": "\U0001f5bc\ufe0f", # 🖼️
    "config": "\u2699\ufe0f",  # ⚙️
    "party": "\U0001f389",     # 🎉
    "reuse": "\u267b\ufe0f",   # ♻️
    "dry": "\U0001f4dd",       # 📝
    "trash": "\U0001f5d1\ufe0f",# 🗑️
}


def _use_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _render_markup(msg: str) -> str:
    """Render Rich markup to a string — ANSI if TTY, plain text otherwise."""
    if _use_color():
        c = Console(highlight=False, force_terminal=True)
        with c.capture() as capture:
            c.print(msg, end="")
        return capture.get()
    else:
        return Text.from_markup(msg).plain


def _render_rich(renderable: object) -> str:
    """Render a Rich renderable (Table, Panel, Rule) to string."""
    if _use_color():
        c = Console(highlight=False, force_terminal=True)
    else:
        c = Console(highlight=False, force_terminal=False, no_color=True)
    with c.capture() as capture:
        c.print(renderable)
    return capture.get()


# ---- Output helpers ----


def info(msg: str) -> None:
    click.echo(_render_markup(f"[cyan]{msg}[/cyan]"))


def success(msg: str) -> None:
    click.echo(_render_markup(f"{EMOJI['check']} [green]{msg}[/green]"))


def warning(msg: str) -> None:
    click.echo(_render_markup(f"{EMOJI['warn']} [yellow]{msg}[/yellow]"))


def error(msg: str) -> None:
    click.echo(_render_markup(f"{EMOJI['error']} [red]{msg}[/red]"), err=True)


def status(msg: str, emoji_key: str = "") -> None:
    prefix = f"{EMOJI[emoji_key]} " if emoji_key and emoji_key in EMOJI else ""
    click.echo(_render_markup(f"{prefix}{msg}"))


def dim(msg: str) -> None:
    click.echo(_render_markup(f"[dim]{msg}[/dim]"))


# ---- Rich tables ----


def cards_table(cards: list[dict]) -> None:
    """Render a table of MYO cards.

    Each dict should have keys: card_id, title, has_spotify.
    """
    table = Table(title=f"{EMOJI['card']} MYO Cards", show_lines=False)
    table.add_column("Card ID", style="cyan")
    table.add_column("Title")
    table.add_column("Spotify", justify="center")
    for card in cards:
        spotify_col = "\U0001f517" if card.get("has_spotify") else ""
        table.add_row(
            card["card_id"],
            card.get("title") or "(untitled)",
            spotify_col,
        )
    click.echo(_render_rich(table))


def status_table(states: list[dict]) -> None:
    """Render a table of sync states.

    Each dict should have keys: mapping_name, last_synced_at, playlist_snapshot_id.
    """
    table = Table(title=f"{EMOJI['sync']} Sync Status", show_lines=False)
    table.add_column("Card", style="cyan")
    table.add_column("Last Synced")
    table.add_column("Snapshot")
    for cs in states:
        table.add_row(
            cs["mapping_name"],
            cs["last_synced_at"],
            cs["playlist_snapshot_id"][:12] + "...",
        )
    click.echo(_render_rich(table))


def auth_panel(verification_url: str, user_code: str) -> None:
    """Render an auth device code panel."""
    body = (
        f"Open this URL in your browser:\n"
        f"  [bold]{verification_url}[/bold]\n\n"
        f"Or enter code: [bold]{user_code}[/bold]"
    )
    panel = Panel(body, title=f"{EMOJI['key']} Yoto Authorization", expand=False)
    click.echo(_render_rich(panel))


# ---- Sync stats & summary ----


@dataclass
class SyncStats:
    """Accumulates counters during a sync run for the end-of-sync summary."""
    total_mappings: int = 0
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    downloaded: int = 0
    uploaded: int = 0
    reused: int = 0
    removed: int = 0


def sync_summary(stats: SyncStats) -> None:
    """Print an end-of-sync summary report."""
    rule = Rule(title=f"{EMOJI['music']} Sync Complete")
    click.echo(_render_rich(rule))

    if stats.failed == 0 and stats.total_mappings > 0:
        success(f"All {stats.total_mappings} mapping(s) synced successfully")
    elif stats.failed > 0:
        warning(f"{stats.failed}/{stats.total_mappings} mapping(s) failed")

    if stats.skipped:
        status(f"{stats.skipped} already up to date", "skip")
    if stats.downloaded:
        status(f"{stats.downloaded} track(s) downloaded", "download")
    if stats.uploaded:
        status(f"{stats.uploaded} track(s) uploaded", "upload")
    if stats.reused:
        status(f"{stats.reused} track(s) reused from cache", "reuse")
    if stats.removed:
        status(f"{stats.removed} track(s) removed", "trash")
