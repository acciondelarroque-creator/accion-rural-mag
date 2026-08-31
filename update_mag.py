import json
import os
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.grupoguarino.com.ar/precios-mag/"
STATE_FILE = "mag_previous.json"
OUTPUT_FILE = "mag.json"
SOURCE_ID = "guarino-completo-v6"

CATEGORIAS = {
    "novillos_431_460": "Novillos 431/460",
    "novillos_461_490": "Novillos 461/490",
    "novillos_491_520": "Novillos 491/520",
    "novillos_mas_520": "Novillos +520",
    "novillos_regulares": "Novillos regulares",
    "novillitos_300_350": "Novillitos 300/350",
    "novillitos_351_390": "Novillitos 351/390",
    "novillitos_391_430": "Novillitos 391/430",
    "novillitos_regulares": "Novillitos regulares",
    "vaquillonas_300_350": "Vaquillonas 300/350",
    "vaquillonas_351_390": "Vaquillonas 351/390",
    "vaquillonas_391_430": "Vaquillonas 391/430",
    "vaquillonas_regulares": "Vaquillonas regulares",
    "vacas_buenas_especiales": "Vacas (buenas a especiales)",
    "vacas_regulares": "Vacas regulares",
    "conserva_buena": "Vacas conserva buena",
    "conserva_inferior": "Vacas conserva inferior",
    "toros_buenos_especiales": "Toros (buenos a especiales)",
    "toros_regulares": "Toros regulares",
}

GRUPOS = {
    "NOVILLOS": ["novillos_431_460", "novillos_461_490", "novillos_491_520", "novillos_mas_520", "novillos_regulares"],
    "NOVILLITOS": ["novillitos_300_350", "novillitos_351_390", "novillitos_391_430", "novillitos_regulares"],
    "VAQUILLONAS": ["vaquillonas_300_350", "vaquillonas_351_390", "vaquillonas_391_430", "vaquillonas_regulares"],
    "VACAS": ["vacas_buenas_especiales", "vacas_regulares"],
    "CONSERVA": ["conserva_buena", "conserva_inferior"],
    "TOROS": ["toros_buenos_especiales", "toros_regulares"],
}


def numero_argentino(token):
    if token is None:
        return None
    token = str(token).strip().replace("$", "").replace(" ", "")
    if token in {"", "—", "-", "–"}:
        return None
    token = token.replace(".", "").replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def obtener_pagina():
    respuesta = requests.get(BASE_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; AccionRuralBot/1.0)"}, timeout=30)
    respuesta.raise_for_status()
    return respuesta.text


def fecha_es(texto):
    meses = {"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06","julio":"07","agosto":"08","septiembre":"09","setiembre":"09","octubre":"10","noviembre":"11","diciembre":"12"}
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", texto, re.I)
    if m:
        return f"{int(m.group(1)):02d}/{meses[m.group(2).lower()]}/{m.group(3)}"
    return None


def variacion(actual, anterior):
    if actual is None or anterior in (None, 0):
        return None
    return round((actual - anterior) / anterior * 100, 2)


def parsear_tabla(soup):
    filas = {}
    for table in soup.find_all("table"):
        headers = [x.get_text(" ", strip=True).lower() for x in table.find_all("th")]
        if not headers or "mín. corriente" not in " | ".join(headers) or "máximos" not in " | ".join(headers):
            continue
        for tr in table.find_all("tr"):
            cells = [x.get_text(" ", strip=True) for x in tr.find_all(["td", "th"])]
            if len(cells) < 5 or cells[0].upper() in {"CATEGORÍA", "NOVILLOS", "NOVILLITOS", "VAQUILLONAS", "VACAS", "CONSERVA", "TOROS"}:
                continue
            nombre = cells[0].lower()
            clave = None
            for k, etiqueta in CATEGORIAS.items():
                if nombre == etiqueta.lower():
                    clave = k
                    break
            if clave:
                filas[clave] = {
                    "min_corriente": numero_argentino(cells[1]),
                    "max_corriente": numero_argentino(cells[2]),
                    "maximo": numero_argentino(cells[3]),
                    "kilos": numero_argentino(cells[4].replace("Kg.", "")),
                }
    if not filas:
        raise RuntimeError("No se encontró la tabla de precios MAG")
    return filas


