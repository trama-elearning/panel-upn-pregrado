#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera el panel público de producción de UPN Pregrado leyendo la API de Wrike.

Se ejecuta desde GitHub Actions (ver .github/workflows/actualizar.yml).
El token de Wrike llega por la variable de entorno WRIKE_TOKEN, que sale de
los Secrets del repositorio: nunca se escribe en el HTML ni queda en el repo.

Salida: index.html (autocontenido, sin llamadas externas).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape

API = "https://www.wrike.com/api/v4"
FOLDER = "MQAAAAEQ3qht"          # proyecto "UPN Pregrado" en Wrike
TOKEN = os.environ.get("WRIKE_TOKEN", "").strip()

# Zona horaria de Argentina (sin horario de verano).
TZ_AR = timezone(timedelta(hours=-3))
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# customStatusId de Wrike -> (etiqueta pública, color, peso de avance, orden)
# El flujo del tablero es:
#   En producción → QA → Correcciones QA → Validación UPN → Correcciones UPN
#   → Montaje BB → QA BB → Validación BB UPN → Completado
ESTADOS = {
    "IEAG4NK5JMAAAAAA": ("Sin iniciar",         "#9e9e9e", 0.00, 1),
    "IEAG4NK5JMHVHLJW": ("En producción",       "#26a69a", 0.15, 2),
    "IEAG4NK5JMHVH2K6": ("QA interno",          "#f4c430", 0.35, 3),
    "IEAG4NK5JMHVH2LS": ("Validación UPN",      "#00838f", 0.60, 5),
    "IEAG4NK5JMHVH2L4": ("Correcciones",        "#e57373", 0.70, 6),
    "IEAG4NK5JMHVH2MG": ("Montaje Blackboard",  "#8d6e63", 0.80, 7),
    "IEAG4NK5JMHVHLJX": ("Completado",          "#2e7d32", 1.00, 10),
    # Estados estándar del workflow por defecto de Wrike
    "IEAG4NK5JMAAAAAB": ("Completado",          "#2e7d32", 1.00, 10),
    "IEAG4NK5JMAAAAAC": ("En pausa",            "#bdbdbd", 0.00, 11),
    "IEAG4NK5JMAAAAAD": ("Cancelado",           "#cfcfcf", 0.00, 12),
}
# Estados del flujo que todavía no tienen tareas y por lo tanto no conocemos
# su id (Correcciones QA, QA BB, Validación BB UPN). Si aparecen, se muestran
# con una etiqueta neutra en vez de romper el panel.
DESCONOCIDO = ("En proceso", "#b0bec5", 0.50, 9)

SLOTS = [
    ("Recepción material", "Material"),
    ("Módulo 1", "M1"), ("Módulo 2", "M2"), ("Módulo 3", "M3"),
    ("Módulo 4", "M4"), ("Módulo 5", "M5"), ("Módulo 6", "M6"),
    ("Módulo 7", "M7"),
    ("Video", "Video"),
    ("Blackboard", "BB"),
]
SLOT_POR_TITULO = {t.lower(): abrev for t, abrev in SLOTS}


def api(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.load(resp)["data"]
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "replace")[:400]
        raise SystemExit(
            f"ERROR: Wrike respondió {e.code} en {path}.\n{detalle}\n"
            "Si dice 'not_authorized' o 'invalid_request', el token venció o es inválido: "
            "generá uno nuevo en Wrike y actualizá el secret WRIKE_TOKEN del repositorio."
        )


def trozos(lista, n):
    for i in range(0, len(lista), n):
        yield lista[i:i + n]


def estado_de(sid):
    return ESTADOS.get(sid, DESCONOCIDO)


