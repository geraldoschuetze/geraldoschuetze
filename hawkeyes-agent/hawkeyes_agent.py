#!/usr/bin/env python3
"""Agente Iowa Hawkeyes: busca os próximos jogos do time de futebol americano
universitário (University of Iowa, NCAA / Big Ten), descobre o canal de TV/streaming nos EUA e envia um e-mail
com a identidade visual do time (preto e dourado + logo Tigerhawk).

Fonte de dados: API pública do ESPN (sem chave). Só usa a biblioteca padrão.

Variáveis de ambiente:
  SMTP_USER       conta Gmail que envia (ex.: geraldoschuetze@gmail.com)
  SMTP_PASSWORD   senha de app do Gmail (https://myaccount.google.com/apppasswords)
  MAIL_TO         destinatário (padrão: geraldoschuetze@gmail.com)
  MODE            auto | digest | reminder   (padrão: auto)
  DAYS_AHEAD      janela do resumo semanal em dias (padrão: 8)
  NEXT_COUNT      quantos jogos seguintes listar no rodapé (padrão: 3)
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
OFFICIAL_SCHEDULE = "https://hawkeyesports.com/sports/football/schedule"
RADIO_URL = "https://hawkeyesports.com/sports/2018/5/9/hawkeye-radio-network.aspx"
ESPN_TEAM_URL = "https://www.espn.com/college-football/team/schedule/_/id/2294/iowa-hawkeyes"
TICKETS_URL = "https://hawkeyesports.com/sports/2018/5/9/tickets.aspx"

SPORTS = {
    "football/college-football": ("NCAA · Big Ten", ""),
}

HAWKEYE_APP_URL = "https://hawkeyesports.com/app/"
YOUTUBE_TV_URL = "https://tv.youtube.com/"
FUBO_URL = "https://www.fubo.tv/welcome/teams/149"
PEACOCK_URL = "https://www.peacocktv.com/sports"

FREE_GREEN = "#0a7a2f"
PAID_RED = "#b3261e"


# canal -> (onde assistir, link). Todos são streamings PAGOS (alguns com teste grátis).
# Ordem importa: chaves mais específicas antes.
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


def gcal_link(g: Game) -> str:
    from urllib.parse import urlencode
    vs = "vs." if g.home or g.neutral else "@"
    start = g.start.astimezone(timezone.utc)
    end = start + timedelta(hours=3, minutes=30)
    tv = ", ".join(g.networks) or "TV a definir"
    params = {
        "action": "TEMPLATE",
        "text": f"Iowa Hawkeyes {vs} {g.opponent}",
        "dates": (f"{start:%Y%m%d}/{(start + timedelta(days=1)):%Y%m%d}" if g.time_tbd
                  else f"{start:%Y%m%dT%H%M%SZ}/{end:%Y%m%dT%H%M%SZ}"),
        "details": f"Onde assistir: {tv}\n{OFFICIAL_SCHEDULE}",
        "location": ", ".join(x for x in [g.venue, g.city] if x),
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params)


def fmt_local(dt: datetime, tz: ZoneInfo) -> str:
    d = dt.astimezone(tz)
    return f"{PT_WEEKDAYS[d.weekday()].capitalize()}, {d.day:02d} {PT_MONTHS[d.month - 1]} · {d:%H:%M}"


FONT = "'Helvetica Neue',Helvetica,Arial,sans-serif"
INK = "#111111"
MUTED = "#6b6b6b"
RULE = "#e3e3e3"


def access_label(free: bool) -> str:
    color = FREE_GREEN if free else MUTED
    text = "Gratuito" if free else "Assinatura"
    return f'<span style="color:{color};font-size:12px;font-weight:{700 if free else 400};">{text}</span>'


def matchup(g: Game) -> str:
    return f"Iowa {'vs.' if g.home or g.neutral else '@'} {g.opponent}"


def date_parts(g: Game, tz: ZoneInfo) -> tuple[str, str, str]:
    d = g.start.astimezone(tz)
    wd = PT_WEEKDAYS[d.weekday()][:3].upper()
    return wd, f"{d.day:02d}", PT_MONTHS[d.month - 1].upper()


def watch_table(g: Game) -> str:
    e = html.escape
    rows = []
    for net, label, link in watch_options(g.networks):
        service = label.split(" · ", 1)[-1]
        rows.append((net, service, link, False))
    if not rows:
        rows.append(("A definir", "Transmissão ainda não anunciada", OFFICIAL_SCHEDULE, True))
    rows.append(("Rádio", "Hawkeye Radio", RADIO_URL, True))
    rows.append(("App", "Hawkeye Sports", HAWKEYE_APP_URL, True))
    cells = []
    for i, (net, service, link, free) in enumerate(rows):
        border = "" if i == 0 else f"border-top:1px solid {RULE};"
        cells.append(
            f'<tr><td style="{border}padding:9px 0;font-size:13px;font-weight:700;color:{INK};width:64px;">{e(net)}</td>'
            f'<td style="{border}padding:9px 8px;font-size:13px;"><a href="{e(link)}" style="color:{INK};text-decoration:underline;">{e(service)}</a></td>'
            f'<td align="right" style="{border}padding:9px 0;white-space:nowrap;">{access_label(free)}</td></tr>')
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:4px;">'
            + "".join(cells) + '</table>')


def game_card(g: Game, tz: ZoneInfo) -> str:
    e = html.escape
    wd, day, mon = date_parts(g, tz)
    local = g.start.astimezone(tz)
    ct = g.start.astimezone(ZoneInfo("America/Chicago"))
    et = g.start.astimezone(ZoneInfo("America/New_York"))
    time_line = ("Horário a definir" if g.time_tbd
                 else f"{local:%H:%M} (Brasília) &nbsp;·&nbsp; {ct:%-I:%M %p} CT &nbsp;·&nbsp; {et:%-I:%M %p} ET")
    where = "Em casa" if g.home and not g.neutral else ("Campo neutro" if g.neutral else "Fora de casa")
    place = " · ".join(x for x in [g.venue, g.city] if x)
    opts = watch_options(g.networks)
    cta = ""
    if opts:
        _, label, link = opts[0]
        cta = (f'<a href="{e(link)}" style="display:inline-block;background-color:{GOLD};border:1px solid {INK};'
               f'color:{INK};font-size:13px;font-weight:700;text-decoration:none;padding:10px 18px;border-radius:3px;">'
               f'Assistir: {e(label)}</a>')
    links = [("Google Agenda", gcal_link(g)), ("Gamecast ESPN", g.espn_link or ESPN_TEAM_URL),
             ("Calendário oficial", OFFICIAL_SCHEDULE)]
    if g.home and not g.neutral:
        links.append(("Ingressos", TICKETS_URL))
    link_row = " &nbsp;|&nbsp; ".join(f'<a href="{e(u)}" style="color:{MUTED};">{t}</a>' for t, u in links)
    note = f'<div style="font-size:12px;color:{MUTED};margin-top:8px;">{e(g.note)}</div>' if g.note else ""
    return f"""
