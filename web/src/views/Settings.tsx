import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { api, setToken } from "@/lib/api";
import { keys, toast, useProxy, useSettings } from "@/lib/hooks";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { CountryChip, Mono } from "@/components/common";

export function Settings() {
  const qc = useQueryClient();
  const { data: settings } = useSettings();
  const { data: proxy } = useProxy();
  const [tok, setTok] = useState("");

  async function saveToken() {
    if (!tok.trim()) return;
    setToken(tok.trim());
    toast("Token saved to this browser", "ok");
    setTok("");
    qc.invalidateQueries();
  }
  async function setAutoheal(v: boolean) {
    try {
      await api("POST", "/api/settings", { autoheal: v });
    } catch (e: any) {
      toast(e.message, "err");
    }
    qc.invalidateQueries({ queryKey: keys.settings });
  }
  async function togglePool(name: string, pool: boolean) {
    try {
      await api("POST", `/api/proxy/${name}`, { pool });
    } catch (e: any) {
      toast(e.message, "err");
    }
    qc.invalidateQueries({ queryKey: keys.proxy });
  }

  return (
    <div className="grid max-w-[1120px] gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Control token</CardTitle>
        </CardHeader>
        <CardBody className="space-y-3">
          <p className="text-[12.5px] text-muted-foreground">
            Required for every API call. It authorises this browser to control the fleet — keep it secret and never expose the
            controller publicly without a proxy in front.
          </p>
          <div className="flex gap-2">
            <Input type="password" value={tok} onChange={(e) => setTok(e.target.value)} placeholder="Paste your control token" autoComplete="off" />
            <Button variant="primary" onClick={saveToken}>
              Save
            </Button>
          </div>
          <p className="text-2xs text-muted-foreground">Stored in this browser only.</p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Auto-heal</CardTitle>
          <div className="ml-auto">
            <Switch checked={!!settings?.autoheal} onCheckedChange={setAutoheal} />
          </div>
        </CardHeader>
        <CardBody className="space-y-2 text-[13px] leading-relaxed text-muted-foreground">
          <p>
            When enabled, a background watchdog reconnects connections that are meant to be up but have dropped or gone
            unhealthy. Manual <b>Disconnect</b> is always respected. After repeated failures a connection is flagged{" "}
            <b>needs attention</b> until you reconnect it.
          </p>
          <p>
            Alerts webhook:{" "}
            <Badge tone={settings?.webhook ? "ok" : "muted"} dot>
              {settings?.webhook ? "configured" : "not set"}
            </Badge>{" "}
            <span className="text-[12px]">
              — set <span className="font-mono">WEBHOOK_URL</span> on the controller to enable.
            </span>
          </p>
        </CardBody>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Proxy pool</CardTitle>
          {proxy && (
            <Badge tone={proxy.enabled ? "ok" : "muted"} dot>
              {proxy.enabled ? "enabled" : "off"}
            </Badge>
          )}
        </CardHeader>
        <CardBody className="space-y-3 text-[13px] leading-relaxed">
          <p className="text-muted-foreground">
            Route any tool (browser, curl, Burp, scanners) through your exits. Each healthy exit is an <b>HTTP proxy</b> on{" "}
            <span className="font-mono">127.0.0.1</span>; the round-robin endpoint rotates across the enabled, healthy exits per
            connection. Loopback-only — tunnel it over SSH for remote use.
          </p>
          <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2">
            <span className="text-[12.5px] text-muted-foreground">Round-robin endpoint</span>
            <Mono className="font-semibold">127.0.0.1:18080</Mono>
            <Button
              size="xs"
              variant="ghost"
              onClick={() => {
                navigator.clipboard?.writeText("http://127.0.0.1:18080");
                toast("Copied", "ok", 1200);
              }}
            >
              <Copy /> Copy
            </Button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b border-border/70 text-left text-2xs uppercase tracking-wider text-muted-foreground">
                  <th className="py-2 pr-2 font-semibold">Exit</th>
                  <th className="px-2 py-2 font-semibold">Proxy address</th>
                  <th className="px-2 py-2 font-semibold">State</th>
                  <th className="px-2 py-2 text-right font-semibold">In rotation</th>
                </tr>
              </thead>
              <tbody>
                {!proxy?.exits.length && (
                  <tr>
                    <td colSpan={4} className="py-6 text-center text-[13px] text-muted-foreground">
                      No exits in the pool yet — connect a tunnel to add one.
                    </td>
                  </tr>
                )}
                {proxy?.exits.map((e) => (
                  <tr key={e.name} className="border-b border-border/60 last:border-0">
                    <td className="py-2.5 pr-2 font-mono text-[13px]">{e.name}</td>
                    <td className="px-2 py-2.5">
                      <Mono className="text-muted-foreground">127.0.0.1:{e.port}</Mono>
                    </td>
                    <td className="px-2 py-2.5">
                      <Badge tone={e.online ? "ok" : "muted"} dot>
                        {e.online ? "online" : "offline"}
                      </Badge>
                    </td>
                    <td className="px-2 py-2.5 text-right">
                      <Switch checked={e.pool} onCheckedChange={(v) => togglePool(e.name, v)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardBody>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>About</CardTitle>
        </CardHeader>
        <CardBody className="space-y-1 text-[13px] leading-relaxed text-muted-foreground">
          <div>
            <b className="text-foreground">Flotilla</b> — one control plane for every exit.
          </div>
          <div>
            Manage a fleet of VPN tunnels from one place; each connection is an isolated exit — run scripts across the fleet,
            probe targets from every region, and stream output live.
          </div>
          <div className="pt-1">
            <a href="https://github.com/amithalder21/vpn-controller" target="_blank" rel="noopener" className="text-accent hover:underline">
              github.com/amithalder21/vpn-controller
            </a>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
