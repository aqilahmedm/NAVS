import { Printer } from "lucide-react";
import { api } from "../api.js";
import { useAsync } from "../hooks.js";
import { Avatar, CollegeLogo } from "../logos.jsx";
import { Async, Button, Card, Checks, Hint, KV } from "../ui.jsx";
import { PageHead } from "../Shell.jsx";
import Certificate from "./Cert.jsx";

export function StudentProfile() {
  const s = useAsync(() => api("/api/student/profile"));
  return (
    <Async s={s}>{j => { const p = j.profile, i = j.institution; return (
      <div className="stack">
        <PageHead title="My profile" sub="Your APAAR-linked record. A flag is a prompt for review, not a finding of fraud." />
        <div className="grid2">
          <Card title="Student details">
            <div className="profile"><Avatar i={p.face} size={84} /><div><h2>{p.name}</h2><span className="muted">APAAR {p.apaar}</span><div className="org-line"><CollegeLogo code={i.code} name={i.name} size={26} /><span>{i.name}</span></div></div></div>
            <KV rows={[["Roll no.", p.roll], ["Date of birth", p.dob], ["Category", p.category], ["Email", p.email], ["Phone", p.phone]]} />
            <p className="hint">Demo avatar only. No real photos are used.</p>
          </Card>
          <Card title="Data verification" sub="How your college record compares with the registry">
            <Checks items={j.checks} />
            {j.review && <div className="mt"><Hint tone="warn">Review status: <b>{j.review}</b></Hint></div>}
          </Card>
        </div>
      </div>); }}</Async>
  );
}
export function StudentCerts() {
  const s = useAsync(() => api("/api/student/profile"));
  return (
    <Async s={s}>{j => (
      <div className="stack">
        <PageHead title="My certificates" sub="Share the QR code. Anyone can verify it without seeing your marks."><Button variant="primary" icon={Printer} onClick={() => print()}>Print or save as PDF</Button></PageHead>
        <div className="certs">{j.certs.map(c => <Certificate key={c.kind} c={c} />)}</div>
      </div>)}</Async>
  );
}
