"""Hex strategy for team JOSETOVAR.

Estrategia híbrida para Hex 11x11. Combina:
- Apertura central inteligente
- Detección de victoria/bloqueo inmediato (1 jugada)
- Heurística basada en shortest_path_distance (Dijkstra)
- Patrón two-bridge (conexión virtual de Hex)
- Búsqueda shallow (1-ply) con poda por tiempo
- Modo conservador en variante dark (fog of war)
- Control estricto de tiempo con fallback seguro

Diseñada para vencer a Random consistentemente y competir con MCTS Tier 1-2.
"""

from __future__ import annotations

import random
import time

from strategy import Strategy, GameConfig
from hex_game import (
    check_winner,
    empty_cells,
    get_neighbors,
    shortest_path_distance,
    tuple_to_board,
    board_to_tuple,
)


# ---------------------------------------------------------------------------
# Constantes y patrones de Hex
# ---------------------------------------------------------------------------

# Los 6 vecinos en hex offset coordinates
HEX_NEIGHBORS = [(-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0)]

# Patrones two-bridge: 6 patrones de "bridge" (conexión virtual)
# Cada bridge: (offset_destino, [celdas_intermedias_que_deben_estar_vacias])
# Los bridges son la base estratégica de Hex moderno
TWO_BRIDGES = [
    ((-2, 1), [(-1, 0), (-1, 1)]),   # bridge arriba-derecha
    ((-1, 2), [(-1, 1), (0, 1)]),    # bridge derecha-arriba
    ((1, 1), [(0, 1), (1, 0)]),      # bridge derecha-abajo
    ((2, -1), [(1, 0), (1, -1)]),    # bridge abajo-izquierda
    ((1, -2), [(0, -1), (1, -1)]),   # bridge izquierda-abajo
    ((-1, -1), [(-1, 0), (0, -1)]),  # bridge izquierda-arriba
]


