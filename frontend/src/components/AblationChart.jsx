import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
         ReferenceLine, ResponsiveContainer } from "recharts";

export default function AblationChart({ backtest }) {
  if (!backtest?.ablation) return null;

  const data = Object.entries(backtest.ablation)
    .map(([label, v]) => ({
      label: label.replace(" only", "").replace("All signals combined", "Combined"),
      accuracy: +(v.accuracy * 100).toFixed(1),
      n: v.n,
    }))
    .sort((a, b) => b.accuracy - a.accuracy);

  return (
    <div style={{ background: "#1e293b", borderRadius: 12, padding: 24, marginBottom: 24 }}>
      <h3 style={{ color: "#f1f5f9", margin: "0 0 4px", fontSize: 15 }}>
        Ablation Study — Signal Contribution
      </h3>
      <p style={{ color: "#64748b", fontSize: 12, margin: "0 0 16px" }}>
        Which signals contribute most to directional accuracy?
      </p>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} layout="vertical"
                  margin={{ top: 4, right: 40, left: 100, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis type="number" domain={[45, 75]} tick={{ fill: "#94a3b8", fontSize: 11 }}
                 tickFormatter={v => `${v}%`} />
          <YAxis type="category" dataKey="label"
                 tick={{ fill: "#94a3b8", fontSize: 12 }} width={95} />
          <Tooltip
            formatter={(v, _, props) => [`${v}%  (n=${props.payload.n})`, "Accuracy"]}
            contentStyle={{ background: "#0f172a", border: "1px solid #334155" }}
            labelStyle={{ color: "#f1f5f9" }}
          />
          <ReferenceLine x={50} stroke="#ef4444" strokeDasharray="4 4" />
          <Bar dataKey="accuracy" fill="#10b981" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
