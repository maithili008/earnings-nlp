export default function SummaryCards({ backtest }) {
  if (!backtest) return null;
  const cards = [
    { label: "T+1 Accuracy",    value: `${(backtest.accuracy_t1 * 100).toFixed(1)}%`,  sub: `CI: ${(backtest.ci_t1[0]*100).toFixed(0)}%–${(backtest.ci_t1[1]*100).toFixed(0)}%`, color: "#3b82f6" },
    { label: "T+3 Accuracy",    value: `${(backtest.accuracy_t3 * 100).toFixed(1)}%`,  sub: "3-day horizon",   color: "#8b5cf6" },
    { label: "Pearson r",       value: `+${backtest.pearson_r.toFixed(3)}`,             sub: `p = ${backtest.pearson_p.toFixed(4)}`, color: "#10b981" },
    { label: "Transcripts",     value: backtest.total,                                  sub: `${Object.keys(backtest.per_ticker).length} tickers`, color: "#f59e0b" },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 32 }}>
      {cards.map(c => (
        <div key={c.label} style={{
          background: "#1e293b", borderRadius: 12, padding: "20px 24px",
          borderLeft: `4px solid ${c.color}`
        }}>
          <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 6 }}>{c.label}</div>
          <div style={{ color: "#f1f5f9", fontSize: 28, fontWeight: 700 }}>{c.value}</div>
          <div style={{ color: "#64748b", fontSize: 12, marginTop: 4 }}>{c.sub}</div>
        </div>
      ))}
    </div>
  );
}
