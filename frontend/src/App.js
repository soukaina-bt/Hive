import React, { useEffect, useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { getOverview, getSchema, login, runNlq, runQuery } from './services/api';
import ChartRenderer from './components/ChartRenderer';
import DataTable from './components/DataTable';
import ExportButtons from './components/ExportButtons';
import statisticsIcon from './assets/statistics-icon.png';

const STORAGE_KEY = 'hive-dashboard-builder-session';
const DASHBOARD_WIDGETS_KEY = 'hive-dashboard-builder-widgets';
const initialCreds = { username: 'admin', password: 'admin123' };

const SAMPLE_QUESTIONS = [
  'Évolution mensuelle du volume des données par période',
  'Top 10 catégories par revenu ou par valeur',
  'Répartition des enregistrements par statut',
  'Comparer les indicateurs clés par pays ou région',
  'Afficher les tendances principales sur les 12 derniers mois',
  'Donner un classement des produits ou services les plus performants',
  'Mesurer la croissance des clients ou utilisateurs par mois',
  'Construire une vue synthétique des KPI importants',
];

const SAMPLE_SQL = `SELECT substr(CAST(order_date AS STRING), 1, 7) AS periode,
       ROUND(SUM(total_amount), 2) AS chiffre_affaires,
       COUNT(*) AS nb_commandes
FROM orders
GROUP BY substr(CAST(order_date AS STRING), 1, 7)
ORDER BY periode`;

const COLORS = ['#3b82f6', '#14b8a6', '#8b5cf6', '#f59e0b', '#ef4444', '#06b6d4', '#22c55e', '#f97316'];
const SECTION_TARGETS = {
  dashboard: 'dashboard-section',
  queries: 'queries-section',
  login: 'login-section',
};
const CHART_TYPES = [
  { value: 'auto', label: 'Auto' },
  { value: 'bar', label: 'Barres' },
  { value: 'stackedBar', label: 'Barres empilées' },
  { value: 'horizontalBar', label: 'Barres horizontales' },
  { value: 'line', label: 'Courbe' },
  { value: 'area', label: 'Aire' },
  { value: 'pie', label: 'Camembert' },
  { value: 'donut', label: 'Donut' },
  { value: 'kpi', label: 'KPI' },
  { value: 'table', label: 'Tableau' },
];
const SINGLE_MEASURE_TYPES = new Set(['pie', 'donut', 'kpi']);
const TABLE_ONLY_TYPES = new Set(['table']);

const COUNTRY_FLAGS = {
  France: '🇫🇷',
  Maroc: '🇲🇦',
  Tunisie: '🇹🇳',
  Algérie: '🇩🇿',
  Allemagne: '🇩🇪',
  Italie: '🇮🇹',
  Espagne: '🇪🇸',
  Belgique: '🇧🇪',
  Canada: '🇨🇦',
  'États-Unis': '🇺🇸',
  'United States': '🇺🇸',
  Royaume_Uni: '🇬🇧',
  'Royaume-Uni': '🇬🇧',
  UK: '🇬🇧',
  Suisse: '🇨🇭',
  Portugal: '🇵🇹',
  Égypte: '🇪🇬',
  Turquie: '🇹🇷',
  Sénégal: '🇸🇳',
  Cameroun: '🇨🇲',
  Pays_Bas: '🇳🇱',
  'Pays-Bas': '🇳🇱',
};

const EMPTY_OVERVIEW = {
  database: '',
  generated_at: '',
  kpis: [],
  revenue_trend: [],
  payments: [],
  countries: [],
  category_rows: [],
  order_status: [],
  top_products: [],
  customer_growth: [],
  unavailable_sections: [],
};

function formatNumber(value) {
  return new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(Number(value || 0));
}

function formatCurrency(value) {
  return new Intl.NumberFormat('fr-FR', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  }).format(Number(value || 0));
}

