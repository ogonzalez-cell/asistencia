"""Sincroniza partidos.json con la agenda de la FCP (Júnior A del CP Sant Celoni).

Lo ejecuta la GitHub Action .github/workflows/partidos.yml.
Fuente: la misma petición que hace https://www.hoqueipatins.fecapa.cat/ag/
"""
import html, json, re, sys, urllib.parse, urllib.request
from datetime import datetime, timezone

URL = "https://server2.sidgad.es/fecapa/00_fecapa_agenda_1.php"
ID_TEMP = "41"          # temporada 2026/27 (cambiará la próxima temporada)
CLUB = "281"            # SANT CELONI, C.P.
COMP = "JÚNIOR OR 1"    # Júnior A
OUR_NAME = "CP SANT CELONI A"

# Jornada de la 1a vuelta según el rival (id de club FCP) y si jugamos en casa.
# La 2a vuelta es la misma jornada + VUELTA con el campo al revés.
PRIMERA = {"322": (1, True), "283": (2, False), "319": (3, True), "315": (4, False),
           "304": (6, True), "252": (7, False)}
VUELTA = 7
POBLACIO = {"322": "Calafell", "283": "Sant Feliu de Codines", "319": "Ripoll", "315": "Olot",
            "304": "Les Masies de Voltregà", "252": "Igualada", CLUB: "Sant Celoni"}


def fetch():
    body = urllib.parse.urlencode({"cliente": "fecapa", "idm": "1", "modal_temp": "", "id_temp": ID_TEMP}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://www.hoqueipatins.fecapa.cat",
        "Referer": "https://www.hoqueipatins.fecapa.cat/ag/",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "text/html, */*; q=0.01"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def clean(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x)).replace("\xa0", " ")).strip()


def parse(page):
    out = []
    for m in re.finditer(r'<tr[^>]*class="fila_agenda[^"]*"[^>]*>(.*?)</tr>', page, re.S | re.I):
        tr = m.group(0)
        pg = re.search(r'param_game="([^"]+)"', tr)
        if not pg:
            continue
        parts = pg.group(1).split("_")
        if len(parts) < 5 or CLUB not in (parts[2], parts[3]):
            continue
        cells = [clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S | re.I)]
        if len(cells) < 9 or cells[0].upper() != COMP:
            continue
        home_id, away_id = parts[2], parts[3]
        home = home_id == CLUB
        if home and cells[4].upper() != OUR_NAME or (not home and cells[6].upper() != OUR_NAME):
            continue  # otro equipo del club en la misma categoría
        rival_id = away_id if home else home_id
        d, mo, y = cells[1].split("/")
        jor = None
        if rival_id in PRIMERA:
            j, h = PRIMERA[rival_id]
            jor = j if h == home else j + VUELTA
        res = cells[7].replace(" ", "")
        out.append({
            "id": f"JUN1-J{jor}" if jor else f"JUN1-{home_id}-{away_id}",
            "jornada": jor,
            "date": f"{y}-{mo}-{d}",
            "time": cells[2],
            "home": home,
            "rival": cells[6] if home else cells[4],
            "rivalId": rival_id,
            "pista": cells[8],
            "poblacio": POBLACIO.get(CLUB if home else rival_id, ""),
            "comp": COMP,
            **({"res": res} if re.fullmatch(r"\d+-\d+", res) else {}),
        })
    return sorted(out, key=lambda x: (x["date"], x["time"]))


def main():
    path = "partidos.json"
    try:
        old = json.load(open(path, encoding="utf-8"))
    except Exception:
        old = {"matches": []}
    prev = {m["id"]: m for m in old.get("matches", [])}
    page = fetch()
    new = parse(page)
    if len(new) < 3:
        print(f"Respuesta: {len(page)} bytes, {page.count('fila_agenda')} filas")
        print(re.sub(r"\s+", " ", page[:400]))
        sys.exit(f"Solo {len(new)} partidos encontrados: no toco partidos.json")
    for m in new:
        p = prev.get(m["id"])
        if not p:
            continue
        if p.get("nota"):
            m["nota"] = p["nota"]
        if (p["date"], p["time"]) != (m["date"], m["time"]) and p["date"] >= datetime.now().strftime("%Y-%m-%d"):
            m["nota"] = "Cambio FCP: antes " + "/".join(reversed(p["date"].split("-")[1:])) + " " + p["time"]
    keep = lambda d: {k: v for k, v in d.items() if k not in ("updated",)}
    if keep(old) == keep({**old, "matches": new, "source": "agenda FCP", "team": "Júnior A · JÚNIOR OR 1"}):
        print("Sin cambios")
        return
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "agenda FCP",
           "team": "Júnior A · JÚNIOR OR 1", "matches": new}
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(path, "a").write("\n")
    print(f"Actualizado: {len(new)} partidos")


if __name__ == "__main__":
    main()
