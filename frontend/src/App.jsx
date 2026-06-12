import { useState, useRef, useEffect, useCallback } from "react";
import {
  Mic, Film, Merge, CheckCircle, Loader, Upload,
  Link, FileText, Download, ChevronRight, AlertCircle, X, Zap, Clock,
  Play, Pause, Square, Save, FolderOpen, Trash2, Edit2, Settings
} from "lucide-react";

// When served by the packaged backend (port 8765) or the dev backend (port 8000),
// use the same origin so API calls work regardless of which port is in use.
// In Vite dev mode the frontend is on :5173, so we fall back to :8000.
const API_BASE = window.location.port === "5173"
  ? "http://localhost:8000"
  : window.location.origin;

async function pollJob(jobId, onProgress) {
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const r = await fetch(`${API_BASE}/api/status/${jobId}`);
        const data = await r.json();
        onProgress(data.progress, data.message);
        if (data.status === "done") return resolve(data.result);
        if (data.status === "error") return reject(new Error(data.error));
        setTimeout(tick, 1500);
      } catch (e) { reject(e); }
    };
    tick();
  });
}

function StepBadge({ n, done, active }) {
  const base = "w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all";
  if (done) return <div className={`${base} bg-green-500 text-white`}><CheckCircle size={16} /></div>;
  if (active) return <div className={`${base} bg-indigo-500 text-white animate-pulse`}>{n}</div>;
  return <div className={`${base} bg-slate-700 text-slate-400`}>{n}</div>;
}

