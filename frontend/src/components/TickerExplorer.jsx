import { useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
         ReferenceLine, ResponsiveContainer, Legend } from "recharts";
import { useApi } from "../hooks/useApi";

const TICKERS = [
  "BAC","BK","C","CFG","COF","FITB","GS","HBAN",
  "JPM","KEY","MS","MTB","NTRS","PNC","RF","STT",
  "TFC","USB","WFC","ZION",
];

export default function TickerExplorer() {
  const [ticker, setTicker] = useState("SIVB");
  const { data, loading } = useApi(ticker ? `/api/signals/${ticker}` : null);

  const chartData = data?.map(d => ({
    label:    `Q${d.quarter} ${d.year}`,
    hedging:  +(d.signals.hedging_zscore || 0).toFixed(3),
    guidance: +(d.signals.guidance_zscore || 0).toFixed(3),
    qa_vol:   +(d.signals.qa_vol_zscore || 0).toFixed(3),
    composite: +(d.signals.composite_rel || 0).toFixed(3),
    sent_drop: +(d.signals.sentiment_drop || 0).toFixed(3),
    return_t1: +(d.returns.t1 * 100 || 0).toFixed(2),
    direction: d.returns.direction_t1,
  })) || [];

  return (
    <div style={{ background: "#1e293b", borderRadius: 12, padding: 24, marginBottom: 24 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
        <h3 style={{ color: "#f1f5f9", margin: 0, fontSize: 15 }}>Ticker Explorer</h3>
        <select
          value={ticker}
          onChange={e => setTicker(e.target.value)}
          style={{
            background: "#0f172a", border: "1px solid #334155",
            color: "#f1f5f9", padding: "6px 12px", borderRadius: 6, fontSize: 13,
          }}
        >
          <option value="SIVB">SIVB (pre-collapse)</option>
          {TICKERS.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        {loading && <span style={{ color: "#64748b", fontSize: 12 }}>Loading...</span>}
      </div>

      {chartData.length > 0 && (
        <>
          <p style={{ color: "#64748b", fontSize: 12, margin: "0 0 12px" }}>
            Z-scores relative to this ticker's own baseline — deviations signal stress
          </p>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 10 }} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155" }}
                labelStyle={{ color: "#f1f5f9" }}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: "#94a3b8" }} />
              <ReferenceLine y={0} stroke="#475569" />
              <Line type="monotone" dataKey="composite" stroke="#3b82f6"
                    strokeWidth={2} dot={{ r: 3 }} name="Composite z-score" />
              <Line type="monotone" dataKey="sent_drop" stroke="#f59e0b"
                    strokeWidth={2} dot={{ r: 3 }} name="Sentiment drop" />
              <Line type="monotone" dataKey="return_t1" stroke="#10b981"
                    strokeWidth={1} strokeDasharray="4 4" dot={false} name="T+1 return %" />
            </LineChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  );
}
