import json
import re
from typing import Any, Dict, List, Optional

import google.generativeai as genai

from app.core.config import settings


# ── SQL compatibility patches for Hive 1.1.0 / CDH 5.13 ─────────────────────
# This cluster does NOT support:
#   - INTERVAL literals (INTERVAL '12' MONTH, etc.)
#   - DATE_SUB / DATE_ADD with INTERVAL
#   - CURRENT_DATE / CURRENT_TIMESTAMP (use from_unixtime(unix_timestamp()))
#   - TABLESAMPLE with aggregations (triggers MapReduce → return code 2)
#   - Subquery aliases without AS keyword in some contexts
# ─────────────────────────────────────────────────────────────────────────────

def _patch_sql_hive11(sql: str) -> str:
    """
    Post-process a Gemini-generated HiveQL query to make it compatible with
    Hive 1.1.0 (CDH 5.13). Fixes known incompatible constructs in-place.
    """
    if not sql or not sql.strip():
        return sql

    patched = sql

    # 1. INTERVAL literals — Hive 1.1.0 does not support them.
    #    Replace date_sub(col, INTERVAL N MONTH/YEAR/DAY) with date_sub(col, N)
    #    or remove filter entirely (we'll let Python handle date filtering).
    patched = re.sub(
        r"date_sub\s*\(\s*([^,]+),\s*INTERVAL\s+(\d+)\s+\w+\s*\)",
        r"date_sub(\1, \2)",
        patched, flags=re.IGNORECASE
    )
    patched = re.sub(
        r"date_add\s*\(\s*([^,]+),\s*INTERVAL\s+(\d+)\s+\w+\s*\)",
        r"date_add(\1, \2)",
        patched, flags=re.IGNORECASE
    )

    # 2. Bare INTERVAL in WHERE / SELECT (e.g. col > INTERVAL '12' MONTH)
    #    → strip the entire comparison containing INTERVAL (safest fallback)
    patched = re.sub(
        r"\bAND\s+\S+\s*(?:>|<|>=|<=|=)\s*INTERVAL\s+['\"]?\d+['\"]?\s+\w+",
        "",
        patched, flags=re.IGNORECASE
    )
    patched = re.sub(
        r"\bWHERE\s+\S+\s*(?:>|<|>=|<=|=)\s*INTERVAL\s+['\"]?\d+['\"]?\s+\w+",
        "WHERE 1=1",
        patched, flags=re.IGNORECASE
    )
    # Any remaining INTERVAL expression
    patched = re.sub(
        r"\bINTERVAL\s+['\"]?\d+['\"]?\s+\w+",
        "NULL",
        patched, flags=re.IGNORECASE
    )

    # 3. CURRENT_DATE / CURRENT_TIMESTAMP → Hive 1.1.0 compatible equivalents
    patched = re.sub(r"\bCURRENT_TIMESTAMP\b", "from_unixtime(unix_timestamp())", patched, flags=re.IGNORECASE)
    patched = re.sub(r"\bCURRENT_DATE\b",      "to_date(from_unixtime(unix_timestamp()))", patched, flags=re.IGNORECASE)

    # 4. NOW() → from_unixtime(unix_timestamp())
    patched = re.sub(r"\bNOW\s*\(\s*\)", "from_unixtime(unix_timestamp())", patched, flags=re.IGNORECASE)

    # 5. DATEDIFF with 3 args (MySQL-style) → Hive only takes 2
    patched = re.sub(
        r"DATEDIFF\s*\(\s*['\"]?\w+['\"]?\s*,\s*([^,]+),\s*([^)]+)\)",
        r"DATEDIFF(\1, \2)",
        patched, flags=re.IGNORECASE
    )

    return patched


