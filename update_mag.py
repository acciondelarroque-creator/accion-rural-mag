import json
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.grupoguarino.com.ar/precios-mag/"
STATE_FILE = "mag_previous.json"
OUTPUT_FILE = "mag.json"
SOURCE_ID = "guarino-completo-v7"

CATEGORIAS = {
    "novillos_431_460": "Novillos 431/460", "novillos_461_490": "Novillos 461/490", "novillos_491_520": "Novillos 491/520", "novillos_mas_520": "Novillos +520", "novillos_regulares": "Novillos regulares",
    "novillitos_300_350": "Novillitos 300/350", "novillitos_351_390": "Novillitos 351/390", "novillitos_391_430": "Novillitos 391/430", "novillitos_regulares": "Novillitos regulares",
    "vaquillonas_300_350": "Vaquillonas 300/350", "vaquillonas_351_390": "Vaquillonas 351/390", "vaquillonas_391_430": "Vaquillonas 391/430", "vaquillonas_regulares": "Vaquillonas regulares",
    "vacas_buenas_especiales": "Vacas (buenas a especiales)", "vacas_regulares": "Vacas regulares", "conserva_buena": "Vacas conserva buena", "conserva_inferior": "Vacas conserva inferior",
    "toros_buenos_especiales": "Toros (buenos a especiales)", "toros_regulares": "Toros regulares",
}


def numero_argentino(token):
    if token is None:
        return None
    token = str(token).strip().replace("$", "").replace(" ", "")
    if token in {"", "—", "-", "–"}:
        return None
    try:
        return float(token.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def obtener_pagina():
    r = requests.get(BASE_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; AccionRuralBot/1.0)"}, timeout=30)
    r.raise_for_status()
    return r.text


def fecha_es(texto):
    meses={"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06","julio":"07","agosto":"08","septiembre":"09","setiembre":"09","octubre":"10","noviembre":"11","diciembre":"12"}
    m=re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})",texto,re.I)
    return f"{int(m.group(1)):02d}/{meses[m.group(2).lower()]}/{m.group(3)}" if m else None


def variacion(actual, anterior):
    if actual is None or anterior in (None, 0):
        return None
    return round((actual-anterior)/anterior*100,2)


def parsear_tabla(soup):
    filas={}
    for table in soup.find_all("table"):
        headers=[x.get_text(" ",strip=True).lower() for x in table.find_all("th")]
        if not headers or "mín. corriente" not in " | ".join(headers) or "máximos" not in " | ".join(headers):
            continue
        for tr in table.find_all("tr"):
            cells=[x.get_text(" ",strip=True) for x in tr.find_all(["td","th"])]
            if len(cells)<5:
                continue
            nombre=cells[0].lower()
            clave=next((k for k,v in CATEGORIAS.items() if nombre==v.lower()),None)
            if clave:
                filas[clave]={"min_corriente":numero_argentino(cells[1]),"max_corriente":numero_argentino(cells[2]),"maximo":numero_argentino(cells[3]),"kilos":numero_argentino(cells[4].replace("Kg.",""))}
    if not filas:
        raise RuntimeError("No se encontró la tabla de precios MAG")
    return filas


def indices(texto):
    def ultimos(etiqueta):
        ms=re.findall(rf"{etiqueta}\s*([\d.]+,\d{{3}})\s*([+-]?\d+(?:,\d+)?)%",texto,re.I)
        if not ms:
            return None,None
        a,b=ms[-1]
        return numero_argentino(a),float(b.replace(",","."))
    inmag,inmag_var=ultimos("INMAG")
    igmag,igmag_var=ultimos("IGMAG")
    arrs=re.findall(r"([\d.]+,\d{2,3})\s*([+-]?\d+(?:,\d+)?)%\s*(?:Índice|Var\.\s*Arrendamiento)",texto,re.I)
    arr_val=numero_argentino(arrs[-1][0]) if arrs else None
    arr_var=float(arrs[-1][1].replace(",",".")) if arrs else None
    monthly={}
    ms=re.findall(r"Promedio Mensual ConsolidadoJulio 2026:\s*([\d.]+,\d{3})\s*Variación:\s*([+-]?\d+(?:,\d+)?)%",texto,re.I)
    if len(ms)>=2:
        monthly["inmag_novillo"]={"promedio":numero_argentino(ms[-3][0] if len(ms)>=3 else ms[0][0]),"variacion":float((ms[-3][1] if len(ms)>=3 else ms[0][1]).replace(",","."))}
        monthly["igmag_general"]={"promedio":numero_argentino(ms[-2][0]),"variacion":float(ms[-2][1].replace(",","."))}
        monthly["arrendamiento"]={"promedio":numero_argentino(ms[-1][0]),"variacion":float(ms[-1][1].replace(",","."))}
    return {"inmag_novillo":inmag,"igmag_general":igmag,"arrendamiento":arr_val},{"inmag_novillo":inmag_var,"igmag_general":igmag_var,"arrendamiento":arr_var},monthly


