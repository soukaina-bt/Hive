from __future__ import annotations

import time
import logging
from collections import defaultdict
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

    def _find_table(self, schema, preferred_names, exclude_keywords=None):
        exclude_keywords = exclude_keywords or []
        normalized_preferred = [self._normalize(n) for n in preferred_names]
        normalized_excluded  = [self._normalize(n) for n in exclude_keywords]
        exact = {}
        for table in schema:
            nt = self._normalize(table)
            if any(w in nt for w in normalized_excluded):
                continue
            for pref in normalized_preferred:
                if nt == pref:
                    exact[table] = len(pref)
        if exact:
            return max(exact, key=exact.get)
        scored = {}
        for table in schema:
            nt = self._normalize(table)
            if any(w in nt for w in normalized_excluded):
                continue
            score = 0
            for pref in normalized_preferred:
                if pref in nt or nt in pref:
                    score = max(score, len(pref))
            if score:
                scored[table] = score
        return max(scored, key=scored.get) if scored else None

    def _find_column(self, columns, aliases):
        normalized_aliases = [self._normalize(a) for a in aliases]
        exact = {}
        for col in columns:
            nc = self._normalize(col)
            for alias in normalized_aliases:
                if nc == alias:
                    exact[col] = len(alias)
        if exact:
            return max(exact, key=exact.get)
        scored = {}
        for col in columns:
            nc = self._normalize(col)
            score = 0
            for alias in normalized_aliases:
                if alias in nc or nc in alias:
                    score = max(score, len(alias))
            if score:
                scored[col] = score
        return max(scored, key=scored.get) if scored else None

    def _fetch(self, sql: str) -> List[dict]:
        """Execute a SELECT … LIMIT query (fetch task, no MapReduce) and return rows."""
        try:
            _, rows = hive_service.run_query(sql)
            return rows
        except Exception as e:
            logger.warning("Query failed: %s — SQL: %.400s", e, sql)
            return []

    def _resolve_schema(self, schema):
        orders_table    = self._find_table(schema, ['orders','sales_orders','customer_orders'], exclude_keywords=['item','line','detail'])
        customers_table = self._find_table(schema, ['customers','customer','clients','client','users','user'])
        products_table  = self._find_table(schema, ['products','product','catalog_products','catalog'])
        items_table     = self._find_table(schema, ['order_items','order_item','order_lines','order_details','line_items'])
        reviews_table   = self._find_table(schema, ['reviews','review','ratings','rating','avis'])

        oc = schema.get(orders_table, [])    if orders_table    else []
        cc = schema.get(customers_table, []) if customers_table else []
        pc = schema.get(products_table, [])  if products_table  else []
        ic = schema.get(items_table, [])     if items_table     else []
        rc = schema.get(reviews_table, [])   if reviews_table   else []

        missing = [n for n, t in [('orders', orders_table), ('customers', customers_table),
                                   ('products', products_table), ('order_items', items_table)] if not t]
        if missing:
            logger.warning("Overview: tables non trouvées: %s", missing)

        subtotal_col = self._find_column(ic, ['subtotal','line_total','item_total','total_price','total_amount','amount'])
        qty_col      = self._find_column(ic, ['quantity','qty','quantite'])
        price_col    = self._find_column(ic, ['unit_price','price','prix_unitaire','sale_price'])

        if subtotal_col:
            revenue_col_oi = subtotal_col
        elif qty_col and price_col:
            revenue_col_oi = None  # computed below
        else:
            revenue_col_oi = None

        return {
            'orders': {
                'table': orders_table, 'columns': oc,
                'id':      self._find_column(oc, ['order_id','id_order','commande_id']),
                'date':    self._find_column(oc, ['order_date','created_at','purchase_date','date_order','date_commande']),
                'total':   self._find_column(oc, ['total_amount','order_total','grand_total','amount_total','montant_total','total','revenue']),
                'payment': self._find_column(oc, ['payment_method','payment_type','mode_paiement','payment']),
                'status':  self._find_column(oc, ['status','order_status','statut']),
                'country': self._find_column(oc, ['shipping_country','country','customer_country','pays']),
            },
            'customers': {
                'table': customers_table, 'columns': cc,
                'id':          self._find_column(cc, ['customer_id','client_id','user_id','id_customer','id']),
                'signup_date': self._find_column(cc, ['signup_date','register_date','registration_date','date_inscription','created_at']),
                'country':     self._find_column(cc, ['country','customer_country','pays']),
            },
            'products': {
                'table': products_table, 'columns': pc,
                'id':           self._find_column(pc, ['product_id','item_id','id_product','sku_id','id']),
                'name':         self._find_column(pc, ['product_name','product_title','title','name','nom_produit','product']),
                'category':     self._find_column(pc, ['category','categorie','product_category']),
                'sub_category': self._find_column(pc, ['sub_category','subcategory','subcategorie','sous_categorie']),
            },
            'order_items': {
                'table': items_table, 'columns': ic,
                'order_id':   self._find_column(ic, ['order_id','id_order','commande_id']),
                'product_id': self._find_column(ic, ['product_id','item_id','id_product','sku_id']),
                'quantity':   qty_col,
                'price':      price_col,
                'subtotal':   subtotal_col,
            },
            'reviews': {
                'table': reviews_table, 'columns': rc,
                'rating': self._find_column(rc, ['rating','note','score']),
            },
        }

    # ── Pure-fetch queries (no aggregation in SQL → hive.fetch.task, no MapReduce)

    def _select_cols(self, table: str, cols: List[str], limit: int) -> List[dict]:
        """SELECT specific columns LIMIT n — always uses fetch task, never MapReduce."""
        col_list = ', '.join(cols)
        sql = f"SELECT {col_list} FROM {table} LIMIT {limit}"
        return self._fetch(sql)

    # ── Python-side aggregation helpers ─────────────────────────────────────

    def _py_count(self, rows) -> int:
        return len(rows)

    def _py_sum(self, rows, col, default=0) -> float:
        total = 0.0
        for r in rows:
            v = r.get(col)
            try:
                total += float(v) if v is not None else 0
            except (TypeError, ValueError):
                pass
        return round(total, 2)

    def _py_avg(self, rows, col) -> Optional[float]:
        vals = []
        for r in rows:
            v = r.get(col)
            try:
                if v is not None:
                    vals.append(float(v))
            except (TypeError, ValueError):
                pass
        return round(sum(vals) / len(vals), 2) if vals else None

    def _py_groupby_count(self, rows, col, fallback='Non renseigné') -> List[dict]:
        counts: Dict[str, float] = defaultdict(float)
        for r in rows:
            v = r.get(col) or fallback
            counts[str(v)] += 1
        result = [{'label': k, 'value': v} for k, v in counts.items()]
        result.sort(key=lambda x: -x['value'])
        return result

    def _py_groupby_sum(self, rows, group_col, sum_col, group_fallback='Non renseigné') -> List[dict]:
        sums: Dict[str, float] = defaultdict(float)
        for r in rows:
            k = str(r.get(group_col) or group_fallback)
            v = r.get(sum_col)
            try:
                sums[k] += float(v) if v is not None else 0
            except (TypeError, ValueError):
                pass
        result = [{'label': k, 'value': round(v, 2)} for k, v in sums.items()]
        result.sort(key=lambda x: -x['value'])
        return result

    def _py_groupby_period(self, rows, date_col, value_col=None, scale=1) -> List[dict]:
        """Group rows by YYYY-MM period. If value_col given, sum it; else count."""
        groups: Dict[str, float] = defaultdict(float)
        for r in rows:
            raw = r.get(date_col)
            if not raw:
                continue
            period = str(raw)[:7]
            if not period or len(period) < 7:
                continue
            if value_col:
                v = r.get(value_col)
                try:
                    groups[period] += float(v) if v is not None else 0
                except (TypeError, ValueError):
                    pass
            else:
                groups[period] += 1
        result = [{'period': k, 'value': round(v * scale, 2)} for k, v in groups.items()]
        result.sort(key=lambda x: x['period'])
        return result

    def _py_revenue_by_period(self, rows, date_col, revenue_col, scale=1) -> List[dict]:
        groups: Dict[str, float] = defaultdict(float)
        for r in rows:
            raw = r.get(date_col)
            if not raw:
                continue
            period = str(raw)[:7]
            if not period or len(period) < 7:
                continue
            v = r.get(revenue_col)
            try:
                groups[period] += float(v) if v is not None else 0
            except (TypeError, ValueError):
                pass
        result = [{'period': k, 'revenue': round(v * scale, 2)} for k, v in groups.items()]
        result.sort(key=lambda x: x['period'])
        return result

    def _py_country_stats(self, rows, country_col, revenue_col=None, fallback='Non renseigné') -> List[dict]:
        counts: Dict[str, float]  = defaultdict(float)
        revenues: Dict[str, float] = defaultdict(float)
        for r in rows:
            country = str(r.get(country_col) or fallback)
            counts[country] += 1
            if revenue_col:
                v = r.get(revenue_col)
                try:
                    revenues[country] += float(v) if v is not None else 0
                except (TypeError, ValueError):
                    pass
        result = [{'country': k, 'orders_count': counts[k], 'revenue': round(revenues[k], 2)} for k in counts]
        result.sort(key=lambda x: -x['revenue'] if revenue_col else -x['orders_count'])
        return result

    def _py_item_revenue(self, r: dict, oi: dict) -> float:
        """Compute revenue for a single order_items row."""
        if oi['subtotal']:
            v = r.get(oi['subtotal'])
            try:
                return float(v) if v is not None else 0.0
            except (TypeError, ValueError):
                return 0.0
        qty_v   = r.get(oi['quantity'])   if oi['quantity'] else None
        price_v = r.get(oi['price'])      if oi['price']    else None
        try:
            q = float(qty_v)   if qty_v   is not None else 1.0
            p = float(price_v) if price_v is not None else 0.0
            return q * p
        except (TypeError, ValueError):
            return 0.0

    # ------------------------------------------------------------------ main

    def get_overview(self, force_refresh: bool = False) -> Dict[str, object]:
        cache_age = time.time() - self._cache_at
        if self._cache and not force_refresh and cache_age < settings.overview_cache_ttl_seconds:
            return self._cache

        schema = hive_service.get_schema(force_refresh=force_refresh)
        r = self._resolve_schema(schema)

        o  = r['orders']
        c  = r['customers']
        p  = r['products']
        rv = r['reviews']
        oi = r['order_items']

        # Row budget: each table gets up to max_query_rows rows fetched.
        # No WHERE, no GROUP BY, no aggregates in SQL → always fetch task, never MapReduce.
        LIMIT = settings.max_query_rows  # default 2000

        t0 = time.time()

        # ── Orders ──────────────────────────────────────────────────────────
        orders_rows = []
        if o['table']:
            order_cols = [col for col in [o['id'], o['date'], o['total'], o['payment'], o['status'], o['country']] if col]
            if order_cols:
                orders_rows = self._select_cols(o['table'], order_cols, LIMIT)

        scale = 1  # no extrapolation — LIMIT is the sample; show as-is
        kpi_order_count = len(orders_rows) if orders_rows else None
        kpi_revenue     = self._py_sum(orders_rows, o['total']) if orders_rows and o['total'] else None
        kpi_avg_order   = self._py_avg(orders_rows, o['total']) if orders_rows and o['total'] else None

        revenue_trend = []
        if orders_rows and o['date'] and o['total']:
            revenue_trend = self._py_revenue_by_period(orders_rows, o['date'], o['total'])

        payments = []
        if orders_rows and o['payment']:
            payments = self._py_groupby_count(orders_rows, o['payment'])

        countries = []
        if orders_rows and o['country']:
            countries = self._py_country_stats(orders_rows, o['country'], revenue_col=o['total'])

        order_status = []
        if orders_rows and o['status']:
            order_status = self._py_groupby_count(orders_rows, o['status'])

        # ── Customers ───────────────────────────────────────────────────────
        customer_rows = []
        if c['table']:
            cust_cols = [col for col in [c['id'], c['signup_date'], c['country']] if col]
            if not cust_cols:
                cust_cols = [c['columns'][0]] if c['columns'] else []
            if cust_cols:
                customer_rows = self._select_cols(c['table'], cust_cols, LIMIT)

        kpi_customer_count = len(customer_rows) if customer_rows else None

        customer_growth = []
        if customer_rows and c['signup_date']:
            periods = self._py_groupby_period(customer_rows, c['signup_date'])
            customer_growth = [{'period': x['period'], 'value': x['value']} for x in periods]

        # If no order countries, use customer country
        if not countries and customer_rows and c['country']:
            countries = self._py_country_stats(customer_rows, c['country'])

        # ── Products ────────────────────────────────────────────────────────
        products_rows = []
        if p['table']:
            prod_cols = [col for col in [p['id'], p['name'], p['category'], p['sub_category']] if col]
            if not prod_cols:
                prod_cols = [p['columns'][0]] if p['columns'] else []
            if prod_cols:
                products_rows = self._select_cols(p['table'], prod_cols, LIMIT)

        kpi_product_count = len(products_rows) if products_rows else None
        # Build product lookup: id → {name, category, sub_category}
        product_map: Dict = {}
        if products_rows and p['id']:
            for row in products_rows:
                pid = row.get(p['id'])
                if pid is not None:
                    product_map[pid] = row

        # ── Reviews ─────────────────────────────────────────────────────────
        kpi_avg_rating = None
        if rv['table'] and rv['rating']:
            review_rows = self._select_cols(rv['table'], [rv['rating']], LIMIT)
            kpi_avg_rating = self._py_avg(review_rows, rv['rating'])

        # ── Order items × Products ───────────────────────────────────────────
        top_products: List[dict]  = []
        category_rows: List[dict] = []

        if oi['table']:
            item_cols = [col for col in [oi['order_id'], oi['product_id'], oi['quantity'], oi['price'], oi['subtotal']] if col]
            if item_cols:
                item_rows = self._select_cols(oi['table'], item_cols, LIMIT)

                # Aggregate by product (using product_map for name/category)
                prod_revenue: Dict = defaultdict(float)
                prod_qty:     Dict = defaultdict(float)
                prod_orders:  Dict = defaultdict(set)
                cat_revenue:  Dict = defaultdict(float)
                subcat_map:   Dict = {}

                for row in item_rows:
                    rev   = self._py_item_revenue(row, oi)
                    pid   = row.get(oi['product_id']) if oi['product_id'] else None
                    pinfo = product_map.get(pid, {}) if pid is not None else {}
                    name  = str(pinfo.get(p['name'], '') or pid or 'Produit inconnu') if p['name'] else str(pid or 'Produit inconnu')
                    cat   = str(pinfo.get(p['category'], '') or 'Non classé') if p['category'] else 'Non classé'
                    sub   = str(pinfo.get(p['sub_category'], '') or 'Général') if p['sub_category'] else 'Général'
                    qty_v = row.get(oi['quantity']) if oi['quantity'] else None

                    prod_revenue[name] += rev
                    try:
                        prod_qty[name] += float(qty_v) if qty_v is not None else 1
                    except (TypeError, ValueError):
                        prod_qty[name] += 1
                    oid = row.get(oi['order_id']) if oi['order_id'] else None
                    if oid is not None:
                        prod_orders[name].add(oid)

                    cat_key = (cat, sub)
                    cat_revenue[cat_key] += rev
                    subcat_map[cat_key] = (cat, sub)

                top_products = [
                    {'product': name, 'revenue': round(rev, 2),
                     'quantity': int(prod_qty[name]), 'orders_count': len(prod_orders.get(name, set()))}
                    for name, rev in prod_revenue.items()
                ]
                top_products.sort(key=lambda x: -x['revenue'])
                top_products = top_products[:12]

                category_rows = [
                    {'category': subcat_map[k][0], 'sub_category': subcat_map[k][1], 'revenue': round(v, 2)}
                    for k, v in cat_revenue.items()
                ]
                category_rows.sort(key=lambda x: -x['revenue'])
                category_rows = category_rows[:24]

        logger.info("Overview: all data fetched in %.1fs", time.time() - t0)

        # ── KPIs ────────────────────────────────────────────────────────────
        kpis = []
        _null_reasons: List[str] = []

        def _kpi(val, label, helper, is_currency=False, allow_zero=True):
            if val is not None:
                try:
                    fv = float(val)
                    kpis.append({'label': label, 'value': int(fv) if not is_currency else round(fv, 2),
                                 'helper': helper, 'is_currency': is_currency})
                except (TypeError, ValueError) as exc:
                    _null_reasons.append(f"{label}: conversion error ({exc})")
            else:
                _null_reasons.append(f"{label}: aucune donnée")
                if allow_zero:
                    kpis.append({'label': label, 'value': 0 if not is_currency else 0.0,
                                 'helper': helper, 'is_currency': is_currency})

        _kpi(kpi_customer_count, 'Clients',              'Clients enregistrés')
        _kpi(kpi_order_count,    'Commandes',            'Volume total (échantillon)')
        _kpi(kpi_revenue,        'Chiffre d\u2019affaires', 'CA sur échantillon', True)
        _kpi(kpi_avg_order,      'Panier moyen',         'Valeur moyenne par commande', True)
        _kpi(kpi_product_count,  'Produits',             'Catalogue disponible')
        _kpi(kpi_avg_rating,     'Note moyenne',         'Moyenne des avis', allow_zero=False)

        if _null_reasons:
            logger.warning("Overview: données manquantes: %s", "; ".join(_null_reasons))

        if customer_growth:
            last = customer_growth[-1]
            kpis.append({'label': 'Nouveaux clients', 'value': int(float(last['value'])),
                         'helper': f"Période {last['period']}", 'is_currency': False})

        unavailable: List[str] = []
        def _check(key, data):
            if not data:
                unavailable.append(key)
            return data or []

        payload = {
            'database':             settings.hive_database,
            'generated_at':         datetime.now(timezone.utc).isoformat(),
            'kpis':                 kpis,
            'revenue_trend':        _check('revenue_trend',   revenue_trend),
            'payments':             _check('payments',         payments),
            'countries':            _check('countries',        countries),
            'category_rows':        _check('category_rows',    category_rows),
            'order_status':         _check('order_status',     order_status),
            'top_products':         _check('top_products',     top_products),
            'customer_growth':      _check('customer_growth',  customer_growth),
            'unavailable_sections': sorted(set(unavailable)),
        }
        self._cache    = payload
        self._cache_at = time.time()
        logger.info("Overview done: %d KPIs, %d unavailable sections", len(kpis), len(unavailable))
        return payload

    def is_cached(self) -> bool:
        cache_age = time.time() - self._cache_at
        return bool(self._cache) and cache_age < settings.overview_cache_ttl_seconds


overview_service = OverviewService()