class GeminiService:
    def __init__(self):
        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
            self.model = genai.GenerativeModel(settings.gemini_model)
        else:
            self.model = None

    def _is_number(self, value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _split_columns(self, columns: List[str], rows: List[Dict[str, Any]]) -> tuple[List[str], List[str]]:
        numeric_columns = []
        for column in columns:
            sample_values = [row.get(column) for row in rows[:25] if row.get(column) is not None]
            if sample_values and all(self._is_number(value) for value in sample_values[:10]):
                numeric_columns.append(column)
        dimension_columns = [column for column in columns if column not in numeric_columns]
        return dimension_columns, numeric_columns

    def _fallback_chart(self, columns: List[str], rows: List[Dict[str, Any]], preferred_chart: Optional[str] = None) -> Dict[str, Any]:
        dimensions, numeric = self._split_columns(columns, rows)
        chosen_type = preferred_chart if preferred_chart and preferred_chart != "auto" else None

        if chosen_type == "kpi" or (len(rows) == 1 and len(numeric) == 1):
            metric = numeric[0] if numeric else (columns[0] if columns else None)
            return {
                "type": "kpi",
                "valueKey": metric,
                "title": metric.replace("_", " ").title() if metric else "Indicateur",
            }

        x_key = dimensions[0] if dimensions else (columns[0] if columns else None)
        y_keys = numeric[:3] if numeric else ([columns[1]] if len(columns) > 1 else [])
        primary = y_keys[0] if y_keys else None
        type_hint = chosen_type

        if not type_hint:
            looks_temporal = bool(x_key and re.search(r"date|day|month|year|period|time", x_key, re.IGNORECASE))
            if looks_temporal:
                type_hint = "line"
            elif len(y_keys) > 1:
                type_hint = "stackedBar"
            else:
                type_hint = "bar"

        return {
            "type": type_hint,
            "xKey": x_key,
            "yKeys": y_keys[:1] if type_hint in {"pie", "donut"} else y_keys,
            "valueKey": primary,
            "title": f"{primary or 'Valeur'} par {x_key or 'dimension'}",
        }

    def _extract_json(self, text: str) -> Dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def generate_hiveql(self, question: str, schema_context: str, preferred_chart: Optional[str] = None) -> Dict[str, Dict]:
        if not self.model:
            raise RuntimeError("GEMINI_API_KEY non configurée")

        prompt = f'''
Tu es un expert Apache Hive spécialisé en analytique sur cluster CDH 5.13 (Hive 1.1.0).
Ta mission :
1. Générer UNE requête HiveQL valide, sûre et performante à partir de la question utilisateur.
2. Proposer le type de graphique le plus adapté parmi : bar, line, pie, donut, area, stackedBar, horizontalBar, table, kpi.
3. Retourner UNIQUEMENT un JSON valide, sans markdown, sans balises ```.

CONTRAINTES ABSOLUES pour Hive 1.1.0 / CDH 5.13 — ces constructions sont INTERDITES :
- INTERVAL : JAMAIS utiliser INTERVAL '12' MONTH, INTERVAL '1' YEAR, etc. → Hive 1.1.0 ne le supporte pas.
- CURRENT_DATE, CURRENT_TIMESTAMP : utiliser from_unixtime(unix_timestamp()) à la place.
- NOW() : utiliser from_unixtime(unix_timestamp()) à la place.
- Filtres temporels glissants : au lieu de col > date_sub(CURRENT_DATE, INTERVAL 12 MONTH),
  utiliser substr(CAST(col AS STRING), 1, 7) >= '2023-01' (avec une date fixe en string).
- Pas de TABLESAMPLE avec GROUP BY ou agrégations (déclenche MapReduce → erreur).
- Pas de fenêtres analytiques (OVER/PARTITION BY) sur grandes tables.

Règles de génération :
- Utilise UNIQUEMENT les tables et colonnes présentes dans le schéma fourni.
- Génère une requête SELECT uniquement (lecture seule).
- Évite SELECT * sauf demande explicite.
- Pour les analyses temporelles : utiliser substr(CAST(colonne AS STRING), 1, 7) pour le mois (format YYYY-MM).
- Ajoute des alias lisibles pour les colonnes de sortie.
- Ajoute LIMIT 2000 si la requête peut retourner beaucoup de lignes.
- Si la préférence graphique n'est pas "auto", respecte-la si cohérente avec le résultat.
- Si la question n'est pas faisable avec le schéma fourni, retourne sql vide et explique pourquoi.

Schéma Hive :
{schema_context}

Question utilisateur :
{question}

Préférence graphique : {preferred_chart or "auto"}

Format JSON attendu :
{{
  "sql": "SELECT ...",
  "explanation": "...",
  "chart": {{
    "type": "bar",
    "xKey": "dimension",
    "yKeys": ["mesure"],
    "title": "Titre du graphique"
  }}
}}
'''
        response = self.model.generate_content(prompt)
        result = self._extract_json(response.text)

        # Safety net: patch any incompatible constructs Gemini still generated
        if result.get("sql"):
            result["sql"] = _patch_sql_hive11(result["sql"])

        return result

    def suggest_chart_from_result(
        self,
        columns: List[str],
        rows: List[Dict[str, Any]],
        preferred_chart: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._fallback_chart(columns, rows, preferred_chart=preferred_chart)


gemini_service = GeminiService()
