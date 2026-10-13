"""Render ARTEFACT.md -> ARTEFACT.html (same content, styled). Usage: python scripts/build_artefact_html.py"""
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
CSS = """
:root{--bg:#fbfaf7;--fg:#1d2328;--muted:#5b6670;--line:#e2ded6;--accent:#0f5f73;--head:#f1eee8;--good:#1f7a4d;--bad:#a8321f}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#14181b;--fg:#e6e9ec;--muted:#9aa5ae;--line:#2b3238;--accent:#6cc3d5;--head:#1c2226;--good:#5fcf95;--bad:#f08a76}}
:root[data-theme="dark"]{--bg:#14181b;--fg:#e6e9ec;--muted:#9aa5ae;--line:#2b3238;--accent:#6cc3d5;--head:#1c2226;--good:#5fcf95;--bad:#f08a76}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:960px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:1.7rem;margin:.2em 0 .6em;letter-spacing:-.01em}h2{font-size:1.2rem;margin:2em 0 .6em;padding-top:.6em;border-top:1px solid var(--line)}
a{color:var(--accent)}p,li{max-width:75ch}code{font-size:.9em;background:var(--head);padding:1px 5px;border-radius:4px}
.tw{overflow-x:auto;margin:12px 0}table{border-collapse:collapse;width:100%;font-size:.92rem}
th,td{border-bottom:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}th{background:var(--head);font-weight:600}
td:first-child{white-space:nowrap}strong{font-weight:650}
"""


def main() -> None:
    md = (ROOT / "ARTEFACT.md").read_text(encoding="utf-8")
    body = markdown.markdown(md, extensions=["tables"])
    body = body.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    html = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>TCC Agent Artefact</title><style>{CSS}</style></head>'
            f"<body><main>{body}</main></body></html>\n")
    (ROOT / "ARTEFACT.html").write_text(html, encoding="utf-8")
    print("wrote ARTEFACT.html")


if __name__ == "__main__":
    main()
