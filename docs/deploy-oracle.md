# Deploying Hai to Oracle Cloud (Always Free VM)

A from-scratch runbook for hosting Hai on an Oracle Cloud "Always Free" ARM VM.
Our storage is plain files under `data/`, so no code changes are needed — we just
need a Linux box with a disk, a reverse proxy for HTTPS, and a service manager to
keep `uvicorn` alive.

**Architecture on the box:**

```
Internet ──443/80──► Caddy (TLS, reverse proxy) ──127.0.0.1:8000──► uvicorn (systemd) ──► data/ on local disk
```

Caddy terminates TLS (auto Let's Encrypt) and forwards to uvicorn bound to
localhost. uvicorn runs under systemd so it restarts on crash/reboot. State lives
on the VM's boot volume — persistent across restarts and redeploys.

---

## 0. Prerequisites (one-time)

- Oracle Cloud account (free; credit card required at signup, not charged for Always Free).
- The repo pushed to a Git remote you can `git clone` from (GitHub).
- A domain name (optional but recommended — needed for automatic HTTPS). If you
  don't have one, you can run HTTP-only on the public IP for early testing, but
  the browser `localStorage`/clipboard niceties and "feels real" demo are better
  over HTTPS. A cheap option: a free subdomain or a $1–10/yr domain.
- Your `GOOGLE_API_KEY` handy.

---

## 1. Create the VM instance

In the Oracle Cloud Console:

1. **Compute → Instances → Create instance.**
2. **Image & shape:**
   - Image: **Canonical Ubuntu 24.04** (simplest for `apt`; Oracle Linux also fine).
   - Shape: **Ampere (Arm) — VM.Standard.A1.Flex.** Set **1 OCPU / 6 GB RAM**
     (well within Always Free; you can go up to 4 OCPU / 24 GB free). Arm is fine —
     our `python:3.13-slim` and all deps have arm64 builds.
   - ⚠️ If A1 capacity is unavailable in your region ("out of host capacity"),
     either retry later, switch availability domain, or fall back to the
     **VM.Standard.E2.1.Micro** (AMD, also Always Free, 1 OCPU / 1 GB — enough for
     ~5 testers but tighter).
3. **Networking:** let it create a new VCN + public subnet with a **public IPv4**.
4. **SSH keys:** upload your public key (or let it generate one and download the
   private key). You'll SSH in as user `ubuntu`.
5. Create. Note the **public IP**.

### 1a. Open ports 80 + 443 (TWO firewalls — common gotcha)

Oracle has a cloud-level firewall *and* the OS firewall. You must open both.

**Cloud level — Security List (or NSG):**
- VCN → your subnet → Security List → **Add Ingress Rules**:
  - Source `0.0.0.0/0`, TCP, dest port **80**
  - Source `0.0.0.0/0`, TCP, dest port **443**
- (Port 22 for SSH is already open by default.)

**OS level** — Ubuntu images ship with strict `iptables` rules from Oracle. After
you SSH in (next step), run:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

(If you chose Oracle Linux instead, use `firewall-cmd --add-service=http
--add-service=https --permanent && firewall-cmd --reload`.)

---

## 2. First login & base setup

```bash
ssh ubuntu@<PUBLIC_IP>

sudo apt update && sudo apt -y upgrade
sudo apt -y install python3.12-venv git   # 3.12 is the default on Ubuntu 24.04
```

> Note: Ubuntu 24.04 ships Python 3.12, not 3.13. Our code targets 3.12+ and runs
> fine on it. (If you specifically want 3.13, use the `deadsnakes` PPA — not
> necessary.)

---

## 3. Deploy the app

```bash
# Clone into /opt/hai (owned by your user for easy git pulls)
sudo mkdir -p /opt/hai && sudo chown ubuntu:ubuntu /opt/hai
git clone <YOUR_REPO_URL> /opt/hai
cd /opt/hai

# Virtualenv + deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3a. Create the production `.env`

```bash
cat > /opt/hai/.env <<'EOF'
LLM_PROVIDER=google
GOOGLE_API_KEY=PASTE_YOUR_KEY_HERE
GOOGLE_MODEL=gemini-3.1-flash-lite
GOOGLE_MODEL_FALLBACKS=gemini-3-flash-preview,gemma-4-31b-it
HAI_ACCESS_CODE=pick-a-shared-passphrase
HAI_DAILY_CALL_CAP=80
EOF
chmod 600 /opt/hai/.env
```

`main.py` already calls `load_dotenv()`, so this file is read automatically.
Setting `HAI_ACCESS_CODE` turns on the tester gate (unset = open, for local dev).

### 3b. Smoke test by hand

```bash
cd /opt/hai && source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
# In another SSH session:  curl -s localhost:8000/gate/required   → {"required":true}
# Ctrl+C when satisfied.
```

---

## 4. Run uvicorn under systemd

Create the service so it survives crashes and reboots:

```bash
sudo tee /etc/systemd/system/hai.service >/dev/null <<'EOF'
[Unit]
Description=Hai MVP (FastAPI/uvicorn)
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/hai
EnvironmentFile=/opt/hai/.env
ExecStart=/opt/hai/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now hai
sudo systemctl status hai --no-pager        # should be "active (running)"
journalctl -u hai -f                         # live logs (Ctrl+C to stop tailing)
```

Note we bind to `127.0.0.1` — only Caddy (next step) can reach uvicorn; it's not
exposed to the internet directly.

---

## 5. HTTPS reverse proxy with Caddy

Caddy auto-provisions and renews Let's Encrypt certs — far less fuss than nginx +
certbot.

```bash
sudo apt -y install debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt -y install caddy
```

Point your domain's **A record** at the VM's public IP first, then:

```bash
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
hai.yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
EOF

sudo systemctl reload caddy
```

Caddy fetches a cert within seconds. Visit `https://hai.yourdomain.com` — you
should hit the access gate.

> **No domain yet?** Replace the Caddyfile site block with `:80 {
> reverse_proxy 127.0.0.1:8000 }` and reach it at `http://<PUBLIC_IP>` (HTTP only,
> no cert). Switch to the domain block when ready.

---

## 6. Verify end-to-end

1. Open `https://hai.yourdomain.com` in a fresh browser → access gate appears.
2. Enter the `HAI_ACCESS_CODE` + a display name → chat with a persona, advance a day.
3. `sudo systemctl restart hai` → reload the page → **state persists** (proves
   files survived the restart; they're on the boot volume).
4. Collect feedback: `curl -s "https://hai.yourdomain.com/admin/feedback?code=YOUR_CODE"`.

---

## 7. Day-2 operations (the fun part)

**Deploy a new version:**

```bash
cd /opt/hai
git pull
source .venv/bin/activate && pip install -r requirements.txt   # only if deps changed
sudo systemctl restart hai
```

**Logs:** `journalctl -u hai -f` (app) · `journalctl -u caddy -f` (proxy/TLS).

**Back up state** (it's just files — copy them off-box periodically):

```bash
tar czf hai-data-$(date +%F).tgz -C /opt/hai data
# then scp it down:  scp ubuntu@<IP>:~/hai-data-*.tgz .
```

A simple cron backup (daily at 03:00):

```bash
( crontab -l 2>/dev/null; echo "0 3 * * * tar czf /home/ubuntu/hai-data-\$(date +\%F).tgz -C /opt/hai data" ) | crontab -
```

**Don't let backups fill the disk** — prune old ones, e.g. add
`find /home/ubuntu -name 'hai-data-*.tgz' -mtime +14 -delete` to cron.

---

## 8. Character-initiated messaging ("the character texts you first")

Personas can reach out **unprompted** — a spontaneous message grounded in their inner
world (an open thread, a preoccupation, something you shared). It's gated for restraint
and runs on the **same single-worker scheduler** as async replies (so the ONE-worker rule
above still applies — multiple workers would double up reach-outs).

How it works: every ~60s the scheduler considers each relationship. Cheap deterministic
gates run first (and cost nothing); only when they all pass does one LLM call both decide
*whether* it's worth interrupting and *write* the opener. Approved reach-outs are queued
like any other delayed message and delivered when due; the in-app inbox poll surfaces them.

### Env knobs (set in `/opt/hai/.env`, then `sudo systemctl restart hai`)

```bash
HAI_INITIATION_ENABLED=1      # master switch. 0/false = no unprompted reach-outs at all
# HAI_INITIATION_MODE=        # "fast" or "real"; unset = follows HAI_DELAY_MODE
HAI_INITIATION_MAX_PER_DAY=1  # daily cap on reach-outs PER (user, persona) relationship
# HAI_INITIATION_QUIET=       # 1/0 to force quiet hours on/off; unset = on in real, off in fast
# HAI_TZ_OFFSET=0             # hours from UTC for the 22:00–09:00 quiet window
```

**GENTLE defaults** (no env needed): never cold-opens (requires prior history *and* at least
one user message), reaches out only after ≥6h user idle, ≥6h cooldown since the last message,
quiet hours 22:00–09:00, at most 1/day, never stacks two pending reach-outs, and backs off
after each decision. In `fast` mode (the tester round) those windows compress to seconds and
quiet hours are off, so you can watch a reach-out land in a single sitting.

To **disable** entirely for a deploy: `HAI_INITIATION_ENABLED=0` + restart. To **tune frequency**:
raise `HAI_INITIATION_MAX_PER_DAY` and/or set `HAI_INITIATION_MODE=real` for true-hour pacing.
Quiet hours use a single server-wide UTC offset (`HAI_TZ_OFFSET`) — per-user timezones are future
work, so pick the offset matching most testers.

> Limitation today: delivery is app-only (in-app inbox + browser notifications). WhatsApp/SMS
> and window-aware routing are deferred (PRD §11) — the adapter seam (`app/messaging.py`) is in
> place so they slot in later without touching the loop.

---

## Gotchas checklist

- [ ] **Both** firewalls opened (Security List *and* OS `iptables`) — the #1 "why
      can't I reach it" cause on Oracle.
- [ ] A record propagated before reloading Caddy (else cert issuance fails; just
      `systemctl reload caddy` again once DNS resolves).
- [ ] `.env` is `chmod 600` and **not** committed (it's gitignored already).
- [ ] uvicorn bound to `127.0.0.1`, not `0.0.0.0` — keep it behind Caddy.
- [ ] Oracle may email about reclaiming **idle** Always Free compute. A1 instances
      are less affected; light real usage + the daily backup cron keeps it active.
- [ ] **Run uvicorn with ONE worker** (the default in `hai.service`). The async-reply
      scheduler is a single in-process asyncio task; multiple workers would each run it
      and deliver duplicate replies. Don't add `--workers N` to the systemd `ExecStart`.
- [ ] Async delivery: set `HAI_DELAY_MODE=fast` in `/opt/hai/.env` for the tester round
      (compressed delays so testers see replies land in a sitting), `real` for true hours.
      Queued replies live on disk (`data/state/<uid>/queue-*.json`) and survive a restart —
      past-due ones deliver on the next tick — but won't fire while the service is stopped.
- [ ] Character-initiated messaging shares that single scheduler (§8). Same ONE-worker rule.
      Disable with `HAI_INITIATION_ENABLED=0`; tune cadence via `HAI_INITIATION_MAX_PER_DAY`
      and `HAI_INITIATION_MODE`. Restart after `.env` edits — systemd reads it only at start.

---

## Troubleshooting: access code rejected (but works locally/Render)

The gate appears but no code is accepted. The value of `HAI_ACCESS_CODE` the running
process sees differs from what you type — usually stray quotes, a trailing space, or a
`\r` from CRLF line endings that systemd took literally from `.env`, or the service
wasn't restarted after editing `.env`.

```bash
# 1. See the EXACT value the live process has (cat -A reveals ^M / $ / quotes)
sudo cat /proc/$(pgrep -f 'uvicorn app.main' | head -1)/environ | tr '\0' '\n' \
  | grep HAI_ACCESS_CODE | cat -A

# 2. Check the raw .env line — must be exactly  HAI_ACCESS_CODE=hai-f1preview$
grep HAI_ACCESS_CODE /opt/hai/.env | cat -A

# 3. Make sure systemd isn't ALSO setting it elsewhere (stray Environment= line)
sudo systemctl show hai -p Environment

# 4. Strip any CRLF, then reload (systemd reads .env only at restart)
sed -i 's/\r$//' /opt/hai/.env
sudo systemctl restart hai
```

Note: systemd injects `EnvironmentFile` vars into the process, and the app's
`load_dotenv()` runs with `override=False`, so the systemd-parsed value wins — `.env`
is the single source of truth, but only after a restart. (The app now also strips
quotes/whitespace from the value defensively, so a clean restart should resolve it.)

## Optional hardening (later)

- `ufw` as a friendlier front-end to the firewall rules.
- Fail2ban for SSH.
- A non-root deploy user separate from `ubuntu`.
- Move `data/` to a dedicated **block volume** (mount at `/opt/hai/data`) if you
  want storage independent of the boot volume — not necessary at this scale, but
  good practice you can learn here.
