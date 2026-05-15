import { useApi } from "../hooks/useApi";

const TICKERS = ["BAC","BK","C","CFG","COF","FITB","GS","HBAN",
                 "JPM","KEY","MS","MTB","NTRS","PNC","RF","STT",
                 "TFC","USB","WFC","ZION"];
const PERIODS = ["Q1 2021","Q2 2021","Q3 2021","Q4 2021",
                 "Q1 2022","Q2 2022","Q3 2022","Q4 2022",
                 "Q1 2023","Q2 2023","Q3 2023","Q4 2023",
                 "Q1 2024","Q2 2024","Q3 2024","Q4 2024"];

function colorForValue(v) {
  if (v === null || v === undefined) return "#1e293b";
  if (v > 1.0)  return "#7f1d1d";
  if (v > 0.5)  return "#991b1b";
  if (v > 0.2)  return "#b45309";
  if (v > 0)    return "#854d0e";
  if (v > -0.2) return "#166534";
  if (v > -0.5) return "#15803d";
  return "#14532d";
}

export default function Heatmap() {
  const { data, loading } = useApi("/api/backtest/heatmap");

  if (loading) return (
    <div style={{ background: "#1e293b", borderRadius: 12, padding: 24, marginBottom: 24 }}>
      <p style={{ color: "#64748b" }}>Loading heatmap...</p>
    </div>
  );

  // Build lookup: symbol+period → composite
  const lookup = {};
  (data || []).forEach(d => {
    lookup[`${d.symbol}|${d.period}`] = {
      composite: d.composite,
      direction: d.direction,
      return_t1: d.return_t1,
    };
  });

  return (
    <div style={{ background: "#1e293b", borderRadius: 12, padding: 24, marginBottom: 24, overflowX: "auto" }}>
      <h3 style={{ color: "#f1f5f9", margin: "0 0 4px", fontSize: 15 }}>
        Evasiveness Heatmap
      </h3>
      <p style={{ color: "#64748b", fontSize: 12, margin: "0 0 16px" }}>
        Composite z-score per ticker per quarter. Red = unusually evasive, Green = unusually direct.
      </p>

      <div style={{ display: "flex", gap: 2 }}>
        {/* Y axis labels */}
        <div style={{ display: "flex", flexDirection: "column", gap: 2, paddingTop: 20 }}>
          {TICKERS.map(t => (
            <div key={t} style={{
              width: 44, height: 18, fontSize: 10, color: "#94a3b8",
              display: "flex", alignItems: "center", justifyContent: "flex-end",
              paddingRight: 6,
            }}>{t}</div>
          ))}
        </div>

        <div>
          {/* X axis labels */}
          <div style={{ display: "flex", gap: 2, marginBottom: 2 }}>
            {PERIODS.map(p => (
              <div key={p} style={{
                width: 32, fontSize: 8, color: "#64748b",
                transform: "rotate(-45deg)", transformOrigin: "left",
                height: 20, whiteSpace: "nowrap",
              }}>{p}</div>
            ))}
          </div>

          {/* Grid */}
          {TICKERS.map(ticker => (
            <div key={ticker} style={{ display: "flex", gap: 2, marginBottom: 2 }}>
              {PERIODS.map(period => {
                const cell = lookup[`${ticker}|${period}`];
                const v = cell?.composite;
                const dir = cell?.direction;
                const ret = cell?.return_t1;
                return (
                  <div
                    key={period}
                    title={cell
                      ? `${ticker} ${period}\nComposite: ${v?.toFixed(2)}\nDirection: ${dir}\nT+1: ${ret ? (ret*100).toFixed(1)+"%" : "n/a"}`
                      : `${ticker} ${period}: no data`}
                    style={{
                      width: 32, height: 18, borderRadius: 3,
                      background: colorForValue(v),
                      border: dir === "down" ? "1px solid rgba(239,68,68,0.4)"
                            : dir === "up"   ? "1px solid rgba(16,185,129,0.4)"
                            : "1px solid transparent",
                      cursor: "default",
                    }}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12 }}>
        <span style={{ color: "#64748b", fontSize: 11 }}>Low evasiveness</span>
        {["#14532d","#15803d","#166534","#854d0e","#b45309","#991b1b","#7f1d1d"].map(c => (
          <div key={c} style={{ width: 16, height: 16, borderRadius: 3, background: c }} />
        ))}
        <span style={{ color: "#64748b", fontSize: 11 }}>High evasiveness</span>
      </div>
    </div>
  );
}
