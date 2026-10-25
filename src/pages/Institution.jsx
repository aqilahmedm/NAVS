import { useEffect, useMemo, useRef, useState } from "react";
import { Download, FileUp, Play, Users, ShieldAlert, ClipboardCheck, Target, TrendingUp, UploadCloud } from "lucide-react";
import { api, post } from "../api.js";
import { useAsync } from "../hooks.js";
import { Avatar, CollegeLogo } from "../logos.jsx";
import { Async, Button, Card, Checks, Chips, Drawer, Empty, Field, Hint, KV, Kpi, LBL, LeadKpi, Pager, Status, reviewTone, useToast } from "../ui.jsx";
import { PageHead } from "../Shell.jsx";

const RD = { clarify: "Ask the student to clarify", corrected: "Mark corrected (re-upload pending)", escalate: "Escalate to AICTE", dismiss: "Dismiss as false positive (minor items only)" };
const SAMPLE = "apaar_id,name,dob,roll_no\n900000000001,Rahul Kumar,01-12-2004,A1\n900000000002,Wrong Name,01-01-2000,A2\n12345,Bad Id,01-01-2000,A3\n";

function Upload() {
  const [file, setFile] = useState(null), [over, setOver] = useState(false), [busy, setBusy] = useState(false), [res, setRes] = useState(null), [err, setErr] = useState(""), ref = useRef(null);
  const run = async () => {
    if (!file) return setErr("Choose a CSV file first."); setBusy(true); setErr(""); setRes(null);
    const fd = new FormData(); fd.append("file", file);
    try { setRes(await api("/api/institution/upload", { method: "POST", body: fd })); } catch (e) { if (!e.silent) setErr(e.message); } finally { setBusy(false); }
  };
  const sample = () => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([SAMPLE], { type: "text/csv" })); a.download = "sample_batch.csv"; a.click(); };
  return (
    <Card title="Check a batch" sub="Compare a CSV with the registry. This is a preview and nothing is saved." actions={<Button size="sm" icon={Download} onClick={sample}>Sample file</Button>}>
      <div className={"drop" + (over ? " over" : "")} onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={e => { e.preventDefault(); setOver(false); setFile(e.dataTransfer.files[0] || null); }}>
        <UploadCloud size={32} /><p>Drop a CSV here, or choose a file</p><small>Columns: <code>apaar_id, name, dob, roll_no</code> · dob as DD-MM-YYYY · no Aadhaar numbers</small>
        {file && <div className="file">{file.name}</div>}
        <div className="row c"><input ref={ref} type="file" accept=".csv,text/csv" hidden onChange={e => setFile(e.target.files[0] || null)} /><Button icon={FileUp} onClick={() => ref.current.click()}>Choose file</Button><Button variant="primary" icon={Play} loading={busy} onClick={run}>Run checks</Button></div>
      </div>
      {err && <div className="mt"><Hint tone="bad">{err}</Hint></div>}
      {res && <div className="mt"><Hint tone="ok">{res.counts.VERIFIED} verified · {res.counts.REVIEW} need review · {res.counts.FLAGGED} flagged. {res.note}</Hint>
        <div className="tbl-wrap"><table className="tbl" style={{ minWidth: 560 }}><thead><tr><th>Roll</th><th>Student</th><th>Result</th><th>What we found</th></tr></thead><tbody>{res.rows.map(x => <tr key={x.roll}><td>{x.roll}</td><td>{x.name}<div className="id mono">{x.apaar}</div></td><td><Status s={x.status} /></td><td className="find">{x.issues.map(y => <div key={y.code}>{LBL[y.code]}</div>)}{!x.issues.length && "—"}</td></tr>)}</tbody></table></div></div>}
    </Card>
  );
}

