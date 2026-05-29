from __future__ import annotations

import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.config import settings
from app.services.hive_service import hive_service

logger = logging.getLogger(__name__)


class OverviewService:
    def __init__(self):
        self._cache: Optional[Dict[str, object]] = None
        self._cache_at = 0.0

    # ------------------------------------------------------------------ utils

    def _normalize(self, value: str) -> str:
        return ''.join(ch for ch in (value or '').lower() if ch.isalnum())

    def _find_table(
        self,
        schema: Dict[str, List[str]],
        preferred_names: List[str],
        exclude_keywords: Optional[List[str]] = None,
    ) -> Optional[str]:
        exclude_keywords = exclude_keywords or []
        normalized_preferred = [self._normalize(name) for name in preferred_names]
        normalized_excluded = [self._normalize(name) for name in exclude_keywords]

        exact_matches = {}
        for table in schema:
            normalized_table = self._normalize(table)
            if any(word in normalized_table for word in normalized_excluded):
                continue
            for preferred in normalized_preferred:
                if normalized_table == preferred:
                    exact_matches[table] = len(preferred)
        if exact_matches:
            return max(exact_matches, key=exact_matches.get)

        scored_matches = {}
        for table in schema:
            normalized_table = self._normalize(table)
            if any(word in normalized_table for word in normalized_excluded):
                continue
            score = 0
            for preferred in normalized_preferred:
                if preferred in normalized_table or normalized_table in preferred:
                    score = max(score, len(preferred))
            if score:
                scored_matches[table] = score
        if scored_matches:
            return max(scored_matches, key=scored_matches.get)
        return None

    def _find_column(self, columns: List[str], aliases: List[str]) -> Optional[str]:
        normalized_aliases = [self._normalize(alias) for alias in aliases]
        exact_matches = {}
        for column in columns:
            normalized_column = self._normalize(column)
            for alias in normalized_aliases:
                if normalized_column == alias:
                    exact_matches[column] = len(alias)
        if exact_matches:
            return max(exact_matches, key=exact_matches.get)

        scored_matches = {}
        for column in columns:
            normalized_column = self._normalize(column)
            score = 0
            for alias in normalized_aliases:
                if alias in normalized_column or normalized_column in alias:
                    score = max(score, len(alias))
            if score:
                scored_matches[column] = score
        if scored_matches:
            return max(scored_matches, key=scored_matches.get)
        return None

    def _run_rows(self, sql: Optional[str]) -> List[dict]:
        if not sql:
            return []
        try:
            _, rows = hive_service.run_query(sql)
            return rows
        except Exception as e:
            logger.warning("Query failed: %s — %s", str(e), sql[:120])
            return []

    def _run_scalar(self, sql: Optional[str], key: str = 'value') -> Optional[float]:
        rows = self._run_rows(sql)
        if not rows:
            return None
        value = rows[0].get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _coalesce_text(self, expression: Optional[str], fallback: str) -> str:
        if not expression:
            return f"'{fallback}'"
        return f"COALESCE(CAST({expression} AS STRING), '{fallback}')"

    def _build_item_revenue_expr(self, item_alias: str, item_columns: List[str]) -> Optional[str]:
        subtotal = self._find_column(item_columns, ['subtotal', 'line_total', 'item_total', 'total_price', 'total_amount', 'amount', 'montant'])
        if subtotal:
            return f'COALESCE({item_alias}.{subtotal}, 0)'

        quantity = self._find_column(item_columns, ['quantity', 'qty', 'quantite'])
        unit_price = self._find_column(item_columns, ['unit_price', 'price', 'prix_unitaire', 'sale_price'])
        if not quantity or not unit_price:
            return None

        base_expr = f'COALESCE({item_alias}.{quantity}, 0) * COALESCE({item_alias}.{unit_price}, 0)'
        discount_amount = self._find_column(item_columns, ['discount_amount', 'discount_value', 'remise_montant'])
        if discount_amount:
            return f'({base_expr} - COALESCE({item_alias}.{discount_amount}, 0))'

        discount_ratio = self._find_column(item_columns, ['discount_rate', 'discount_pct', 'discount_percent', 'discount', 'remise'])
        if discount_ratio:
            return f'({base_expr} * (1 - COALESCE({item_alias}.{discount_ratio}, 0)))'

        return base_expr

    def _resolve_schema(self, schema: Dict[str, List[str]]) -> Dict[str, dict]:
        orders_table = self._find_table(schema, ['orders', 'sales_orders', 'customer_orders'], exclude_keywords=['item', 'line', 'detail'])
        customers_table = self._find_table(schema, ['customers', 'customer', 'clients', 'client', 'users', 'user'])
        products_table = self._find_table(schema, ['products', 'product', 'catalog_products', 'catalog'])
        order_items_table = self._find_table(schema, ['order_items', 'order_item', 'order_lines', 'order_details', 'line_items'])
        reviews_table = self._find_table(schema, ['reviews', 'review', 'ratings', 'rating', 'avis'])

        orders_columns = schema.get(orders_table, []) if orders_table else []
        customers_columns = schema.get(customers_table, []) if customers_table else []
        products_columns = schema.get(products_table, []) if products_table else []
        item_columns = schema.get(order_items_table, []) if order_items_table else []
        review_columns = schema.get(reviews_table, []) if reviews_table else []

        return {
            'orders': {
                'table': orders_table,
                'columns': orders_columns,
                'id': self._find_column(orders_columns, ['order_id', 'id_order', 'commande_id']),
                'date': self._find_column(orders_columns, ['order_date', 'created_at', 'purchase_date', 'date_order', 'date_commande']),
                'total': self._find_column(orders_columns, ['total_amount', 'order_total', 'grand_total', 'amount_total', 'montant_total', 'total', 'revenue']),
                'payment': self._find_column(orders_columns, ['payment_method', 'payment_type', 'mode_paiement', 'payment']),
                'status': self._find_column(orders_columns, ['status', 'order_status', 'statut']),
                'country': self._find_column(orders_columns, ['shipping_country', 'country', 'customer_country', 'pays', 'shipping_country_name']),
                'customer_id': self._find_column(orders_columns, ['customer_id', 'client_id', 'user_id', 'id_customer']),
            },
            'customers': {
                'table': customers_table,
                'columns': customers_columns,
                'id': self._find_column(customers_columns, ['customer_id', 'client_id', 'user_id', 'id_customer', 'id']),
                'signup_date': self._find_column(customers_columns, ['signup_date', 'register_date', 'registration_date', 'date_inscription', 'created_at']),
                'country': self._find_column(customers_columns, ['country', 'customer_country', 'pays']),
            },
            'products': {
                'table': products_table,
                'columns': products_columns,
                'id': self._find_column(products_columns, ['product_id', 'item_id', 'id_product', 'sku_id', 'id']),
                'name': self._find_column(products_columns, ['product_name', 'product_title', 'title', 'name', 'nom_produit', 'product']),
                'category': self._find_column(products_columns, ['category', 'categorie', 'product_category']),
                'sub_category': self._find_column(products_columns, ['sub_category', 'subcategory', 'subcategorie', 'sous_categorie', 'sub_category_name']),
            },
            'order_items': {
                'table': order_items_table,
                'columns': item_columns,
                'order_id': self._find_column(item_columns, ['order_id', 'id_order', 'commande_id']),
                'product_id': self._find_column(item_columns, ['product_id', 'item_id', 'id_product', 'sku_id']),
                'quantity': self._find_column(item_columns, ['quantity', 'qty', 'quantite']),
                'revenue_expr': self._build_item_revenue_expr('oi', item_columns),
            },
            'reviews': {
                'table': reviews_table,
                'columns': review_columns,
                'rating': self._find_column(review_columns, ['rating', 'note', 'score']),
            },
        }

    # ------------------------------------------------------------------ SQL builders

    def _build_queries(self, resolved: dict) -> dict:
        """Return a dict of {key: sql} for all sections."""
        orders = resolved['orders']
        customers = resolved['customers']
        products = resolved['products']
        order_items = resolved['order_items']
        reviews = resolved['reviews']

        queries: dict = {}

        if customers['table']:
            queries['kpi_customer_count'] = f"SELECT COUNT(*) AS value FROM {customers['table']}"
        if orders['table']:
            queries['kpi_order_count'] = f"SELECT COUNT(*) AS value FROM {orders['table']}"
        if orders['table'] and orders['total']:
            queries['kpi_revenue'] = f"SELECT ROUND(SUM(COALESCE({orders['total']}, 0)), 2) AS value FROM {orders['table']}"
            queries['kpi_avg_order'] = f"SELECT ROUND(AVG(COALESCE({orders['total']}, 0)), 2) AS value FROM {orders['table']}"
        if products['table']:
            queries['kpi_product_count'] = f"SELECT COUNT(*) AS value FROM {products['table']}"
        if reviews['table'] and reviews['rating']:
            queries['kpi_avg_rating'] = f"SELECT ROUND(AVG(COALESCE({reviews['rating']}, 0)), 2) AS value FROM {reviews['table']}"
        if customers['table'] and customers['signup_date']:
            queries['kpi_new_customers'] = f"""
                SELECT period, value FROM (
                    SELECT substr(CAST({customers['signup_date']} AS STRING), 1, 7) AS period,
                           COUNT(*) AS value
                    FROM {customers['table']}
                    WHERE {customers['signup_date']} IS NOT NULL
                    GROUP BY substr(CAST({customers['signup_date']} AS STRING), 1, 7)
                ) t ORDER BY period DESC LIMIT 1
            """

        if orders['table'] and orders['date'] and orders['total']:
            queries['revenue_trend'] = f"""
                SELECT substr(CAST({orders['date']} AS STRING), 1, 7) AS period,
                       ROUND(SUM(COALESCE({orders['total']}, 0)), 2) AS revenue
                FROM {orders['table']}
                WHERE {orders['date']} IS NOT NULL
                GROUP BY substr(CAST({orders['date']} AS STRING), 1, 7)
                ORDER BY period
            """

        if orders['table'] and orders['payment']:
            queries['payments'] = f"""
                SELECT {self._coalesce_text(orders['payment'], 'Non renseigné')} AS label,
                       COUNT(*) AS value
                FROM {orders['table']}
                GROUP BY {self._coalesce_text(orders['payment'], 'Non renseigné')}
                ORDER BY value DESC
            """

        if orders['table'] and orders['country'] and orders['total']:
            queries['countries'] = f"""
                SELECT {self._coalesce_text(orders['country'], 'Non renseigné')} AS country,
                       COUNT(*) AS orders_count,
                       ROUND(SUM(COALESCE({orders['total']}, 0)), 2) AS revenue
                FROM {orders['table']}
                GROUP BY {self._coalesce_text(orders['country'], 'Non renseigné')}
                ORDER BY revenue DESC LIMIT 12
            """
        elif customers['table'] and customers['country']:
            queries['countries'] = f"""
                SELECT {self._coalesce_text(customers['country'], 'Non renseigné')} AS country,
                       COUNT(*) AS orders_count,
                       CAST(0 AS DOUBLE) AS revenue
                FROM {customers['table']}
                GROUP BY {self._coalesce_text(customers['country'], 'Non renseigné')}
                ORDER BY orders_count DESC LIMIT 12
            """

        if (order_items['table'] and products['table']
                and order_items['product_id'] and products['id']
                and order_items['revenue_expr']):
            cat_expr = self._coalesce_text(f"p.{products['category']}" if products['category'] else None, 'Non classé')
            sub_expr = self._coalesce_text(f"p.{products['sub_category']}" if products['sub_category'] else None, 'Général')
            queries['category_rows'] = f"""
                SELECT {cat_expr} AS category, {sub_expr} AS sub_category,
                       ROUND(SUM({order_items['revenue_expr']}), 2) AS revenue
                FROM {order_items['table']} oi
                JOIN {products['table']} p ON oi.{order_items['product_id']} = p.{products['id']}
                GROUP BY {cat_expr}, {sub_expr}
                ORDER BY revenue DESC LIMIT 24
            """

        if orders['table'] and orders['status']:
            queries['order_status'] = f"""
                SELECT {self._coalesce_text(orders['status'], 'Non renseigné')} AS label,
                       COUNT(*) AS value
                FROM {orders['table']}
                GROUP BY {self._coalesce_text(orders['status'], 'Non renseigné')}
                ORDER BY value DESC
            """

        if (order_items['table'] and products['table']
                and order_items['product_id'] and products['id']
                and order_items['revenue_expr']):
            name_expr = self._coalesce_text(f"p.{products['name']}" if products['name'] else None, 'Produit')
            qty_expr = f"SUM(COALESCE(oi.{order_items['quantity']}, 1))" if order_items['quantity'] else 'COUNT(*)'
            ord_expr = f"COUNT(DISTINCT oi.{order_items['order_id']})" if order_items['order_id'] else 'COUNT(*)'
            queries['top_products'] = f"""
                SELECT {name_expr} AS product,
                       ROUND(SUM({order_items['revenue_expr']}), 2) AS revenue,
                       CAST({qty_expr} AS BIGINT) AS quantity,
                       CAST({ord_expr} AS BIGINT) AS orders_count
                FROM {order_items['table']} oi
                JOIN {products['table']} p ON oi.{order_items['product_id']} = p.{products['id']}
                GROUP BY {name_expr}
                ORDER BY revenue DESC LIMIT 12
            """

        if customers['table'] and customers['signup_date']:
            queries['customer_growth'] = f"""
                SELECT substr(CAST({customers['signup_date']} AS STRING), 1, 7) AS period,
                       COUNT(*) AS value
                FROM {customers['table']}
                WHERE {customers['signup_date']} IS NOT NULL
                GROUP BY substr(CAST({customers['signup_date']} AS STRING), 1, 7)
                ORDER BY period
            """

        return queries

    # ------------------------------------------------------------------ parallel runner

    def _run_parallel(self, queries: dict, max_workers: int = 4) -> Dict[str, list]:
        """
        Run queries in parallel with a conservative pool size to avoid
        overwhelming HiveServer2 with too many simultaneous connections.
        Falls back to sequential if parallel fails.
        """
        results: Dict[str, list] = {}
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_to_key = {
                    pool.submit(self._run_rows, sql): key
                    for key, sql in queries.items()
                }
                for future in as_completed(future_to_key, timeout=300):
                    key = future_to_key[future]
                    try:
                        results[key] = future.result()
                    except Exception as e:
                        logger.warning("Parallel query %s failed: %s", key, e)
                        results[key] = []
        except Exception as e:
            logger.error("ThreadPoolExecutor failed (%s), falling back to sequential", e)
            # Sequential fallback — guaranteed to work even if Hive limits connections
            for key, sql in queries.items():
                if key not in results:
                    results[key] = self._run_rows(sql)
        return results

    # ------------------------------------------------------------------ main

    def get_overview(self, force_refresh: bool = False) -> Dict[str, object]:
        cache_age = time.time() - self._cache_at
        if self._cache and not force_refresh and cache_age < settings.overview_cache_ttl_seconds:
            return self._cache

        schema = hive_service.get_schema(force_refresh=force_refresh)
        resolved = self._resolve_schema(schema)

        queries = self._build_queries(resolved)
        logger.info("Overview: running %d queries (max_workers=4)", len(queries))

        # Use conservative parallelism — HiveServer2 on Cloudera VMs typically
        # handles 4–6 concurrent sessions; beyond that connections time out.
        results = self._run_parallel(queries, max_workers=4)

        unavailable_sections: List[str] = []

        # ── KPIs ──
        kpis = []

        def scalar(key: str) -> Optional[float]:
            rows = results.get(key, [])
            if not rows:
                return None
            value = rows[0].get('value')
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        if (v := scalar('kpi_customer_count')) is not None:
            kpis.append({'label': 'Clients', 'value': int(v), 'helper': 'Clients enregistrés', 'is_currency': False})
        if (v := scalar('kpi_order_count')) is not None:
            kpis.append({'label': 'Commandes', 'value': int(v), 'helper': 'Volume total', 'is_currency': False})
        if (v := scalar('kpi_revenue')) is not None:
            kpis.append({'label': 'Chiffre d\u2019affaires', 'value': v, 'helper': 'CA cumulé', 'is_currency': True})
        if (v := scalar('kpi_avg_order')) is not None:
            kpis.append({'label': 'Panier moyen', 'value': v, 'helper': 'Valeur moyenne par commande', 'is_currency': True})
        if (v := scalar('kpi_product_count')) is not None:
            kpis.append({'label': 'Produits', 'value': int(v), 'helper': 'Catalogue disponible', 'is_currency': False})
        if (v := scalar('kpi_avg_rating')) is not None:
            kpis.append({'label': 'Note moyenne', 'value': v, 'helper': 'Moyenne des avis', 'is_currency': False})

        new_customers_rows = results.get('kpi_new_customers', [])
        if new_customers_rows:
            last_row = new_customers_rows[0]
            kpis.append({
                'label': 'Nouveaux clients',
                'value': int(last_row.get('value') or 0),
                'helper': f"Période {last_row.get('period')}",
                'is_currency': False,
            })

        # ── Charts ──
        revenue_trend = results.get('revenue_trend', [])
        if not revenue_trend:
            unavailable_sections.append('revenue_trend')

        payments = results.get('payments', [])
        if not payments:
            unavailable_sections.append('payments')

        countries = results.get('countries', [])
        if not countries:
            unavailable_sections.append('countries')

        category_rows = results.get('category_rows', [])
        if not category_rows:
            unavailable_sections.append('category_rows')

        order_status = results.get('order_status', [])
        if not order_status:
            unavailable_sections.append('order_status')

        top_products = results.get('top_products', [])
        if not top_products:
            unavailable_sections.append('top_products')

        customer_growth = results.get('customer_growth', [])
        if not customer_growth:
            unavailable_sections.append('customer_growth')

        payload = {
            'database': settings.hive_database,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'kpis': kpis,
            'revenue_trend': revenue_trend,
            'payments': payments,
            'countries': countries,
            'category_rows': category_rows,
            'order_status': order_status,
            'top_products': top_products,
            'customer_growth': customer_growth,
            'unavailable_sections': sorted(set(unavailable_sections)),
        }
        self._cache = payload
        self._cache_at = time.time()
        logger.info("Overview ready: %d KPIs, unavailable=%s", len(kpis), unavailable_sections)
        return payload


overview_service = OverviewService()
