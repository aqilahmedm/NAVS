import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Type, Image as ImageIcon } from "lucide-react";
import { api } from "./api.js";
import { Skeleton } from "./ui.jsx";

/* Self-hosted CAPTCHA. value = { id, text, enabled }. Each challenge works for one attempt, so refresh after any failed try. */
export default function Captcha({ value, onChange, resetKey = 0 }) {
  const [ch, setCh] = useState(null), [kind, setKind] = useState("image"), [err, setErr] = useState("");
  const load = useCallback(async k => {
    setErr("");
    try { const j = await api("/api/captcha" + (k === "text" ? "?kind=text" : "")); setCh(j); onChange({ id: j.id || "", text: "", enabled: j.enabled !== false }); }
    catch (e) { setErr(e.message); }
  }, []);
  useEffect(() => { load(kind); }, [kind, resetKey]);
  if (ch && ch.enabled === false) return null;
  return (
    <div className="captcha">
      <div className="cap-top"><label htmlFor="cap-in">Human check</label><button type="button" className="link" onClick={() => load(kind)}><RefreshCw size={14} /> New one</button></div>
      <div className="cap-box">
        {!ch ? <Skeleton h={86} r={12} /> : kind === "image" ? <img src={ch.image} width="236" height="86" alt="CAPTCHA picture. Type the 5 letters and numbers you see." /> : <p className="cap-q">{ch.question}</p>}
        {ch?.answer && <span hidden data-test-answer="">{ch.answer}</span>}
      </div>
      <input id="cap-in" className="input" value={value.text} onChange={e => onChange({ ...value, text: e.target.value })} maxLength={8} autoComplete="off" autoCapitalize="characters" spellCheck="false"
        inputMode={kind === "text" ? "numeric" : "text"} placeholder={kind === "image" ? "Type the 5 characters" : "Your answer"} aria-describedby="cap-help" />
      <button type="button" id="cap-help" className="link" onClick={() => setKind(k => (k === "image" ? "text" : "image"))}>{kind === "image" ? <><Type size={14} /> Can't see it? Use a text question</> : <><ImageIcon size={14} /> Use a picture instead</>}</button>
      {err && <span className="err-t">{err}</span>}
    </div>
  );
}
