#!/usr/bin/env python3
"""Agente Iowa Hawkeyes: busca os próximos jogos (futebol americano e basquete
masculino/feminino), descobre o canal de TV/streaming nos EUA e envia um e-mail
com a identidade visual do time (preto e dourado + logo Tigerhawk).

Fonte de dados: API pública do ESPN (sem chave). Só usa a biblioteca padrão.

Variáveis de ambiente:
  SMTP_USER       conta Gmail que envia (ex.: geraldoschuetze@gmail.com)
  SMTP_PASSWORD   senha de app do Gmail (https://myaccount.google.com/apppasswords)
  MAIL_TO         destinatário (padrão: geraldoschuetze@gmail.com)
  MODE            auto | digest | reminder   (padrão: auto)
  DAYS_AHEAD      janela do resumo semanal em dias (padrão: 8)
  LOCAL_TZ        fuso para exibir horários (padrão: America/Sao_Paulo)
  DRY_RUN=1       não envia, só grava preview.html

Modo auto: às segundas envia o resumo da semana; nos outros dias só envia
se houver jogo hoje (lembrete do dia do jogo).
"""
from __future__ import annotations

import html
import json
import os
import smtplib
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

TEAM_ID = "2294"  # Iowa Hawkeyes no ESPN
LOGO_URL = "https://a.espncdn.com/i/teamlogos/ncaa/500/2294.png"
GOLD = "#FFCD00"
BLACK = "#000000"
OFFICIAL_SCHEDULE = "https://hawkeyesports.com/calendar/"

SPORTS = {
    "football/college-football": ("Futebol Americano", "🏈"),
    "basketball/mens-college-basketball": ("Basquete Masculino", "🏀"),
    "basketball/womens-college-basketball": ("Basquete Feminino", "🏀"),
}

# canal -> (onde assistir, link). Ordem importa: chaves mais específicas antes.
WATCH_LINKS = [
    ("BIG TEN NETWORK", "BTN · FOX One / YouTube TV / Fubo", "https://www.foxsports.com/live/btn"),
    ("BTN", "BTN · FOX One / YouTube TV / Fubo", "https://www.foxsports.com/live/btn"),
    ("B1G+", "B1G+ (streaming oficial Big Ten)", "https://www.bigtenplus.com/"),
    ("BIG TEN+", "B1G+ (streaming oficial Big Ten)", "https://www.bigtenplus.com/"),
    ("FS1", "FS1 · FOX One / YouTube TV / Fubo", "https://www.foxsports.com/live/fs1"),
    ("FS2", "FS2 · FOX One / Fubo", "https://www.foxsports.com/live/fs2"),
    ("FOX", "FOX · FOX One / YouTube TV / Fubo", "https://www.foxsports.com/live"),
    ("PEACOCK", "Peacock", "https://www.peacocktv.com/sports"),
    ("NBC", "NBC · Peacock", "https://www.peacocktv.com/sports"),
    ("CBSSN", "CBS Sports Network · Paramount+ / YouTube TV", "https://www.cbssports.com/watch/cbs-sports-network"),
    ("CBS", "CBS · Paramount+", "https://www.paramountplus.com/live-tv/"),
    ("PARAMOUNT", "Paramount+", "https://www.paramountplus.com/"),
    ("ESPN+", "ESPN+ / ESPN app", "https://www.espn.com/watch/"),
    ("ESPN", "ESPN · ESPN app / YouTube TV", "https://www.espn.com/watch/"),
    ("ABC", "ABC · ESPN app / YouTube TV", "https://www.espn.com/watch/"),
    ("SEC NETWORK", "SEC Network · ESPN app", "https://www.espn.com/watch/"),
    ("TRUTV", "truTV · HBO Max", "https://www.hbomax.com/sports"),
    ("TNT", "TNT · HBO Max", "https://www.hbomax.com/sports"),
    ("TBS", "TBS · HBO Max", "https://www.hbomax.com/sports"),
    ("HBO", "HBO Max", "https://www.hbomax.com/sports"),
    ("PRIME", "Prime Video", "https://www.amazon.com/primevideo"),
    ("NETFLIX", "Netflix", "https://www.netflix.com/"),
]

PT_WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
PT_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


