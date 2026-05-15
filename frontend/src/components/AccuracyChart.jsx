import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
         ReferenceLine, ResponsiveContainer, Cell } from "recharts";

export default function AccuracyChart({ backtest }) {
  if (!backtest?.per_ticker) return null;

  const data = Object.entries(backtest.per_ticker)
    .map(([ticker, s]) => ({
      ticker,
      accuracy: +(s.accuracy * 100).toFixed(1),
      inverted: s.direction === "inverted",
    }))
    .sort((a, b) => b.accuracy - a.accuracy);

  return (
    <div style={{ background: "#1e293b", borderRadius: 12, padding: 24, marginBottom: 24 }}>
      <h3 style={{ color: "#f1f5f9", margin: "0 0 16px", fontSize: 15 }}>
        Per-Ticker T+1 Accuracy
        <span style={{ color: "#64748b", fontSize: 12, marginLeft: 12 }}>
          ↑ = inverted signal applied
        </span>
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="ticker" tick={{ fill: "#94a3b8", fontSize: 11 }} />
          <YAxis domain={[0, 100]} tick={{ fill: "#94a3b8", fontSize: 11 }}
                 tickFormatter={v => `${v}%`} />
          <Tooltip
            formatter={v => [`${v}%`, "Accuracy"]}
            contentStyle={{ background: "#0f172a", border: "1px solid #334155" }}
            labelStyle={{ color: "#f1f5f9" }}
          />
          <ReferenceLine y={50} stroke="#ef4444" strokeDasharray="4 4"
                         label={{ value: "50% baseline", fill: "#ef4444", fontSize: 11 }} />
          <Bar dataKey="accuracy" radius={[4, 4, 0, 0]}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.inverted ? "#8b5cf6" : "#3b82f6"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