def recolectar():
    cursos_raw = api(f"/folders/{FOLDER}/tasks", {
        "descendants": "false",
        "subTasks": "false",
        "fields": '["subTaskIds"]',
        "pageSize": 200,
    })
    cursos_raw = [c for c in cursos_raw if c.get("subTaskIds")]
    if not cursos_raw:
        raise SystemExit("ERROR: Wrike no devolvió cursos para el proyecto UPN Pregrado.")

    ids = [sid for c in cursos_raw for sid in c["subTaskIds"]]
    detalle = {}
    for lote in trozos(ids, 90):
        for t in api("/tasks/" + ",".join(lote)):
            detalle[t["id"]] = t

    cursos = []
    conteo = {}
    total = suma = recibido = 0

    for c in cursos_raw:
        codigo = c["title"].split(".")[0].strip()
        nombre = ".".join(c["title"].split(".")[1:]).strip()
        fila = {"codigo": codigo, "nombre": nombre, "slots": {}, "peso": 0.0, "n": 0}
        for sid in c["subTaskIds"]:
            t = detalle.get(sid)
            if not t:
                continue
            abrev = SLOT_POR_TITULO.get((t.get("title") or "").strip().lower())
            if not abrev:
                continue
            etiqueta, color, peso, orden = estado_de(t.get("customStatusId"))
            fila["slots"][abrev] = (etiqueta, color)
            if abrev == "Material":
                # La recepción de material no es un entregable de producción.
                if t.get("status") == "Completed":
                    recibido += 1
            else:
                clave = (orden, etiqueta, color)
                conteo[clave] = conteo.get(clave, 0) + 1
                total += 1
                suma += peso
                fila["peso"] += peso
                fila["n"] += 1
        fila["pct"] = round(100 * fila["peso"] / fila["n"]) if fila["n"] else 0
        cursos.append(fila)

    def num(c):
        digitos = "".join(ch for ch in c["codigo"] if ch.isdigit())
        return int(digitos) if digitos else 0

    cursos.sort(key=num)
    fases = [(o, e, col, n) for (o, e, col), n in sorted(conteo.items())]
    return {
        "cursos": cursos,
        "fases": fases,
        "avance": round(100 * suma / total) if total else 0,
        "recibido": recibido,
        "total_cursos": len(cursos_raw),
        "total": total,
    }


CSS = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;padding:34px 20px 60px;background:#f7f7f5;color:#1a1a17;
     font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
     font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
