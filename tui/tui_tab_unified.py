# SPDX-License-Identifier: GPL-2.0-only
"""Unified tab: apply a synchronised scene to keyboard + lightbar."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from client import _real_home
from tui_widgets import Panel, InfoButton


class UnifiedTabMixin:
    """Compose + behaviour for the Unified tab. Mixed into PredatorSenseApp."""

    def _compose_unified(self) -> ComposeResult:
        yield InfoButton(
            "Apply a synchronised scene to BOTH the keyboard and the rear "
            "lightbar in one click. Pick a built-in below, or snapshot the "
            "current state with `venator unified save NAME`."
        )
        yield Static("…", id="uni_status")
        with Panel(title="◆ BUILT-IN SCENES", variant="magenta"):
            # One button per shipped theme. Buttons are added dynamically
            # in _refresh_unified() so user-saved themes show up too.
            with Vertical(id="uni_buttons"):
                yield Static("(loading…)", id="uni_buttons_placeholder")
            with Horizontal(classes="btn-row"):
                yield Button("Refresh list", id="uni_refresh")
                yield Button("Open profiles dir", id="uni_open_dir")

    def _unified_handle_button(self, bid: str, event) -> bool:
        if bid.startswith("uni_apply_"):
            self._apply_unified(bid.removeprefix("uni_apply_"))
        elif bid == "uni_refresh":
            self._refresh_unified()
        elif bid == "uni_open_dir":
            import subprocess
            d = _real_home() / ".config" / "venator" / "designs" / "unified"
            d.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.Popen(["xdg-open", str(d)])
            except Exception:
                self.notify(f"Open: {d}", timeout=4)
        else:
            return False
        return True

    def _refresh_unified(self) -> None:
        """Rebuild the Unified tab's theme buttons by scanning
        ~/.config/venator/designs/unified and the shipped
        directory. Idempotent — safe to call repeatedly."""
        try:
            box = self.query_one("#uni_buttons", Vertical)
        except Exception:
            return
        # Drop everything currently in the container then re-populate.
        box.remove_children()
        themes = self._list_unified_themes()
        if not themes:
            box.mount(Static("[yellow]no unified themes found "
                              "(install missing?)[/]"))
            self.query_one("#uni_status", Static).update(
                "no themes available")
            return
        # Sort: shipped first (in repo order), then user.
        SHIPPED_ORDER = ["red-alert", "ocean", "forest", "sunset",
                         "rainbow", "cyber-mauve", "off"]
        ordered = []
        for n in SHIPPED_ORDER:
            if n in themes:
                ordered.append(n)
        for n in sorted(themes):
            if n not in ordered:
                ordered.append(n)
        # 4 buttons per row.
        row: list[Button] = []
        for name in ordered:
            variant = "primary"
            if name == "off":
                variant = "error"
            elif name == "red-alert":
                variant = "warning"
            elif name not in SHIPPED_ORDER:
                variant = "success"     # user-saved themes stand out
            row.append(Button(name, id=f"uni_apply_{name}",
                              variant=variant))
            if len(row) == 4:
                box.mount(Horizontal(*row, classes="btn-row"))
                row = []
        if row:
            box.mount(Horizontal(*row, classes="btn-row"))
        self.query_one("#uni_status", Static).update(
            f"  {len(themes)} themes available")

    def _list_unified_themes(self) -> dict:
        """Mirror _list_unified() from the CLI."""
        from pathlib import Path as _P
        out: dict[str, _P] = {}
        candidates = [
            _real_home() / ".config" / "venator" / "designs" / "unified",
            _P("/usr/local/share/venator/designs/unified"),
            _P("/usr/share/venator/designs/unified"),
        ]
        # Source-checkout fallback (cli/ next to tui/)
        try:
            here = _P(__file__).resolve().parent
            candidates.append(here.parent / "cli" / "designs" / "unified")
        except Exception:
            pass
        for d in candidates:
            if not d.is_dir():
                continue
            for f in d.glob("*.json"):
                out.setdefault(f.stem, f)
        return out

    def _apply_unified(self, name: str) -> None:
        self._run_cli(lambda: self._client_unified_apply(name))
        self.call_after_refresh(self._refresh_lightbar)

    def _client_unified_apply(self, name: str):
        """Shell out via the main CLI. Mirrors client.py shape."""
        import subprocess
        return subprocess.run(
            [self.client.cli_path, "unified", "apply", name],
            capture_output=True, text=True, timeout=20)