function formatLabel(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function getFlag(country) {
  return COUNTRY_FLAGS[country] || '🌍';
}

function buildSunburstData(rows) {
  if (!rows || !rows.length) return { categories: [], subCategories: [] };
  const categoryTotals = rows.reduce((acc, row) => {
    acc[row.category] = (acc[row.category] || 0) + Number(row.revenue || 0);
    return acc;
  }, {});

  const categories = Object.entries(categoryTotals).map(([name, value], index) => ({
    name,
    value,
    fill: COLORS[index % COLORS.length],
  }));

  const categoryIndex = Object.keys(categoryTotals).reduce((acc, key, index) => {
    acc[key] = index;
    return acc;
  }, {});

  const subCategories = rows.map((row, index) => {
    const hueIndex = categoryIndex[row.category] ?? index;
    return {
      name: row.sub_category,
      parent: row.category,
      value: Number(row.revenue || 0),
      fill: `hsl(${(hueIndex * 55 + index * 11) % 360} 78% 62%)`,
    };
  });

  return { categories, subCategories };
}

function isNumericValue(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function deriveColumnMeta(columns = [], rows = []) {
  const numeric = columns.filter((column) => {
    const values = rows.map((row) => row?.[column]).filter((value) => value !== null && value !== undefined && value !== '');
    if (!values.length) return false;
    return values.slice(0, 12).every((value) => isNumericValue(value));
  });

  const dimensions = columns.filter((column) => !numeric.includes(column));
  return { numeric, dimensions };
}

function buildDefaultTitle(type, xKey, yKeys) {
  if (type === 'kpi') {
    return formatLabel(yKeys[0] || 'indicateur');
  }
  if (type === 'table') {
    return 'Tableau détaillé';
  }
  return `${formatLabel(yKeys[0] || 'valeur')} par ${formatLabel(xKey || 'dimension')}`;
}

function buildChartBuilderFromResult(data) {
  if (!data?.columns?.length) {
    return { type: 'auto', title: '', xKey: '', yKeys: [] };
  }

  const meta = deriveColumnMeta(data.columns, data.rows || []);
  const suggestion = data.chart_suggestion || {};
  const suggestedYKeys = suggestion.yKeys?.length
    ? suggestion.yKeys
    : suggestion.valueKey
      ? [suggestion.valueKey]
      : meta.numeric.slice(0, 1);

  return {
    type: suggestion.type || 'auto',
    title: suggestion.title || '',
    xKey: suggestion.xKey || meta.dimensions[0] || data.columns[0] || '',
    yKeys: suggestedYKeys,
  };
}

function resolveChartConfig(result, chartBuilder) {
  if (!result?.columns?.length) return null;

  const meta = deriveColumnMeta(result.columns, result.rows || []);
  const suggestion = result.chart_suggestion || {};
  const preferredType = chartBuilder?.type || 'auto';
  const type = preferredType === 'auto' ? suggestion.type || 'bar' : preferredType;

  const fallbackYKeys = suggestion.yKeys?.length
    ? suggestion.yKeys
    : suggestion.valueKey
      ? [suggestion.valueKey]
      : meta.numeric.slice(0, type === 'stackedBar' ? 3 : 1);

  let yKeys = chartBuilder?.yKeys?.length ? chartBuilder.yKeys : fallbackYKeys;
  if (SINGLE_MEASURE_TYPES.has(type)) {
    yKeys = yKeys.slice(0, 1);
  }
  if (!yKeys.length && meta.numeric.length) {
    yKeys = meta.numeric.slice(0, SINGLE_MEASURE_TYPES.has(type) ? 1 : 2);
  }

  const xKey = chartBuilder?.xKey || suggestion.xKey || meta.dimensions[0] || result.columns[0];
  const title = chartBuilder?.title?.trim() || suggestion.title || buildDefaultTitle(type, xKey, yKeys);

  return {
    type,
    xKey,
    yKeys,
    valueKey: yKeys[0],
    title,
  };
}

function WidgetHeader({ title, subtitle, action }) {
  return (
    <div className="widget-header">
      <div>
        <h3>{title}</h3>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {action ? <div className="widget-header-action">{action}</div> : null}
    </div>
  );
}

function EmptyWidget({ title }) {
  return <p className="widget-note">{title}</p>;
}

function SkeletonKpi() {
  return (
    <article className="kpi-card skeleton-card">
      <span className="skeleton-line skeleton-short" />
      <strong className="skeleton-line skeleton-value" />
      <span className="skeleton-line skeleton-xshort" />
    </article>
  );
}

function SkeletonChart({ height = 220 }) {
  return (
    <div className="skeleton-chart" style={{ height }} />
  );
}

export default function App() {
  const [credentials, setCredentials] = useState(initialCreds);
  const [token, setToken] = useState('');
  const [schema, setSchema] = useState(null);
  const [question, setQuestion] = useState(SAMPLE_QUESTIONS[0]);
  const [sql, setSql] = useState(SAMPLE_SQL);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [overviewError, setOverviewError] = useState('');
  const [loading, setLoading] = useState(false);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewElapsed, setOverviewElapsed] = useState(0);
  const [activeTab, setActiveTab] = useState('nlq');
  const [activeNav, setActiveNav] = useState('dashboard');
  const [overview, setOverview] = useState(EMPTY_OVERVIEW);
  const [preferredChart, setPreferredChart] = useState('auto');
  const [chartBuilder, setChartBuilder] = useState({ type: 'auto', title: '', xKey: '', yKeys: [] });
  const [dashboardWidgets, setDashboardWidgets] = useState(() => {
    if (typeof window === 'undefined') return [];
    try {
      const raw = window.localStorage.getItem(DASHBOARD_WIDGETS_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  });

  const schemaText = useMemo(() => {
    if (!schema?.tables) return '';
    return Object.entries(schema.tables)
      .map(([table, columns]) => `${table}: ${columns.join(', ')}`)
      .join('\n');
  }, [schema]);

  const schemaEntries = useMemo(() => Object.entries(schema?.tables || {}), [schema]);
  const sunburstData = useMemo(() => buildSunburstData(overview.category_rows || []), [overview.category_rows]);
  const resultMeta = useMemo(() => deriveColumnMeta(result?.columns || [], result?.rows || []), [result]);
  const previewChart = useMemo(() => resolveChartConfig(result, chartBuilder), [result, chartBuilder]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(DASHBOARD_WIDGETS_KEY, JSON.stringify(dashboardWidgets));
  }, [dashboardWidgets]);

  const persistSession = (authToken, username) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: authToken, username }));
  };

  const clearSession = () => {
    localStorage.removeItem(STORAGE_KEY);
  };

  const syncChartBuilder = (data) => {
    setChartBuilder(buildChartBuilderFromResult(data));
  };

  const loadOverview = async (authToken, refresh = false) => {
    setOverviewLoading(true);
    setOverviewError('');
    setOverviewElapsed(0);
    if (refresh) setOverview(EMPTY_OVERVIEW);
    // elapsed updates handled by getOverview onProgress callback
    try {
      const data = await getOverview(authToken, refresh, (sec) => setOverviewElapsed(sec));
      // Merge with EMPTY_OVERVIEW so every field is guaranteed to be an array
      setOverview({ ...EMPTY_OVERVIEW, ...data });
      if (!data.kpis?.length) {
        setOverviewError(`Aucune métrique retournée par Hive. Vérifiez les logs backend — cherchez 'Overview: tables non trouvées' ou 'KPI(s) sans données'.`);
      }
    } catch (e) {
      setOverview(EMPTY_OVERVIEW);
      const detail = e?.response?.data?.detail;
      const status = e?.response?.status;
      const msg = detail
        ? `Erreur ${status || ''}: ${detail}`
        : `Impossible de charger le dashboard (${e?.message || 'erreur réseau'})`;
      setOverviewError(msg);
      console.error('[Overview]', e?.response?.data || e);
    } finally {
      // timer cleared by getOverview
      setOverviewLoading(false);
    }
  };

  const hydrateSession = async (authToken, username) => {
    setToken(authToken);
    setError('');
    if (username) {
      setCredentials((current) => ({ ...current, username }));
    }
    // Load schema and overview IN PARALLEL — much faster than sequential
    const [schemaData] = await Promise.all([
      getSchema(authToken),
      loadOverview(authToken),
    ]);
    setSchema(schemaData);
  };

  const handleLogout = () => {
    clearSession();
    setToken('');
    setSchema(null);
    setResult(null);
    setError('');
    setOverviewError('');
    setOverview(EMPTY_OVERVIEW);
    setActiveNav('dashboard');
  };

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return;

    const restore = async () => {
      try {
        const parsed = JSON.parse(stored);
        if (!parsed?.token) return;
        await hydrateSession(parsed.token, parsed.username || initialCreds.username);
      } catch (e) {
        handleLogout();
      }
    };

    restore();
  }, []);

  const scrollToSection = (navKey) => {
    const targetId = token ? SECTION_TARGETS[navKey] : SECTION_TARGETS.login;
    setActiveNav(navKey);
    const section = document.getElementById(targetId);
    if (section) {
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const handleLogin = async () => {
    try {
      setError('');
      const data = await login(credentials);
      persistSession(data.access_token, credentials.username);
      await hydrateSession(data.access_token, credentials.username);
    } catch (e) {
      clearSession();
      setError(e?.response?.data?.detail || 'Connexion impossible');
    }
  };

  const handleNlq = async () => {
    try {
      setLoading(true);
      setError('');
      const data = await runNlq(token, { question, schema_context: schemaText, preferred_chart: preferredChart });
      setResult(data);
      if (data?.sql) {
        setSql(data.sql);
      }
      syncChartBuilder(data);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Erreur lors de la génération de la requête');
    } finally {
      setLoading(false);
    }
  };

  const handleSqlRun = async () => {
    try {
      setLoading(true);
      setError('');
      const data = await runQuery(token, { sql, preferred_chart: preferredChart });
      setResult(data);
      syncChartBuilder(data);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Erreur SQL');
    } finally {
      setLoading(false);
    }
  };

  const handleChartTypeChange = (nextType) => {
    setPreferredChart(nextType);
    setChartBuilder((current) => {
      const normalizedYKeys = SINGLE_MEASURE_TYPES.has(nextType) ? current.yKeys.slice(0, 1) : current.yKeys;
      return {
        ...current,
        type: nextType,
        yKeys: normalizedYKeys.length ? normalizedYKeys : resultMeta.numeric.slice(0, SINGLE_MEASURE_TYPES.has(nextType) ? 1 : 2),
      };
    });
  };

  const handlePrimaryMetricChange = (metric) => {
    setChartBuilder((current) => {
      const remaining = current.yKeys.filter((item) => item !== metric);
      const nextYKeys = SINGLE_MEASURE_TYPES.has(current.type) ? [metric] : [metric, ...remaining].slice(0, 3);
      return {
        ...current,
        yKeys: nextYKeys,
      };
    });
  };

  const toggleAdditionalMetric = (metric) => {
    setChartBuilder((current) => {
      if (SINGLE_MEASURE_TYPES.has(current.type)) {
        return { ...current, yKeys: [metric] };
      }

      const exists = current.yKeys.includes(metric);
      if (exists) {
        const next = current.yKeys.filter((item) => item !== metric);
        return { ...current, yKeys: next.length ? next : [metric] };
      }

      return { ...current, yKeys: [...current.yKeys, metric].slice(0, 3) };
    });
  };

  const handleAddWidget = () => {
    if (!result?.rows?.length || !previewChart) return;
    const widget = {
      id: `widget-${Date.now()}`,
      title: previewChart.title,
      chart: previewChart,
      data: result.rows,
      columns: result.columns,
      sql: result.sql,
      createdAt: new Date().toISOString(),
    };
    setDashboardWidgets((current) => [widget, ...current].slice(0, 12));
    scrollToSection('dashboard');
  };

  const handleRemoveWidget = (widgetId) => {
    setDashboardWidgets((current) => current.filter((item) => item.id !== widgetId));
  };

  const handleClearWidgets = () => {
    setDashboardWidgets([]);
  };

  return (
    <div className="app-shell">
      <header className={`topbar ${token ? '' : 'topbar-public'}`}>
        <div className="brand-block">
          <div className="brand-badge image-badge">
            <img src={statisticsIcon} alt="Icône statistiques" />
          </div>
          <div>
            <h1>Hive Dashboard Builder</h1>
            <p>Visual analytics pour Apache Hive avec requêtes en langage naturel, SQL et dashboard visuel.</p>
          </div>
        </div>

        {token ? (
          <>
            <nav className="top-nav" aria-label="Navigation principale">
              <button className={activeNav === 'dashboard' ? 'nav-link active' : 'nav-link'} onClick={() => scrollToSection('dashboard')}>
                Dashboard
              </button>
              <button className={activeNav === 'queries' ? 'nav-link active' : 'nav-link'} onClick={() => scrollToSection('queries')}>
                Analyses
              </button>
            </nav>

            <div className="top-actions">
              <div className={`status-pill ${token ? 'online' : 'offline'}`}>
                <span className="status-dot" />
                {schema?.database || 'default'}
              </div>
              <button className="secondary-button" onClick={() => loadOverview(token, true)} disabled={overviewLoading}>
                {overviewLoading ? `Chargement… ${overviewElapsed}s` : 'Actualiser'}
              </button>
              <button className="secondary-button logout-button" onClick={handleLogout}>
                Se déconnecter
              </button>
            </div>
          </>
        ) : (
          <div className="public-top-copy">
            <span className="eyebrow">Connexion</span>
            <p>Accès à l’espace de pilotage Hive et au dashboard builder.</p>
          </div>
        )}
      </header>

      {!token ? (
        <section className="login-layout simple" id="login-section">
          <div className="login-hero card">
            <span className="eyebrow">Visual analytics</span>
            <h2>Créez des dashboards à partir de vos données Apache Hive</h2>
            <p className="panel-copy">
              Cette interface permet de charger les données réelles depuis Hive, d’exécuter des requêtes SQL ou en langage naturel,
              puis de composer un dashboard avec les graphiques de votre choix.
            </p>
            <ul className="intro-list">
              <li>Connexion directe à Hive</li>
              <li>Analyse NLQ + SQL dans la même interface</li>
              <li>Construction visuelle d’un dashboard personnalisé</li>
            </ul>
          </div>

          <div className="login-panel card">
            <span className="eyebrow">Accès sécurisé</span>
            <h2>Se connecter</h2>
            <p className="panel-copy">Entrez vos identifiants pour afficher le dashboard et les analyses.</p>
            <div className="grid-2 compact single-column-mobile">
              <input
                placeholder="Nom d'utilisateur"
                value={credentials.username}
                onChange={(e) => setCredentials({ ...credentials, username: e.target.value })}
              />
              <input
                placeholder="Mot de passe"
                type="password"
                value={credentials.password}
                onChange={(e) => setCredentials({ ...credentials, password: e.target.value })}
              />
            </div>
            <div className="login-actions">
              <button onClick={handleLogin}>Se connecter</button>
              <span className="muted small">Le schéma Hive et les données seront chargés après authentification.</span>
            </div>
            {error ? <p className="error">{error}</p> : null}
          </div>
        </section>
      ) : (
        <div className="workspace">
          <aside className="sidebar card">
            <div className="sidebar-section">
              <span className="eyebrow">Base active</span>
              <h2>{schema?.database || 'default'}</h2>
              <p className="muted">Schéma utilisé pour le dashboard builder, les questions métier et les requêtes HiveQL.</p>
              <div className="sidebar-status-list">
                <div className="sidebar-status-item">
                  <span>Session</span>
                  <strong>Active</strong>
                </div>
                <div className="sidebar-status-item">
                  <span>Dernière mise à jour</span>
                  <strong>{overview.generated_at ? new Date(overview.generated_at).toLocaleString('fr-FR') : 'En attente'}</strong>
                </div>
                <div className="sidebar-status-item">
                  <span>Tables détectées</span>
                  <strong>{schemaEntries.length}</strong>
                </div>
              </div>
              {overviewError ? <p className="error subtle">{overviewError}</p> : null}
            </div>

            <div className="sidebar-section">
              <div className="section-title-row">
                <h3>Tables</h3>
                <span className="soft-badge">{schemaEntries.length}</span>
              </div>
              <div className="schema-list">
                {schemaEntries.map(([table, columns]) => (
                  <details key={table} className="schema-item" open={table === 'orders' || table === 'customers'}>
                    <summary>
                      <span>{table}</span>
                      <span className="muted small">{columns.length} champs</span>
                    </summary>
                    <ul>
                      {columns.map((column) => (
                        <li key={`${table}-${column}`}>{column}</li>
                      ))}
                    </ul>
                  </details>
                ))}
              </div>
            </div>
          </aside>

          <main className="content-area">
            <section className="overview-grid" id="dashboard-section">
              <div className="section-heading-row">
                <div>
                  <span className="eyebrow">Dashboard</span>
                  <h2 className="section-heading">Indicateurs et widgets visuels</h2>
                </div>
                {overview.unavailable_sections?.length ? (
                  <p className="muted compact-text">Certaines zones restent vides si les colonnes nécessaires n’existent pas encore côté backend.</p>
                ) : null}
              </div>

              <div className="kpi-grid expanded">
                {overviewLoading && !(overview.kpis || []).length ? (
                  [1,2,3,4,5,6].map((n) => <SkeletonKpi key={n} />)
                ) : (overview.kpis || []).length ? (
                  (overview.kpis || []).map((item) => (
                    <article key={item.label} className="kpi-card">
                      <span className="kpi-label">{item.label}</span>
                      <strong>{item.is_currency ? formatCurrency(item.value) : formatNumber(item.value)}</strong>
                      <span className="kpi-helper">{item.helper}</span>
                    </article>
                  ))
                ) : (
                  <article className="widget card empty-widget-card">
                    <WidgetHeader title="Aucune métrique disponible" subtitle="Le backend doit remonter les indicateurs pour remplir cette zone." />
                  </article>
                )}
              </div>

              <article className="widget card dashboard-builder-widget">
                <WidgetHeader
                  title="Dashboard builder"
                  subtitle="Ajoutez vos graphiques personnalisés depuis les résultats d’analyse."
                  action={
                    dashboardWidgets.length ? (
                      <button className="ghost-inline-button" onClick={handleClearWidgets}>
                        Vider les widgets
                      </button>
                    ) : (
                      <span className="widget-action">{dashboardWidgets.length} widget</span>
                    )
                  }
                />
                {dashboardWidgets.length ? (
                  <div className="saved-dashboard-grid">
                    {dashboardWidgets.map((widget) => (
                      <article key={widget.id} className="saved-widget-card">
                        <div className="saved-widget-header">
                          <div>
                            <h4>{widget.title}</h4>
                            <span className="muted small">Ajouté le {new Date(widget.createdAt).toLocaleString('fr-FR')}</span>
                          </div>
                          <button className="ghost-inline-button" onClick={() => handleRemoveWidget(widget.id)}>
                            Supprimer
                          </button>
                        </div>
                        {widget.chart?.type === 'table' ? (
                          <DataTable columns={widget.columns} rows={widget.data.slice(0, 12)} />
                        ) : (
                          <ChartRenderer chart={widget.chart} data={widget.data} />
                        )}
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="empty-builder-state">
                    <h3>Commencez votre dashboard personnalisé</h3>
                    <p className="muted">
                      Lancez une analyse, choisissez un type de graphique, puis ajoutez la visualisation à votre dashboard.
                    </p>
                  </div>
                )}
              </article>

              <article className="widget widget-xl card">
                <WidgetHeader
                  title="Vue revenus"
                  subtitle="Évolution mensuelle du chiffre d’affaires réel"
                  action={overviewLoading ? <span className="widget-action">Actualisation…</span> : <span className="widget-action">Données Hive</span>}
                />
                <div className="chart-box large">
                  {overviewLoading && !(overview.revenue_trend || []).length ? (
                    <SkeletonChart height={240} />
                  ) : (overview.revenue_trend || []).length ? (
                    <ResponsiveContainer>
                      <AreaChart data={overview.revenue_trend}>
                        <defs>
                          <linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.32} />
                            <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.04} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="period" tickLine={false} axisLine={false} />
                        <YAxis tickFormatter={(value) => formatNumber(value)} tickLine={false} axisLine={false} />
                        <Tooltip formatter={(value) => formatCurrency(value)} />
                        <Area type="monotone" dataKey="revenue" stroke="#2563eb" strokeWidth={3} fill="url(#revenueFill)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  ) : (
                    <EmptyWidget title="Aucune série de revenus disponible." />
                  )}
                </div>
              </article>

              <article className="widget card">
                <WidgetHeader title="Parcours revenu" subtitle="Catégories et sous-catégories produits" action={<span className="widget-action">Vue hiérarchique</span>} />
                <div className="chart-box">
                  {sunburstData.categories.length ? (
                    <ResponsiveContainer>
                      <PieChart>
                        <Tooltip formatter={(value) => formatCurrency(value)} />
                        <Pie
                          data={sunburstData.categories}
                          dataKey="value"
                          nameKey="name"
                          innerRadius={52}
                          outerRadius={88}
                          paddingAngle={2}
                        >
                          {sunburstData.categories.map((entry) => (
                            <Cell key={entry.name} fill={entry.fill} />
                          ))}
                        </Pie>
                        <Pie
                          data={sunburstData.subCategories}
                          dataKey="value"
                          nameKey="name"
                          innerRadius={96}
                          outerRadius={132}
                          paddingAngle={1}
                        >
                          {sunburstData.subCategories.map((entry) => (
                            <Cell key={`${entry.parent}-${entry.name}`} fill={entry.fill} />
                          ))}
                        </Pie>
                      </PieChart>
                    </ResponsiveContainer>
                  ) : (
                    <EmptyWidget title="Les données catégories / sous-catégories ne sont pas encore disponibles." />
                  )}
                </div>
                {sunburstData.categories.length ? (
                  <div className="legend-list compact">
                    {sunburstData.categories.slice(0, 4).map((entry) => (
                      <div key={entry.name} className="legend-item">
                        <span className="legend-swatch" style={{ background: entry.fill }} />
                        <span>{entry.name}</span>
                        <strong>{formatCurrency(entry.value)}</strong>
                      </div>
                    ))}
                  </div>
                ) : null}
              </article>

              <div className="widget-pair">
                <article className="widget widget-donut card">
                  <WidgetHeader title="Moyens de paiement" subtitle="Répartition des commandes par mode de paiement" action={<span className="widget-action">Top modes</span>} />
                  <div className="chart-box medium">
                    {overviewLoading && !(overview.payments || []).length ? (
                      <SkeletonChart height={200} />
                    ) : (overview.payments || []).length ? (
                      <ResponsiveContainer>
                        <PieChart>
                          <Pie
                            data={overview.payments}
                            dataKey="value"
                            nameKey="label"
                            innerRadius={62}
                            outerRadius={108}
                            paddingAngle={3}
                          >
                            {(overview.payments || []).map((entry, index) => (
                              <Cell key={entry.label} fill={COLORS[index % COLORS.length]} />
                            ))}
                          </Pie>
                          <Tooltip formatter={(value) => formatNumber(value)} />
                        </PieChart>
                      </ResponsiveContainer>
                    ) : (
                      <EmptyWidget title="Aucune répartition de paiement disponible." />
                    )}
                  </div>
                  {(overview.payments || []).length ? (
                    <div className="legend-list">
                      {(overview.payments || []).map((entry, index) => (
                        <div key={entry.label} className="legend-item">
                          <span className="legend-swatch" style={{ background: COLORS[index % COLORS.length] }} />
                          <span>{formatLabel(entry.label)}</span>
                          <strong>{formatNumber(entry.value)}</strong>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </article>

                <article className="widget widget-countries card">
                  <WidgetHeader title="Pays performants" subtitle="Top pays par commandes et chiffre d’affaires" action={<span className="widget-action">Vue géographique</span>} />
                  <div className="country-table">
                    <div className="country-table-head">
                      <span>Pays</span>
                      <span>Commandes</span>
                      <span>Revenu</span>
                    </div>
                    {(overview.countries || []).length ? (
                      (overview.countries || []).map((row) => (
                        <div key={row.country} className="country-row">
                          <div className="country-name">
                            <span className="flag-circle">{getFlag(row.country)}</span>
                            <span>{formatLabel(row.country)}</span>
                          </div>
                          <span>{formatNumber(row.orders_count)}</span>
                          <strong>{formatCurrency(row.revenue)}</strong>
                        </div>
                      ))
                    ) : (
                      <div className="empty-list-row">Aucune donnée pays disponible.</div>
                    )}
                  </div>
                </article>
              </div>

              <div className="widget-pair widget-pair-extended">
                <article className="widget card">
                  <WidgetHeader title="Statut des commandes" subtitle="Volume par état de traitement" action={<span className="widget-action">Temps réel</span>} />
                  <div className="chart-box medium">
                    {overviewLoading && !(overview.order_status || []).length ? (
                      <SkeletonChart height={200} />
                    ) : (overview.order_status || []).length ? (
                      <ResponsiveContainer>
                        <BarChart data={overview.order_status}>
                          <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
                          <XAxis dataKey="label" tickLine={false} axisLine={false} />
                          <YAxis tickLine={false} axisLine={false} tickFormatter={formatNumber} />
                          <Tooltip formatter={(value) => formatNumber(value)} />
                          <Bar dataKey="value" fill="#14b8a6" radius={[8, 8, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <EmptyWidget title="Aucune donnée de statut disponible." />
                    )}
                  </div>
                </article>

                <article className="widget card">
                  <WidgetHeader title="Croissance clients" subtitle="Évolution mensuelle des nouvelles inscriptions" action={<span className="widget-action">Acquisition</span>} />
                  <div className="chart-box medium">
                    {overviewLoading && !(overview.customer_growth || []).length ? (
                      <SkeletonChart height={200} />
                    ) : (overview.customer_growth || []).length ? (
                      <ResponsiveContainer>
                        <LineChart data={overview.customer_growth}>
                          <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
                          <XAxis dataKey="period" tickLine={false} axisLine={false} />
                          <YAxis tickLine={false} axisLine={false} tickFormatter={formatNumber} />
                          <Tooltip formatter={(value) => formatNumber(value)} />
                          <Line type="monotone" dataKey="value" stroke="#8b5cf6" strokeWidth={3} dot={{ r: 3 }} />
                        </LineChart>
                      </ResponsiveContainer>
                    ) : (
                      <EmptyWidget title="Aucune donnée de croissance clients disponible." />
                    )}
                  </div>
                </article>
              </div>

              <article className="widget card">
                <WidgetHeader title="Top produits" subtitle="Produits les plus performants selon le revenu réel" action={<span className="widget-action">Top 12</span>} />
                {(overview.top_products || []).length ? (
                  <DataTable columns={['product', 'revenue', 'quantity', 'orders_count']} rows={overview.top_products} />
                ) : (
                  <EmptyWidget title="Le backend ne remonte pas encore de classement produits." />
                )}
              </article>
            </section>

            <section className="query-studio card" id="queries-section">
              <div className="studio-header">
                <div>
                  <span className="eyebrow">Analyses</span>
                  <h2>Questions métier et exécution SQL</h2>
                </div>
                <div className="query-tabs">
                  <button className={activeTab === 'nlq' ? 'tab active' : 'tab'} onClick={() => setActiveTab('nlq')}>
                    Langage naturel
                  </button>
                  <button className={activeTab === 'sql' ? 'tab active' : 'tab'} onClick={() => setActiveTab('sql')}>
                    Éditeur SQL
                  </button>
                </div>
              </div>

              <div className="chart-preference-row">
                <label className="field-group inline-field compact-field">
                  <span>Graphique souhaité</span>
                  <select value={preferredChart} onChange={(e) => handleChartTypeChange(e.target.value)}>
                    {CHART_TYPES.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="muted small">Vous pouvez garder “Auto” ou imposer un type de visualisation dès l’exécution.</span>
              </div>

              {activeTab === 'nlq' && (
                <>
                  <div className="pill-row">
                    {SAMPLE_QUESTIONS.map((item) => (
                      <button key={item} className="pill" onClick={() => setQuestion(item)}>
                        {item}
                      </button>
                    ))}
                  </div>
                  <textarea
                    className="editor-input"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    rows={3}
                    placeholder="Pose une question métier en français"
                  />
                  <div className="studio-actions">
                    <button onClick={handleNlq} disabled={loading}>
                      {loading ? 'Génération…' : 'Générer la requête'}
                    </button>
                    <span className="muted small">Le SQL généré reste modifiable avant exécution.</span>
                  </div>
                </>
              )}

              {activeTab === 'sql' && (
                <>
                  <textarea
                    className="editor-input code"
                    value={sql}
                    onChange={(e) => setSql(e.target.value)}
                    rows={10}
                    placeholder="Écris ou colle une requête HiveQL"
                  />
                  <div className="studio-actions">
                    <button onClick={handleSqlRun} disabled={loading}>
                      {loading ? 'Exécution…' : 'Exécuter'}
                    </button>
                    <span className="muted small">Le backend accepte uniquement les requêtes de lecture.</span>
                  </div>
                </>
              )}
            </section>

            <section className="results-panel card" id="export-zone">
              <div className="results-header">
                <div>
                  <span className="eyebrow">Résultats</span>
                  <h2>Visualisations et tableau détaillé</h2>
                </div>
                <ExportButtons targetId="export-zone" title="hive-dashboard-builder" />
              </div>

              {error ? <p className="error">{error}</p> : null}

              {result ? (
                <>
                  {result.sql ? (
                    <details className="sql-preview">
                      <summary>SQL exécuté</summary>
                      <pre>{result.sql}</pre>
                    </details>
                  ) : null}

                  <div className="result-summary">
                    <div>
                      <span className="muted small">Lignes retournées</span>
                      <strong>{formatNumber(result.row_count || result.rows?.length || 0)}</strong>
                    </div>
                    <div>
                      <span className="muted small">Colonnes</span>
                      <strong>{formatNumber(result.columns?.length || 0)}</strong>
                    </div>
                    <div>
                      <span className="muted small">Statut</span>
                      <strong>Exécuté</strong>
                    </div>
                  </div>

                  <p className="muted">{result.explanation}</p>

                  {result.rows?.length ? (
                    <div className="chart-builder-panel">
                      <div className="section-title-row">
                        <h3>Construire la visualisation</h3>
                        <span className="soft-badge">{resultMeta.numeric.length} mesure(s)</span>
                      </div>

                      <div className="chart-builder-grid">
                        <label className="field-group">
                          <span>Type</span>
                          <select value={chartBuilder.type || 'auto'} onChange={(e) => handleChartTypeChange(e.target.value)}>
                            {CHART_TYPES.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </label>

                        {!TABLE_ONLY_TYPES.has(chartBuilder.type) ? (
                          <label className="field-group">
                            <span>Axe X / dimension</span>
                            <select
                              value={chartBuilder.xKey || resultMeta.dimensions[0] || result.columns[0] || ''}
                              onChange={(e) => setChartBuilder((current) => ({ ...current, xKey: e.target.value }))}
                            >
                              {[...resultMeta.dimensions, ...result.columns.filter((col) => !resultMeta.dimensions.includes(col))].map((column) => (
                                <option key={column} value={column}>
                                  {formatLabel(column)}
                                </option>
                              ))}
                            </select>
                          </label>
                        ) : null}

                        {!TABLE_ONLY_TYPES.has(chartBuilder.type) ? (
                          <label className="field-group">
                            <span>Mesure principale</span>
                            <select
                              value={chartBuilder.yKeys[0] || resultMeta.numeric[0] || ''}
                              onChange={(e) => handlePrimaryMetricChange(e.target.value)}
                            >
                              {resultMeta.numeric.map((column) => (
                                <option key={column} value={column}>
                                  {formatLabel(column)}
                                </option>
                              ))}
                            </select>
                          </label>
                        ) : null}

                        <label className="field-group field-group-wide">
                          <span>Titre</span>
                          <input
                            value={chartBuilder.title}
                            onChange={(e) => setChartBuilder((current) => ({ ...current, title: e.target.value }))}
                            placeholder="Titre du widget"
                          />
                        </label>
                      </div>

                      {!TABLE_ONLY_TYPES.has(chartBuilder.type) && resultMeta.numeric.length > 1 && !SINGLE_MEASURE_TYPES.has(chartBuilder.type) ? (
                        <div className="metric-chip-group">
                          <span className="muted small">Mesures supplémentaires</span>
                          <div className="chip-row">
                            {resultMeta.numeric.map((column) => {
                              const active = chartBuilder.yKeys.includes(column);
                              return (
                                <button
                                  key={column}
                                  type="button"
                                  className={active ? 'metric-chip active' : 'metric-chip'}
                                  onClick={() => toggleAdditionalMetric(column)}
                                >
                                  {formatLabel(column)}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      ) : null}

                      <div className="studio-actions compact-actions">
                        <button onClick={handleAddWidget}>Ajouter au dashboard</button>
                        <span className="muted small">Le graphique ci-dessous suit votre configuration actuelle.</span>
                      </div>
                    </div>
                  ) : null}

                  {previewChart?.type === 'table' ? <DataTable columns={result.columns} rows={result.rows} /> : <ChartRenderer chart={previewChart} data={result.rows} />}
                  {previewChart?.type !== 'table' ? <DataTable columns={result.columns} rows={result.rows} /> : null}
                </>
              ) : (
                <div className="empty-state">
                  <h3>Prêt pour la première analyse</h3>
                  <p className="muted">
                    Utilise une question métier ou une requête SQL pour alimenter les graphiques, choisir un visuel, puis construire ton dashboard.
                  </p>
                </div>
              )}
            </section>
          </main>
        </div>
      )}
    </div>
  );
}
