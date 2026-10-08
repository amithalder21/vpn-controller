# Default example scripts

These ship with Flotilla and are **seeded into the scripts library on startup**,
so they always appear in **Run script → script dropdown** and in a schedule's
**Source** picker. Seeding is non-destructive: an existing script of the same
name (e.g. one you edited) is never overwritten, and a deleted default reappears
on the next controller restart.

Each script has an editable `TARGET` (or `URL`) near the top — change it to your
own endpoint, or set it as an environment variable before running.

| Script             | What it does |
|--------------------|--------------|
| `geo-check.sh`     | Prints the exit's geo identity, then how a URL is served from there (status, content fingerprint, localization, CDN/cache headers). Compare across regions to spot geo variance. |
| `latency.sh`       | DNS / connect / TLS / TTFB / total timing from each exit, averaged over N runs, plus p50/min/max. A latency map of your service across regions. |
| `throughput.sh`    | Download-speed test per exit (MB/s and Mbit/s). Watch **Overview → Live throughput** fill in while it runs. |
| `uptime-probe.sh`  | Health check from each exit; exits non-zero on failure. Put it on a **Schedule** and set `WEBHOOK_URL` to get alerts when a region can't reach your service. |

They target the Debian worker image (`bash`, `curl`, `jq`, coreutils, dnsutils),
so standard tooling is available.
