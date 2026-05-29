import React from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

const COLORS = ['#2563eb', '#14b8a6', '#8b5cf6', '#f59e0b', '#ef4444', '#06b6d4', '#22c55e'];

function formatLabel(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatNumber(value) {
  if (typeof value === 'number') {
    return new Intl.NumberFormat('fr-FR').format(value);
  }
  return value;
}

export default function ChartRenderer({ chart, data }) {
  if (!chart || !data?.length) return <p className="muted">Aucune donnée à visualiser.</p>;

  const { type, xKey, yKeys = [], title, valueKey } = chart;
  const resolvedXKey = xKey || Object.keys(data[0] || {})[0];
  const resolvedYKeys = yKeys.length ? yKeys : valueKey ? [valueKey] : [Object.keys(data[0] || {})[1]];
  const primaryYKey = resolvedYKeys[0];

  if (!primaryYKey && type !== 'table') {
    return <p className="muted">Aucune mesure numérique exploitable pour ce graphique.</p>;
  }

  const pieData = data.map((row) => ({
    name: formatLabel(row[resolvedXKey]),
    value: Number(row[primaryYKey] || 0),
  }));

  return (
    <section className="chart-renderer">
      <div className="chart-title-row">
        <h3>{title || 'Graphique'}</h3>
        <span className="soft-badge">{type || 'auto'}</span>
      </div>

      {type === 'kpi' ? (
        <div className="inline-kpi-card">
          <span className="kpi-label">{title || 'Indicateur'}</span>
          <strong>{formatNumber(Number(data[0]?.[primaryYKey] || data[0]?.[valueKey] || 0))}</strong>
          <span className="kpi-helper">{formatLabel(primaryYKey)}</span>
        </div>
      ) : type === 'table' ? (
        <p className="muted">Le mode tableau est affiché juste en dessous avec les données détaillées.</p>
      ) : (
        <div className="chart-canvas">
          <ResponsiveContainer>
            {type === 'line' ? (
              <LineChart data={data}>
                <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey={resolvedXKey} tickLine={false} axisLine={false} />
                <YAxis tickLine={false} axisLine={false} tickFormatter={formatNumber} />
                <Tooltip formatter={formatNumber} />
                <Legend />
                {resolvedYKeys.map((key, index) => (
                  <Line
                    key={key}
                    type="monotone"
                    dataKey={key}
                    stroke={COLORS[index % COLORS.length]}
                    strokeWidth={3}
                    dot={false}
                    name={formatLabel(key)}
                  />
                ))}
              </LineChart>
            ) : type === 'pie' || type === 'donut' ? (
              <PieChart>
                <Tooltip formatter={formatNumber} />
                <Legend verticalAlign="middle" align="right" layout="vertical" />
                <Pie
                  data={pieData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={type === 'donut' ? 58 : 0}
                  outerRadius={104}
                  paddingAngle={3}
                >
                  {pieData.map((entry, index) => (
                    <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
              </PieChart>
            ) : type === 'area' ? (
              <AreaChart data={data}>
                <defs>
                  <linearGradient id="resultAreaFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#2563eb" stopOpacity={0.28} />
                    <stop offset="95%" stopColor="#2563eb" stopOpacity={0.04} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey={resolvedXKey} tickLine={false} axisLine={false} />
                <YAxis tickLine={false} axisLine={false} tickFormatter={formatNumber} />
                <Tooltip formatter={formatNumber} />
                {resolvedYKeys.map((key, index) => (
                  <Area
                    key={key}
                    type="monotone"
                    dataKey={key}
                    stroke={COLORS[index % COLORS.length]}
                    strokeWidth={3}
                    fill={index === 0 ? 'url(#resultAreaFill)' : COLORS[index % COLORS.length]}
                    fillOpacity={index === 0 ? 1 : 0.14}
                    name={formatLabel(key)}
                  />
                ))}
              </AreaChart>
            ) : type === 'horizontalBar' ? (
              <BarChart data={data} layout="vertical" margin={{ left: 16, right: 16 }}>
                <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tickLine={false} axisLine={false} tickFormatter={formatNumber} />
                <YAxis type="category" dataKey={resolvedXKey} tickLine={false} axisLine={false} width={110} />
                <Tooltip formatter={formatNumber} />
                <Legend />
                {resolvedYKeys.map((key, index) => (
                  <Bar key={key} dataKey={key} fill={COLORS[index % COLORS.length]} radius={[0, 8, 8, 0]} name={formatLabel(key)} />
                ))}
              </BarChart>
            ) : (
              <BarChart data={data}>
                <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey={resolvedXKey} tickLine={false} axisLine={false} />
                <YAxis tickLine={false} axisLine={false} tickFormatter={formatNumber} />
                <Tooltip formatter={formatNumber} />
                <Legend />
                {resolvedYKeys.map((key, index) => (
                  <Bar
                    key={key}
                    dataKey={key}
                    fill={COLORS[index % COLORS.length]}
                    radius={[8, 8, 0, 0]}
                    name={formatLabel(key)}
                    stackId={type === 'stackedBar' ? 'stack-group' : undefined}
                  />
                ))}
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
