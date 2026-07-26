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

That's it — no flags. `start` skips anything already running; `stop` always
stops all of it, including Ollama, and sweeps for stray/duplicate processes
too. `status` ends with a duplicate check — if it ever warns about more than
one instance of something, run `stop` then `start` to clear it.

One manual step: the codebase-agent needs its device approved by name in
Obrenna's Settings the first time it connects.

**Always use this script to start/stop things.** Starting the backend or
frontend by hand in another terminal is how duplicate/orphaned processes
creep in (this took the app down once already — see git history on
obrenna.ps1 for the fix).

Open the app at http://localhost:5173.