<tr><td style="padding:0 28px 22px;">
 <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {RULE};">
  <tr><td bgcolor="{INK}" style="background-color:{INK};padding:10px 18px;border-bottom:3px solid {GOLD};">
    <span style="color:{GOLD};font-size:13px;font-weight:800;letter-spacing:1.5px;">{wd} {day} {mon}</span>
    <span style="color:#ffffff;font-size:13px;font-weight:700;letter-spacing:1px;">&nbsp;·&nbsp; {"A DEFINIR" if g.time_tbd else local.strftime("%H:%M")}</span>
   </td></tr>
  <tr>
   <td valign="top" style="padding:16px 18px;">
    <div style="font-size:11px;color:{MUTED};letter-spacing:1.2px;text-transform:uppercase;">{e(g.sport)} &nbsp;·&nbsp; {where}</div>
    <div style="font-size:20px;font-weight:800;color:{INK};margin:4px 0 6px;line-height:1.25;">{e(matchup(g))}</div>
    <div style="font-size:14px;color:{INK};">{time_line}</div>
    {f'<div style="font-size:13px;color:{MUTED};margin-top:2px;">{e(place)}</div>' if place else ''}
    {f'<div style="margin-top:14px;">{cta}</div>' if cta else ''}
    <div style="font-size:11px;color:{MUTED};letter-spacing:1.2px;text-transform:uppercase;margin-top:16px;">Onde acompanhar</div>
    {watch_table(g)}
    <div style="font-size:12px;margin-top:10px;">{link_row}</div>
    {note}
   </td>
  </tr>
 </table>
