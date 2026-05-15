import { useState, useEffect } from "react";
import axios from "axios";

const BASE = process.env.REACT_APP_API_URL || "";

export function useApi(endpoint) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  useEffect(() => {
    if (!endpoint) return;
    setLoading(true);
    axios.get(`${BASE}${endpoint}`)
      .then(r => { setData(r.data); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [endpoint]);

  return { data, loading, error };
}
