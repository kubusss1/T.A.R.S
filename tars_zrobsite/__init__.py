"""tars_zrobsite – statusy stron klientów ZrobSite i analityka (wtyczka WordPress „TARS Bridge”).

Zakładka panelu TARS „Statusy i analityka”:

    from tars_zrobsite import load_sites, build_dashboard, render_html, render_telegram
    dash = build_dashboard(load_sites(), sort="health")
    html = render_html(dash)
"""
from .client import fetch_analytics, fetch_site, fetch_status
from .dashboard import SORT_MODES, build_dashboard, pct_change
from .render import render_html, render_telegram, render_text
from .sites import SitesConfigError, load_sites

__all__ = [
    "load_sites",
    "SitesConfigError",
    "fetch_status",
    "fetch_analytics",
    "fetch_site",
    "build_dashboard",
    "pct_change",
    "SORT_MODES",
    "render_html",
    "render_telegram",
    "render_text",
]
