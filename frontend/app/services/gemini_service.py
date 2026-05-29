import json
import re
from typing import Any, Dict, List, Optional

import google.generativeai as genai

from app.core.config import settings


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
Tu es un expert Apache Hive spécialisé en analytique et data visualization.
Ta mission :
1. Générer UNE requête HiveQL valide, sûre et performante à partir de la question utilisateur.
2. Proposer le type de graphique le plus adapté parmi : bar, line, pie, donut, area, stackedBar, horizontalBar, table, kpi.
3. Retourner UNIQUEMENT un JSON valide, sans markdown, sans balises ```.

Règles importantes :
- Utilise UNIQUEMENT les tables et colonnes présentes dans le schéma fourni.
- Génère une requête de lecture seulement.
- Évite SELECT * sauf demande explicite.
- Privilégie les agrégations et le nombre minimum de colonnes nécessaires.
- Si une analyse temporelle est demandée, préfère substr(CAST(colonne AS STRING), 1, 7) pour le niveau mensuel.
- Ajoute des alias lisibles pour les colonnes de sortie.
- Si la préférence graphique n'est pas "auto", respecte-la si elle reste cohérente avec le résultat attendu.
- Si la question n'est pas faisable avec le schéma fourni, retourne sql vide et explique clairement pourquoi.

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
        return self._extract_json(response.text)

    def suggest_chart_from_result(
        self,
        columns: List[str],
        rows: List[Dict[str, Any]],
        preferred_chart: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._fallback_chart(columns, rows, preferred_chart=preferred_chart)


gemini_service = GeminiService()
