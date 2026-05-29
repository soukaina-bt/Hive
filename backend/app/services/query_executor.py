"""
query_executor.py
-----------------
Exécute les requêtes HiveQL générées par Gemini (ou saisies manuellement)
sur un cluster CDH 5.13 / Hive 1.1.0 où GROUP BY + agrégations déclenchent
MapReduce et échouent avec return code 2.

Stratégie :
  1. Analyser le SQL pour détecter GROUP BY / ORDER BY / agrégations.
  2. Si la requête est "complexe" → extraire la table source + les colonnes
     nécessaires, faire un SELECT brut (fetch task, jamais MapReduce),
     puis agréger/trier côté Python.
  3. Si la requête est "simple" (pas de GROUP BY ni agrégation) → exécuter
     directement via hive_service.run_query().
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from app.services.hive_service import hive_service
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Regex helpers ──────────────────────────────────────────────────────────────

_RE_GROUPBY   = re.compile(r'\bGROUP\s+BY\b',   re.IGNORECASE)
_RE_ORDERBY   = re.compile(r'\bORDER\s+BY\b',    re.IGNORECASE)
_RE_AGG       = re.compile(r'\b(SUM|COUNT|AVG|MIN|MAX|ROUND|COLLECT_SET|COLLECT_LIST)\s*\(', re.IGNORECASE)
_RE_HAVING    = re.compile(r'\bHAVING\b',         re.IGNORECASE)
_RE_FROM      = re.compile(r'\bFROM\s+(\w+)',     re.IGNORECASE)
_RE_JOIN      = re.compile(r'\bJOIN\b',           re.IGNORECASE)
_RE_LIMIT     = re.compile(r'\bLIMIT\s+(\d+)',    re.IGNORECASE)
_RE_WHERE     = re.compile(r'\bWHERE\b',          re.IGNORECASE)
_RE_SUBQUERY  = re.compile(r'\(\s*SELECT\b',      re.IGNORECASE)

# ── SQL parser (léger, pas de vrai AST) ───────────────────────────────────────

def _is_complex(sql: str) -> bool:
    """Retourne True si la requête nécessite MapReduce (GROUP BY ou agrégation)."""
    return bool(_RE_GROUPBY.search(sql) or _RE_AGG.search(sql) or _RE_HAVING.search(sql))

def _has_join(sql: str) -> bool:
    return bool(_RE_JOIN.search(sql))

def _has_subquery(sql: str) -> bool:
    return bool(_RE_SUBQUERY.search(sql))

def _extract_main_table(sql: str) -> Optional[str]:
    m = _RE_FROM.search(sql)
    return m.group(1) if m else None

def _extract_limit(sql: str) -> int:
    m = _RE_LIMIT.search(sql)
    return int(m.group(1)) if m else settings.max_query_rows

def _extract_where_clause(sql: str) -> Optional[str]:
    """Extrait la clause WHERE brute (sans GROUP BY / ORDER BY / HAVING / LIMIT)."""
    upper = sql.upper()
    where_pos = -1
    for m in re.finditer(r'\bWHERE\b', sql, re.IGNORECASE):
        where_pos = m.start()
        break
    if where_pos == -1:
        return None
    # Tout ce qui vient après WHERE jusqu'à GROUP/ORDER/HAVING/LIMIT
    rest = sql[where_pos + 5:]
    stop = re.search(r'\b(GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b', rest, re.IGNORECASE)
    clause = rest[:stop.start()].strip() if stop else rest.strip()
    return clause if clause else None

# ── Valeur numérique sûre ─────────────────────────────────────────────────────

def _to_float(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0

def _to_str(v: Any) -> str:
    return str(v) if v is not None else ''

# ── Parseur de SELECT columns ─────────────────────────────────────────────────

def _parse_select_expressions(sql: str) -> List[Dict]:
    """
    Parse les expressions entre SELECT et FROM pour identifier :
      - alias de chaque expression
      - type : group_key | agg_sum | agg_count | agg_avg | agg_min | agg_max | expr
      - colonne source (quand détectable)
    """
    upper = sql.upper()
    select_start = upper.index('SELECT') + 6
    from_pos = _RE_FROM.search(sql).start()
    raw_select = sql[select_start:from_pos].strip()

    # Séparer les expressions (attention aux parenthèses imbriquées)
    exprs = []
    depth = 0
    current = []
    for ch in raw_select:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            exprs.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        exprs.append(''.join(current).strip())

    parsed = []
    for expr in exprs:
        # Extraire alias
        alias_match = re.search(r'\bAS\s+(\w+)\s*$', expr, re.IGNORECASE)
        alias = alias_match.group(1) if alias_match else None
        core = expr[:alias_match.start()].strip() if alias_match else expr.strip()

        # Identifier le type
        agg_m = re.match(r'(SUM|COUNT|AVG|MIN|MAX)\s*\((.+)\)', core, re.IGNORECASE)
        round_m = re.match(r'ROUND\s*\(\s*(SUM|COUNT|AVG|MIN|MAX)\s*\((.+?)\)\s*(?:,\s*\d+)?\s*\)', core, re.IGNORECASE)

        if round_m:
            agg_type = round_m.group(1).upper()
            inner    = round_m.group(2).strip()
            src_col  = None if inner == '*' else inner.strip()
            parsed.append({'alias': alias or agg_type.lower(), 'type': f'agg_{agg_type.lower()}',
                           'col': src_col, 'expr': core})
        elif agg_m:
            agg_type = agg_m.group(1).upper()
            inner    = agg_m.group(2).strip()
            src_col  = None if inner == '*' else inner.strip()
            parsed.append({'alias': alias or agg_type.lower(), 'type': f'agg_{agg_type.lower()}',
                           'col': src_col, 'expr': core})
        else:
            # Clé de groupement (peut être substr(CAST(...)) ou colonne simple)
            # Extraire la colonne source réelle pour le fetch brut
            col_match = re.search(r'\b([a-zA-Z_]\w*)\b', core)
            src_col   = col_match.group(1) if col_match else core
            parsed.append({'alias': alias or src_col, 'type': 'group_key',
                           'col': src_col, 'expr': core})
    return parsed

def _parse_groupby_keys(sql: str) -> List[str]:
    """Extrait les expressions du GROUP BY."""
    m = re.search(r'\bGROUP\s+BY\s+(.+?)(?:\bORDER\s+BY\b|\bHAVING\b|\bLIMIT\b|$)',
                  sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return []
    raw = m.group(1).strip()
    # Séparer par virgule (hors parenthèses)
    keys, depth, current = [], 0, []
    for ch in raw:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            keys.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        keys.append(''.join(current).strip())
    return [k for k in keys if k]

def _parse_orderby(sql: str) -> List[Tuple[str, bool]]:
    """Retourne [(alias_ou_expr, ascending), ...]."""
    m = re.search(r'\bORDER\s+BY\s+(.+?)(?:\bLIMIT\b|$)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return []
    raw = m.group(1).strip()
    result = []
    for part in raw.split(','):
        part = part.strip()
        desc = bool(re.search(r'\bDESC\b', part, re.IGNORECASE))
        key  = re.sub(r'\b(ASC|DESC)\b', '', part, flags=re.IGNORECASE).strip()
        result.append((key, not desc))
    return result

# ── Évaluateur d'expression GROUP BY sur une ligne ───────────────────────────

def _eval_groupby_expr(expr: str, row: Dict[str, Any]) -> str:
    """
    Évalue une expression GROUP BY sur une ligne Python.
    Supporte : substr(CAST(col AS STRING), start, len), col simple.
    """
    # substr(CAST(col AS STRING), 1, 7)
    m = re.match(
        r"substr\s*\(\s*CAST\s*\(\s*(\w+)\s+AS\s+STRING\s*\)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)",
        expr, re.IGNORECASE)
    if m:
        col, start, length = m.group(1), int(m.group(2)), int(m.group(3))
        val = _to_str(row.get(col, ''))
        return val[start - 1: start - 1 + length]

    # substr(col, 1, 7)
    m = re.match(r"substr\s*\(\s*(\w+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", expr, re.IGNORECASE)
    if m:
        col, start, length = m.group(1), int(m.group(2)), int(m.group(3))
        val = _to_str(row.get(col, ''))
        return val[start - 1: start - 1 + length]

    # CAST(col AS STRING)
    m = re.match(r"CAST\s*\(\s*(\w+)\s+AS\s+STRING\s*\)", expr, re.IGNORECASE)
    if m:
        return _to_str(row.get(m.group(1), ''))

    # Colonne simple
    col_m = re.search(r'\b([a-zA-Z_]\w*)\b', expr)
    col   = col_m.group(1) if col_m else expr
    return _to_str(row.get(col, ''))

# ── Agrégateur Python ─────────────────────────────────────────────────────────

def _aggregate(raw_rows: List[Dict], parsed_exprs: List[Dict],
               groupby_exprs: List[str], orderby: List[Tuple[str, bool]],
               limit: int) -> Tuple[List[str], List[Dict]]:
    """
    Agrège raw_rows côté Python selon les expressions parsées.
    Retourne (columns, rows) au même format que hive_service.run_query().
    """
    if not groupby_exprs:
        # Pas de GROUP BY → agrégation globale sur toutes les lignes
        group_keys_list = [()]
        def get_key(_row):
            return ()
    else:
        def get_key(row):
            return tuple(_eval_groupby_expr(expr, row) for expr in groupby_exprs)
        group_keys_list = None  # on découvrira les clés au vol

    # Accumulation
    sums:   Dict[tuple, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    counts: Dict[tuple, Dict[str, int]]   = defaultdict(lambda: defaultdict(int))
    mins:   Dict[tuple, Dict[str, Any]]   = {}
    maxs:   Dict[tuple, Dict[str, Any]]   = {}
    key_vals: Dict[tuple, Dict[str, str]] = {}   # valeurs des clés de groupe
    order_of_keys: List[tuple] = []

    for row in raw_rows:
        key = get_key(row)
        if key not in key_vals:
            order_of_keys.append(key)
            key_vals[key] = {}
            mins[key]  = {}
            maxs[key]  = {}
            # Stocker les valeurs des expressions de groupe
            for i, expr in enumerate(groupby_exprs):
                gb_alias = None
                # Trouver l'alias correspondant dans parsed_exprs (type group_key)
                gk_exprs = [e for e in parsed_exprs if e['type'] == 'group_key']
                if i < len(gk_exprs):
                    gb_alias = gk_exprs[i]['alias']
                key_vals[key][gb_alias or f'_key{i}'] = _eval_groupby_expr(expr, row)

        for pexpr in parsed_exprs:
            if pexpr['type'] == 'group_key':
                continue
            alias = pexpr['alias']
            col   = pexpr['col']
            t     = pexpr['type']
            val   = row.get(col) if col else None

            if t == 'agg_sum':
                sums[key][alias] += _to_float(val)
            elif t == 'agg_count':
                counts[key][alias] += 1
            elif t == 'agg_avg':
                sums[key][alias]   += _to_float(val)
                counts[key][alias] += 1
            elif t == 'agg_min':
                prev = mins[key].get(alias)
                fval = _to_float(val)
                mins[key][alias] = fval if prev is None else min(prev, fval)
            elif t == 'agg_max':
                prev = maxs[key].get(alias)
                fval = _to_float(val)
                maxs[key][alias] = fval if prev is None else max(prev, fval)

    # Construire les lignes résultat
    result_rows = []
    for key in order_of_keys:
        out = {}
        out.update(key_vals.get(key, {}))
        for pexpr in parsed_exprs:
            if pexpr['type'] == 'group_key':
                continue
            alias = pexpr['alias']
            t     = pexpr['type']
            if t == 'agg_sum':
                out[alias] = round(sums[key][alias], 4)
            elif t == 'agg_count':
                out[alias] = counts[key][alias]
            elif t == 'agg_avg':
                c = counts[key][alias]
                out[alias] = round(sums[key][alias] / c, 4) if c else 0.0
            elif t == 'agg_min':
                out[alias] = mins[key].get(alias, 0.0)
            elif t == 'agg_max':
                out[alias] = maxs[key].get(alias, 0.0)
        result_rows.append(out)

    # Tri ORDER BY
    for ob_key, ascending in reversed(orderby):
        # ob_key peut être un alias ou une expression
        def sort_key(r, k=ob_key):
            v = r.get(k)
            if v is None:
                # Chercher par correspondance partielle
                for rk in r:
                    if rk.lower() == k.lower():
                        v = r[rk]
                        break
            try:
                return float(v)
            except (TypeError, ValueError):
                return str(v) if v is not None else ''
        try:
            result_rows.sort(key=sort_key, reverse=not ascending)
        except Exception:
            pass

    # Appliquer LIMIT
    result_rows = result_rows[:limit]

    # Colonnes dans l'ordre des expressions parsées
    columns = [e['alias'] for e in parsed_exprs]
    return columns, result_rows


# ── Extracteur de colonnes sources nécessaires ────────────────────────────────

def _needed_columns(parsed_exprs: List[Dict], groupby_exprs: List[str],
                    table_cols: List[str]) -> List[str]:
    """
    Détermine les colonnes réelles à inclure dans le SELECT brut.
    On prend toutes les colonnes mentionnées dans les expressions.
    """
    needed = set()

    for pexpr in parsed_exprs:
        col = pexpr.get('col')
        if col and col != '*':
            # Chercher la colonne réelle (peut être aliasée)
            for tc in table_cols:
                if tc.lower() == col.lower():
                    needed.add(tc)
                    break
            else:
                needed.add(col)  # on la garde même si non trouvée

    for expr in groupby_exprs:
        col_m = re.search(r'\b([a-zA-Z_]\w*)\b', expr)
        if col_m:
            col = col_m.group(1)
            for tc in table_cols:
                if tc.lower() == col.lower():
                    needed.add(tc)
                    break
            else:
                needed.add(col)

    # Si rien trouvé, prendre toutes les colonnes
    if not needed:
        return list(table_cols)

    # Préserver l'ordre du schéma
    return [tc for tc in table_cols if tc in needed] or list(needed)


# ── Point d'entrée principal ──────────────────────────────────────────────────

def execute_safe(sql: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Exécute sql de façon sûre sur Hive 1.1.0 / CDH 5.13.

    - Requête simple (pas de GROUP BY, pas d'agrégation) → exécution directe.
    - Requête avec GROUP BY / agrégations → réécriture en SELECT brut + agrégation Python.
    - Requête avec JOIN ou sous-requêtes → tentative directe avec fallback Python si erreur.
    """
    stripped = sql.strip()

    # Cas simple : pas d'agrégation → exécution directe (fetch task)
    if not _is_complex(stripped):
        logger.info("execute_safe: requête simple → exécution directe")
        return hive_service.run_query(stripped)

    # Cas complexe avec JOIN ou sous-requête → tentative directe d'abord
    if _has_join(stripped) or _has_subquery(stripped):
        logger.info("execute_safe: requête avec JOIN/sous-requête → tentative directe")
        try:
            return hive_service.run_query(stripped)
        except Exception as e:
            err_str = str(e)
            if 'MapRedTask' not in err_str and 'return code 2' not in err_str:
                raise  # Erreur SQL réelle, pas MapReduce
            logger.warning("execute_safe: JOIN/sous-requête → MapReduce échoué, impossible de récrire automatiquement")
            raise RuntimeError(
                "Cette requête nécessite MapReduce (JOIN complexe) qui n'est pas disponible sur ce cluster. "
                "Essayez une question plus simple sans jointure, ou consultez directement l'overview."
            ) from e

    # Cas GROUP BY sans JOIN → réécriture complète
    logger.info("execute_safe: GROUP BY détecté → mode agrégation Python")

    table = _extract_main_table(stripped)
    if not table:
        # Pas de table trouvée → tentative directe
        return hive_service.run_query(stripped)

    # Récupérer le schéma de la table
    schema = hive_service.get_schema()
    table_cols = schema.get(table, [])

    # Parser les expressions SELECT
    try:
        parsed_exprs  = _parse_select_expressions(stripped)
        groupby_exprs = _parse_groupby_keys(stripped)
        orderby       = _parse_orderby(stripped)
        limit         = _extract_limit(stripped)
        where_clause  = _extract_where_clause(stripped)
    except Exception as parse_err:
        logger.warning("execute_safe: parse échoué (%s) → tentative directe", parse_err)
        return hive_service.run_query(stripped)

    # Colonnes nécessaires pour le SELECT brut
    needed_cols = _needed_columns(parsed_exprs, groupby_exprs, table_cols)

    # Construire le SELECT brut (fetch task, jamais MapReduce)
    col_list = ', '.join(needed_cols) if needed_cols else '*'
    raw_sql   = f"SELECT {col_list} FROM {table}"
    if where_clause:
        raw_sql += f" WHERE {where_clause}"
    raw_sql += f" LIMIT {settings.max_query_rows}"

    logger.info("execute_safe: SELECT brut → %s", raw_sql)

    _, raw_rows = hive_service.run_query(raw_sql)

    logger.info("execute_safe: %d lignes brutes récupérées → agrégation Python", len(raw_rows))

    columns, agg_rows = _aggregate(raw_rows, parsed_exprs, groupby_exprs, orderby, limit)

    logger.info("execute_safe: %d groupes après agrégation", len(agg_rows))
    return columns, agg_rows
