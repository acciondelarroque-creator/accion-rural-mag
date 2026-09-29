# Acción Rural MAG

Actualización automática de precios del Mercado Agroganadero de Cañuelas (MAG) para Acción Rural.

## Fuente única

- Precios MAG: Grupo Guarino
- Índices: Grupo Guarino
- No se utilizan otras fuentes para completar o reemplazar datos.

## Actualización automática

El workflow consulta Guarino automáticamente los martes, miércoles y viernes desde las 11:00 hasta las 18:00 de Argentina, realizando un nuevo intento cada hora. Si Guarino publica la rueda después de las 11:00, una comprobación posterior la detecta y actualiza `mag.json`.

La marquesina consume directamente `mag.json` y fuerza una consulta sin caché.

## Archivos

- `update_mag.py`: extractor y actualizador.
- `mag.json`: datos publicados para la marquesina.
- `mag_previous.json`: estado de comparación.
