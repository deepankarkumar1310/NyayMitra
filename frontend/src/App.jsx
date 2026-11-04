import { useEffect, useRef, useState } from "react";
import { ask, getCase, listCases, transcribe } from "./api.js";
import Admin from "./Admin.jsx";
import { HELPLINES, LANGUAGES, STRINGS } from "./i18n.js";

function readPref(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

function writePref(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode) - ignore */
  }
}

function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

function useRecorder({ onAudio, onError }) {
  const [recording, setRecording] = useState(false);
  const recorderRef = useRef(null);

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      const parts = [];
      recorder.ondataavailable = (e) => e.data.size && parts.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        onAudio(new Blob(parts, { type: recorder.mimeType || "audio/webm" }));
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch {
      onError("micDenied");
    }
  }

  function stop() {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
  }

  return { recording, start, stop };
}

export default function App() {
  const route = useHashRoute();
  return route.startsWith("#/admin") ? <Admin /> : <WorkerApp />;
}

function WorkerApp() {
  const [language, setLanguage] = useState(() => {
    const saved = readPref("nm-lang", "hi");
    return STRINGS[saved] ? saved : "hi";
  });
  const [text, setText] = useState("");
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState(null); // "transcribing" | "thinking" | null
  const [error, setError] = useState("");
  const [answer, setAnswer] = useState(null);
  const [cases, setCases] = useState([]);
  const fileInput = useRef(null);
  const t = STRINGS[language];

  useEffect(() => {
    writePref("nm-lang", language);
    document.documentElement.lang = language;
    document.title = language === "en" ? "NyayMitra" : `${STRINGS[language].title} · NyayMitra`;
  }, [language]);

  useEffect(() => {
    refreshCases();
  }, []);

  function refreshCases() {
    listCases().then(setCases).catch(() => {});
  }

  function showError(err) {
    const key = typeof err === "string" ? err : err.message;
    setError(t[key] || key);
  }

  const recorder = useRecorder({
    onAudio: async (blob) => {
      setStatus("transcribing");
      try {
        const { text: heard } = await transcribe(blob, language);
        setText((prev) => (prev ? `${prev} ${heard}` : heard));
      } catch (err) {
        showError(err);
      } finally {
        setStatus(null);
      }
    },
    onError: showError,
  });

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setStatus("thinking");
    try {
      const result = await ask({ text, language, file });
      setAnswer(result);
      refreshCases();
    } catch (err) {
      showError(err);
    } finally {
      setStatus(null);
    }
  }

  async function openCase(id) {
    try {
      const c = await getCase(id);
      setAnswer({ id: c.id, question: c.question, ...c.answer });
      setText(c.question);
      if (STRINGS[c.language]) setLanguage(c.language);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      showError(err);
    }
  }

  const busy = status !== null;

  return (
    <div className="page">
      <header className="top">
        <div>
          <h1>⚖️ {t.title}</h1>
          <p className="tagline">{t.tagline}</p>
        </div>
        <label className="lang-select">
          <span aria-hidden="true">🌐</span>
          <select value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="Language / भाषा">
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
      </header>

      <main className="layout">
        <section>
          <form className="card ask" onSubmit={onSubmit}>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t.placeholder}
              rows={4}
              disabled={busy}
            />
            <div className="actions">
              <button
                type="button"
                className={`mic ${recorder.recording ? "on" : ""}`}
                onClick={recorder.recording ? recorder.stop : recorder.start}
                disabled={busy}
              >
                {recorder.recording ? `■ ${t.stop}` : `🎤 ${t.speak}`}
              </button>
              <button type="button" className="ghost" onClick={() => fileInput.current.click()} disabled={busy}>
                📎 {t.attach}
              </button>
              <input
                ref={fileInput}
                type="file"
                accept="application/pdf,image/jpeg,image/png,image/webp"
                hidden
                onChange={(e) => setFile(e.target.files[0] || null)}
              />
              <button type="submit" className="primary" disabled={busy || recorder.recording || (!text.trim() && !file)}>
                {t.submit}
              </button>
            </div>
            {file && (
              <p className="file">
                {file.name}{" "}
                <button
                  type="button"
                  className="link"
                  onClick={() => {
                    setFile(null);
                    fileInput.current.value = "";
                  }}
                >
                  {t.remove}
                </button>
              </p>
            )}
            {recorder.recording && <p className="status">🔴 {t.listening}</p>}
            {status && <p className="status">⏳ {t[status]}</p>}
            {error && <p className="error">{error}</p>}
          </form>

          {answer && <Answer answer={answer} t={t} />}

          <div className="card helplines">
            <h2>{t.helplines}</h2>
            <div className="chips">
              {HELPLINES.map((h) => (
                <a key={h.number} className="chip" href={`tel:${h.number}`}>
                  📞 {t.hl[h.key]} <strong>{h.number}</strong>
                </a>
              ))}
            </div>
          </div>
          <p className="disclaimer">
            {t.disclaimer} · <a href="#/admin">Dashboard</a>
          </p>
        </section>

        <aside className="card history">
          <h2>{t.history}</h2>
          {cases.length === 0 && <p className="muted">{t.noHistory}</p>}
          <ul>
            {cases.map((c) => (
              <li key={c.id}>
                <button type="button" onClick={() => openCase(c.id)}>
                  <span className={`dot ${c.urgency}`} />
                  <span className="q">{c.question || c.file_name || `#${c.id}`}</span>
                  <span className="muted small">{new Date(c.created_at).toLocaleDateString()}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
      </main>
    </div>
  );
}

function Answer({ answer, t }) {
  return (
    <article className="card answer">
      <div className="answer-head">
        <h2>{t.summary}</h2>
        <span className={`badge ${answer.urgency}`}>{t.urgency[answer.urgency] || answer.urgency}</span>
      </div>
      <p>{answer.summary}</p>
      {answer.not_found && <p className="warn">{t.notFound}</p>}

      <h3>{t.steps}</h3>
      <ol className="steps">
        {answer.steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>

      {answer.document_findings?.length > 0 && (
        <>
          <h3>{t.findings}</h3>
          <ul className="findings">
            {answer.document_findings.map((f, i) => (
              <li key={i}>⚠️ {f}</li>
            ))}
          </ul>
        </>
      )}

      {answer.sources?.length > 0 && (
        <>
          <h3>{t.sources}</h3>
          <div className="chips">
            {answer.sources.map((s) => (
              <a key={s.url} className="chip source" href={s.url} target="_blank" rel="noreferrer">
                🔗 {s.name}
              </a>
            ))}
          </div>
        </>
      )}
    </article>
  );
}