def indices(texto):
    def buscar(etiqueta):
        m = re.search(rf"{etiqueta}\s*([\d.]+,\d{{3}})\s*([+-]?\d+(?:,\d+)?)%", texto, re.I)
        return (numero_argentino(m.group(1)), float(m.group(2).replace(",", "."))) if m else (None, None)
    inmag, inmag_var = buscar("INMAG")
    igmag, igmag_var = buscar("IGMAG")
    arr = re.search(r"([\d.]+,\d{2,3})\s+Índice Arrendamiento", texto, re.I)
    arr_var = re.search(r"([+-]?\d+(?:,\d+)?)%Var\. Arrendamiento", texto, re.I)
    arr_val = numero_argentino(arr.group(1)) if arr else None
    arr_change = float(arr_var.group(1).replace(",", ".")) if arr_var else None
    monthly = {}
    patrones = {
        "inmag_novillo": r"Promedio Mensual ConsolidadoJulio 2026:\s*([\d.]+,\d{3})\s*Variación:\s*([+-]?\d+(?:,\d+)?)%",
        "igmag_general": r"IGMAG[^\n]*?Promedio Mensual ConsolidadoJulio 2026:\s*([\d.]+,\d{3})\s*Variación:\s*([+-]?\d+(?:,\d+)?)%",
        "arrendamiento": r"ÍNDICE SUGERIDO ARRENDAMIENTOS RURALES[^\n]*?Promedio Mensual ConsolidadoJulio 2026:\s*([\d.]+,\d{3})\s*Variación:\s*([+-]?\d+(?:,\d+)?)%",
    }
    for k, patron in patrones.items():
        m = re.search(patron, texto, re.I)
        if m:
            monthly[k] = {"promedio": numero_argentino(m.group(1)), "variacion": float(m.group(2).replace(",", "."))}
    return {"inmag_novillo": inmag, "igmag_general": igmag, "arrendamiento": arr_val}, {"inmag_novillo": inmag_var, "igmag_general": igmag_var, "arrendamiento": arr_change}, monthly


def cargar_anterior():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    html = obtener_pagina()
    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text(" ", strip=True)
    fecha = fecha_es(texto)
    if not fecha:
        raise RuntimeError("No se pudo determinar la fecha de la rueda MAG")
    filas = parsear_tabla(soup)
    entrada = re.search(r"Entrada del día\s+([\d.]+)\s+Cabezas", texto, re.I)
    camiones = re.search(r"([\d.]+)\s+Camiones", texto, re.I)
    semana = re.search(r"([\d.]+)\s+Cabezas semana", texto, re.I)
    cabezas = int(entrada.group(1).replace(".", "")) if entrada else None
    trucks = int(camiones.group(1).replace(".", "")) if camiones else None
    week_heads = int(semana.group(1).replace(".", "")) if semana else None
    indices_data, indices_changes, indices_monthly = indices(texto)
    anterior = cargar_anterior()
    old = anterior.get("prices", {})
    for clave, fila in filas.items():
        oldfila = old.get(clave, {}) if isinstance(old.get(clave, {}), dict) else {}
        fila["changes"] = {
            "min_corriente": variacion(fila["min_corriente"], oldfila.get("min_corriente")),
            "max_corriente": variacion(fila["max_corriente"], oldfila.get("max_corriente")),
            "maximo": variacion(fila["maximo"], oldfila.get("maximo")),
        }
    datos = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "Guarino Producciones · Mercado Agroganadero de Cañuelas (MAG)",
        "url": BASE_URL,
        "date": fecha,
        "heads": cabezas,
        "trucks": trucks,
        "week_heads": week_heads,
        "label": "Mín. Corriente / Máx. Corriente / Máximos",
        "categories": CATEGORIAS,
        "groups": GRUPOS,
        "prices": filas,
        "indices": indices_data,
        "indices_changes": indices_changes,
        "indices_monthly": indices_monthly,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"source_id": SOURCE_ID, "date": fecha, "prices": filas, "indices": indices_data}, f, ensure_ascii=False, indent=2)
    print(json.dumps(datos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