def cargar_estado():
    try:
        with open(STATE_FILE,"r",encoding="utf-8") as f:
            return json.load(f)
    except (OSError,json.JSONDecodeError):
        return {}


def main():
    html=obtener_pagina()
    soup=BeautifulSoup(html,"html.parser")
    texto=soup.get_text(" ",strip=True)
    fecha=fecha_es(texto)
    if not fecha:
        raise RuntimeError("No se pudo determinar la fecha de la rueda MAG")

    filas=parsear_tabla(soup)
    m=re.search(r"Entrada del día\s+([\d.]+)\s+Cabezas",texto,re.I)
    cabezas=int(m.group(1).replace(".","")) if m else None
    m=re.search(r"([\d.]+)\s+Camiones",texto,re.I)
    trucks=int(m.group(1).replace(".","")) if m else None
    m=re.search(r"([\d.]+)\s+Cabezas semana",texto,re.I)
    week_heads=int(m.group(1).replace(".","")) if m else None
    idx,idx_changes,idx_monthly=indices(texto)

    estado=cargar_estado()

    # La comparación es contra la rueda anterior, nunca contra una actualización
    # intradiaria de 30 minutos. La base queda fija durante toda la rueda.
    if "baseline_date" in estado and "baseline_prices" in estado:
        if fecha != estado.get("last_date"):
            baseline_date=estado.get("last_date")
            baseline_prices=estado.get("last_prices",estado.get("baseline_prices",{}))
        else:
            baseline_date=estado.get("baseline_date")
            baseline_prices=estado.get("baseline_prices",{})
    else:
        baseline_date=estado.get("date")
        baseline_prices=estado.get("prices",{})

    for k,fila in filas.items():
        o=baseline_prices.get(k,{}) if isinstance(baseline_prices.get(k,{}),dict) else {}
        fila["changes"]={
            "min_corriente":variacion(fila["min_corriente"],o.get("min_corriente")),
            "max_corriente":variacion(fila["max_corriente"],o.get("max_corriente")),
            "maximo":variacion(fila["maximo"],o.get("maximo"))
        }

    datos={"updated":datetime.now(timezone.utc).isoformat(),"source":"Guarino Producciones · Mercado Agroganadero de Cañuelas (MAG)","url":BASE_URL,"date":fecha,"comparison_date":baseline_date,"heads":cabezas,"trucks":trucks,"week_heads":week_heads,"label":"Mín. Corriente / Máx. Corriente / Máximos","categories":CATEGORIAS,"prices":filas,"indices":idx,"indices_changes":idx_changes,"indices_monthly":idx_monthly}
    with open(OUTPUT_FILE,"w",encoding="utf-8") as f:
        json.dump(datos,f,ensure_ascii=False,indent=2)

    if fecha != estado.get("last_date"):
        nuevo={"source_id":SOURCE_ID,"baseline_date":baseline_date,"baseline_prices":baseline_prices,"last_date":fecha,"last_prices":filas}
    else:
        nuevo={"source_id":SOURCE_ID,"baseline_date":estado.get("baseline_date",baseline_date),"baseline_prices":estado.get("baseline_prices",baseline_prices),"last_date":fecha,"last_prices":filas}
    with open(STATE_FILE,"w",encoding="utf-8") as f:
        json.dump(nuevo,f,ensure_ascii=False,indent=2)
    print(json.dumps(datos,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
