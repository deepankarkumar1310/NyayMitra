import { useCallback, useEffect, useMemo, useState } from "react";
import { adminCases, adminDeleteCase, adminStats } from "./api.js";
import { LANGUAGES } from "./i18n.js";

const CRISIS_LABELS = {
  unpaid_wages: "Unpaid wages",
  termination: "Termination",
  injury: "Injury",
  harassment: "Harassment",
  documents: "Documents",
  schemes: "Schemes",
  jobs: "Jobs",
  social_security: "PF / ESI / gratuity",
  safety: "Safety",
  bonded_labour: "Bonded labour",
  child_labour: "Child labour",
  fraud: "Fraud",
  other: "Other",
  unknown: "Unknown",
};
const URGENCY_ORDER = ["critical", "high", "medium", "low"];
const URGENCY_LABELS = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };
const LANGUAGE_LABELS = Object.fromEntries(LANGUAGES.map((l) => [l.code, l.name]));

const pct = (v) => `${(v * 100).toFixed(0)}%`;
const secs = (ms) => (ms == null ? "–" : `${(ms / 1000).toFixed(1)} s`);

function readToken() {
  try {
    return sessionStorage.getItem("nm-admin-token") || "";
  } catch {
    return "";
  }
}

function saveToken(token) {
  try {
    sessionStorage.setItem("nm-admin-token", token);
  } catch {
    /* ignore */
  }
}

/* ---------- Charts ---------- */

function Tooltip({ tip }) {
  if (!tip) return null;
  return (
    <div className="tooltip" style={{ left: tip.x, top: tip.y }} role="status">
      <strong>{tip.value}</strong> {tip.label}
    </div>
  );
}

function useTooltip() {
  const [tip, setTip] = useState(null);
  const bind = (label, value) => ({
    onMouseMove: (e) => {
      const box = e.currentTarget.closest(".chart").getBoundingClientRect();
      setTip({ label, value, x: e.clientX - box.left + 12, y: e.clientY - box.top - 12 });
    },
    onMouseLeave: () => setTip(null),
    onFocus: (e) => {
      const box = e.currentTarget.closest(".chart").getBoundingClientRect();
      const r = e.currentTarget.getBoundingClientRect();
      setTip({ label, value, x: r.left - box.left + r.width / 2, y: r.top - box.top - 8 });
    },
    onBlur: () => setTip(null),
    tabIndex: 0,
  });
  return { tip, bind };
}

/** Horizontal bars: one series, sorted, value labelled at the bar end. */
function BarList({ rows, labelFor, colorFor, unit = "cases" }) {
  const { tip, bind } = useTooltip();
  const max = Math.max(1, ...rows.map((r) => r.count));
  if (!rows.length) return <p className="muted">No data yet</p>;
  return (
    <div className="chart barlist">
      {rows.map((r) => (
        <div className="barrow" key={r.key} {...bind(`${unit} · ${labelFor(r.key)}`, r.count)}>
          <span className="barlabel">{labelFor(r.key)}</span>
          <span className="bartrack">
            <span
              className={`bar ${colorFor ? colorFor(r.key) : ""}`}
              style={{ width: `${(r.count / max) * 100}%` }}
            />
          </span>
          <span className="barvalue">{r.count}</span>
        </div>
      ))}
      <Tooltip tip={tip} />
    </div>
  );
}

