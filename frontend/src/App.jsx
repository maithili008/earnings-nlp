import { useApi } from "./hooks/useApi";
import SummaryCards  from "./components/SummaryCards";
import AccuracyChart from "./components/AccuracyChart";
import AblationChart from "./components/AblationChart";
import TickerExplorer from "./components/TickerExplorer";
import Heatmap       from "./components/Heatmap";

export default function App() {
  const { data: backtest, loading } = useApi("/api/backtest");

  return (
    <div style={{
      minHeight: "100vh", background: "#0f172a",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      padding: "32px 40px",
    }}>
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <h1 style={{ color: "#f1f5f9", margin: 0, fontSize: 22, fontWeight: 700 }}>
          Earnings Call NLP Signal Extractor
        </h1>
        <p style={{ color: "#64748b", margin: "6px 0 0", fontSize: 14 }}>
          CEO evasiveness detection across 344 earnings calls · 20 US banks · 2021–2024
        </p>
      </div>

      {loading ? (
        <p style={{ color: "#64748b" }}>Loading backtest results...</p>
      ) : (
        <>
          <SummaryCards  backtest={backtest} />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
            <AccuracyChart backtest={backtest} />
            <AblationChart backtest={backtest} />
          </div>
          <Heatmap />
          <TickerExplorer />
        </>
      )}

      <footer style={{ color: "#334155", fontSize: 11, marginTop: 32, textAlign: "center" }}>
        Stack: Python · HuggingFace (FinBERT · all-MiniLM-L6-v2) · FastAPI · React · SQLite
      </footer>
    </div>
  );
}