function ProgressBar({ value, label }) {
  return (
    <div className="mt-3">
      <div className="flex justify-between text-xs text-slate-400 mb-1">
        <span>{label}</span><span>{value}%</span>
      </div>
      <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
        <div className="h-full bg-indigo-500 rounded-full transition-all duration-500" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function ProviderBadge({ provider }) {
  const colors = {
    elevenlabs: "bg-yellow-500/20 text-yellow-300 border-yellow-500/40",
    openai:     "bg-green-500/20 text-green-300 border-green-500/40",
    google:     "bg-blue-500/20 text-blue-300 border-blue-500/40",
    gemini:     "bg-purple-500/20 text-purple-300 border-purple-500/40",
  };
  const labels = { elevenlabs: "ElevenLabs", openai: "OpenAI TTS", google: "Google TTS", gemini: "Gemini TTS" };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${colors[provider] || "bg-slate-700 text-slate-300 border-slate-600"}`}>
      {labels[provider] || provider}
    </span>
  );
}

// ── Settings Modal ────────────────────────────────────────────────────────────
function SettingsModal({ onClose, onSaved }) {
  const [form, setForm] = useState({ tts_provider: "elevenlabs", elevenlabs_api_key: "", openai_api_key: "", google_cloud_api_key: "", gemini_api_key: "", google_docs_api_key: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [showKeys, setShowKeys] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/settings`)
      .then(r => r.json())
      .then(d => { setForm(f => ({ ...f, tts_provider: d.tts_provider || "elevenlabs", gemini_api_key: d.gemini_api_key || "" })); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const save = async () => {
    setSaving(true); setMsg("");
    const body = { tts_provider: form.tts_provider };
    if (form.elevenlabs_api_key && !form.elevenlabs_api_key.includes("*")) body.elevenlabs_api_key = form.elevenlabs_api_key;
    if (form.openai_api_key && !form.openai_api_key.includes("*")) body.openai_api_key = form.openai_api_key;
    if (form.google_cloud_api_key && !form.google_cloud_api_key.includes("*")) body.google_cloud_api_key = form.google_cloud_api_key;
    if (form.gemini_api_key && !form.gemini_api_key.includes("*")) body.gemini_api_key = form.gemini_api_key;
    if (form.google_docs_api_key && !form.google_docs_api_key.includes("*")) body.google_docs_api_key = form.google_docs_api_key;
    try {
      const r = await fetch(`${API_BASE}/api/settings`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json();
      setMsg(d.message || "Saved!");
      if (onSaved) onSaved();
    } catch { setMsg("Save failed."); }
    setSaving(false);
  };

  const Field = ({ label, field, placeholder, hint }) => (
    <div>
      <label className="block text-xs text-slate-400 mb-1">{label}</label>
      <div className="relative">
        <input type={showKeys ? "text" : "password"} value={form[field]}
          onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))}
          placeholder={placeholder}
          className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono" />
      </div>
      {hint && <p className="text-xs text-slate-500 mt-1">{hint}</p>}
    </div>
  );

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <Settings size={16} className="text-indigo-400" />
            <span className="font-semibold text-slate-100">API Keys &amp; Settings</span>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={18} /></button>
        </div>

        {loading ? (
          <div className="p-8 text-center text-slate-400"><Loader size={20} className="animate-spin mx-auto mb-2" />Loading…</div>
        ) : (
          <div className="p-6 space-y-5">
            {/* TTS Provider */}
            <div>
              <label className="block text-xs text-slate-400 mb-2">TTS Provider</label>
              <div className="grid grid-cols-2 gap-2">
                {[
                  ["gemini",     "✨ Gemini TTS",  "bg-purple-600 border-purple-500"],
                  ["elevenlabs", "ElevenLabs",      "bg-indigo-600 border-indigo-500"],
                  ["openai",     "OpenAI TTS",      "bg-indigo-600 border-indigo-500"],
                  ["google",     "Google TTS",      "bg-indigo-600 border-indigo-500"],
                ].map(([v, l, activeClass]) => (
                  <button key={v} onClick={() => setForm(f => ({ ...f, tts_provider: v }))}
                    className={`py-2 rounded-lg text-xs font-medium border transition-colors ${form.tts_provider === v ? `${activeClass} text-white` : "bg-slate-700 border-slate-600 text-slate-300 hover:border-slate-500"}`}>
                    {l}
                  </button>
                ))}
              </div>
            </div>

            <div className="border-t border-slate-700/60 pt-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400 font-medium">API Keys</span>
                <button onClick={() => setShowKeys(v => !v)} className="text-xs text-slate-500 hover:text-slate-300">
                  {showKeys ? "Hide" : "Show"} keys
                </button>
              </div>
              <Field label="✨ Gemini API Key" field="gemini_api_key" placeholder="AIza..."
                hint={form.tts_provider === "gemini" ? "Required — get from aistudio.google.com/apikey" : "For Gemini TTS (aistudio.google.com/apikey)"} />
              <Field label="ElevenLabs API Key" field="elevenlabs_api_key" placeholder="sk_..." hint={form.tts_provider === "elevenlabs" ? "Required for current provider" : ""} />
              <Field label="OpenAI API Key" field="openai_api_key" placeholder="sk-proj-..." hint={form.tts_provider === "openai" ? "Required for current provider" : ""} />
              <Field label="Google Cloud API Key" field="google_cloud_api_key" placeholder="AIza..." hint={form.tts_provider === "google" ? "Required for current provider" : ""} />
              <Field label="Google Docs API Key (optional)" field="google_docs_api_key" placeholder="AIza... (for importing Google Docs scripts)" />
            </div>

            <div className="bg-slate-700/40 rounded-lg px-3 py-2 text-xs text-slate-400">
              💡 Keys are saved to <code className="text-slate-300">%APPDATA%\ScriptToVideo\.env</code> on your PC only — never shared.
            </div>

            {msg && <p className={`text-xs text-center ${msg.includes("fail") ? "text-red-400" : "text-green-400"}`}>{msg}</p>}

            <div className="flex gap-2 pt-1">
              <button onClick={onClose} className="flex-1 py-2 rounded-lg text-sm bg-slate-700 hover:bg-slate-600 text-slate-300">Cancel</button>
              <button onClick={save} disabled={saving} className="flex-1 py-2 rounded-lg text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium flex items-center justify-center gap-2">
                {saving ? <><Loader size={14} className="animate-spin" /> Saving…</> : "Save Settings"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Audio Modal ───────────────────────────────────────────────────────────────
function AudioModal({ onClose, onDone }) {
  const [inputMode, setInputMode] = useState("text");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState(null);
  const [voice, setVoice] = useState("");
  const [model, setModel] = useState("eleven_multilingual_v2");
  const [speed, setSpeed] = useState(1.0);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [config, setConfig] = useState(null);
  const [playingPreview, setPlayingPreview] = useState(false);
  const previewAudioRef = useRef(null);
  const fileRef = useRef();

  useEffect(() => {
    fetch(`${API_BASE}/api/audio/config`)
      .then(r => r.json())
      .then(data => {
        setConfig(data);
        setVoice(data.default_voice || "");
        if (data.default_model) setModel(data.default_model);
      })
      .catch(() => setConfig({ provider: "unknown", voices: [], default_voice: "", models: [] }));
  }, []);

  // Stop preview when voice changes
  useEffect(() => {
    if (previewAudioRef.current) { previewAudioRef.current.pause(); previewAudioRef.current = null; }
    setPlayingPreview(false);
  }, [voice]);

  const playPreview = () => {
    const selectedVoice = config?.voices?.find(v => v.id === voice);
    const url = selectedVoice?.preview_url;
    if (!url) return;
    if (playingPreview && previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current = null;
      setPlayingPreview(false);
      return;
    }
    const audio = new Audio(url);
    previewAudioRef.current = audio;
    setPlayingPreview(true);
    audio.play();
    audio.onended = () => { setPlayingPreview(false); previewAudioRef.current = null; };
    audio.onerror = () => { setPlayingPreview(false); previewAudioRef.current = null; };
  };

  const submit = async () => {
    setError(""); setRunning(true); setProgress(0);
    try {
      const form = new FormData();
      if (inputMode === "text") form.append("text", text);
      else if (inputMode === "url") form.append("google_doc_url", url);
      else if (inputMode === "file" && file) form.append("file", file);
      form.append("voice", voice);
      form.append("speed", String(speed));
      form.append("language", "en-US");
      form.append("model", model);

      const r = await fetch(`${API_BASE}/api/audio/generate`, { method: "POST", body: form });
      if (!r.ok) throw new Error(await r.text());
      const { job_id } = await r.json();
      const result = await pollJob(job_id, (p, m) => { setProgress(p); setMessage(m); });
      onDone(result);
      onClose();
    } catch (e) {
      setError(e.message);
      setRunning(false);
    }
  };

  const isElevenLabs = config?.provider === "elevenlabs";
  const providerLabel = { elevenlabs: "ElevenLabs", openai: "OpenAI", google: "Google", gemini: "Gemini" }[config?.provider] ?? config?.provider ?? "";
  const selectedVoicePreviewUrl = config?.voices?.find(v => v.id === voice)?.preview_url;

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-2xl w-full max-w-lg shadow-2xl border border-slate-700">
        <div className="flex items-center justify-between p-5 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <Mic size={20} className="text-indigo-400" />
            <span className="font-semibold text-lg">Generate Audio</span>
            {config && <ProviderBadge provider={config.provider} />}
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>

        <div className="p-5 space-y-4">
          <div className="flex gap-2">
            {[
              { id: "text", label: "Paste Text", icon: <FileText size={14} /> },
              { id: "url",  label: "Doc URL",    icon: <Link size={14} /> },
              { id: "file", label: "Upload File", icon: <Upload size={14} /> },
            ].map(m => (
              <button key={m.id} onClick={() => setInputMode(m.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
                  ${inputMode === m.id ? "bg-indigo-600 text-white" : "bg-slate-700 text-slate-300 hover:bg-slate-600"}`}>
                {m.icon}{m.label}
              </button>
            ))}
          </div>

          {inputMode === "text" && (
            <textarea value={text} onChange={e => setText(e.target.value)}
              placeholder="Paste your script here..." rows={6}
              className="w-full bg-slate-900 border border-slate-600 rounded-xl p-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none" />
          )}
          {inputMode === "url" && (
            <input value={url} onChange={e => setUrl(e.target.value)}
              placeholder="https://docs.google.com/document/d/..."
              className="w-full bg-slate-900 border border-slate-600 rounded-xl p-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500" />
          )}
          {inputMode === "file" && (
            <div onClick={() => fileRef.current?.click()}
              className="border-2 border-dashed border-slate-600 rounded-xl p-8 text-center cursor-pointer hover:border-indigo-500 transition-colors">
              <Upload size={24} className="mx-auto mb-2 text-slate-400" />
              <p className="text-sm text-slate-400">{file ? file.name : "Click to upload .docx or .txt"}</p>
              <input ref={fileRef} type="file" accept=".docx,.txt" className="hidden" onChange={e => setFile(e.target.files[0])} />
            </div>
          )}

          {/* Voice selector + preview button */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Voice ({providerLabel})</label>
              <div className="flex gap-1.5">
                {config && config.voices.length > 0 ? (
                  <select value={voice} onChange={e => setVoice(e.target.value)}
                    className="flex-1 bg-slate-900 border border-slate-600 rounded-lg p-2 text-sm text-slate-100">
                    {config.voices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
                  </select>
                ) : (
                  <div className="flex-1 bg-slate-900 border border-slate-600 rounded-lg p-2 text-sm text-slate-500">
                    {config ? "Loading voices..." : "Connecting..."}
                  </div>
                )}
                {selectedVoicePreviewUrl && (
                  <button onClick={playPreview} title={playingPreview ? "Stop preview" : "Play voice sample"}
                    className={`px-2.5 rounded-lg border transition-colors ${playingPreview
                      ? "bg-indigo-600 border-indigo-500 text-white"
                      : "bg-slate-700 border-slate-600 text-slate-300 hover:border-indigo-500 hover:text-white"}`}>
                    {playingPreview ? <Square size={13} /> : <Play size={13} />}
                  </button>
                )}
              </div>
            </div>

            {!isElevenLabs ? (
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Speed: {speed}x</label>
                <input type="range" min="0.5" max="2" step="0.1" value={speed}
                  onChange={e => setSpeed(parseFloat(e.target.value))}
                  className="w-full accent-indigo-500 mt-2" />
              </div>
            ) : (
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Speed: {speed}x</label>
                <input type="range" min="0.5" max="2" step="0.1" value={speed}
                  onChange={e => setSpeed(parseFloat(e.target.value))}
                  className="w-full accent-indigo-500 mt-2" />
              </div>
            )}
          </div>

          {/* ElevenLabs model selector */}
          {isElevenLabs && config?.models?.length > 0 && (
            <div>
              <label className="text-xs text-slate-400 mb-1.5 block">Model</label>
              <div className="grid grid-cols-3 gap-2">
                {config.models.map(m => (
                  <button key={m.id} onClick={() => setModel(m.id)}
                    className={`flex flex-col items-start px-3 py-2 rounded-lg border text-left transition-colors ${model === m.id
                      ? "bg-indigo-600/20 border-indigo-500 text-white"
                      : "bg-slate-700/50 border-slate-600 text-slate-300 hover:border-slate-500"}`}>
                    <span className="text-xs font-medium leading-tight">{m.name.split(" — ")[0]}</span>
                    <span className="text-xs text-slate-400 mt-0.5">{m.cost}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {running && <ProgressBar value={progress} label={message || "Processing..."} />}
          {error && (
            <div className="flex items-start gap-2 bg-red-900/40 border border-red-700 rounded-lg p-3">
              <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
              <p className="text-sm text-red-300">{error}</p>
            </div>
          )}
        </div>

        <div className="p-5 border-t border-slate-700 flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-400 hover:text-white">Cancel</button>
          <button onClick={submit} disabled={running}
            className="flex items-center gap-2 px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-xl text-sm font-medium transition-colors">
            {running ? <Loader size={15} className="animate-spin" /> : <Mic size={15} />}
            {running ? "Generating..." : "Generate Audio"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Slides Modal ──────────────────────────────────────────────────────────────
function SlidesModal({ onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [duration, setDuration] = useState(3);
  const [transition, setTransition] = useState("fade");
  const [resolution, setResolution] = useState("1920x1080");
  const [animation, setAnimation] = useState("none");
  const [transitionClipId, setTransitionClipId] = useState("");
  const [transitionClipName, setTransitionClipName] = useState("");
  const [uploadingTransition, setUploadingTransition] = useState(false);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef();
  const transRef = useRef();

  const uploadTransition = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    setUploadingTransition(true);
    try {
      const form = new FormData();
      form.append("file", f);
      const r = await fetch(`${API_BASE}/api/slides/upload-transition`, { method: "POST", body: form });
      if (!r.ok) throw new Error((await r.json()).detail || "Upload failed");
      const data = await r.json();
      setTransitionClipId(data.transition_clip_id);
      setTransitionClipName(f.name);
    } catch (ex) {
      setError("Transition upload failed: " + ex.message);
    } finally {
      setUploadingTransition(false);
      e.target.value = "";
    }
  };

  const submit = async () => {
    if (!file) return setError("Please select a .pptx file.");
    setError(""); setRunning(true); setProgress(0);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("slide_duration", String(duration));
      form.append("transition", transition);
      form.append("resolution", resolution);
      form.append("animation", animation);
      form.append("transition_clip_id", transitionClipId);
      const r = await fetch(`${API_BASE}/api/slides/convert`, { method: "POST", body: form });
      if (!r.ok) throw new Error(await r.text());
      const { job_id } = await r.json();
      const result = await pollJob(job_id, (p, m) => { setProgress(p); setMessage(m); });
      onDone(result);
      onClose();
    } catch (e) {
      setError(e.message);
      setRunning(false);
    }
  };

  const isTextAnim = animation.startsWith("text_") || animation === "char_overshoot_scale";

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4 overflow-y-auto">
      <div className="bg-slate-800 rounded-2xl w-full max-w-lg shadow-2xl border border-slate-700 my-4">
        <div className="flex items-center justify-between p-5 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <Film size={20} className="text-violet-400" />
            <span className="font-semibold text-lg">Slides to Video</span>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>
        <div className="p-5 space-y-4">
          <div onClick={() => fileRef.current?.click()}
            className="border-2 border-dashed border-slate-600 rounded-xl p-8 text-center cursor-pointer hover:border-violet-500 transition-colors">
            <Film size={28} className="mx-auto mb-2 text-slate-400" />
            <p className="text-sm text-slate-400">{file ? file.name : "Click to upload .pptx / .ppt / .pdf"}</p>
            <input ref={fileRef} type="file" accept=".pptx,.ppt,.pdf" className="hidden" onChange={e => setFile(e.target.files[0])} />
          </div>

          {/* Animation */}
          <div>
            <label className="text-xs text-slate-400 mb-1.5 block font-medium">Slide / Text Animation</label>
            <div className="grid grid-cols-2 gap-2">
              {[
                { id: "none",           label: "None",              group: "slide" },
                { id: "fade_in",        label: "🎞 Slide Fade-in",  group: "slide" },
                { id: "slide_in_right", label: "➡ Slide Slide-in",  group: "slide" },
                { id: "zoom_in",        label: "🔍 Slide Zoom-in",  group: "slide" },
                { id: "text_fade",           label: "✨ Text Fade",         group: "text"  },
                { id: "text_slide_up",       label: "⬆ Text Slide Up",     group: "text"  },
                { id: "text_wipe",           label: "▶ Text Wipe",         group: "text"  },
                { id: "char_overshoot_scale", label: "🎯 Overshoot Scale",  group: "text"  },
              ].map(opt => (
                <button key={opt.id} onClick={() => setAnimation(opt.id)}
                  className={`px-3 py-2 rounded-lg text-xs font-medium border text-left transition-colors
                    ${animation === opt.id
                      ? (opt.group === "text" ? "bg-fuchsia-700 border-fuchsia-500 text-white" : "bg-violet-700 border-violet-500 text-white")
                      : "border-slate-600 text-slate-400 hover:border-slate-400 hover:text-slate-200"}`}>
                  {opt.label}
                  {opt.group === "text" && <span className="block text-xs font-normal opacity-70 mt-0.5">Animates text elements</span>}
                </button>
              ))}
            </div>
            {isTextAnim && (
              <p className="text-xs text-fuchsia-400 mt-1.5">
                ✦ Text elements animate in per-box with stagger. Requires PPTX source for box detection.
              </p>
            )}
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Default Duration (s)</label>
              <input type="number" value={duration} min={1} max={30} onChange={e => setDuration(Number(e.target.value))}
                className="w-full bg-slate-900 border border-slate-600 rounded-lg p-2 text-sm text-slate-100" />
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Slide Transition</label>
              <select value={transition} onChange={e => setTransition(e.target.value)}
                className="w-full bg-slate-900 border border-slate-600 rounded-lg p-2 text-sm text-slate-100">
                {["fade","slide","wiperight","wipeleft","circlecrop","none"].map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Resolution</label>
              <select value={resolution} onChange={e => setResolution(e.target.value)}
                className="w-full bg-slate-900 border border-slate-600 rounded-lg p-2 text-sm text-slate-100">
                {["1920x1080","1280x720","3840x2160"].map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
          </div>

          {/* Custom transition upload */}
          <div>
            <label className="text-xs text-slate-400 mb-1.5 block font-medium">Custom Alpha Transition Clip <span className="text-slate-600 font-normal">(optional)</span></label>
            <input ref={transRef} type="file" accept=".mp4,.mov,.webm,.avi" className="hidden" onChange={uploadTransition} />
            <button onClick={() => transRef.current?.click()} disabled={uploadingTransition}
              className="w-full py-2 border border-dashed border-slate-600 hover:border-fuchsia-500 rounded-xl text-sm text-slate-400 hover:text-fuchsia-300 transition-colors flex items-center justify-center gap-2 disabled:opacity-50">
              {uploadingTransition ? <Loader size={14} className="animate-spin" /> : <Upload size={14} />}
              {transitionClipName ? `✓ ${transitionClipName}` : uploadingTransition ? "Uploading..." : "Upload transition clip (MP4 / WebM with alpha)"}
            </button>
            {transitionClipName && (
              <div className="flex items-center justify-between mt-1">
                <p className="text-xs text-fuchsia-400">Clip will play between each slide</p>
                <button onClick={() => { setTransitionClipId(""); setTransitionClipName(""); }}
                  className="text-xs text-slate-500 hover:text-red-400">✕ Remove</button>
              </div>
            )}
          </div>

          {running && <ProgressBar value={progress} label={message || "Processing..."} />}
          {error && (
            <div className="flex items-start gap-2 bg-red-900/40 border border-red-700 rounded-lg p-3">
              <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
              <p className="text-sm text-red-300">{error}</p>
            </div>
          )}
        </div>
        <div className="p-5 border-t border-slate-700 flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-400 hover:text-white">Cancel</button>
          <button onClick={submit} disabled={running}
            className="flex items-center gap-2 px-5 py-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-xl text-sm font-medium transition-colors">
            {running ? <Loader size={15} className="animate-spin" /> : <Film size={15} />}
            {running ? "Converting..." : "Convert Slides"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Time parser: "2:22.7" or "142.7" → seconds ───────────────────────────────
function parseTimeInput(str) {
  str = (str || "").trim();
  const colon = str.match(/^(\d+):(\d+\.?\d*)$/);
  if (colon) return parseFloat(colon[1]) * 60 + parseFloat(colon[2]);
  const plain = str.match(/^\d+\.?\d*$/);
  if (plain) return parseFloat(str);
  return null;
}

// ── Audio Region Lightbox ─────────────────────────────────────────────────────
function AudioRegionLightbox({ audioUrl, totalDuration, slideIndex, slideTitle, initialStart, initialEnd, onApply, onClose }) {
  // ── State ──────────────────────────────────────────────────────────────────
  const [localStart,   setLocalStart]   = useState(initialStart);
  const [localEnd,     setLocalEnd]     = useState(initialEnd);
  const [isPlaying,    setIsPlaying]    = useState(false);
  const [audioReady,   setAudioReady]   = useState("loading"); // 'loading'|'ready'|'error'
  const [playhead,     setPlayhead]     = useState(initialStart);
  const [dragging,     setDragging]     = useState(null);      // 'left'|'right'|null
  const [draggingHead, setDraggingHead] = useState(false);
  const [draggingPan,  setDraggingPan]  = useState(false);
  const [zoom,         setZoom]         = useState(1);
  const [viewStart,    setViewStart]    = useState(0);
  const [peaks,        setPeaks]        = useState(null);      // Float32Array waveform

  // ── Refs ───────────────────────────────────────────────────────────────────
  const audioRef    = useRef(null);
  const timelineRef = useRef(null);
  const waveCanvasRef = useRef(null);
  const animRef     = useRef(null);
  const blobUrlRef  = useRef(null);
  const panOriginRef = useRef(null);   // { clientX, viewStart }

  // Stable refs (avoid stale closures in callbacks/effects)
  const startRef    = useRef(localStart);
  const endRef      = useRef(localEnd);
  const playheadRef = useRef(initialStart);
  const viewStartRef = useRef(0);
  const zoomRef     = useRef(1);
  useEffect(() => { startRef.current    = localStart; }, [localStart]);
  useEffect(() => { endRef.current      = localEnd;   }, [localEnd]);
  useEffect(() => { playheadRef.current = playhead;   }, [playhead]);
  useEffect(() => { viewStartRef.current = viewStart; }, [viewStart]);
  useEffect(() => { zoomRef.current     = zoom;       }, [zoom]);

  // ── Computed view window ───────────────────────────────────────────────────
  const viewWindow = totalDuration / zoom;
  const toViewPct  = (t) => Math.max(-5, Math.min(105, ((t - viewStart) / viewWindow) * 100));

  // ── Fetch blob + decode waveform ──────────────────────────────────────────
  useEffect(() => {
    let blobUrl = null;
    let cancelled = false;
    setAudioReady("loading");
    setPeaks(null);

    fetch(audioUrl)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.blob(); })
      .then(async blob => {
        if (cancelled) return;
        blobUrl = URL.createObjectURL(blob);
        blobUrlRef.current = blobUrl;
        const a = audioRef.current;
        if (a) {
          a.src = blobUrl;
          a.addEventListener("loadedmetadata", () => {
            if (!cancelled) setAudioReady("ready");
          }, { once: true });
          a.load();
        }

        // Decode waveform peaks — runs INDEPENDENTLY so any error here
        // does NOT set audioReady to "error" (buttons stay usable).
        // For long files (10+ min) decodeAudioData can take several seconds;
        // without this isolation it was disabling play/stop mid-playback.
        let ac = null;
        try {
          const buf = await blob.arrayBuffer();
          if (cancelled) return;
          ac = new AudioContext();
          const decoded = await ac.decodeAudioData(buf);
          if (cancelled) return;
          const data  = decoded.getChannelData(0);
          const N     = 3000;
          const block = Math.floor(data.length / N);
          const arr   = new Float32Array(N);
          for (let i = 0; i < N; i++) {
            let mx = 0;
            for (let j = 0; j < block; j++) mx = Math.max(mx, Math.abs(data[i * block + j]));
            arr[i] = mx;
          }
          if (!cancelled) setPeaks(arr);
        } catch (waveErr) {
          console.warn("[waveform] decode failed (audio still usable):", waveErr);
        } finally {
          try { await ac?.close(); } catch (_) {}
        }
      })
      .catch(() => { if (!cancelled) setAudioReady("error"); });

    return () => {
      cancelled = true;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
      blobUrlRef.current = null;
    };
  }, [audioUrl]);

  // ── Draw waveform canvas ──────────────────────────────────────────────────
  useEffect(() => {
    const canvas = waveCanvasRef.current;
    if (!canvas || !peaks || totalDuration === 0) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width  = rect.width  * dpr;
    canvas.height = rect.height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    const W = rect.width, H = rect.height, mid = H / 2;
    ctx.clearRect(0, 0, W, H);

    const vStart = viewStart / totalDuration;
    const vEnd   = Math.min(1, (viewStart + viewWindow) / totalDuration);
    const si = Math.floor(vStart * peaks.length);
    const ei = Math.ceil(vEnd   * peaks.length);
    const visible = peaks.slice(si, ei);
    const bw = W / visible.length;

    for (let i = 0; i < visible.length; i++) {
      const t       = viewStart + (i / visible.length) * viewWindow;
      const inReg   = t >= startRef.current && t <= endRef.current;
      const amp     = visible[i];
      const barH    = Math.max(1, amp * mid * 0.9);
      // gradient: violet inside region, dark slate outside
      ctx.fillStyle = inReg ? `rgba(139,92,246,${0.5 + amp * 0.5})` : `rgba(71,85,105,${0.4 + amp * 0.4})`;
      ctx.fillRect(i * bw, mid - barH, Math.max(0.5, bw - 0.5), barH * 2);
    }
    // Centre line
    ctx.fillStyle = "rgba(100,116,139,0.25)";
    ctx.fillRect(0, mid - 0.5, W, 1);
  }, [peaks, zoom, viewStart, viewWindow, totalDuration, localStart, localEnd]);

  const fmt = (s) => {
    const m   = Math.floor(s / 60);
    const sec = String((s % 60).toFixed(1)).padStart(4, "0");
    return `${m}:${sec}`;
  };

  // ── Helpers ────────────────────────────────────────────────────────────────
  const getTime = useCallback((clientX) => {
    const rect = timelineRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    const frac = (clientX - rect.left) / rect.width;
    return Math.max(0, Math.min(totalDuration,
      viewStartRef.current + frac * (totalDuration / zoomRef.current)));
  }, [totalDuration]);

  const seekAudio = useCallback((t) => {
    const c = Math.max(0, Math.min(totalDuration, t));
    setPlayhead(c);
    playheadRef.current = c;
    const a = audioRef.current;
    if (a) a.currentTime = c;
  }, [totalDuration]);

  const applyZoom = useCallback((newZoom, centerTime) => {
    newZoom = Math.max(1, Math.min(64, newZoom));
    const newWin = totalDuration / newZoom;
    const frac   = (centerTime - viewStartRef.current) / (totalDuration / zoomRef.current);
    const newVs  = Math.max(0, Math.min(totalDuration - newWin, centerTime - frac * newWin));
    setZoom(newZoom);
    setViewStart(newVs);
    viewStartRef.current = newVs;
    zoomRef.current      = newZoom;
  }, [totalDuration]);

  // ── Scroll-to-zoom on timeline ────────────────────────────────────────────
  useEffect(() => {
    const el = timelineRef.current;
    if (!el) return;
    const onWheel = (e) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const ct   = viewStartRef.current + ((e.clientX - rect.left) / rect.width) * (totalDuration / zoomRef.current);
      applyZoom(zoomRef.current * (e.deltaY < 0 ? 2 : 0.5), ct);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [totalDuration, applyZoom]);

  // ── rAF tick with auto-follow ─────────────────────────────────────────────
  const tick = useCallback(() => {
    const a = audioRef.current;
    if (!a || a.paused) return;   // guard: stop scheduling if audio was paused externally
    const t = a.currentTime;
    setPlayhead(t);
    playheadRef.current = t;
    // Auto-pan: keep playhead in the left 80% of the view
    const vw = totalDuration / zoomRef.current;
    const vs = viewStartRef.current;
    if (t > vs + vw * 0.80 || t < vs) {
      const nv = Math.max(0, Math.min(totalDuration - vw, t - vw * 0.15));
      setViewStart(nv);
      viewStartRef.current = nv;
    }
    if (t >= endRef.current) {
      a.pause();
      setIsPlaying(false);
      const s = startRef.current;
      setPlayhead(s); playheadRef.current = s; a.currentTime = s;
      return;
    }
    animRef.current = requestAnimationFrame(tick);
  }, [totalDuration]);

  // ── Play from current playhead ────────────────────────────────────────────
  const playRegion = useCallback(() => {
    const a = audioRef.current;
    if (!a) return;
    cancelAnimationFrame(animRef.current);
    a.pause();
    setIsPlaying(false);
    let target = playheadRef.current;
    if (target < startRef.current || target >= endRef.current) {
      target = startRef.current;
      setPlayhead(target); playheadRef.current = target;
    }
    let committed = false, fallbackId = null;
    const doPlay = () => {
      if (committed) return;
      committed = true;
      clearTimeout(fallbackId);
      a.removeEventListener("seeked", doPlay);
      a.play()
        .then(() => { setIsPlaying(true); animRef.current = requestAnimationFrame(tick); })
        .catch(() => {});
    };
    a.addEventListener("seeked", doPlay, { once: true });
    a.currentTime = target;
    fallbackId = setTimeout(() => { if (!committed) doPlay(); }, 1000);
  }, [tick]);

  const pauseRegion = useCallback(() => {
    cancelAnimationFrame(animRef.current);
    audioRef.current?.pause();
    setIsPlaying(false);
  }, []);

  const stopRegion = useCallback(() => {
    cancelAnimationFrame(animRef.current);
    audioRef.current?.pause();
    setIsPlaying(false);
    const s = startRef.current;
    setPlayhead(s); playheadRef.current = s;
    if (audioRef.current) audioRef.current.currentTime = s;
  }, []);

  useEffect(() => () => { cancelAnimationFrame(animRef.current); audioRef.current?.pause(); }, []);

  // ── Drag: region handles ──────────────────────────────────────────────────
  useEffect(() => {
    if (!dragging) return;
    const onMove = (e) => {
      const t = getTime(e.clientX);
      if (dragging === "left")  setLocalStart(Math.max(0, Math.min(t, endRef.current - 0.5)));
      if (dragging === "right") setLocalEnd(Math.max(startRef.current + 0.5, Math.min(totalDuration, t)));
    };
    const onUp = () => setDragging(null);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup",   onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, [dragging, getTime, totalDuration]);

  // ── Drag: playhead ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!draggingHead) return;
    const onMove = (e) => seekAudio(getTime(e.clientX));
    const onUp   = () => setDraggingHead(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup",   onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, [draggingHead, getTime, seekAudio]);

  // ── Drag: pan ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!draggingPan) return;
    const onMove = (e) => {
      if (!panOriginRef.current) return;
      const rect = timelineRef.current?.getBoundingClientRect();
      if (!rect) return;
      const dx = e.clientX - panOriginRef.current.clientX;
      const dt = (totalDuration / zoomRef.current) / rect.width;
      const nv = Math.max(0, Math.min(totalDuration - totalDuration / zoomRef.current,
                           panOriginRef.current.viewStart - dx * dt));
      setViewStart(nv); viewStartRef.current = nv;
    };
    const onUp = () => setDraggingPan(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup",   onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, [draggingPan, totalDuration]);

  // ── Derived layout values ─────────────────────────────────────────────────
  const leftPct  = toViewPct(localStart);
  const rightPct = toViewPct(localEnd);
  const widthPct = rightPct - leftPct;
  const headPct  = toViewPct(playhead);
  const dur      = Math.max(0, localEnd - localStart);
  const isStopped = !isPlaying && Math.abs(playhead - localStart) < 0.05;

  // ── Manual time input handler ─────────────────────────────────────────────
  const handleStartInput = (e) => {
    const t = parseTimeInput(e.target.value);
    if (t !== null && t >= 0 && t < localEnd - 0.1) setLocalStart(t);
    else e.target.value = fmt(localStart);
  };
  const handleEndInput = (e) => {
    const t = parseTimeInput(e.target.value);
    if (t !== null && t > localStart + 0.1 && t <= totalDuration) setLocalEnd(t);
    else e.target.value = fmt(localEnd);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
         onMouseDown={onClose}>
      <div className="bg-slate-800 rounded-2xl w-full max-w-5xl border border-slate-600 shadow-2xl flex flex-col"
           style={{ maxHeight: "90vh" }}
           onMouseDown={e => e.stopPropagation()}>

        {/* ── Header ── */}
        <div className="flex items-center justify-between px-7 py-4 border-b border-slate-700 shrink-0">
          <div>
            <p className="text-xs text-slate-500 mb-0.5">Slide {slideIndex + 1} — timing editor</p>
            <p className="font-semibold text-slate-100 truncate max-w-2xl">{slideTitle || "—"}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1 rounded ml-4 shrink-0">
            <X size={18} />
          </button>
        </div>

        <div className="px-7 py-5 space-y-4 overflow-y-auto">

          {/* ── Zoom toolbar ── */}
          <div className="flex items-center gap-3 select-none">
            <span className="text-xs text-slate-500">Zoom</span>
            <button onClick={() => applyZoom(zoom * 0.5, viewStart + viewWindow / 2)}
                    className="w-7 h-7 flex items-center justify-center rounded bg-slate-700 hover:bg-slate-600 text-slate-200 font-bold text-sm">−</button>
            <span className="text-xs font-mono text-slate-300 w-10 text-center">{zoom < 2 ? "1×" : zoom < 4 ? "2×" : zoom < 8 ? "4×" : zoom < 16 ? "8×" : zoom < 32 ? "16×" : "32×"}</span>
            <button onClick={() => applyZoom(zoom * 2, viewStart + viewWindow / 2)}
                    className="w-7 h-7 flex items-center justify-center rounded bg-slate-700 hover:bg-slate-600 text-slate-200 font-bold text-sm">+</button>
            <button onClick={() => { setZoom(1); setViewStart(0); }}
                    className="px-2 h-7 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-400">Reset</button>
            <span className="text-xs text-slate-600 ml-1">· scroll to zoom · drag background to pan</span>
            {zoom > 1 && (
              <span className="ml-auto text-xs text-slate-500 font-mono">
                {fmt(viewStart)} – {fmt(Math.min(totalDuration, viewStart + viewWindow))}
              </span>
            )}
          </div>

          {/* ── Timeline ── */}
          <div>
            {/* Time ruler */}
            <div className="relative h-5 mb-1 select-none overflow-hidden">
              {(() => {
                // Adaptive tick interval based on viewWindow
                const intervals = [1,2,5,10,15,30,60,120,300];
                const targetTicks = 8;
                const interval = intervals.find(i => viewWindow / i <= targetTicks) || 300;
                const first = Math.ceil(viewStart / interval) * interval;
                const ticks = [];
                for (let t = first; t < viewStart + viewWindow; t += interval) {
                  ticks.push(t);
                }
                return ticks.map(t => (
                  <span key={t} className="absolute text-xs text-slate-500 -translate-x-1/2"
                        style={{ left: `${toViewPct(t)}%` }}>
                    {fmt(t)}
                  </span>
                ));
              })()}
            </div>

            {/* Track */}
            <div ref={timelineRef}
                 className="relative bg-slate-900 rounded-xl overflow-hidden select-none"
                 style={{ height: "120px", cursor: draggingPan ? "grabbing" : "crosshair" }}
                 onClick={e => { if (dragging || draggingHead || draggingPan) return; seekAudio(getTime(e.clientX)); }}
                 onMouseDown={e => {
                   // Middle button or Shift+drag = pan
                   if (e.button === 1 || e.shiftKey) {
                     e.preventDefault();
                     panOriginRef.current = { clientX: e.clientX, viewStart: viewStartRef.current };
                     setDraggingPan(true);
                   }
                 }}>

              {/* Waveform canvas */}
              <canvas ref={waveCanvasRef} className="absolute inset-0 w-full h-full" />

              {/* Tick lines (adaptive) */}
              {(() => {
                const intervals = [1,2,5,10,15,30,60,120,300];
                const targetTicks = 8;
                const interval = intervals.find(i => viewWindow / i <= targetTicks) || 300;
                const first = Math.ceil(viewStart / interval) * interval;
                const ticks = [];
                for (let t = first; t < viewStart + viewWindow; t += interval) ticks.push(t);
                return ticks.map(t => (
                  <div key={t} className="absolute top-0 h-full w-px bg-slate-700/40 pointer-events-none"
                       style={{ left: `${toViewPct(t)}%` }} />
                ));
              })()}

              {/* Region dim overlay (outside selected area) */}
              <div className="absolute top-0 h-full pointer-events-none bg-slate-900/40"
                   style={{ left: 0, width: `${leftPct}%` }} />
              <div className="absolute top-0 h-full pointer-events-none bg-slate-900/40"
                   style={{ left: `${rightPct}%`, right: 0 }} />

              {/* Region border lines */}
              <div className="absolute top-0 h-full border-l-2 border-r-2 border-violet-400 pointer-events-none bg-violet-500/10"
                   style={{ left: `${leftPct}%`, width: `${widthPct}%` }} />

              {/* Left handle */}
              {leftPct >= -2 && leftPct <= 102 && (
                <div className="absolute top-0 h-full w-6 flex items-center justify-center cursor-ew-resize z-10 group"
                     style={{ left: `calc(${leftPct}% - 12px)` }}
                     onMouseDown={e => { e.stopPropagation(); e.preventDefault(); setDragging("left"); }}>
                  <div className="w-2 h-14 bg-violet-400 group-hover:bg-violet-200 rounded-full shadow-lg transition-colors" />
                </div>
              )}

              {/* Right handle */}
              {rightPct >= -2 && rightPct <= 102 && (
                <div className="absolute top-0 h-full w-6 flex items-center justify-center cursor-ew-resize z-10 group"
                     style={{ left: `calc(${rightPct}% - 12px)` }}
                     onMouseDown={e => { e.stopPropagation(); e.preventDefault(); setDragging("right"); }}>
                  <div className="w-2 h-14 bg-violet-400 group-hover:bg-violet-200 rounded-full shadow-lg transition-colors" />
                </div>
              )}

              {/* Playhead */}
              {headPct >= 0 && headPct <= 100 && (
                <div className="absolute top-0 h-full z-20"
                     style={{ left: `${headPct}%` }}>
                  <div className="absolute top-0 left-0 w-0.5 h-full bg-yellow-400 pointer-events-none" />
                  {/* Drag handle */}
                  <div className="absolute -top-0 left-1/2 -translate-x-1/2 w-7 h-7 flex items-center justify-center
                                  cursor-grab active:cursor-grabbing z-30"
                       onMouseDown={e => { e.stopPropagation(); e.preventDefault(); setDraggingHead(true); }}>
                    <div className="w-3.5 h-3.5 bg-yellow-400 rounded-full shadow-lg border-2 border-yellow-200" />
                  </div>
                  {/* Time chip */}
                  <div className="absolute top-7 left-1/2 -translate-x-1/2 bg-yellow-400 text-black
                                  text-xs font-mono font-bold px-1.5 py-0.5 rounded whitespace-nowrap pointer-events-none shadow">
                    {fmt(playhead)}
                  </div>
                </div>
              )}

              {/* Region boundary times */}
              {leftPct >= 0 && leftPct <= 98 && (
                <span className="absolute bottom-1.5 text-xs text-violet-300 font-mono pointer-events-none bg-slate-900/60 px-1 rounded"
                      style={{ left: `calc(${leftPct}% + 8px)` }}>
                  {fmt(localStart)}
                </span>
              )}
              {rightPct <= 100 && rightPct >= 2 && (
                <span className="absolute bottom-1.5 text-xs text-violet-300 font-mono pointer-events-none bg-slate-900/60 px-1 rounded"
                      style={{ right: `calc(${100 - rightPct}% + 8px)` }}>
                  {fmt(localEnd)}
                </span>
              )}
            </div>

            {/* Minimap scrollbar */}
            {zoom > 1 && (
              <div className="relative h-1.5 bg-slate-900 rounded-full mt-1.5 cursor-pointer"
                   onClick={e => {
                     const rect = e.currentTarget.getBoundingClientRect();
                     const frac = (e.clientX - rect.left) / rect.width;
                     const nv = Math.max(0, Math.min(totalDuration - viewWindow, frac * totalDuration - viewWindow / 2));
                     setViewStart(nv); viewStartRef.current = nv;
                   }}>
                <div className="absolute h-full bg-slate-500 rounded-full"
                     style={{ left: `${(viewStart / totalDuration) * 100}%`, width: `${(viewWindow / totalDuration) * 100}%` }} />
              </div>
            )}
          </div>

          {/* ── Stats + manual inputs ── */}
          <div className="flex items-end gap-6 flex-wrap">

            {/* Start input */}
            <div>
              <p className="text-xs text-slate-500 mb-1">Start</p>
              <input
                key={`s-${localStart.toFixed(1)}`}
                type="text"
                defaultValue={fmt(localStart)}
                onBlur={handleStartInput}
                onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }}
                className="w-24 bg-slate-700/50 border border-slate-600 focus:border-indigo-400
                           text-indigo-300 text-base font-mono font-semibold rounded-lg px-2 py-1
                           outline-none text-center"
              />
            </div>

            {/* End input */}
            <div>
              <p className="text-xs text-slate-500 mb-1">End</p>
              <input
                key={`e-${localEnd.toFixed(1)}`}
                type="text"
                defaultValue={fmt(localEnd)}
                onBlur={handleEndInput}
                onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }}
                className="w-24 bg-slate-700/50 border border-slate-600 focus:border-indigo-400
                           text-indigo-300 text-base font-mono font-semibold rounded-lg px-2 py-1
                           outline-none text-center"
              />
            </div>

            {/* Duration (read-only) */}
            <div>
              <p className="text-xs text-slate-500 mb-1">Duration</p>
              <p className="text-base font-mono font-semibold text-green-400 px-2">{fmt(dur)}</p>
            </div>

            {/* Live position counter */}
            <div className="ml-4">
              <p className="text-xs text-slate-500 mb-1">Current position</p>
              <p className={`text-3xl font-mono font-bold tabular-nums ${isPlaying ? "text-yellow-400" : "text-yellow-300/60"}`}>
                {fmt(playhead)}
              </p>
            </div>
          </div>

          {/* ── Controls ── */}
          <div className="flex items-center gap-3 pt-1">
            {/* Play / Pause toggle */}
            <button
              onClick={isPlaying ? pauseRegion : playRegion}
              disabled={audioReady !== "ready"}
              className="flex items-center gap-2 px-5 py-2.5 bg-violet-700 hover:bg-violet-600
                         text-white rounded-xl text-sm font-medium transition-colors
                         disabled:opacity-50 disabled:cursor-wait">
              {audioReady === "loading"
                ? <><Loader size={14} className="animate-spin" /> Loading audio…</>
                : audioReady === "error"
                  ? <><AlertCircle size={14} /> Load failed</>
                  : isPlaying
                    ? <><Pause size={14} /> Pause</>
                    : isStopped
                      ? <><Play size={14} /> Play Region</>
                      : <><Play size={14} /> Resume</>}
            </button>

            {/* Stop — only shown when not already at start */}
            {!isStopped && (
              <button
                onClick={stopRegion}
                disabled={audioReady !== "ready"}
                className="flex items-center gap-2 px-4 py-2.5 bg-slate-700 hover:bg-slate-600
                           text-white rounded-xl text-sm font-medium transition-colors disabled:opacity-50">
                <Square size={14} /> Stop
              </button>
            )}

            <div className="ml-auto flex gap-3">
              <button onClick={onClose}
                      className="px-5 py-2.5 text-sm text-slate-400 hover:text-white border border-slate-600
                                 hover:border-slate-400 rounded-xl transition-colors">
                Cancel
              </button>
              <button onClick={() => onApply(
                          parseFloat(localStart.toFixed(2)),
                          parseFloat(dur.toFixed(2))
                        )}
                      className="px-6 py-2.5 text-sm font-semibold bg-green-700 hover:bg-green-600
                                 text-white rounded-xl transition-colors">
                Apply Changes
              </button>
            </div>
          </div>
        </div>

        {/* src is set imperatively via blob URL — see useEffect above */}
        <audio ref={audioRef} preload="none" />
      </div>
    </div>
  );
}

// ── Helper: AI sync debug info → video-timeline slide durations ───────────────
// AI sync stores duration_sec as gap between consecutive *spoken* markers.
// Example: slide 1 spoken marker at 14 s, slide 2 at 51 s → duration_sec[0]=37 s.
// But in the video slide 1 plays from t=0, so its correct video duration = 51 s.
//
// sync.py pads the LAST slide so sum(duration_sec) = T (total audio duration).
// That padding can include both a preamble AND cap-transfer amounts from other
// slides.  Subtracting only the preamble leaves cap-transfer excess, making the
// video longer than the audio (transition drift at end).
//
// Correct formula:
//   slide 0   → starts[1]               (covers the preamble + narration up to slide 2)
//   slide i   → duration_sec[i]         (gap between markers, no change needed)
//   last slide → T - starts[n-1]        (narration from last marker to end of audio)
//
//   sum = starts[1] + Σ(starts[i+1]-starts[i], i=1..n-2) + (T - starts[n-1]) = T ✓
function toVideoDurations(debugInfo) {
  if (!debugInfo?.length) return null;
  const n = debugInfo.length;
  const starts = debugInfo.map(d => parseFloat(d.start_sec) || 0);
  // Total audio duration = sum of all duration_sec (sync.py guarantees this = audio length)
  const totalDur = debugInfo.reduce((s, d) => s + (parseFloat(d.duration_sec) || 0), 0);

  return debugInfo.map((d, i) => {
    if (i === 0 && n > 1) {
      // Slide 1: video plays from t=0 to when the narrator reaches slide 2.
      // This absorbs any preamble silence before "Slide 1" is spoken.
      return Math.max(0.1, starts[1]);
    }
    if (i < n - 1) {
      // Middle slides: use the ACTUAL audio gap between consecutive markers.
      // Using duration_sec here would drift if sync.py's cap-transfer mechanism
      // inflated/deflated durations for weak-match slides.
      // starts[i+1] - starts[i] is always the ground-truth narration window.
      return Math.max(0.1, starts[i + 1] - starts[i]);
    }
    // Last slide: from its audio marker to the very end of the audio track.
    // totalDur - starts[n-1] removes ALL sync.py padding (preamble gap +
    // any cap-transfer excess) so sum(toVideoDurations) == totalDur exactly.
    return Math.max(0.1, totalDur - starts[n - 1]);
  });
}

// ── AI Sync Button ────────────────────────────────────────────────────────────
function AiSyncButton({ audioResult, slidesResult, onSynced, onDebugInfo, onSyncComplete, initialDebugInfo }) {
  const [syncStatus, setSyncStatus] = useState("idle"); // idle | running | done | error
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("");
  const [debugInfo, setDebugInfo] = useState(initialDebugInfo || null);
  const [showDebug, setShowDebug] = useState(false);

  // When a saved project is loaded the parent passes a new initialDebugInfo prop.
  // useState only uses the initial value at mount, so we need this effect to
  // update local state whenever the prop changes (e.g. after loadProject()).
  // We also flip syncStatus to "done" so the debug table becomes visible —
  // without this the table is hidden behind the syncStatus === "done" gate
  // and the user thinks their saved sync data is gone.
  useEffect(() => {
    if (initialDebugInfo && initialDebugInfo.length > 0) {
      setDebugInfo(initialDebugInfo);
      setSyncStatus("done");
      setMessage(`Loaded ${initialDebugInfo.length} slides — view or edit timing below`);
      setShowDebug(false); // keep collapsed; user can click "Show sync debug table"
    }
  }, [initialDebugInfo]);
  const [refreshStatus, setRefreshStatus] = useState("idle"); // idle | running | done | error
  const [refreshMsg, setRefreshMsg] = useState("");
  const [refreshCount, setRefreshCount] = useState(null);   // titles_extracted after refresh
  const [diagShapes, setDiagShapes] = useState(null);
  const [showDiag, setShowDiag] = useState(false);
  const [editingRow, setEditingRow] = useState(null);       // index of row open in lightbox

  const fmtTime = s => {
    const m = Math.floor(s / 60), sec = (s % 60).toFixed(1);
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  };

  // Total audio span inferred from the last slide's end time
  const totalAudioDuration = debugInfo
    ? debugInfo.reduce((mx, d) => Math.max(mx, (d.start_sec || 0) + (d.duration_sec || 0)), 0)
    : 0;

  // Apply timing edit from the lightbox with full cascade:
  //  • Previous slide: its duration is trimmed/extended to end exactly at newStart
  //  • Edited slide: gets newStart + newDuration verbatim
  //  • All subsequent slides: start times are shifted so they follow each other
  //    without gaps (their durations stay unchanged)
  const handleApplyTiming = (newStart, newDuration) => {
    if (editingRow === null || !debugInfo) return;
    const idx    = editingRow;
    const newEnd = parseFloat((newStart + newDuration).toFixed(2));

    // Build updated array (immutable copy)
    const updated = debugInfo.map((d, i) => ({ ...d }));

    // ① Edited slide
    updated[idx].start_sec    = parseFloat(newStart.toFixed(2));
    updated[idx].duration_sec = parseFloat(newDuration.toFixed(2));

    // ② Previous slide — shrink/grow its duration to meet new start
    if (idx > 0) {
      const prevStart = updated[idx - 1].start_sec || 0;
      const newPrevDur = Math.max(0.1, newStart - prevStart);
      updated[idx - 1].duration_sec = parseFloat(newPrevDur.toFixed(2));
    }

    // ③ All subsequent slides — cascade start times forward, preserve durations
    for (let i = idx + 1; i < updated.length; i++) {
      const prev = updated[i - 1];
      updated[i].start_sec = parseFloat(((prev.start_sec || 0) + (prev.duration_sec || 0)).toFixed(2));
    }

    setDebugInfo(updated);
    onDebugInfo?.(updated);
    // Use corrected video durations (slide 0 plays from t=0, not its start_sec)
    onSynced(toVideoDurations(updated) ?? updated.map(d => d.duration_sec));
    setEditingRow(null);
  };

  // Re-extract slide titles from the stored source.pptx (no full re-conversion)
  const refreshTitles = async () => {
    if (!slidesResult?.frames_job_id) return;
    setRefreshStatus("running");
    setRefreshMsg("Re-extracting titles…");
    try {
      const r = await fetch(
        `${API_BASE}/api/slides/refresh-texts/${slidesResult.frames_job_id}`,
        { method: "POST" }
      );
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || "Refresh failed");
      }
      const data = await r.json();
      setRefreshMsg(`✓ Refreshed — ${data.titles_extracted}/${data.slide_count} titles found`);
      setRefreshCount(data.titles_extracted);
      setRefreshStatus("done");
    } catch (e) {
      setRefreshMsg(`✗ ${e.message}`);
      setRefreshStatus("error");
    }
  };

  const runDiag = async () => {
    if (!slidesResult?.frames_job_id) return;
    setShowDiag(true);
    setDiagShapes(null);
    try {
      const r = await fetch(
        `${API_BASE}/api/slides/debug-texts/${slidesResult.frames_job_id}?slide=1`
      );
      const data = await r.json();
      setDiagShapes(data);
    } catch (e) {
      setDiagShapes({ error: e.message });
    }
  };

  const run = async () => {
    if (!audioResult?.filename || !slidesResult?.frames_job_id) return;
    setSyncStatus("running"); setDebugInfo(null); setShowDebug(false);
    setProgress(5);
    setMessage("Starting AI sync…");
    try {
      const r = await fetch(`${API_BASE}/api/sync/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audio_filename: audioResult.filename,
          frames_job_id: slidesResult.frames_job_id,
        }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || "Failed to start sync");
      }
      const { job_id } = await r.json();

      const result = await pollJob(job_id, (p, m) => {
        setProgress(p);
        setMessage(m || "Processing…");
      });

      setMessage(`Synced ${result.slide_count} slides — ${result.total_duration.toFixed(1)}s total`);
      setSyncStatus("done");
      if (result.debug) {
        setDebugInfo(result.debug);
        onDebugInfo?.(result.debug);
      }
      // Convert audio-gap durations → correct video-timeline durations.
      // (Slide 1 plays from t=0 in the video, not from when "Slide 1" is spoken.)
      const videoDurs = toVideoDurations(result.debug) ?? result.slide_durations;
      onSynced(videoDurs);
      // Notify parent with fresh data so it can auto-save without stale-closure issues
      onSyncComplete?.(result.debug ?? null, videoDurs);
    } catch (e) {
      setMessage(e.message);
      setSyncStatus("error");
    }
  };

  return (
    <div className="space-y-1">
      {/* Refresh titles — useful when sync shows all "—" titles */}
      {slidesResult?.frames_job_id && (
        <div className="flex items-center gap-2">
          <button
            onClick={refreshTitles}
            disabled={refreshStatus === "running"}
            title="Re-extract slide titles from the PPTX without re-converting"
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-medium border transition-colors
              bg-slate-700/40 hover:bg-slate-700/70 border-slate-600/50 text-slate-300 disabled:opacity-50"
          >
            {refreshStatus === "running"
              ? <><Loader size={12} className="animate-spin" /> Refreshing…</>
              : <><FileText size={12} /> Refresh Slide Titles</>}
          </button>
        </div>
      )}
      {refreshMsg && (
        <div className="space-y-0.5">
          <p className={`text-xs text-center ${refreshStatus === "done" ? "text-green-400" : "text-red-400"}`}>
            {refreshMsg}
          </p>
          {refreshStatus === "done" && refreshCount === 0 && (
            <button onClick={runDiag}
              className="w-full text-xs text-yellow-400 hover:text-yellow-200 underline text-center">
              0 titles found — show PPTX shape diagnostics
            </button>
          )}
        </div>
      )}
      {showDiag && (
        <div className="rounded-lg border border-yellow-600/40 bg-yellow-900/20 p-2 text-xs space-y-1">
          <div className="flex justify-between items-center">
            <span className="text-yellow-300 font-medium">Shape diagnostics — Slide 1</span>
            <button onClick={() => setShowDiag(false)} className="text-slate-400 hover:text-white"><X size={12}/></button>
          </div>
          {!diagShapes
            ? <p className="text-slate-400">Loading…</p>
            : diagShapes.error
              ? <p className="text-red-400">{diagShapes.error}</p>
              : diagShapes.shapes?.length === 0
                ? <p className="text-slate-400">No shapes found on slide 1.</p>
                : <div className="max-h-40 overflow-y-auto space-y-1">
                    {diagShapes.shapes.map((s, i) => (
                      <div key={i} className="bg-slate-800/60 rounded px-2 py-1">
                        <span className="text-slate-400">{s.shape_type}</span>
                        {" · "}
                        <span className="text-slate-300">{s.name}</span>
                        {s.ph_type && <span className="text-indigo-300"> [ph:{s.ph_type} idx:{s.ph_idx}]</span>}
                        {s.text && <div className="text-green-300 truncate">"{s.text}"</div>}
                        {s.has_text && !s.text && <div className="text-slate-500 italic">empty text frame</div>}
                      </div>
                    ))}
                  </div>
          }
        </div>
      )}
      <button
        onClick={run}
        disabled={syncStatus === "running"}
        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium border transition-colors
          bg-violet-700/30 hover:bg-violet-700/50 border-violet-600/50 text-violet-200 disabled:opacity-50"
      >
        {syncStatus === "running"
          ? <><Loader size={15} className="animate-spin" /> {message || "Analysing with Whisper…"}</>
          : <><Zap size={15} /> AI Auto-Sync Slides to Audio</>}
      </button>
      {syncStatus === "running" && (
        <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
          <div className="h-full bg-violet-500 rounded-full transition-all duration-500" style={{ width: `${progress}%` }} />
        </div>
      )}
      {syncStatus === "done" && (
        <div className="space-y-1">
          <p className="text-xs text-green-400 text-center">✓ {message}</p>
          {debugInfo && (
            <button onClick={() => setShowDebug(v => !v)}
              className="w-full text-xs text-slate-500 hover:text-slate-300 underline text-center">
              {showDebug ? "Hide" : "Show"} sync debug table
            </button>
          )}
          {showDebug && debugInfo && (
            <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-700 text-xs">
              <table className="w-full">
                <thead className="bg-slate-800 sticky top-0">
                  <tr className="text-slate-400">
                    <th className="px-2 py-1 text-left">#</th>
                    <th className="px-2 py-1 text-left">Title</th>
                    <th className="px-2 py-1 text-left">Match</th>
                    <th className="px-2 py-1 text-right">Starts at</th>
                    <th className="px-2 py-1 text-right">Duration</th>
                    <th className="px-1 py-1 text-center w-6" title="Edit timing">▶</th>
                  </tr>
                </thead>
                <tbody>
                  {debugInfo.map((d, i) => {
                    const isProp = !d.match || d.match === "proportional" || d.match === "slide0";
                    const matchColor = isProp ? "text-yellow-400" : "text-green-400";
                    return (
                      <tr key={i} className={i % 2 === 0 ? "bg-slate-900/60" : "bg-slate-800/40"}>
                        <td className="px-2 py-1 text-slate-500">{d.slide}</td>
                        <td className="px-2 py-1 text-slate-300 max-w-28 truncate">{d.title || "—"}</td>
                        <td className={`px-2 py-1 ${matchColor}`}>{d.match || "—"}</td>
                        <td className="px-2 py-1 text-right text-indigo-300">{fmtTime(d.start_sec)}</td>
                        <td className="px-2 py-1 text-right text-green-400">{fmtTime(d.duration_sec)}</td>
                        <td className="px-1 py-1 text-center">
                          <button
                            onClick={() => setEditingRow(i)}
                            title="Edit timing in audio editor"
                            className="text-slate-500 hover:text-violet-400 transition-colors rounded p-0.5">
                            <Play size={11} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      {syncStatus === "error" && (
        <p className="text-xs text-red-400 text-center">✗ {message}</p>
      )}
      {syncStatus === "idle" && (
        <p className="text-xs text-slate-500 text-center">
          Uses Whisper to transcribe audio and match each slide to when it's spoken
        </p>
      )}

      {/* Audio Region Lightbox — rendered at component root so it's a true overlay */}
      {editingRow !== null && debugInfo && debugInfo[editingRow] && (
        <AudioRegionLightbox
          audioUrl={`${API_BASE}/downloads/${audioResult?.filename}`}
          totalDuration={totalAudioDuration}
          slideIndex={editingRow}
          slideTitle={debugInfo[editingRow].title}
          initialStart={debugInfo[editingRow].start_sec || 0}
          initialEnd={(debugInfo[editingRow].start_sec || 0) + (debugInfo[editingRow].duration_sec || 0)}
          onApply={handleApplyTiming}
          onClose={() => setEditingRow(null)}
        />
      )}
    </div>
  );
}

// ── Slide Timing Panel ────────────────────────────────────────────────────────
function SlideTimingPanel({ slidesResult, audioResult, slideTimes, setSlideTimes, thumbnails }) {
  const [autoFitting, setAutoFitting] = useState(false);

  const totalTime = slideTimes.reduce((a, b) => a + (parseFloat(b) || 0), 0);

  const formatTime = (s) => {
    const m = Math.floor(s / 60);
    const sec = (s % 60).toFixed(1);
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  };

  const autoFit = async () => {
    if (!audioResult?.filename) return;
    setAutoFitting(true);
    try {
      const r = await fetch(`${API_BASE}/api/audio/duration/${audioResult.filename}`);
      const { duration } = await r.json();
      const perSlide = Math.round((duration / slideTimes.length) * 10) / 10;
      setSlideTimes(slideTimes.map(() => perSlide));
    } catch (e) {
      console.error("Auto-fit failed:", e);
    } finally {
      setAutoFitting(false);
    }
  };

  const updateTime = (index, value) => {
    const updated = [...slideTimes];
    updated[index] = parseFloat(value) || 1;
    setSlideTimes(updated);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400 flex items-center gap-1">
          <Clock size={12} /> Set duration per slide
        </span>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500">Total: <span className="text-indigo-300">{formatTime(totalTime)}</span></span>
          {audioResult && (
            <button onClick={autoFit} disabled={autoFitting}
              className="flex items-center gap-1 text-xs px-2.5 py-1 bg-indigo-900/50 hover:bg-indigo-800/60 border border-indigo-700/50 text-indigo-300 rounded-lg transition-colors disabled:opacity-50">
              {autoFitting ? <Loader size={11} className="animate-spin" /> : <Zap size={11} />}
              Auto-fit to audio
            </button>
          )}
        </div>
      </div>

      <div className="max-h-56 overflow-y-auto space-y-1 pr-1">
        {slideTimes.map((dur, i) => (
          <div key={i} className="flex items-center gap-2 bg-slate-900/70 rounded-lg px-2 py-1.5">
            {thumbnails[i] ? (
              <img
                src={`${API_BASE}${thumbnails[i].url}`}
                alt={`Slide ${i + 1}`}
                className="w-14 h-8 object-cover rounded border border-slate-700 shrink-0"
              />
            ) : (
              <div className="w-14 h-8 bg-slate-700 rounded border border-slate-600 shrink-0 flex items-center justify-center">
                <Film size={12} className="text-slate-500" />
              </div>
            )}
            <span className="text-xs text-slate-400 w-14 shrink-0">Slide {i + 1}</span>
            <div className="flex items-center gap-1 ml-auto">
              <input
                type="number" min="1" max="300" step="0.5"
                value={dur}
                onChange={e => updateTime(i, e.target.value)}
                className="w-16 bg-slate-800 border border-slate-600 rounded p-1 text-xs text-center text-slate-100 focus:outline-none focus:border-indigo-500"
              />
              <span className="text-xs text-slate-500">s</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Upload helpers ────────────────────────────────────────────────────────────
function UploadAudioButton({ onDone }) {
  const ref = useRef();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const handleFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setError(""); setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await fetch(`${API_BASE}/api/audio/upload`, { method: "POST", body: form });
      if (!r.ok) throw new Error((await r.json()).detail || await r.text());
      const result = await r.json();
      onDone(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  return (
    <div>
      <input ref={ref} type="file" accept=".mp3,.wav,.m4a,.aac,.ogg,.flac" className="hidden" onChange={handleFile} />
      <button onClick={() => ref.current?.click()} disabled={uploading}
        className="w-full py-2 mt-2 border border-dashed border-slate-600 hover:border-indigo-500 rounded-xl text-sm text-slate-400 hover:text-indigo-300 transition-colors flex items-center justify-center gap-2 disabled:opacity-50">
        {uploading ? <Loader size={14} className="animate-spin" /> : <Upload size={14} />}
        {uploading ? "Uploading..." : "Upload existing audio file"}
      </button>
      {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
    </div>
  );
}

function UploadVideoButton({ onDone }) {
  const ref = useRef();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const handleFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setError(""); setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await fetch(`${API_BASE}/api/slides/upload-video`, { method: "POST", body: form });
      if (!r.ok) throw new Error((await r.json()).detail || await r.text());
      const result = await r.json();
      onDone(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  return (
    <div>
      <input ref={ref} type="file" accept=".mp4,.mov,.avi,.mkv,.webm" className="hidden" onChange={handleFile} />
      <button onClick={() => ref.current?.click()} disabled={uploading}
        className="w-full py-2 mt-2 border border-dashed border-slate-600 hover:border-violet-500 rounded-xl text-sm text-slate-400 hover:text-violet-300 transition-colors flex items-center justify-center gap-2 disabled:opacity-50">
        {uploading ? <Loader size={14} className="animate-spin" /> : <Upload size={14} />}
        {uploading ? "Uploading..." : "Upload existing video file"}
      </button>
      {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
    </div>
  );
}

// ── Load Project Modal ────────────────────────────────────────────────────────
function LoadProjectModal({ onClose, onLoad }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState("");
  const [deleting, setDeleting] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/project/list`)
      .then(r => r.json())
      .then(d => { setProjects(d.projects || []); setLoading(false); })
      .catch(() => { setError("Could not load projects."); setLoading(false); });
  }, []);

  const fmtDate = iso => {
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  };

  const handleDelete = async (pid) => {
    setDeleting(pid);
    await fetch(`${API_BASE}/api/project/delete/${pid}`, { method: "DELETE" }).catch(() => {});
    setProjects(p => p.filter(x => x.project_id !== pid));
    setDeleting(null);
  };

  const handleLoad = async (pid) => {
    try {
      const r = await fetch(`${API_BASE}/api/project/load/${pid}`);
      if (!r.ok) throw new Error("Not found");
      const data = await r.json();
      onLoad(data);
      onClose();
    } catch (e) {
      setError("Failed to load project: " + e.message);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-2xl w-full max-w-lg shadow-2xl border border-slate-700">
        <div className="flex items-center justify-between p-5 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <FolderOpen size={20} className="text-indigo-400" />
            <span className="font-semibold text-lg">Load Project</span>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>
        <div className="p-5 max-h-96 overflow-y-auto">
          {loading && <p className="text-slate-400 text-sm text-center py-4">Loading…</p>}
          {error   && <p className="text-red-400 text-sm">{error}</p>}
          {!loading && projects.length === 0 && (
            <p className="text-slate-400 text-sm text-center py-4">No saved projects yet.</p>
          )}
          <div className="space-y-2">
            {projects.map(p => (
              <div key={p.project_id}
                className="flex items-center gap-3 bg-slate-700/50 border border-slate-600 rounded-xl px-4 py-3">
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-sm text-slate-100 truncate">{p.project_name}</p>
                  <p className="text-xs text-slate-400">
                    {p.slide_count ? `${p.slide_count} slides` : "—"}{" "}
                    · {fmtDate(p.saved_at)}
                  </p>
                </div>
                <button onClick={() => handleLoad(p.project_id)}
                  className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-xs font-medium whitespace-nowrap">
                  Load
                </button>
                <button onClick={() => handleDelete(p.project_id)} disabled={deleting === p.project_id}
                  className="p-1.5 text-slate-500 hover:text-red-400 transition-colors disabled:opacity-40">
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>
        <div className="p-4 border-t border-slate-700 flex justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-400 hover:text-white">Close</button>
        </div>
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [showAudio, setShowAudio] = useState(false);
  const [showSlides, setShowSlides] = useState(false);
  const [audioResult, setAudioResult] = useState(null);
  const [slidesResult, setSlidesResult] = useState(null);
  const [mergeProgress, setMergeProgress] = useState(0);
  const [mergeMessage, setMergeMessage] = useState("");
  const [merging, setMerging] = useState(false);
  const [finalResult, setFinalResult] = useState(null);
  const [mergeError, setMergeError] = useState("");
  const [syncMode, setSyncMode] = useState("auto_fit");
  const [providerInfo, setProviderInfo] = useState(null);
  const [slideTimes, setSlideTimes] = useState([]);
  const [thumbnails, setThumbnails] = useState([]);
  // Project save / load
  const [currentProjectId, setCurrentProjectId] = useState(null);
  const [projectName, setProjectName]     = useState("Untitled Project");
  const [showLoadProject, setShowLoadProject] = useState(false);
  const [showSettings, setShowSettings]       = useState(false);
  const [saving, setSaving]               = useState(false);
  const [savedMsg, setSavedMsg]           = useState("");
  const [syncDebugInfo, setSyncDebugInfo] = useState(null);
  const [editingProjectName, setEditingProjectName] = useState(false);
  const [projectNameDraft, setProjectNameDraft]     = useState("");

  // Show settings on first launch if no API keys are configured
  useEffect(() => {
    fetch(`${API_BASE}/api/settings`)
      .then(r => r.json())
      .then(d => { if (!d.is_configured) setShowSettings(true); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/audio/config`)
      .then(r => r.json())
      .then(data => setProviderInfo(data))
      .catch(() => {});
  }, []);

  // Load thumbnails when slides result changes.
  // IMPORTANT: only reset slideTimes to defaults when the frame count actually
  // changes (new PPTX uploaded).  If we already hold the right number of
  // entries — from a project load, AI sync, or manual edits — keep them so
  // we don't silently wipe custom timing every time slidesResult updates.
  useEffect(() => {
    if (slidesResult?.frames_job_id) {
      fetch(`${API_BASE}/api/slides/frames/${slidesResult.frames_job_id}`)
        .then(r => r.json())
        .then(data => {
          const frames = data.frames || [];
          setThumbnails(frames);
          // Use functional updater: preserve existing times if count matches.
          setSlideTimes(prev =>
            prev.length === frames.length ? prev : Array(frames.length).fill(5)
          );
        })
        .catch(() => {
          // Fallback: create placeholders from slide_count
          const n = slidesResult.slide_count || 0;
          setThumbnails([]);
          setSlideTimes(prev =>
            prev.length === n ? prev : Array(n).fill(5)
          );
        });
    }
  }, [slidesResult]);

  const canMerge = audioResult && slidesResult && !merging && !finalResult;

  const startMerge = async () => {
    setMergeError(""); setMerging(true); setMergeProgress(0);
    try {
      const mode = effectiveSyncMode;
      const body = {
        audio_filename: audioResult.filename,
        video_filename: slidesResult.filename,
        sync_mode: mode,
      };

      if (mode === "auto_fit" || mode === "per_slide") {
        body.frames_job_id       = slidesResult.frames_job_id;
        body.transition          = slidesResult.transition          || "none";
        body.resolution          = slidesResult.resolution          || "1920x1080";
        body.animation           = slidesResult.animation           || "none";
        body.transition_clip_id  = slidesResult.transition_clip_id  || null;
      }
      if (mode === "per_slide") {
        // Source of truth priority:
        // 1. slideTimes  — the "Set duration per slide" panel values.
        //    These are populated by AI sync (via onSynced) AND updated by
        //    manual edits.  Using slideTimes as primary means the user can
        //    always override individual slides by typing in the panel.
        // 2. toVideoDurations(syncDebugInfo) — computed from the AI sync
        //    debug table.  Used only as a fallback when slideTimes are
        //    clearly invalid (all zeros / 1-second defaults).
        const panelDurations = slideTimes.map(t => parseFloat(t) || 0);
        const debugDurations = toVideoDurations(syncDebugInfo);

        // Treat slideTimes as valid when at least half the values are > 2 s
        // (rules out the "frames useEffect reset everything to 5 s default" case
        //  and also handles partly-filled states gracefully).
        const validSlideCount = panelDurations.filter(d => d > 2).length;
        const panelIsValid = validSlideCount >= panelDurations.length / 2;

        let source;
        if (panelIsValid && panelDurations.length > 0) {
          body.slide_durations = panelDurations;
          source = "panel (user edits / AI-sync)";
        } else if (debugDurations && debugDurations.length > 0) {
          body.slide_durations = debugDurations;
          source = "AI-sync debug fallback";
        } else {
          body.slide_durations = panelDurations;
          source = "panel (fallback — no debug info)";
        }

        const totalSent = body.slide_durations.reduce((s, d) => s + d, 0);
        console.log(`[merge] slide_durations source: ${source} | ` +
          `count=${body.slide_durations.length} | total=${totalSent.toFixed(1)}s | ` +
          `first5=[${body.slide_durations.slice(0,5).map(d=>d.toFixed(2)).join(', ')}]`);
      }

      const r = await fetch(`${API_BASE}/api/merge/combine`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(await r.text());
      const { job_id } = await r.json();
      const result = await pollJob(job_id, (p, m) => { setMergeProgress(p); setMergeMessage(m); });
      setFinalResult(result);
    } catch (e) {
      setMergeError(e.message);
    } finally {
      setMerging(false);
    }
  };

  const reset = () => {
    setAudioResult(null); setSlidesResult(null);
    setFinalResult(null); setMergeError("");
    setMergeProgress(0); setMergeMessage("");
    setSlideTimes([]); setThumbnails([]);
  };

  // ── Project save / load ─────────────────────────────────────────────────────
  const buildProjectState = () => ({
    project_name:  projectName,
    audio_result:  audioResult,
    slides_result: slidesResult,
    slide_times:   slideTimes,
    sync_mode:     syncMode,
    debug_info:    syncDebugInfo,
  });

  // overrides: optional partial state to merge into the saved body.
  // Used by auto-save after AI sync to pass fresh data that hasn't yet
  // propagated through React's async state updates.
  const handleSave = async (overrides) => {
    // Guard: only accept a plain object as overrides (never a DOM Event etc.)
    const safeOverrides = (overrides && overrides.constructor === Object) ? overrides : {};
    setSaving(true); setSavedMsg("");
    try {
      const body = { ...buildProjectState(), ...safeOverrides };
      let r;
      if (currentProjectId) {
        r = await fetch(`${API_BASE}/api/project/save/${currentProjectId}`,
          { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      } else {
        r = await fetch(`${API_BASE}/api/project/save`,
          { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      }
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setCurrentProjectId(data.project_id);
      setSavedMsg("Saved ✓");
      setTimeout(() => setSavedMsg(""), 3000);
    } catch (e) {
      setSavedMsg("Save failed: " + e.message);
    } finally {
      setSaving(false);
    }
  };

  // Auto-save immediately after AI sync completes.
  // The fresh debugInfo and durations are passed directly to avoid
  // reading stale React state (setSyncDebugInfo is async and may not
  // have committed by the time handleSave reads syncDebugInfo).
  const handleAutoSaveAfterSync = (debugInfo, durations) => {
    handleSave({
      debug_info:  debugInfo,
      slide_times: durations,
      sync_mode:   "per_slide",
    });
  };

  const handleLoadProject = (data) => {
    if (data.audio_result)  setAudioResult(data.audio_result);
    if (data.sync_mode)     setSyncMode(data.sync_mode);
    if (data.debug_info)    setSyncDebugInfo(data.debug_info);
    if (data.project_name)  setProjectName(data.project_name);
    if (data.project_id)    setCurrentProjectId(data.project_id);
    setFinalResult(null);
    setMergeError("");

    // Restore slide timings as corrected video-timeline durations.
    // Always prefer re-computing from debug_info (has start_sec for the
    // video-start correction) over the raw slide_times that were saved with
    // the old duration_sec values.  Fall back to slide_times only if there
    // is no debug_info (e.g. manually-timed project with no AI sync).
    // Set BEFORE slidesResult so the frames-fetch useEffect sees the correct
    // count and its functional updater preserves them instead of resetting to 5 s.
    const restoredTimes =
      data.debug_info?.length  ? toVideoDurations(data.debug_info) :
      data.slide_times?.length ? data.slide_times :
      null;
    if (restoredTimes) setSlideTimes(restoredTimes);

    // Set slidesResult last — triggers the frames-fetch useEffect.
    if (data.slides_result) setSlidesResult(data.slides_result);
  };

  const steps = [
    { label: "Script → Audio", done: !!audioResult,  active: !audioResult },
    { label: "Slides → Video", done: !!slidesResult, active: !slidesResult },
    { label: "Merge",          done: !!finalResult,  active: canMerge },
    { label: "Download",       done: !!finalResult,  active: !!finalResult },
  ];

  const hasFrames = !!slidesResult?.frames_job_id;

  const syncModes = [
    { id: "auto_fit",  label: "🎵 Auto-fit",   desc: "Evenly distribute audio across all slides", requiresFrames: true },
    { id: "per_slide", label: "⏱️ Per slide",   desc: "Set a custom duration for each slide",      requiresFrames: true },
    { id: "pad",       label: "🔇 Pad",         desc: "Freeze last frame when video ends first",   requiresFrames: false },
    { id: "loop",      label: "🔁 Loop",        desc: "Loop video to match audio length",           requiresFrames: false },
  ];

  // If selected mode needs frames but we don't have them, fall back to loop
  const effectiveSyncMode = (!hasFrames && (syncMode === "auto_fit" || syncMode === "per_slide")) ? "loop" : syncMode;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <header className="border-b border-slate-700/50 px-6 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 shrink-0">
          <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center"><Film size={18} /></div>
          <div className="flex flex-col leading-tight">
            <span className="font-bold text-xl tracking-tight">ScriptToVideo</span>
            <span className="text-xs text-slate-400 tracking-wide">by Anoob C</span>
          </div>
        </div>

        {/* Project name (editable) */}
        <div className="flex-1 flex items-center justify-center min-w-0">
          {editingProjectName ? (
            <input autoFocus value={projectNameDraft}
              onChange={e => setProjectNameDraft(e.target.value)}
              onBlur={() => { setProjectName(projectNameDraft || "Untitled Project"); setEditingProjectName(false); }}
              onKeyDown={e => { if (e.key === "Enter") { setProjectName(projectNameDraft || "Untitled Project"); setEditingProjectName(false); } }}
              className="text-sm font-medium bg-slate-700 border border-indigo-500 rounded-lg px-3 py-1 text-slate-100 focus:outline-none w-64" />
          ) : (
            <button onClick={() => { setProjectNameDraft(projectName); setEditingProjectName(true); }}
              className="flex items-center gap-1.5 text-sm text-slate-300 hover:text-white group">
              <span className="font-medium truncate max-w-xs">{projectName}</span>
              <Edit2 size={12} className="text-slate-500 group-hover:text-slate-300 shrink-0" />
            </button>
          )}
          {currentProjectId && (
            <span className="ml-2 text-xs text-slate-600 hidden sm:inline">#{currentProjectId}</span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {providerInfo && <ProviderBadge provider={providerInfo.provider} />}
          {/* Load project */}
          <button onClick={() => setShowLoadProject(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors">
            <FolderOpen size={13} /> Load
          </button>
          {/* Save project */}
          <button onClick={() => handleSave()} disabled={saving || (!audioResult && !slidesResult)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white transition-colors">
            {saving ? <Loader size={12} className="animate-spin" /> : <Save size={13} />}
            {saving ? "Saving…" : currentProjectId ? "Save" : "Save Project"}
          </button>
          {savedMsg && <span className="text-xs text-green-400">{savedMsg}</span>}
          {/* Settings */}
          <button onClick={() => setShowSettings(true)}
            title="API Keys & Settings"
            className="w-8 h-8 flex items-center justify-center rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-400 hover:text-slate-200 transition-colors">
            <Settings size={15} />
          </button>
        </div>
      </header>

      <div className="max-w-3xl mx-auto px-6 pt-8">
        {/* Step indicators */}
        <div className="flex items-center justify-between mb-8">
          {steps.map((s, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="flex flex-col items-center gap-1">
                <StepBadge n={i + 1} done={s.done} active={s.active} />
                <span className={`text-xs font-medium ${s.done ? "text-green-400" : s.active ? "text-indigo-300" : "text-slate-500"}`}>{s.label}</span>
              </div>
              {i < steps.length - 1 && <ChevronRight size={16} className={`mb-5 ${s.done ? "text-green-500" : "text-slate-600"}`} />}
            </div>
          ))}
        </div>

        {/* Cards row */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          {/* Audio card */}
          <div className={`rounded-2xl border p-5 transition-all ${audioResult ? "border-green-500/50 bg-green-900/10" : "border-slate-700 bg-slate-800/50"}`}>
            <div className="flex items-center gap-2 mb-3">
              <Mic size={18} className={audioResult ? "text-green-400" : "text-indigo-400"} />
              <span className="font-semibold">Audio Generation</span>
              {audioResult && <CheckCircle size={16} className="text-green-400 ml-auto" />}
            </div>
            {audioResult ? (
              <div className="space-y-2">
                <p className="text-xs text-green-400">✓ Audio ready</p>
                <audio controls src={`${API_BASE}${audioResult.audio_url}`} className="w-full h-8 rounded" />
                <button onClick={() => setAudioResult(null)} className="text-xs text-slate-400 hover:text-white underline">Replace</button>
              </div>
            ) : (
              <div>
                <p className="text-sm text-slate-400 mb-3">Generate from your script, or upload an existing audio file.</p>
                <button onClick={() => setShowAudio(true)}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 rounded-xl text-sm font-medium transition-colors flex items-center justify-center gap-2">
                  <Mic size={15} /> Open Audio Generator
                </button>
                <UploadAudioButton onDone={r => setAudioResult(r)} />
              </div>
            )}
          </div>

          {/* Slides card */}
          <div className={`rounded-2xl border p-5 transition-all ${slidesResult ? "border-green-500/50 bg-green-900/10" : "border-slate-700 bg-slate-800/50"}`}>
            <div className="flex items-center gap-2 mb-3">
              <Film size={18} className={slidesResult ? "text-green-400" : "text-violet-400"} />
              <span className="font-semibold">Slides to Video</span>
              {slidesResult && <CheckCircle size={16} className="text-green-400 ml-auto" />}
            </div>
            {slidesResult ? (
              <div className="space-y-2">
                <p className="text-xs text-green-400">
                  ✓ {slidesResult.slide_count ? `${slidesResult.slide_count} slides converted` : "Video ready"}
                </p>
                <video controls src={`${API_BASE}${slidesResult.video_url}`} className="w-full rounded-lg" style={{maxHeight:"120px"}} />
                <button onClick={() => { setSlidesResult(null); setThumbnails([]); setSlideTimes([]); }} className="text-xs text-slate-400 hover:text-white underline">Replace</button>
              </div>
            ) : (
              <div>
                <p className="text-sm text-slate-400 mb-3">Convert a PPTX, or upload an existing video file.</p>
                <button onClick={() => setShowSlides(true)}
                  className="w-full py-2 bg-violet-600 hover:bg-violet-500 rounded-xl text-sm font-medium transition-colors flex items-center justify-center gap-2">
                  <Film size={15} /> Open Slides Converter
                </button>
                <UploadVideoButton onDone={r => { setSlidesResult(r); setThumbnails([]); setSlideTimes([]); }} />
              </div>
            )}
          </div>
        </div>

        {/* Merge panel */}
        <div className={`rounded-2xl border p-5 mb-6 transition-all ${finalResult ? "border-green-500/50 bg-green-900/10" : canMerge ? "border-indigo-500/50 bg-indigo-900/10" : "border-slate-700 bg-slate-800/30 opacity-60"}`}>
          <div className="flex items-center gap-2 mb-3">
            <Merge size={18} className={finalResult ? "text-green-400" : "text-indigo-400"} />
            <span className="font-semibold">Merge & Export</span>
            {finalResult && <CheckCircle size={16} className="text-green-400 ml-auto" />}
          </div>

          {finalResult ? (
            <div className="space-y-3">
              <p className="text-sm text-green-400 font-medium">✓ Your final video is ready!</p>
              <video controls src={`${API_BASE}${finalResult.video_url}`} className="w-full rounded-xl border border-green-500/30" />
              <div className="flex gap-3">
                <a href={`${API_BASE}${finalResult.video_url}`} download
                  className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-green-600 hover:bg-green-500 rounded-xl text-sm font-medium transition-colors">
                  <Download size={15} /> Download MP4
                </a>
                <button onClick={reset} className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-xl text-sm text-slate-300 transition-colors">Start Over</button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-slate-400">
                {canMerge ? "Both audio and slides are ready. Choose a sync mode and merge." : "Complete both steps above to unlock the merge."}
              </p>

              {canMerge && (
                <>
                  {/* Sync mode selector */}
                  {!hasFrames && (
                    <div className="flex items-center gap-2 bg-amber-900/20 border border-amber-700/40 rounded-lg px-3 py-2 text-xs text-amber-300">
                      <AlertCircle size={12} className="shrink-0" />
                      Auto-fit and Per-slide require a PPTX-converted video. Using uploaded video: only Pad/Loop available.
                    </div>
                  )}
                  <div className="grid grid-cols-2 gap-2">
                    {syncModes.map(m => {
                      const disabled = m.requiresFrames && !hasFrames;
                      const active = effectiveSyncMode === m.id;
                      return (
                        <button key={m.id}
                          onClick={() => !disabled && setSyncMode(m.id)}
                          title={disabled ? "Requires PPTX-converted slides" : m.desc}
                          className={`px-3 py-2 rounded-lg text-xs font-medium border transition-colors text-left
                            ${disabled ? "opacity-40 cursor-not-allowed border-slate-700 text-slate-600" :
                              active ? "bg-indigo-600 border-indigo-500 text-white" :
                              "border-slate-600 text-slate-400 hover:border-indigo-500 hover:text-slate-200"}`}>
                          <div>{m.label}</div>
                          <div className={`text-xs mt-0.5 font-normal ${active ? "text-indigo-200" : "text-slate-500"}`}>{m.desc}</div>
                        </button>
                      );
                    })}
                  </div>

                  {/* AI Sync — shown when frames are available */}
                  {hasFrames && (
                    <AiSyncButton
                      audioResult={audioResult}
                      slidesResult={slidesResult}
                      initialDebugInfo={syncDebugInfo}
                      onDebugInfo={setSyncDebugInfo}
                      onSyncComplete={handleAutoSaveAfterSync}
                      onSynced={(durations) => {
                        setSlideTimes(durations);
                        setSyncMode("per_slide");
                      }}
                    />
                  )}

                  {/* Auto-fit info */}
                  {syncMode === "auto_fit" && (
                    <div className="bg-indigo-900/30 border border-indigo-700/40 rounded-lg p-3 text-xs text-indigo-300">
                      <Zap size={12} className="inline mr-1" />
                      Audio duration will be measured and split evenly across all {slidesResult.slide_count} slides automatically.
                    </div>
                  )}

                  {/* Per-slide timing */}
                  {syncMode === "per_slide" && slideTimes.length > 0 && (
                    <SlideTimingPanel
                      slidesResult={slidesResult}
                      audioResult={audioResult}
                      slideTimes={slideTimes}
                      setSlideTimes={setSlideTimes}
                      thumbnails={thumbnails}
                    />
                  )}

                  <button onClick={startMerge} disabled={merging}
                    className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-xl text-sm font-medium transition-colors flex items-center justify-center gap-2">
                    {merging ? <Loader size={15} className="animate-spin" /> : <Merge size={15} />}
                    {merging ? "Merging..." : "Create Final Video"}
                  </button>
                </>
              )}

              {merging && <ProgressBar value={mergeProgress} label={mergeMessage || "Merging..."} />}
              {mergeError && (
                <div className="flex items-start gap-2 bg-red-900/40 border border-red-700 rounded-lg p-3">
                  <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
                  <p className="text-sm text-red-300">{mergeError}</p>
                </div>
              )}
            </div>
          )}
        </div>

        <p className="text-center text-xs text-slate-600 pb-8">
          Backend at <span className="text-slate-400">localhost:8000</span> · Frontend at <span className="text-slate-400">localhost:5173</span>
        </p>
      </div>

      {showAudio && <AudioModal onClose={() => setShowAudio(false)} onDone={r => setAudioResult(r)} />}
      {showSlides && <SlidesModal onClose={() => setShowSlides(false)} onDone={r => setSlidesResult(r)} />}
      {showLoadProject && (
        <LoadProjectModal
          onClose={() => setShowLoadProject(false)}
          onLoad={handleLoadProject}
        />
      )}
      {showSettings && (
        <SettingsModal
          onClose={() => setShowSettings(false)}
          onSaved={() => setTimeout(() => window.location.reload(), 1200)}
        />
      )}
    </div>
  );
}