/** Vertical columns over time (one series). */
function Columns({ rows }) {
  const { tip, bind } = useTooltip();
  const max = Math.max(1, ...rows.map((r) => r.count));
  const ticks = [max, Math.round(max / 2), 0];
  const fmt = (d) => new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return (
    <div className="chart columns">
      <div className="yaxis">
        {ticks.map((t, i) => (
          <span key={i}>{t}</span>
        ))}
      </div>
      <div className="plot">
        <div className="grid">
          {ticks.map((_, i) => (
            <span key={i} />
          ))}
        </div>
        {rows.map((r) => (
          <div className="col" key={r.day} {...bind(`cases on ${fmt(r.day)}`, r.count)}>
            <span className="colbar" style={{ height: `${(r.count / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="xaxis">
        <span>{fmt(rows[0].day)}</span>
        <span>{fmt(rows[rows.length - 1].day)}</span>
      </div>
      <Tooltip tip={tip} />
    </div>
  );
}

function Stat({ label, value, note }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {note && <span className="stat-note">{note}</span>}
    </div>
  );
}

/* ---------- Page ---------- */

export default function Admin() {
  const [token, setToken] = useState(readToken);
  const [tokenInput, setTokenInput] = useState("");
  const [stats, setStats] = useState(null);
  const [cases, setCases] = useState([]);
  const [error, setError] = useState("");
  const [needsToken, setNeedsToken] = useState(false);
  const [filter, setFilter] = useState("all");

  const load = useCallback(async () => {
    setError("");
    try {
      const [s, c] = await Promise.all([adminStats(token), adminCases(token)]);
      setStats(s);
      setCases(c);
      setNeedsToken(false);
    } catch (err) {
      if (err.message.includes("token")) setNeedsToken(true);
      else setError(err.message === "network" ? "Could not reach the backend." : err.message);
    }
  }, [token]);

  useEffect(() => {
    document.title = "Dashboard · NyayMitra";
    load();
  }, [load]);

  async function remove(id) {
    if (!window.confirm(`Delete case #${id}? This cannot be undone.`)) return;
    try {
      await adminDeleteCase(token, id);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  const visible = useMemo(
    () => (filter === "all" ? cases : cases.filter((c) => c.crisis_type === filter)),
    [cases, filter]
  );

  if (needsToken) {
    return (
      <div className="page">
        <AdminHeader />
        <form
          className="card token"
          onSubmit={(e) => {
            e.preventDefault();
            saveToken(tokenInput);
            setToken(tokenInput);
          }}
        >
          <h2>Admin token required</h2>
          <p className="muted">Enter the ADMIN_TOKEN configured on the backend.</p>
          <input type="password" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} autoFocus />
          <button className="primary" type="submit">
            Open dashboard
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="page admin">
      <AdminHeader onRefresh={load} />
      {error && <p className="error">{error}</p>}
      {!stats ? (
        !error && <p className="muted">Loading…</p>
      ) : (
        <>
          <div className="stats">
            <Stat label="Total cases" value={stats.total_cases} />
            <Stat
              label="Median response time"
              value={secs(stats.latency_ms.p50)}
              note={`p95 ${secs(stats.latency_ms.p95)}`}
            />
            <Stat
              label="Answered from sources"
              value={stats.total_cases ? pct(1 - stats.not_found_rate) : "–"}
              note="rest fell back to helpline"
            />
            <Stat label="With a document" value={stats.with_document} />
          </div>

          <div className="admin-grid">
            <section className="card wide">
              <h2>Cases per day</h2>
              <p className="muted small">Last {stats.per_day.length} days</p>
              <Columns rows={stats.per_day} />
            </section>
            <section className="card">
              <h2>Problem type</h2>
              <BarList rows={stats.by_crisis_type} labelFor={(k) => CRISIS_LABELS[k] || k} />
            </section>
            <section className="card">
              <h2>Urgency</h2>
              <BarList
                rows={URGENCY_ORDER.map(
                  (k) => stats.by_urgency.find((r) => r.key === k) || { key: k, count: 0 }
                )}
                labelFor={(k) => URGENCY_LABELS[k] || k}
                colorFor={(k) => `status-${k}`}
              />
            </section>
            <section className="card">
              <h2>Language</h2>
              <BarList rows={stats.by_language} labelFor={(k) => LANGUAGE_LABELS[k] || k} />
            </section>
          </div>

          <section className="card">
            <div className="table-head">
              <h2>Cases</h2>
              <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by problem type">
                <option value="all">All problem types</option>
                {stats.by_crisis_type.map((r) => (
                  <option key={r.key} value={r.key}>
                    {CRISIS_LABELS[r.key] || r.key} ({r.count})
                  </option>
                ))}
              </select>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Date</th>
                    <th>Question</th>
                    <th>Type</th>
                    <th>Urgency</th>
                    <th>Lang</th>
                    <th className="num">Time</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((c) => (
                    <tr key={c.id}>
                      <td>{c.id}</td>
                      <td>{new Date(c.created_at).toLocaleString()}</td>
                      <td className="q">
                        {c.question || <em>{c.file_name}</em>}
                        {c.not_found && <span className="tag">not found</span>}
                      </td>
                      <td>{CRISIS_LABELS[c.crisis_type] || c.crisis_type}</td>
                      <td>
                        <span className={`dot ${c.urgency}`} /> {URGENCY_LABELS[c.urgency] || c.urgency}
                      </td>
                      <td>{c.language}</td>
                      <td className="num">{secs(c.latency_ms)}</td>
                      <td>
                        <button className="link danger" onClick={() => remove(c.id)}>
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!visible.length && (
                    <tr>
                      <td colSpan={8} className="muted">
                        No cases
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function AdminHeader({ onRefresh }) {
  return (
    <header className="top">
      <div>
        <h1>⚖️ NyayMitra · Dashboard</h1>
        <p className="tagline">Usage, response times and case history</p>
      </div>
      <div className="admin-actions">
        {onRefresh && (
          <button className="ghost" onClick={onRefresh}>
            ↻ Refresh
          </button>
        )}
        <a className="ghost" href="#/">
          ← Back to app
        </a>
      </div>
    </header>
  );
}