class JoseTovarStrategy(Strategy):
    """Estrategia híbrida heurística + búsqueda shallow para Hex 11x11."""

    # ------------------------------------------------------------------
    # Identificación
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "HybridHeuristic_josetovar"

    # ------------------------------------------------------------------
    # Inicialización por partida
    # ------------------------------------------------------------------

    def begin_game(self, config: GameConfig) -> None:
        """Inicializa estado al comienzo de cada partida."""
        self._size = config.board_size
        self._player = config.player
        self._opponent = config.opponent
        self._variant = config.variant
        self._time_limit = config.time_limit

        # Estado interno
        self._turn_count = 0
        self._known_collisions: set[tuple[int, int]] = set()  # dark mode
        self._rng = random.Random()

        # Centro del tablero (jugada de apertura preferida)
        self._center = (self._size // 2, self._size // 2)

    # ------------------------------------------------------------------
    # Callback de resultado de jugada (relevante para dark mode)
    # ------------------------------------------------------------------

    def on_move_result(
        self,
        move: tuple[int, int],
        success: bool,
    ) -> None:
        """Registra colisiones en dark mode.

        Si en dark mode intenté colocar una piedra y colisioné, esa celda
        contiene una piedra rival oculta. La memorizo para evitarla después.
        """
        if not success:
            self._known_collisions.add(move)

    # ------------------------------------------------------------------
    # Punto de entrada principal
    # ------------------------------------------------------------------

    def play(
        self,
        board: tuple[tuple[int, ...], ...],
        last_move: tuple[int, int] | None,
    ) -> tuple[int, int]:
        """Decide la próxima jugada con control estricto de tiempo."""
        self._turn_count += 1

        # Deadline: 90% del tiempo límite (margen de seguridad)
        self._deadline = time.monotonic() + (self._time_limit * 0.90)

        try:
            if self._variant == "classic":
                return self._play_classic(board, last_move)
            else:
                return self._play_dark(board)
        except Exception:
            # Fallback ultra-seguro si algo falla: una celda vacía cualquiera
            return self._safe_fallback(board)

    # ==================================================================
    # CLASSIC MODE — información completa
    # ==================================================================

    def _play_classic(
        self,
        board: tuple[tuple[int, ...], ...],
        last_move: tuple[int, int] | None,
    ) -> tuple[int, int]:
        """Estrategia para classic mode (información perfecta)."""
        empties = empty_cells(board, self._size)

        # Caso degenerado: solo queda una celda
        if len(empties) == 1:
            return empties[0]

        # 1) APERTURA: si el tablero está vacío o casi vacío, ir al centro
        opening = self._opening_move(board, empties)
        if opening is not None:
            return opening

        # 2) VICTORIA INMEDIATA: ¿puedo ganar en 1 jugada?
        winning = self._find_immediate_win(board, self._player, empties)
        if winning is not None:
            return winning

        # 3) BLOQUEO: ¿el oponente puede ganar en 1 jugada?
        blocking = self._find_immediate_win(board, self._opponent, empties)
        if blocking is not None:
            return blocking

        # 4) BÚSQUEDA HEURÍSTICA: evaluar candidatos
        return self._heuristic_search(board, empties)

    # ------------------------------------------------------------------
    # Apertura
    # ------------------------------------------------------------------

    def _opening_move(
        self,
        board: tuple[tuple[int, ...], ...],
        empties: list[tuple[int, int]],
    ) -> tuple[int, int] | None:
        """Jugada de apertura: centro o cerca del centro."""
        size = self._size
        total_cells = size * size
        empty_count = len(empties)

        # Solo aplicar apertura en las primeras 2-3 jugadas
        if total_cells - empty_count > 3:
            return None

        # Centro está libre -> tómalo
        cr, cc = self._center
        if board[cr][cc] == 0:
            return (cr, cc)

        # Centro ocupado: jugar adyacente al centro
        # Preferimos celdas cercanas al centro pero ligeramente sesgadas
        # hacia nuestro eje de conexión
        candidates = []
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                nr, nc = cr + dr, cc + dc
                if 0 <= nr < size and 0 <= nc < size and board[nr][nc] == 0:
                    candidates.append((nr, nc))

        if candidates:
            # Para Black (player 1): preferir centro vertical
            # Para White (player 2): preferir centro horizontal
            if self._player == 1:
                candidates.sort(key=lambda p: (abs(p[1] - cc), abs(p[0] - cr)))
            else:
                candidates.sort(key=lambda p: (abs(p[0] - cr), abs(p[1] - cc)))
            return candidates[0]

        return None

    # ------------------------------------------------------------------
    # Detección de jugada ganadora (1-ply lookahead)
    # ------------------------------------------------------------------

    def _find_immediate_win(
        self,
        board: tuple[tuple[int, ...], ...],
        player: int,
        empties: list[tuple[int, int]],
    ) -> tuple[int, int] | None:
        """Busca una jugada que gane inmediatamente para `player`.

        Solo evalúa celdas adyacentes a piedras existentes del jugador
        (optimización: una jugada ganadora siempre conecta).
        """
        # Optimización: solo probar celdas adyacentes a piedras del jugador
        candidates = self._candidate_cells(board, player, empties)

        for (r, c) in candidates:
            if self._is_time_up():
                return None
            # Simular: colocar piedra
            new_board = self._place_stone(board, r, c, player)
            if check_winner(new_board, self._size) == player:
                return (r, c)
        return None

    # ------------------------------------------------------------------
    # Búsqueda heurística principal (1-ply con scoring posicional)
    # ------------------------------------------------------------------

    def _heuristic_search(
        self,
        board: tuple[tuple[int, ...], ...],
        empties: list[tuple[int, int]],
    ) -> tuple[int, int]:
        """Evalúa candidatos con heurística: minimizar mi distancia,
        maximizar la del oponente.

        Score = (dist_oponente - dist_mio) + bonus_two_bridge + bonus_central
        """
        # Reducir candidatos: solo celdas relevantes (cerca de piedras existentes
        # o en zonas centrales si el tablero está casi vacío)
        candidates = self._candidate_cells_aggressive(board, empties)

        best_move = candidates[0] if candidates else empties[0]
        best_score = float('-inf')

        for (r, c) in candidates:
            if self._is_time_up():
                break

            # Simular jugada
            new_board = self._place_stone(board, r, c, self._player)

            # Componente 1: diferencia de caminos más cortos
            my_dist = shortest_path_distance(new_board, self._size, self._player)
            opp_dist = shortest_path_distance(new_board, self._size, self._opponent)

            # Componente 2: bonus por crear two-bridges
            bridge_bonus = self._count_two_bridges(new_board, r, c, self._player) * 0.5

            # Componente 3: bonus posicional (centro es mejor que esquinas)
            central_bonus = self._central_bonus(r, c)

            # Score combinado: queremos MAX(opp_dist - my_dist) + bonuses
            score = (opp_dist - my_dist) + bridge_bonus + central_bonus

            if score > best_score:
                best_score = score
                best_move = (r, c)

        return best_move

    # ------------------------------------------------------------------
    # Generación de candidatos
    # ------------------------------------------------------------------

    def _candidate_cells(
        self,
        board: tuple[tuple[int, ...], ...],
        player: int,
        empties: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        """Devuelve celdas vacías adyacentes a piedras de `player`.

        Si no hay piedras, devuelve celdas adyacentes a la frontera del jugador.
        """
        size = self._size
        adjacent: set[tuple[int, int]] = set()

        # Encontrar celdas adyacentes a piedras del jugador
        for r in range(size):
            for c in range(size):
                if board[r][c] == player:
                    for nr, nc in get_neighbors(r, c, size):
                        if board[nr][nc] == 0:
                            adjacent.add((nr, nc))

        # Si no hay piedras del jugador, usar la frontera de inicio
        if not adjacent:
            if player == 1:  # Black: borde superior
                for c in range(size):
                    if board[0][c] == 0:
                        adjacent.add((0, c))
            else:  # White: borde izquierdo
                for r in range(size):
                    if board[r][0] == 0:
                        adjacent.add((r, 0))

        if not adjacent:
            return empties[:20]  # Fallback

        return list(adjacent)

    def _candidate_cells_aggressive(
        self,
        board: tuple[tuple[int, ...], ...],
        empties: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        """Genera candidatos relevantes para búsqueda heurística.

        Combina: celdas adyacentes a piedras propias, celdas adyacentes a
        piedras rivales, y celdas centrales.
        Limita a ~30 candidatos para mantener búsqueda rápida.
        """
        size = self._size
        candidates: set[tuple[int, int]] = set()

        # 1) Celdas adyacentes a piedras (propias y rivales)
        for r in range(size):
            for c in range(size):
                if board[r][c] != 0:  # cualquier piedra
                    for nr, nc in get_neighbors(r, c, size):
                        if board[nr][nc] == 0:
                            candidates.add((nr, nc))

        # 2) Si el tablero está vacío o casi, agregar zona central
        if len(candidates) < 5:
            cr, cc = self._center
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    nr, nc = cr + dr, cc + dc
                    if 0 <= nr < size and 0 <= nc < size and board[nr][nc] == 0:
                        candidates.add((nr, nc))

        result = list(candidates)

        # Si hay demasiados candidatos, priorizar los más centrales
        if len(result) > 30:
            cr, cc = self._center
            result.sort(key=lambda p: (p[0] - cr) ** 2 + (p[1] - cc) ** 2)
            result = result[:30]

        if not result:
            return empties[:20]
        return result

    # ------------------------------------------------------------------
    # Two-bridge: patrón de conexión virtual de Hex
    # ------------------------------------------------------------------

    def _count_two_bridges(
        self,
        board: tuple[tuple[int, ...], ...],
        r: int,
        c: int,
        player: int,
    ) -> int:
        """Cuenta cuántos two-bridges forma la celda (r, c) con piedras propias.

        Un two-bridge es una conexión virtual: dos piedras del mismo color
        separadas por dos celdas vacías que pueden conectar garantizado.
        """
        size = self._size
        count = 0
        for (dr, dc), gap_offsets in TWO_BRIDGES:
            tr, tc = r + dr, c + dc
            if not (0 <= tr < size and 0 <= tc < size):
                continue
            # ¿Es una piedra mía la del otro lado?
            if board[tr][tc] != player:
                continue
            # ¿Las dos celdas intermedias están vacías?
            ok = True
            for (gr, gc) in gap_offsets:
                gr_abs, gc_abs = r + gr, c + gc
                if not (0 <= gr_abs < size and 0 <= gc_abs < size):
                    ok = False
                    break
                if board[gr_abs][gc_abs] != 0:
                    ok = False
                    break
            if ok:
                count += 1
        return count

    # ------------------------------------------------------------------
    # Bonus posicional
    # ------------------------------------------------------------------

    def _central_bonus(self, r: int, c: int) -> float:
        """Pequeño bonus por estar cerca del centro (zona estratégica)."""
        cr, cc = self._center
        max_dist = self._size  # distancia Chebyshev máxima
        dist = max(abs(r - cr), abs(c - cc))
        return 0.3 * (1.0 - dist / max_dist)

    # ==================================================================
    # DARK MODE — fog of war
    # ==================================================================

    def _play_dark(
        self,
        board: tuple[tuple[int, ...], ...],
        last_move: tuple[int, int] | None,
    ) -> tuple[int, int]:
        """Estrategia para dark mode: conservadora, enfoque en mi camino.

        En dark mode no veo al oponente. Solo veo mis piedras + colisiones.
        Estrategia: construir mi camino más corto evitando colisiones conocidas.
        """
        size = self._size
        # Lista de celdas que parecen vacías
        empties = [
            (r, c) for r in range(size) for c in range(size)
            if board[r][c] == 0 and (r, c) not in self._known_collisions
        ]

        if not empties:
            # Todo colisiona; intentar lo que sea
            empties = empty_cells(board, size)
            if not empties:
                return (0, 0)  # nunca debería pasar
            return self._rng.choice(empties)

        # Caso degenerado
        if len(empties) == 1:
            return empties[0]

        # Apertura: ir al centro
        opening = self._opening_move(board, empties)
        if opening is not None and opening not in self._known_collisions:
            return opening

        # ¿Puedo ganar inmediatamente?
        winning = self._find_immediate_win(board, self._player, empties)
        if winning is not None:
            return winning

        # Estrategia conservadora: minimizar mi distancia al objetivo
        # Considerar solo candidatos relevantes (cerca de mis piedras o frontera)
        candidates = self._candidate_cells(board, self._player, empties)
        candidates = [c for c in candidates if c not in self._known_collisions]

        if not candidates:
            candidates = empties

        best_move = candidates[0]
        best_dist = float('inf')

        for (r, c) in candidates:
            if self._is_time_up():
                break
            new_board = self._place_stone(board, r, c, self._player)
            my_dist = shortest_path_distance(new_board, self._size, self._player)
            # Bonus por centralidad para diversificar
            score = my_dist - self._central_bonus(r, c) * 0.5
            if score < best_dist:
                best_dist = score
                best_move = (r, c)

        return best_move

    # ==================================================================
    # UTILIDADES
    # ==================================================================

    def _place_stone(
        self,
        board: tuple[tuple[int, ...], ...],
        r: int,
        c: int,
        player: int,
    ) -> tuple[tuple[int, ...], ...]:
        """Devuelve un nuevo tablero con la piedra colocada (inmutable)."""
        new_row = list(board[r])
        new_row[c] = player
        new_board = list(board)
        new_board[r] = tuple(new_row)
        return tuple(new_board)

    def _is_time_up(self) -> bool:
        """Devuelve True si nos acercamos al deadline."""
        return time.monotonic() >= self._deadline

    def _safe_fallback(
        self,
        board: tuple[tuple[int, ...], ...],
    ) -> tuple[int, int]:
        """Fallback de emergencia: cualquier celda vacía válida.

        Intenta evitar colisiones conocidas en dark mode.
        """
        size = self._size
        empties = [
            (r, c) for r in range(size) for c in range(size)
            if board[r][c] == 0 and (r, c) not in self._known_collisions
        ]
        if empties:
            return self._rng.choice(empties)
        # Último recurso: cualquier celda vacía
        all_empties = empty_cells(board, size)
        if all_empties:
            return self._rng.choice(all_empties)
        # Esto NUNCA debería pasar, pero por si acaso:
        return (0, 0)