.wrap{max-width:1000px;margin:0 auto}
h1{font-size:26px;line-height:1.25;margin:0 0 6px;font-weight:650;letter-spacing:-.01em}
.sub{color:#6b6b62;font-size:14px;margin:0 0 26px}
.card{background:#fff;border:1px solid #e7e7e2;border-radius:12px;padding:22px;margin-bottom:20px}
.card h2{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#6b6b62;margin:0 0 16px;font-weight:650}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:20px}
.kpi{background:#fff;border:1px solid #e7e7e2;border-radius:12px;padding:16px 18px}
.kpi .n{font-size:27px;font-weight:660;letter-spacing:-.02em;line-height:1.15}
.kpi .l{font-size:13px;color:#6b6b62;margin-top:3px}
.fase{display:flex;align-items:center;gap:10px;margin-bottom:9px;font-size:14px}
.fase .nm{flex:1}
.fase .ct{font-weight:650;width:38px;text-align:right}
.mini{height:8px;border-radius:5px;background:#eee;width:140px;overflow:hidden}
.mini>i{display:block;height:100%}
.dot{width:11px;height:11px;border-radius:50%;display:inline-block;flex:none}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 6px;text-align:center;border-bottom:1px solid #eee;white-space:nowrap}
th{color:#6b6b62;font-weight:650;font-size:11px;text-transform:uppercase;letter-spacing:.03em}
td.curso{text-align:left;font-weight:600;white-space:normal;min-width:230px}
.badge{display:inline-block;width:14px;height:14px;border-radius:4px}
.bar{height:8px;background:#eee;border-radius:5px;overflow:hidden;min-width:70px;flex:1}
.bar>i{display:block;height:100%;background:#2e7d32}
.prog{display:flex;align-items:center;gap:8px}
.prog small{color:#6b6b62;width:36px;text-align:right;font-size:12px}
.scroll{overflow-x:auto}
.leyenda{display:flex;flex-wrap:wrap;gap:10px 20px;margin-top:4px;font-size:13px}
.leyenda span{display:inline-flex;align-items:center;gap:7px}
footer{font-size:12.5px;color:#9a9a90;margin-top:26px;line-height:1.6}
"""


def construir_html(d, actualizado):
    out = []
    w = out.append
    w('<!DOCTYPE html>')
    w('<html lang="es"><head><meta charset="utf-8">')
    w('<meta name="viewport" content="width=device-width, initial-scale=1">')
    w('<meta name="robots" content="noindex, nofollow, noarchive">')
    w('<meta name="googlebot" content="noindex, nofollow">')
    w('<title>Producción de cursos — UPN Pregrado</title>')
    w('<style>' + CSS + '</style></head><body><div class="wrap">')
    w('<h1>Producción de cursos — UPN Pregrado</h1>')
    w(f'<p class="sub">Estado de avance al {escape(actualizado)}</p>')

    pct_rec = f'{d["recibido"]}/{d["total_cursos"]}'
    w('<div class="kpis">')
    w(f'<div class="kpi"><div class="n">{d["avance"]}%</div>'
      '<div class="l">Avance promedio</div></div>')
    w(f'<div class="kpi"><div class="n">{pct_rec}</div>'
      '<div class="l">Cursos con material recibido</div></div>')
    w(f'<div class="kpi"><div class="n">{d["total_cursos"]}</div>'
      '<div class="l">Cursos en producción</div></div>')
    w(f'<div class="kpi"><div class="n">{d["total"]}</div>'
      '<div class="l">Entregables en seguimiento</div></div>')
    w('</div>')

    maximo = max([n for _, _, _, n in d["fases"]] or [1])
    w('<div class="card"><h2>Entregables por etapa</h2>')
    for _, etiqueta, color, n in d["fases"]:
        ancho = round(100 * n / maximo)
        w(f'<div class="fase"><span class="dot" style="background:{color}"></span>'
          f'<span class="nm">{escape(etiqueta)}</span>'
          f'<span class="mini"><i style="width:{ancho}%;background:{color}"></i></span>'
          f'<span class="ct">{n}</span></div>')
    w('</div>')

    w('<div class="card"><h2>Avance por curso</h2><div class="scroll"><table><thead><tr>')
    w('<th class="curso" style="text-align:left">Curso</th>')
    for _, abrev in SLOTS:
        w(f'<th>{escape(abrev)}</th>')
    w('<th style="min-width:120px">Avance</th></tr></thead><tbody>')
    for c in d["cursos"]:
        w(f'<tr><td class="curso">{escape(c["codigo"])} · {escape(c["nombre"])}</td>')
        for _, abrev in SLOTS:
            celda = c["slots"].get(abrev)
            if celda:
                etiqueta, color = celda
                w(f'<td><span class="badge" style="background:{color}" '
                  f'title="{escape(etiqueta)}"></span></td>')
            else:
                w('<td><span style="color:#ccc">–</span></td>')
        w(f'<td><div class="prog"><div class="bar"><i style="width:{c["pct"]}%"></i></div>'
          f'<small>{c["pct"]}%</small></div></td></tr>')
    w('</tbody></table></div>')

    w('<div class="leyenda" style="margin-top:18px">')
    for _, etiqueta, color, _n in d["fases"]:
        w(f'<span><i class="dot" style="background:{color}"></i>{escape(etiqueta)}</span>')
    w('</div></div>')

    w('<footer>Cada curso se compone de 7 módulos (con sus 4 temas, video y cierre), '
      'un video de presentación y la carga final en Blackboard. '
      'El porcentaje de avance pondera en qué etapa del flujo de producción está cada entregable.<br>'
      'Esta página se actualiza automáticamente a partir del tablero de producción.</footer>')
    w('</div></body></html>')
    return "\n".join(out)


def main():
    if not TOKEN:
        raise SystemExit(
            "ERROR: falta la variable de entorno WRIKE_TOKEN.\n"
            "En GitHub: Settings → Secrets and variables → Actions → New repository secret, "
            "con el nombre WRIKE_TOKEN."
        )
    datos = recolectar()
    ahora = datetime.now(TZ_AR)
    actualizado = f"{ahora.day} de {MESES[ahora.month - 1]} de {ahora.year}, {ahora:%H:%M} h"
    html = construir_html(datos, actualizado)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open("robots.txt", "w", encoding="utf-8") as f:
        f.write("User-agent: *\nDisallow: /\n")

    print(f"Panel generado: {len(datos['cursos'])} cursos, "
          f"{datos['total']} entregables, avance {datos['avance']}%.")


if __name__ == "__main__":
    main()