</td></tr>"""


def later_block(later: list[Game], tz: ZoneInfo) -> str:
    if not later:
        return ""
    e = html.escape
    rows = []
    for i, g in enumerate(later):
        d = g.start.astimezone(tz)
        when = f"{PT_WEEKDAYS[d.weekday()][:3]} {d.day:02d}/{d.month:02d}" + ("" if g.time_tbd else f", {d:%H:%M}")
        tv = ", ".join(g.networks) or "TV a definir"
        border = "" if i == 0 else f"border-top:1px solid {RULE};"
        rows.append(
            f'<tr><td style="{border}padding:10px 0;">'
            f'<div style="font-size:14px;color:{INK};font-weight:700;">{e(matchup(g))}</div>'
            f'<div style="font-size:12px;color:{MUTED};margin-top:2px;">{when} &nbsp;·&nbsp; {e(tv)} &nbsp;·&nbsp; '
            f'<a href="{e(gcal_link(g))}" style="color:{MUTED};">adicionar à agenda</a></div></td></tr>')
    return (f'<tr><td style="padding:4px 28px 22px;">'
            f'<div style="font-size:11px;color:{MUTED};letter-spacing:1.2px;text-transform:uppercase;'
            f'border-bottom:2px solid {INK};padding-bottom:6px;">Próximos jogos</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(rows)}</table></td></tr>')


def render_email(games: list[Game], title: str, subtitle: str, logo_src: str, tz: ZoneInfo,
                 later: list[Game] | None = None) -> str:
    cards = "".join(game_card(g, tz) for g in games) or (
        f'<tr><td style="padding:0 28px 22px;font-size:15px;color:{INK};">Semana sem jogo (bye week).</td></tr>')
    cards += later_block(later or [], tz)
    logo = (f'<img src="{logo_src}" width="56" height="56" alt="" style="display:block;border:0;">' if logo_src else "")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"></head>
<body style="margin:0;padding:0;background-color:#f4f4f4;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#f4f4f4" style="background-color:#f4f4f4;font-family:{FONT};">
<tr><td align="center" style="padding:24px 10px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" bgcolor="#ffffff" style="max-width:600px;width:100%;background-color:#ffffff;border:1px solid {RULE};">
 <tr><td bgcolor="{INK}" style="background-color:{INK};border-bottom:4px solid {GOLD};padding:20px 28px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
   {f'<td width="68" valign="middle">{logo}</td>' if logo else ''}
   <td valign="middle">
    <div style="color:{GOLD};font-size:22px;font-weight:800;letter-spacing:2px;">IOWA HAWKEYES</div>
    <div style="color:#d6d6d6;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;margin-top:2px;">Football &nbsp;·&nbsp; {html.escape(title)}</div>
   </td></tr></table>
 </td></tr>
 <tr><td style="padding:22px 28px 18px;font-size:14px;line-height:1.5;color:#333333;">{html.escape(subtitle)}</td></tr>
 {cards}
 <tr><td style="padding:0 28px 24px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {RULE};border-left:3px solid {GOLD};">
   <tr><td style="padding:14px 16px;font-size:13px;line-height:1.6;color:#333333;">
    <div style="font-size:11px;color:{MUTED};letter-spacing:1.2px;text-transform:uppercase;margin-bottom:4px;">Para assistir a temporada inteira</div>
    <b style="color:{INK};"><a href="{YOUTUBE_TV_URL}" style="color:{INK};">YouTube TV</a></b> (plano base) reúne BTN, FOX, FS1, CBS, NBC, ABC e ESPN.
    O plano “Sports” não inclui a BTN. Jogos exclusivos do <a href="{PEACOCK_URL}" style="color:{INK};">Peacock</a> exigem assinatura à parte.
    Alternativa com a mesma grade: <a href="{FUBO_URL}" style="color:{INK};">Fubo</a>. Ambos oferecem período de teste.
   </td></tr></table>
 </td></tr>
 <tr><td style="padding:16px 28px 22px;border-top:1px solid {RULE};font-size:11px;line-height:1.6;color:{MUTED};">
  Horários convertidos para Brasília a partir do calendário da ESPN; podem mudar — confirme no
  <a href="{OFFICIAL_SCHEDULE}" style="color:{MUTED};">calendário oficial</a>.
  Serviços de streaming exigem conexão a partir dos EUA (VPN).<br>
  Resumo enviado às segundas-feiras e no dia de cada jogo. &nbsp;Go Hawks.
 </td></tr>
</table></td></tr></table></body></html>"""