@dataclass
class Game:
    sport: str
    icon: str
    start: datetime  # UTC
    opponent: str
    home: bool
    neutral: bool = False
    venue: str = ""
    city: str = ""
    networks: list[str] = field(default_factory=list)
    time_tbd: bool = False
    opponent_logo: str = ""
    espn_link: str = ""
    note: str = ""


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "hawkeyes-schedule-agent/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def parse_event(ev: dict, sport: str, icon: str) -> Game | None:
    comp = (ev.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    me = next((c for c in competitors if str(c.get("id") or c.get("team", {}).get("id")) == TEAM_ID), None)
    opp = next((c for c in competitors if c is not me), None)
    if not me or not opp:
        return None
    start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
    nets: list[str] = []
    for b in comp.get("broadcasts") or []:
        names = [(b.get("media") or {}).get("shortName")] + list(b.get("names") or [])
        for name in names:
            if name and name not in nets:
                nets.append(name)
    for gb in comp.get("geoBroadcasts") or []:
        name = (gb.get("media") or {}).get("shortName")
        if name and name not in nets:
            nets.append(name)
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    opp_team = opp.get("team") or {}
    logos = opp_team.get("logos") or []
    link = next((l.get("href") for l in ev.get("links", []) if "summary" in (l.get("rel") or [])), "")
    status = (comp.get("status") or ev.get("status") or {}).get("type", {})
    return Game(
        sport=sport,
        icon=icon,
        start=start,
        opponent=opp_team.get("displayName") or opp_team.get("location") or "Adversário",
        home=me.get("homeAway") == "home",
        neutral=bool(comp.get("neutralSite")),
        venue=venue.get("fullName", ""),
        city=", ".join(x for x in [addr.get("city"), addr.get("state")] if x),
        networks=nets,
        time_tbd=bool(comp.get("timeValid") is False or status.get("name") == "STATUS_TBD" or ev.get("timeValid") is False),
        opponent_logo=(logos[0].get("href") if logos else opp_team.get("logo", "")),
        espn_link=link,
    )


def fetch_games() -> list[Game]:
    games: list[Game] = []
    for path, (label, icon) in SPORTS.items():
        url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams/{TEAM_ID}/schedule"
        try:
            data = fetch_json(url)
        except Exception as exc:  # noqa: BLE001
            print(f"[aviso] falha ao buscar {label}: {exc}", file=sys.stderr)
            continue
        for ev in data.get("events", []):
            g = parse_event(ev, label, icon)
            if g:
                games.append(g)
    return sorted(games, key=lambda g: g.start)


def load_fixture(path: str) -> list[Game]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for r in raw:
        r = dict(r)
        r["start"] = datetime.fromisoformat(r["start"])
        out.append(Game(**r))
    return sorted(out, key=lambda g: g.start)


def watch_options(networks: list[str]) -> list[tuple[str, str, str]]:
    opts, seen = [], set()
    for net in networks:
        up = net.upper()
        for key, label, link in WATCH_LINKS:
            if key in up:
                if link not in seen:
                    opts.append((net, label, link))
                    seen.add(link)
                break
        else:
            opts.append((net, net, f"https://www.google.com/search?q={urllib.request.quote(net + ' live stream')}"))
    return opts


def fmt_local(dt: datetime, tz: ZoneInfo) -> str:
    d = dt.astimezone(tz)
    return f"{PT_WEEKDAYS[d.weekday()].capitalize()}, {d.day:02d} {PT_MONTHS[d.month - 1]} · {d:%H:%M}"


def game_card(g: Game, tz: ZoneInfo) -> str:
    e = html.escape
    et = g.start.astimezone(ZoneInfo("America/New_York"))
    ct = g.start.astimezone(ZoneInfo("America/Chicago"))
    when = f"{PT_WEEKDAYS[g.start.astimezone(tz).weekday()].capitalize()}, {g.start.astimezone(tz).day:02d} {PT_MONTHS[g.start.astimezone(tz).month - 1]} · horário a definir" if g.time_tbd else fmt_local(g.start, tz)
    us_time = "" if g.time_tbd else f"{ct:%-I:%M %p} CT · {et:%-I:%M %p} ET"
    vs = "vs." if g.home or g.neutral else "@"
    where = "Em casa" if g.home and not g.neutral else ("Campo neutro" if g.neutral else "Fora")
    place = " · ".join(x for x in [g.venue, g.city] if x)
    opts = watch_options(g.networks)
    if opts:
        buttons = "".join(
            f'<a href="{e(link)}" style="display:inline-block;margin:4px 6px 4px 0;padding:9px 14px;'
            f'background:{GOLD};color:{BLACK};font-weight:700;font-size:13px;text-decoration:none;border-radius:4px;">'
            f'📺 {e(label)}</a>'
            for _, label, link in opts
        )
    else:
        buttons = (f'<span style="color:#666;font-size:13px;">Canal ainda não anunciado — '
                   f'<a href="{OFFICIAL_SCHEDULE}" style="color:#000;font-weight:700;">ver calendário oficial</a></span>')
    opp_logo = (f'<img src="{e(g.opponent_logo)}" width="36" height="36" alt="" '
                f'style="vertical-align:middle;margin-right:8px;border:0;">' if g.opponent_logo else "")
    extra = ""
    if g.espn_link:
        extra += f'<a href="{e(g.espn_link)}" style="color:#000;font-size:12px;">Detalhes no ESPN ›</a>'
    if g.note:
        extra += f'<div style="color:#666;font-size:12px;margin-top:6px;">{e(g.note)}</div>'
    return f"""
<tr><td style="padding:0 24px 16px;">
 <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e5e5;border-left:6px solid {GOLD};border-radius:6px;background:#fff;">
  <tr><td style="padding:14px 16px;">
   <div style="font-size:11px;letter-spacing:1px;text-transform:uppercase;color:#7a6200;font-weight:700;">{g.icon} {e(g.sport)} · {where}</div>
   <div style="font-size:20px;font-weight:800;color:{BLACK};margin:6px 0 4px;">{opp_logo}Iowa {vs} {e(g.opponent)}</div>
   <div style="font-size:16px;font-weight:700;color:{BLACK};">🕒 {e(when)} <span style="font-weight:400;color:#555;font-size:13px;">(Brasília)</span></div>
   {f'<div style="font-size:12px;color:#666;margin-top:2px;">{us_time}</div>' if us_time else ''}
   {f'<div style="font-size:13px;color:#444;margin-top:4px;">📍 {e(place)}</div>' if place else ''}
   <div style="margin-top:10px;">{buttons}</div>
   <div style="margin-top:6px;">{extra}</div>
  </td></tr>
 </table>
</td></tr>"""


def render_email(games: list[Game], title: str, subtitle: str, logo_src: str, tz: ZoneInfo) -> str:
    cards = "".join(game_card(g, tz) for g in games) or (
        '<tr><td style="padding:0 24px 16px;font-size:15px;">Nenhum jogo nos próximos dias. Go Hawks! 🐤</td></tr>')
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f2f2f2;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2f2f2;">
<tr><td align="center" style="padding:20px 8px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fafafa;border-radius:8px;overflow:hidden;">
 <tr><td align="center" style="background:{BLACK};padding:24px 16px 18px;">
  <img src="{logo_src}" width="96" height="96" alt="Iowa Hawkeyes" style="display:block;border:0;">
  <div style="color:{GOLD};font-size:26px;font-weight:900;letter-spacing:2px;margin-top:10px;">IOWA HAWKEYES</div>
  <div style="color:#fff;font-size:14px;margin-top:4px;">{html.escape(title)}</div>
 </td></tr>
 <tr><td style="background:{GOLD};height:6px;line-height:6px;font-size:0;">&nbsp;</td></tr>
 <tr><td style="padding:18px 24px 12px;font-size:14px;color:#333;">{html.escape(subtitle)}</td></tr>
 {cards}
 <tr><td style="padding:4px 24px 20px;font-size:12px;color:#555;line-height:1.6;">
  <b>Dicas com VPN (servidor nos EUA):</b><br>
  • <a href="https://www.foxsports.com/fox-one" style="color:#000;">FOX One</a> cobre FOX, FS1 e BTN num só app.<br>
  • <a href="https://tv.youtube.com/" style="color:#000;">YouTube TV</a> e <a href="https://www.fubo.tv/" style="color:#000;">Fubo</a> têm FOX, FS1, BTN, CBS, NBC, ESPN e ABC.<br>
  • Jogos na NBC passam ao vivo no <a href="https://www.peacocktv.com/" style="color:#000;">Peacock</a>; na CBS, no <a href="https://www.paramountplus.com/" style="color:#000;">Paramount+</a>; TNT/truTV no <a href="https://www.hbomax.com/" style="color:#000;">HBO Max</a>.<br>
  • Rádio grátis: <a href="https://hawkeyesports.com/sports/2018/5/9/hawkeye-radio-network.aspx" style="color:#000;">Hawkeye Radio Network</a>.<br>
  • Calendário oficial: <a href="{OFFICIAL_SCHEDULE}" style="color:#000;">hawkeyesports.com</a> — horários podem mudar; confira perto do jogo.
 </td></tr>
 <tr><td align="center" style="background:{BLACK};color:{GOLD};padding:14px;font-size:13px;font-weight:700;letter-spacing:1px;">GO HAWKS! 🐤 &nbsp;·&nbsp; <span style="color:#bbb;font-weight:400;">Agente automático Hawkeyes</span></td></tr>
</table></td></tr></table></body></html>"""


def render_text(games: list[Game], title: str, tz: ZoneInfo) -> str:
    lines = [f"IOWA HAWKEYES — {title}", ""]
    for g in games:
        vs = "vs." if g.home or g.neutral else "@"
        when = "horário a definir" if g.time_tbd else fmt_local(g.start, tz)
        lines.append(f"{g.sport}: Iowa {vs} {g.opponent} — {when} (Brasília)")
        for net, label, link in watch_options(g.networks) or [("", "Canal a definir", OFFICIAL_SCHEDULE)]:
            lines.append(f"   📺 {label}: {link}")
        lines.append("")
    lines.append("Go Hawks!")
    return "\n".join(lines)


def download_logo() -> bytes | None:
    try:
        req = urllib.request.Request(LOGO_URL, headers={"User-Agent": "hawkeyes-schedule-agent/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except Exception as exc:  # noqa: BLE001
        print(f"[aviso] logo não baixado ({exc}); usando URL remota", file=sys.stderr)
        return None


def send(subject: str, html_body: str, text_body: str, logo: bytes | None) -> None:
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    to = os.environ.get("MAIL_TO", "geraldoschuetze@gmail.com")
    root = MIMEMultipart("related")
    root["Subject"] = subject
    root["From"] = f"Hawkeyes Agent <{user}>"
    root["To"] = to
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    root.attach(alt)
    if logo:
        img = MIMEImage(logo, "png")
        img.add_header("Content-ID", "<hawkeyes-logo>")
        img.add_header("Content-Disposition", "inline", filename="hawkeyes.png")
        root.attach(img)
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", "465"))) as s:
        s.login(user, password)
        s.sendmail(user, [to], root.as_string())
    print(f"E-mail enviado para {to}: {subject}")


def main() -> int:
    tz = ZoneInfo(os.environ.get("LOCAL_TZ", "America/Sao_Paulo"))
    mode = os.environ.get("MODE", "auto").lower()
    days = int(os.environ.get("DAYS_AHEAD", "8"))
    now = datetime.now(timezone.utc)
    today = now.astimezone(tz).date()

    fixture = os.environ.get("FIXTURE")
    games = load_fixture(fixture) if fixture else fetch_games()
    upcoming = [g for g in games if g.start >= now - timedelta(hours=4)]

    todays = [g for g in upcoming if g.start.astimezone(tz).date() == today]
    if mode == "auto":
        mode = "digest" if today.weekday() == 0 else ("reminder" if todays else "skip")
    if mode == "skip":
        print("Nenhum jogo hoje e não é segunda-feira — nada a enviar.")
        return 0

    if mode == "reminder":
        selected = todays
        if not selected:
            print("Nenhum jogo hoje — nada a enviar.")
            return 0
        title = "É DIA DE JOGO!"
        subtitle = "Jogo(s) de hoje, com horário de Brasília e onde assistir:"
        first = selected[0]
        subject = f"🏈🐤 Hoje: Iowa {'vs.' if first.home else '@'} {first.opponent} — {('a definir' if first.time_tbd else first.start.astimezone(tz).strftime('%H:%M'))}"
    else:
        end = now + timedelta(days=days)
        selected = [g for g in upcoming if g.start <= end]
        title = f"Agenda da semana · {today:%d/%m} a {(today + timedelta(days=days - 1)):%d/%m}"
        subtitle = f"{len(selected)} jogo(s) nos próximos {days} dias. Horários em Brasília, com links para assistir nos EUA (via VPN)."
        subject = f"🐤 Iowa Hawkeyes — agenda da semana ({len(selected)} jogos)"

    logo = None if os.environ.get("DRY_RUN") else download_logo()
    logo_src = "cid:hawkeyes-logo" if logo else LOGO_URL
    html_body = render_email(selected, title, subtitle, logo_src, tz)
    text_body = render_text(selected, title, tz)

    if os.environ.get("DRY_RUN"):
        out = Path(os.environ.get("PREVIEW_PATH", "preview.html"))
        out.write_text(html_body, encoding="utf-8")
        print(f"[dry-run] {subject}\nPreview salvo em {out}")
        return 0
    send(subject, html_body, text_body, logo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
