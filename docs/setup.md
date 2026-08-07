# Obrenna — Setup

## One-time

```powershell
cd e:\code\LLM\GrebGlob\backend
pip install -r requirements.txt

cd e:\code\LLM\GrebGlob\frontend
npm install
```

## Run it

From **PowerShell**, at the repo root (`e:\code\LLM\GrebGlob`):

```powershell
.\obrenna.ps1 start      # starts everything: backend, frontend, Ollama, codebase-agent, gateway
.\obrenna.ps1 stop       # stops everything, Ollama included
.\obrenna.ps1 restart    # stop then start
.\obrenna.ps1 status     # show what's currently running
```

One file, native PowerShell, no Git Bash dependency.

`start` skips anything already running; `stop` always stops all of it,
including Ollama, and sweeps for stray/duplicate processes too. `status` ends
with a duplicate check — if it ever warns about more than one instance of
something, run `stop` then `start` to clear it.

One manual step: the codebase-agent needs its device approved by name in
Obrenna's Settings the first time it connects.

**Always use this script to start/stop things.** Starting the backend or
frontend by hand in another terminal is how duplicate/orphaned processes
creep in (this took the app down once already — see git history on
obrenna.ps1 for the fix).

Open the app at http://localhost:5173.

---

## Codebases on other computers

Work on a repo that lives on a **different machine**, while this PC runs the
LLM. Nothing about the model moves — inference stays here on your GPU; only
file reads and edits happen on the other machine.

This already works by design: the **codebase-agent** runs on the machine that
holds the files and **dials out** to Obrenna over a WebSocket. The remote
machine needs no open ports and no port forwarding — only this PC does.

```
   Other PC (has the code)                    This PC (has the GPU)
   ┌──────────────────────┐                   ┌────────────────────┐
   │  codebase-agent      │ ──── dials ────►  │  Obrenna backend   │
   │  reads/edits files   │ ◄─── commands ──  │  Ollama + the LLM  │
   └──────────────────────┘                   └────────────────────┘
```

### 1. Start Obrenna so other machines can reach it

By default the backend binds `127.0.0.1` — localhost only, unreachable from
another PC. `-Lan` binds all interfaces instead and prints the exact command
to run on the other machine:

```powershell
.\obrenna.ps1 start -Lan
```

`-BindAddress <ip>` pins one interface if you'd rather not open all of them.
The default stays localhost-only: exposure is opt-in, because the API (chats,
settings) has **no authentication of its own** — see the security note below.

### 2. Allow inbound port 8000 through Windows Firewall

Required once, and **not done automatically** — opening a firewall port is a
security change worth making deliberately. In an **Administrator** PowerShell:

```powershell
New-NetFirewallRule -DisplayName "Obrenna backend (LAN)" `
  -Direction Inbound -Protocol TCP -LocalPort 8000 `
  -Profile Private -Action Allow
```

`-Profile Private` limits it to networks you've marked private (home/office).
Do not use `Public` on an untrusted network. To undo:

```powershell
Remove-NetFirewallRule -DisplayName "Obrenna backend (LAN)"
```

### 3. Run the agent on the other machine

Copy the `codebase-agent/` folder over, install its deps, and point it at this
PC's LAN IP (step 1 prints it):

```powershell
cd codebase-agent
pip install -r requirements.txt
python -m codebase_agent.main --server http://<this-pc-ip>:8000 --name work-laptop
```

`--name` is what you'll see in Settings, so give each machine a distinct one.

### 4. Approve the device, then add the project

In Obrenna → **Settings → Codebase projects**: approve the newly-connected
device by name, then add the project with its path **as it exists on that
machine** (e.g. `C:\dev\myapp` on the laptop, not a path on this PC).

Pick the project in the composer's codebase dropdown and it works exactly like
a local one — including manual/plan mode and per-edit approval.

### Security note

`-Lan` puts the whole backend API on your network, and Obrenna's own API has no
login. On a trusted home LAN that's usually fine. Two things do still protect
the codebase specifically:

- a device must be **approved by name** before any file operation runs, and
  approval is re-checked from the database on *every* dispatch, not just at
  connect time;
- `write_enabled` is per project, so a project can be attached read-only.

For anything beyond a trusted LAN — a machine over the internet — use the
gateway instead (`obrenna-gateway`: Caddy + auth service + Cloudflare tunnel).
That path has an actual login in front of it; `-Lan` does not.
