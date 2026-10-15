"""Sincroniza partidos.json con la agenda de la FCP (Júnior A del CP Sant Celoni).

Lo ejecuta la GitHub Action .github/workflows/partidos.yml.
Fuente: la misma petición que hace https://www.hoqueipatins.fecapa.cat/ag/

Pensado para no tocarlo durante la temporada:
- la temporada (id_temp) se lee de la propia web de la FCP;
- coge cualquier competición Júnior donde juegue el equipo (liga, 2a fase, copa...);
- en grupos nuevos numera las jornadas por orden de fecha la primera vez que las ve
  y ese número ya no cambia aunque el partido se aplace.
"""
import html, json, re, sys, urllib.parse, urllib.request
from datetime import datetime, timezone

AG = "https://www.hoqueipatins.fecapa.cat/ag/"
URL = "https://server2.sidgad.es/fecapa/00_fecapa_agenda_1.php"
ID_TEMP_DEFECTO = "41"      # 2026/27, solo si no se puede leer de la web
CLUB = "281"                # SANT CELONI, C.P.
CATEGORIA = "JÚNIOR"        # cualquier competición que empiece así
EQUIPO = "CP SANT CELONI A"

# 1a fase (grupo 4900): jornadas oficiales según rival. 2a vuelta = +7 con el campo al revés.
GRUPO_1A_FASE = "4900"
PRIMERA = {"322": (1, True), "283": (2, False), "319": (3, True), "315": (4, False),
           "304": (6, True), "252": (7, False)}
VUELTA = 7
POBLACIO = {"322": "Calafell", "283": "Sant Feliu de Codines", "319": "Ripoll", "315": "Olot",
            "304": "Les Masies de Voltregà", "252": "Igualada", CLUB: "Sant Celoni"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Origin": "https://www.hoqueipatins.fecapa.cat",
    "Referer": AG,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "text/html, */*; q=0.01",
}


def get(url, data=None):
    h = dict(HEADERS)
    if data:
        h["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def temporada():
    try:
        m = re.search(r"id_temp\s*:\s*['\"]?(\d+)", get(AG))
        if m:
            return m.group(1)
    except Exception as e:
        print("No pude leer la temporada de la web:", e)
    return ID_TEMP_DEFECTO


def fetch(id_temp):
    body = urllib.parse.urlencode({"cliente": "fecapa", "idm": "1", "modal_temp": "", "id_temp": id_temp}).encode()
    return get(URL, body)


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
        if len(cells) < 9 or not cells[0].upper().startswith(CATEGORIA):
            continue
        home_id, away_id, grupo = parts[2], parts[3], parts[4]
        home = home_id == CLUB
        if (cells[4] if home else cells[6]).upper() != EQUIPO:
            continue  # otro equipo del club
        rival_id = away_id if home else home_id
        try:
            d, mo, y = cells[1].split("/")
        except ValueError:
            continue  # sin fecha todavía
        res = cells[7].replace(" ", "")
        out.append({
            "grupo": grupo,
            "date": f"{y}-{mo}-{d}",
            "time": cells[2],
            "home": home,
            "rival": cells[6] if home else cells[4],
            "rivalId": rival_id,
            "pista": cells[8],
            "poblacio": POBLACIO.get(CLUB if home else rival_id) or cells[8].title(),
            "comp": cells[0],
            "key": f"{grupo}-{home_id}-{away_id}",
            **({"res": res} if re.fullmatch(r"\d+-\d+", res) else {}),
        })
    return sorted(out, key=lambda x: (x["date"], x["time"]))


def numerar(new, prev):
    """Asigna id y jornada. Respeta lo que ya había para que las convocatorias no se pierdan."""
    prev_by_key = {p.get("key"): p for p in prev if p.get("key")}
    usados = {}
    for m in new:
        p = prev_by_key.get(m["key"])
        if p:
            m["id"], m["jornada"] = p["id"], p.get("jornada")
        elif m["grupo"] == GRUPO_1A_FASE and m["rivalId"] in PRIMERA:
            j, h = PRIMERA[m["rivalId"]]
            m["jornada"] = j if h == m["home"] else j + VUELTA
            m["id"] = f"JUN1-J{m['jornada']}"
        else:
            m["id"] = "G" + m["key"]
            m["jornada"] = None
        if m["jornada"]:
            usados.setdefault(m["grupo"], set()).add(m["jornada"])
    for m in new:  # grupos nuevos: siguiente número libre, por orden de fecha
        if m["jornada"] is None:
            j = max(usados.get(m["grupo"], {0})) + 1
            m["jornada"] = j
            usados.setdefault(m["grupo"], set()).add(j)


def main():
    path = "partidos.json"
    try:
        old = json.load(open(path, encoding="utf-8"))
    except Exception:
        old = {"matches": []}
    prev = old.get("matches", [])
    id_temp = temporada()
    page = fetch(id_temp)
    new = parse(page)
    if len(new) < 1:
        print(f"Temporada {id_temp}. Respuesta: {len(page)} bytes, {page.count('fila_agenda')} filas")
        print(re.sub(r"\s+", " ", page[:400]))
        sys.exit("No he encontrado partidos: no toco partidos.json")
    if old.get("temporada") not in (None, id_temp):
        print(f"Temporada nueva ({old.get('temporada')} -> {id_temp}): empiezo calendario nuevo")
        prev = []
    numerar(new, prev)
    prev_by_id = {p["id"]: p for p in prev}
    hoy = datetime.now().strftime("%Y-%m-%d")
    for m in new:
        p = prev_by_id.get(m["id"])
        if not p:
            continue
        if p.get("nota"):
            m["nota"] = p["nota"]
        if (p["date"], p["time"]) != (m["date"], m["time"]) and p["date"] >= hoy:
            m["nota"] = "Cambio FCP: antes " + "/".join(reversed(p["date"].split("-")[1:])) + " " + p["time"]
    new.sort(key=lambda x: (x["date"], x["time"]))
    out = {"source": "agenda FCP", "team": "Júnior A", "temporada": id_temp, "matches": new}
    if {k: v for k, v in old.items() if k != "updated"} == out:
        print("Sin cambios")
        return
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **out}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"Actualizado: {len(new)} partidos (temporada {id_temp})")


if __name__ == "__main__":
    main()