def render_text(games: list[Game], title: str, tz: ZoneInfo) -> str:
    lines = [f"IOWA HAWKEYES FOOTBALL — {title}", ""]
    for g in games:
        when = "horário a definir" if g.time_tbd else fmt_local(g.start, tz)
        lines.append(f"{matchup(g)} — {when} (Brasília)")
        for net, label, link in watch_options(g.networks):
            lines.append(f"  {net}: {label.split(' · ', 1)[-1]} (assinatura) — {link}")
        lines.append(f"  Rádio: Hawkeye Radio Network (gratuito) — {RADIO_URL}")
        lines.append(f"  Google Agenda: {gcal_link(g)}")
        lines.append("")
    lines.append(f"Temporada inteira: YouTube TV, plano base — {YOUTUBE_TV_URL}")
    lines.append(f"Calendário oficial: {OFFICIAL_SCHEDULE}")
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
    root["From"] = f"Iowa Hawkeyes · Agenda <{user}>"
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
        title = "Dia de jogo"
        subtitle = "Hoje tem Hawkeyes. Horário, transmissão e links abaixo."
        first = selected[0]
        subject = f"Hoje: {matchup(first)} · {('horário a definir' if first.time_tbd else first.start.astimezone(tz).strftime('%Hh%M'))} · {', '.join(first.networks) or 'TV a definir'}"
    else:
        end = now + timedelta(days=days)
        selected = [g for g in upcoming if g.start <= end]
        title = f"Semana {today:%d/%m} a {(today + timedelta(days=days - 1)):%d/%m}"
        if selected:
            subtitle = "Programação da semana com horários de Brasília, transmissão e opções gratuitas de acompanhamento."
        else:
            subtitle = "Sem jogo nesta semana. Confira os próximos compromissos."
        if selected:
            g0 = selected[0]
            d0 = g0.start.astimezone(tz)
            subject = (f"{matchup(g0)} · {PT_WEEKDAYS[d0.weekday()][:3]} {d0:%d/%m}"
                       + ("" if g0.time_tbd else f", {d0:%Hh%M}") + f" · {', '.join(g0.networks) or 'TV a definir'}")
        else:
            subject = "Iowa Hawkeyes · semana sem jogo"

    logo = None if os.environ.get("DRY_RUN") else download_logo()
    logo_src = "cid:hawkeyes-logo" if logo else LOGO_URL
    n_next = int(os.environ.get("NEXT_COUNT", "3"))
    later = [g for g in upcoming if g not in selected][:n_next] if mode == "digest" else []
    html_body = render_email(selected, title, subtitle, logo_src, tz, later)
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