function ReviewForm({ x, onSaved }) {
  const [d, setD] = useState("clarify"), [n, setN] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState(""), toast = useToast();
  const save = async () => { setBusy(true); setErr(""); try { const j = await post("/api/institution/review", { cert_id: x.cert_id, decision: d, note: n }); toast("Decision saved and logged"); setN(""); onSaved(j.row); } catch (e) { if (!e.silent) setErr(e.message); } finally { setBusy(false); } };
  return (
    <div className="rev">
      <h4>Reviewer decision</h4>
      {x.review && <div className="note warn"><div><b>{x.state}</b> · {x.review.by} · {x.review.ts}<br />“{x.review.note}”</div></div>}
      <Field label="Decision" htmlFor="rd"><select id="rd" className="input" value={d} onChange={e => setD(e.target.value)}>{Object.entries(RD).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="Reason (required, kept in the audit log)" htmlFor="rn" hint="Don't put personal details in the reason."><textarea id="rn" className="input" rows={3} maxLength={300} value={n} onChange={e => setN(e.target.value)} /></Field>
      {err && <Hint tone="bad">{err}</Hint>}
      <Button variant="primary" loading={busy} onClick={save} disabled={n.trim().length < 8}>Save decision</Button>
      <p className="hint">Saving a decision asks you to confirm with a fresh code.</p>
    </div>
  );
}

function View({ j, queue }) {
  const i = j.institution, c = j.counts, [rows, setRows] = useState(j.students), [f, setF] = useState(queue ? "FLAGGED" : "ALL"), [q, setQ] = useState(""), [pg, setPg] = useState(0), [open, setOpen] = useState(null);
  const list = useMemo(() => rows.filter(x => (queue ? x.status !== "VERIFIED" : true) && (f === "ALL" || x.status === f) && (!q || (x.name + x.roll).toLowerCase().includes(q.toLowerCase()))), [rows, f, q, queue]);
  const P = 12, pages = Math.max(1, Math.ceil(list.length / P)), cur = Math.min(pg, pages - 1), sel = open != null ? rows.find(r => r.cert_id === open) : null;
  useEffect(() => setPg(0), [f, q]);
  const chips = [["ALL", "All"], ["VERIFIED", "Verified"], ["REVIEW", "Needs review"], ["FLAGGED", "Flagged"]].filter(c => !queue || c[0] !== "VERIFIED");
  const pct = Math.min(100, Math.round((i.reported / i.intake) * 100));
  const upd = r => setRows(a => a.map(x => (x.cert_id === r.cert_id ? { ...x, state: r.state, review: r.review } : x)));
  return (
    <div className="stack">
      <PageHead lead={<CollegeLogo code={i.code} name={i.name} size={60} />} title={queue ? "Review queue" : i.name} sub={queue ? "Records that need a person to look at them. A flag is not a finding of fraud." : `AICTE ID ${i.code} · ${i.city}, ${i.state}`} />
      {!queue && <>
        <div className="kpis">
          <LeadKpi label="Records checked" value={rows.length} parts={[{ label: "Verified", v: c.VERIFIED, color: "var(--ok)" }, { label: "Review", v: c.REVIEW, color: "var(--saffron)" }, { label: "Flagged", v: c.FLAGGED, color: "var(--bad)" }]} />
          <Kpi label="Approved intake" value={i.intake} icon={Target} /><Kpi label="Reported admissions" value={i.reported} icon={TrendingUp} tone={j.over_intake ? "bad" : ""} />
          <Kpi label="Needs review" value={c.REVIEW} tone="warn" icon={ClipboardCheck} /><Kpi label="Flagged" value={c.FLAGGED} tone="bad" icon={ShieldAlert} />
        </div>
        <Card title="Admissions against approved intake" sub={j.over_intake ? `Over by ${j.over_intake}. AICTE can see this.` : "Within the approved intake."}>
          <div className={"gauge" + (j.over_intake ? " over" : "")}><div className="gauge-t"><i style={{ width: pct + "%" }} /></div><div className="gauge-l"><span>0</span><b>{i.reported} reported</b><span>{i.intake} approved</span></div></div>
        </Card>
        <Upload />
      </>}
      <Card flush title={queue ? "Awaiting review" : "Records on file"} sub="Select a row for the evidence." actions={<div className="tools"><Chips options={chips} value={f} onChange={setF} /><input className="search" type="search" placeholder="Search roll or name" aria-label="Search records" value={q} onChange={e => setQ(e.target.value)} /></div>}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Roll / APAAR</th><th>Student</th><th>Programme</th><th>Result</th><th>What we found</th><th>Review</th></tr></thead>
          <tbody>{list.slice(cur * P, cur * P + P).map(x => (
            <tr key={x.cert_id} className="clk" tabIndex={0} onClick={() => setOpen(x.cert_id)} onKeyDown={e => e.key === "Enter" && setOpen(x.cert_id)}>
              <td><div className="roll">{x.roll}</div><div className="id mono">{x.apaar}</div></td>
              <td><span className="who-c"><Avatar i={x.face} size={30} />{x.name}</span></td><td>{x.program} {x.branch}</td><td><Status s={x.status} /></td>
              <td className="find">{x.issues.map(y => <div key={y.code}>{LBL[y.code]}</div>)}{!x.issues.length && "—"}</td>
              <td>{x.status === "VERIFIED" ? "—" : <Status tone={reviewTone(x.state)}>{x.state}</Status>}</td></tr>))}</tbody></table></div>
        {!list.length && <Empty>No records match.</Empty>}
        {list.length > P && <div className="card-b"><Pager page={cur} pages={pages} onPage={setPg} /></div>}
      </Card>
      <Drawer open={!!sel} onClose={() => setOpen(null)} title={sel && <span className="who-c"><Avatar i={sel.face} size={44} />{sel.name}</span>} status={sel && <Status s={sel.status} />}>
        {sel && <><h4>Record</h4><KV rows={[["Roll no.", sel.roll], ["APAAR ID", sel.apaar], ["Programme", sel.program + " " + sel.branch], ["Admission year", sel.year], ["Certificate", sel.cert_id]]} />
          <h4>Checks</h4><Checks items={sel.issues} />{sel.status !== "VERIFIED" && <ReviewForm x={sel} onSaved={upd} />}</>}
      </Drawer>
    </div>
  );
}
export default function Institution({ queue }) {
  const s = useAsync(() => api("/api/institution/overview"));
  return <Async s={s}>{j => <View j={j} queue={queue} />}</Async>;
}
