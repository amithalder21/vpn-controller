import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api, setToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function TokenGate({ onAuthed }: { onAuthed: () => void }) {
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const t = val.trim();
    if (!t) return;
    setBusy(true);
    setErr("");
    setToken(t);
    try {
      await api("GET", "/api/settings");
      onAuthed();
    } catch {
      setErr("That token was rejected. Check it and try again.");
      setToken("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-background bg-grid px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-border bg-card p-7 shadow-float">
        <div className="mb-5 flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
            <ShieldCheck className="size-5" />
          </span>
          <div>
            <div className="text-lg font-bold tracking-tight">Flotilla</div>
            <div className="text-xs text-muted-foreground">Enter your control token to continue</div>
          </div>
        </div>
        <Input
          type="password"
          autoFocus
          placeholder="Control token"
          value={val}
          onChange={(e) => setVal(e.target.value)}
          autoComplete="off"
        />
        {err && <p className="mt-2 text-xs text-bad">{err}</p>}
        <Button type="submit" variant="primary" className="mt-4 w-full" disabled={busy}>
          {busy ? "Checking…" : "Unlock"}
        </Button>
        <p className="mt-3 text-center text-2xs text-muted-foreground">Stored in this browser only.</p>
      </form>
    </div>
  );
}
