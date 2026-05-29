import React from 'react';

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
  UK: '🇬🇧',
  'Royaume-Uni': '🇬🇧',
  Suisse: '🇨🇭',
  Portugal: '🇵🇹',
  Sénégal: '🇸🇳',
};

function formatHeader(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatCell(value) {
  if (typeof value === 'number') {
    return new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(value);
  }
  return String(value ?? '');
}

function isCountryColumn(name) {
  return /country|pays/i.test(name || '');
}

export default function DataTable({ columns = [], rows = [] }) {
  if (!columns.length) return null;

  return (
    <div className="table-wrapper modern-table">
      <table>
        <thead>
          <tr>{columns.map((col) => <th key={col}>{formatHeader(col)}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx}>
              {columns.map((col) => {
                const value = row[col];
                const numeric = typeof value === 'number';
                const withFlag = isCountryColumn(col);
                const flag = COUNTRY_FLAGS[value] || '🌍';

                return (
                  <td key={col} className={numeric ? 'numeric-cell' : ''}>
                    {withFlag ? (
                      <span className="cell-with-flag">
                        <span className="flag-circle">{flag}</span>
                        <span>{formatCell(value)}</span>
                      </span>
                    ) : (
                      formatCell(value)
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
