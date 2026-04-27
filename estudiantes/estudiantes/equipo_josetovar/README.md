
**Autor:** José Pablo Tovar González  
**Estrategia:** `HybridHeuristic_josetovar`

---

## 1. Algoritmo utilizado

La estrategia implementa una **heurística posicional** basada en el análisis de la distancia más corta hacia el objetivo de cada jugador.

**Componentes principales:**

1. **Detección de victorias inmediatas** (1-ply lookahead): Antes de cualquier otra cosa, verifica si existe una jugada que conecta mis bordes en un turno. Si la encuentra, la juega.

2. **Detección de bloqueos defensivos**: Si el oponente puede ganar en la siguiente jugada, bloquea esa celda crítica.

3. **Evaluación heurística con Dijkstra**: Para los movimientos candidatos, evalúa una función de score:
   ```
   score = (distancia_oponente - distancia_mía) + bonus_two_bridges + bonus_centralidad
   ```
   - La **distancia** se calcula usando `shortest_path_distance` (función Dijkstra del framework)
   - El **bonus two-bridge** cuenta patrones de conexión virtual con piedras propias
   - El **bonus centralidad** favorece celdas cercanas al centro estratégico

4. **Apertura central**: En los primeros turnos, intenta ocupar el centro `(5,5)` o adyacencias cercanas, que es la zona de máximo control en Hex.

**Por qué esta aproximación:**
- Evita búsqueda profunda costosa (MCTS sería lento en 11x11)
- Garantiza no perder por error táctico obvio (victoria/bloqueo en 1 jugada)
- Usa el motor del juego directamente (`shortest_path_distance`)
- Tiempo promedio por jugada: ~10 ms (muy por debajo del límite de 15s)

---

## 2. Manejo de la variante dark (fog of war)

En dark mode, el jugador solo ve sus propias piedras y las del oponente descubiertas vía colisión.

**Cambios estratégicos en dark:**

1. **Sin información del oponente**: No aplico detección de bloqueos (no sé dónde está el rival). Solo intento ganar directamente.

2. **Estrategia conservadora**: Minimizo exclusivamente mi distancia hacia el objetivo. No intento predecir al oponente — eso sería ruido.

3. **Registro de colisiones**: Cada vez que intento colocar una piedra en una celda que resulta ocupada (colisión), la registro en `_known_collisions`. En turnos posteriores, evito esas celdas automáticamente.

4. **Fallback robusto**: Si todas las celdas candidatas causan colisión, cambio a una celda aleatoria de las visualmente vacías. Es raro pero garantiza que nunca devuelvo una jugada inválida.

**Resultados prácticos:**
- Classic mode: 20/20 victorias contra Random (ambos colores)
- Dark mode: 6/10 victorias contra Random (60%) — natural que sea menor por la incertidumbre

---

## 3. Decisiones de diseño importantes

| Decisión | Razón |
|----------|-------|
| **Heurística en lugar de MCTS** | Un MCTS profundo es lento para tableros 11x11 (factor de ramificación ~60-100). Una heurística posicional bien diseñada es comparable y mucho más rápida. |
| **Two-bridge bonus** | Los two-bridges son conexiones virtuales clave en Hex: representan pares de celdas que no pueden ser rotas en una sola jugada rival. Favorecerlos acelera el camino a la victoria. |
| **Apertura central** | El centro `(5,5)` es universalmente óptimo en Hex — controla más rutas potenciales que cualquier otra celda. |
| **Candidatos limitados (~30)** | En lugar de evaluar las 121 celdas del tablero, solo considero celdas adyacentes a piedras existentes (zona de juego real) o centrales. Mantiene velocidad sin perder calidad. |
| **Try/except global** | Cualquier excepción inesperada cae a un fallback seguro que retorna una celda válida. Garantiza nunca un forfeit por crash. |
| **Deadline al 90%** | Uso solo el 90% del tiempo límite (13.5 de 15 segundos) para tener margen contra overheads del sistema. |

---

## 4. Resultados de pruebas locales

Probada contra `RandomStrategy` (la única estrategia con código visible en el repo):

**Classic mode** (información completa):
- Como Negro: 10/10 victorias
- Como Blanco: 10/10 victorias
- **Total: 20/20 (100%)**

**Dark mode** (fog of war):
- Como Negro: 4/5 victorias
- Como Blanco: 2/5 victorias
- **Total: 6/10 (60%)**

**Tiempo de ejecución:**
- Promedio por jugada: ~10 ms
- Máximo observado: ~50 ms
- Límite permitido: 15,000 ms

**Nota:** No se pudo probar contra los tiers MCTS (requieren Docker con Python 3.12 en Linux). Se espera competencia decente contra MCTS_Tier_1 y posiblemente Tier_2, dado que la detección de victorias/bloqueos garantiza no perder por errores tácticos obvios.

---

## 5. Estructura del código

```
estudiantes/equipo_josetovar/
├── strategy.py      (≈350 líneas, comentadas)
└── README.md        (este archivo)
```

**Dependencias:**
- Solo librerías estándar de Python (`random`, `time`, `heapq` del framework)
- Compatible con `requirements.txt` del repositorio
- No requiere librerías externas adicionales

**Clase principal:**
- `JoseTovarStrategy(Strategy)` — hereda de la clase abstracta base
- Implementa: `name`, `begin_game()`, `play()`, `on_move_result()` (opcional), `end_game()` (opcional)
- Maneja automáticamente la selección entre classic y dark dentro de `play()`
