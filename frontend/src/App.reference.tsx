// This file is the original mock provided by the user. Do not edit.
// It is kept verbatim as the pixel reference for component decomposition.
// See src/App.tsx and src/components/ for the decomposed implementation.

import React, {
  useEffect, useMemo, useRef, useState, useCallback, createContext, useContext,
} from "react";
import {
  Plus, Search, Settings as SettingsIcon, FolderPlus, Folder, MessageSquare,
  Send, Paperclip, Globe, X, ChevronDown, ChevronRight, MoreHorizontal,
  ArrowRight, Cpu, HardDrive, Download, Check, AlertTriangle, Ban,
  FileText, BarChart3, Table, LayoutDashboard, Download as DownloadIcon,
  Copy, PanelRight, Minimize2, Maximize2, FolderOpen, Move, Trash2,
  ShieldCheck, Wifi, WifiOff, Sun, Moon, Sparkles, FileCheck,
  ArrowLeft, RefreshCw, Link2, Server,
} from "lucide-react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, AreaChart, Area,
} from "recharts";

/* ------------------------------------------------------------------ */
/*  Theme context                                                      */
/* ------------------------------------------------------------------ */

const ThemeCtx = createContext();
const useTheme = () => useContext(ThemeCtx);

function ThemeProvider({ children }) {
  const [mode, setMode] = useState("light");
  useEffect(() => {
    document.documentElement.classList.toggle("dark", mode === "dark");
  }, [mode]);
  const toggle = () => setMode(m => (m === "light" ? "dark" : "light"));
  return (
    <ThemeCtx.Provider value={{ mode, toggle, setMode }}>
      {children}
    </ThemeCtx.Provider>
  );
}

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const HARDWARE = {
  cpu: "Apple M2 Pro â€” 12-core",
  ram: "32 GB unified memory",
  gpu: "Integrated 19-core GPU",
  vram: "24 GB shared",
};

const MODELS = [
  { id: "reasoner", name: "Qwen 2.5 14B", role: "Main reasoner", size: "9.2 GB", fit: "ok", note: "Runs well on your machine" },
  { id: "summarizer", name: "Phi-3.5 Mini", role: "Summarizer", size: "2.3 GB", fit: "ok", note: "Runs well on your machine" },
  { id: "utility", name: "Llama 3.2 3B", role: "Utility", size: "2.0 GB", fit: "ok", note: "Runs well on your machine" },
  { id: "big", name: "Llama 3.1 70B", role: "Not selected", size: "39 GB", fit: "bad", note: "Too large for this machine" },
  { id: "med", name: "Mistral 7B", role: "Not selected", size: "4.4 GB", fit: "warn", note: "Will run slowly under load" },
];

const PROVIDERS = ["Ollama", "LM Studio", "llama.cpp", "OpenAI-compatible"];

const FOLDERS = [
  { id: "f1", name: "Client work" },
  { id: "f2", name: "Internal" },
];

const initialChats = [
  {
    id: "c1", title: "Q2 revenue analysis", folder: null, group: "today",
    messages: [
      {
        id: "m1", role: "user",
        text: "Summarize Q2 revenue from the attached CSV and show me a dashboard with monthly totals and the top five customers.",
        files: [{ name: "q2_revenue.csv", size: "142 KB" }],
      },
      {
        id: "m2", role: "assistant",
        text: "Q2 closed at $1.28M in recognized revenue, up 11% from Q1. The strongest month was May, driven by three renewals in the mid-market segment. Your top customer by revenue this quarter was Halberd & Sons at $184K, followed by Northline, Greenleaf, Marlowe, and Finch. I put together a dashboard so you can scan the shape of the quarter at a glance and drill into the customer table when you need it.",
        artifacts: ["a-dashboard"],
      },
    ],
  },
  {
    id: "c2", title: "Draft client proposal for Greenleaf", folder: "f1", group: "today",
    messages: [
      { id: "m3", role: "user", text: "Draft a proposal for Greenleaf Landscaping to renew their service contract, with pricing options for 12 and 24 months." },
      {
        id: "m4", role: "assistant",
        text: "I drafted a proposal you can send as a PDF. It leads with the outcomes Greenleaf saw on the current contract, lays out two pricing options side by side, and ends with a simple next-step. Open it on the right to review â€” every section is editable before you export.",
        artifacts: ["a-pdf"],
      },
    ],
  },
  {
    id: "c3", title: "Sales team meeting notes", folder: "f2", group: "yesterday",
    messages: [
      { id: "m5", role: "user", text: "Here's the transcript from this morning's sales standup. Turn it into clean notes with owners and dates." },
      {
        id: "m6", role: "assistant",
        text: "Done. I captured the three blockers the team flagged, the owners for each action item, and the dates they committed to. The full note is on the right â€” I kept the discussion about the Marlowe renewal intact since it's sensitive.",
        artifacts: ["a-markdown"],
      },
    ],
  },
  {
    id: "c4", title: "Inventory forecast by SKU", folder: "f1", group: "week",
    messages: [
      { id: "m7", role: "user", text: "Forecast the next 30 days of inventory for our top 20 SKUs." },
      {
        id: "m8", role: "assistant",
        text: "I ran a 30-day forecast across the top 20 SKUs. Six of them are trending toward a stockout before the end of the month if the current sales pace holds â€” I called them out in the chart and the table so you can decide which to reorder first.",
        artifacts: ["a-chart", "a-table"],
      },
    ],
  },
  {
    id: "c5", title: "Rewrite homepage hero", folder: null, group: "older",
    messages: [
      { id: "m9", role: "user", text: "Give me three tighter versions of the homepage hero, same meaning, fewer words." },
      { id: "m10", role: "assistant", text: "Here are three rewrites. Option A keeps the original structure and just tightens the language. Option B leads with the outcome instead of the feature. Option C is the shortest â€” it trusts the reader to click through for detail.\
\
A. Run AI on your own machine. Turn files into reports, dashboards, and documents â€” no cloud, no configuration.\
\
B. Your files, answered. Ask questions across your documents and get finished artifacts back, all on your own hardware.\
\
C. Private AI that just runs. Drop a file, ask a question, get a report." },
    ],
  },
  {
    id: "c6", title: "Onboarding email sequence", folder: "f1", group: "older",
    messages: [
      { id: "m11", role: "user", text: "Sketch a 4-email onboarding sequence for new trial users." },
      { id: "m12", role: "assistant", text: "Four emails over ten days, each with one job:\
\
Day 0 â€” Welcome. One thing to do in the next five minutes.\
Day 2 â€” First win. A concrete example of a report they can produce today.\
Day 5 â€” Depth. A feature they haven't seen yet, shown through a real use case.\
Day 10 â€” Decision. A plain ask about what would make them stay." },
    ],
  },
];

/* ---- Artifact content -------------------------------------------- */

const ARTIFACTS = {
  "a-pdf": {
    id: "a-pdf",
    type: "pdf",
    title: "Greenleaf Landscaping â€” Q2 2026 Service Renewal Proposal",
    summary: "12- and 24-month pricing options with projected outcomes.",
    body: {
      prepared: "June 29, 2026",
      for: "Greenleaf Landscaping â€” Attn: Priya Anand, Operations",
      from: "Halcyon Grounds Co.",
      sections: [
        {
          heading: "What you've gotten on the current contract",
          paragraphs: [
            "Over the past twelve months Greenleaf moved from a reactive maintenance schedule to a routed, zone-based plan. Site visits dropped 18% while the number of documented issues resolved per visit rose 31%. The two properties that had the most callbacks in 2025 â€” the Elm Street depot and the Riverside campus â€” are now the two quietest sites in the book.",
            "Invoicing moved from per-visit to a fixed monthly rate in February. Cash flow on the account has been predictable every month since, and Greenleaf's accounts payable team has not flagged a single dispute.",
          ],
        },
        {
          heading: "What we're proposing for the next contract",
          paragraphs: [
            "Two options, same scope, same crew, same response times. The difference is commitment length and the rate.",
          ],
          table: {
            headers: ["Option", "Term", "Monthly rate", "Annual total", "Includes"],
            rows: [
              ["A", "12 months", "$8,400", "$100,800", "Weekly routing, 4h emergency response, quarterly site reports"],
              ["B", "24 months", "$7,650", "$91,800", "Weekly routing, 4h emergency response, quarterly site reports, two seasonal redesigns per year"],
            ],
          },
        },
        {
          heading: "What happens next",
          paragraphs: [
            "Reply with the option letter and a start date. We'll send a countersigned agreement within two business days and schedule the first quarterly review before the first invoice.",
          ],
        },
      ],
    },
  },

  "a-dashboard": {
    id: "a-dashboard",
    type: "dashboard",
    title: "Q2 2026 Revenue Dashboard",
    summary: "Quarterly totals, monthly trend, and top customers.",
    body: {
      kpis: [
        { label: "Recognized revenue", value: "$1.28M", delta: "+11% vs Q1", positive: true },
        { label: "Closed deals", value: "38", delta: "+4 vs Q1", positive: true },
        { label: "Average deal size", value: "$33.7K", delta: "+2.1%", positive: true },
        { label: "Days to close", value: "27", delta: "-3 days", positive: true },
      ],
      monthly: [
        { month: "Apr", revenue: 348 },
        { month: "May", revenue: 512 },
        { month: "Jun", revenue: 421 },
      ],
      pipeline: [
        { month: "Apr", new: 210, renewed: 138 },
        { month: "May", new: 280, renewed: 232 },
        { month: "Jun", new: 198, renewed: 223 },
      ],
      topCustomers: [
        { customer: "Halberd & Sons", revenue: 184200, deals: 2, segment: "Mid-market" },
        { customer: "Northline Fabricators", revenue: 156800, deals: 3, segment: "SMB" },
        { customer: "Greenleaf Landscaping", revenue: 121400, deals: 1, segment: "SMB" },
        { customer: "Marlowe & Co.", revenue: 108900, deals: 2, segment: "Mid-market" },
        { customer: "Finch Trading", revenue: 97300, deals: 1, segment: "SMB" },
      ],
    },
  },

  "a-chart": {
    id: "a-chart",
    type: "chart",
    title: "30-day inventory forecast â€” top 20 SKUs",
    summary: "Units on hand vs projected demand, with stockout risk flagged.",
    body: {
      series: [
        { sku: "SKU-1041", onHand: 840, projected: 410, flag: false },
        { sku: "SKU-1188", onHand: 312, projected: 485, flag: true },
        { sku: "SKU-1202", onHand: 605, projected: 540, flag: false },
        { sku: "SKU-1277", onHand: 240, projected: 380, flag: true },
        { sku: "SKU-1319", onHand: 900, projected: 612, flag: false },
        { sku: "SKU-1405", onHand: 188, projected: 260, flag: true },
        { sku: "SKU-1488", onHand: 720, projected: 505, flag: false },
        { sku: "SKU-1512", onHand: 290, projected: 440, flag: true },
      ],
    },
  },

  "a-table": {
    id: "a-table",
    type: "table",
    title: "Inventory forecast â€” detail",
    summary: "Projected end-of-month units and reorder flag for the top 20 SKUs.",
    body: {
      headers: ["SKU", "On hand", "30-day demand", "Projected end", "Reorder"],
      rows: [
        ["SKU-1041", "840", "430", "410", "No"],
        ["SKU-1188", "312", "490", "âˆ’178", "Yes â€” urgent"],
        ["SKU-1202", "605", "580", "25", "Watch"],
        ["SKU-1277", "240", "395", "âˆ’155", "Yes â€” urgent"],
        ["SKU-1319", "900", "420", "480", "No"],
        ["SKU-1405", "188", "270", "âˆ’82", "Yes"],
        ["SKU-1488", "720", "380", "340", "No"],
        ["SKU-1512", "290", "460", "âˆ’170", "Yes â€” urgent"],
        ["SKU-1601", "512", "300", "212", "No"],
        ["SKU-1655", "388", "410", "âˆ’22", "Watch"],
      ],
    },
  },

  "a-markdown": {
    id: "a-markdown",
    type: "markdown",
    title: "Sales standup â€” June 28, 2026",
    summary: "Attendees, decisions, owners, and dates.",
    body: `## Attendees\
Maya (lead), Daniel, Noor, Sam, Priya\
\
## Decisions made\
- The Marlowe renewal stays with Maya. No handoff this quarter.\
- New-demo decks move to the shorter 8-slide format starting next week.\
- Weekly pipeline review moves from Tuesday to Thursday.\
\
## Action items\
- **Daniel** â€” send the revised Marlowe pricing to Maya by **July 1**.\
- **Noor** â€” ship the 8-slide demo template to the team by **July 3**.\
- **Sam** â€” close the three stalled Halberd opportunities or write them off by **July 5**.\
- **Priya** â€” schedule pipeline reviews with each rep for the week of **July 7**.\
\
## Open questions\
- Do we extend the mid-market discount to Finch, or hold list price?\
- Should Q3 kickoff be in-person or remote? Maya will decide by July 2.\
\
## Notes\
The Marlowe conversation is sensitive. Please keep discussion inside this thread until the renewal is signed.`,
  },
};

/* ------------------------------------------------------------------ */
/*  Utilities                                                          */
/* ------------------------------------------------------------------ */

const cn = (...xs) => xs.filter(Boolean).join(" ");

const useReducedMotion = () => {
  const [rm, setRm] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setRm(mq.matches);
    const h = e => setRm(e.matches);
    mq.addEventListener("change", h);
    return () => mq.removeEventListener("change", h);
  }, []);
  return rm;
};

/* ------------------------------------------------------------------ */
/*  Tiny UI primitives                                                 */
/* ------------------------------------------------------------------ */

function FitBadge({ fit, note }) {
  if (fit === "ok")
    return (
      <span className="inline-flex items-center gap-1 text-[12px] text-(--ok)" title={note}>
        <Check className="w-3.5 h-3.5" strokeWidth={2.5} /> <span className="text-(--ink-muted)">Runs well</span>
      </span>
    );
  if (fit === "warn")
    return (
      <span className="inline-flex items-center gap-1 text-[12px] text-(--warn)" title={note}>
        <AlertTriangle className="w-3.5 h-3.5" strokeWidth={2.5} /> <span className="text-(--ink-muted)">Runs slowly</span>
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 text-[12px] text-(--err)" title={note}>
      <Ban className="w-3.5 h-3.5" strokeWidth={2.5} /> <span className="text-(--ink-muted)">Too large</span>
    </span>
  );
}

function IconButton({ className, ...p }) {
  return (
    <button
      {...p}
      className={cn(
        "inline-flex items-center justify-center w-8 h-8 rounded-md",
        "text-(--ink-muted) hover:text-(--ink) hover:bg-(--surface-2)",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--bg)",
        "transition-colors",
        className
      )}
    />
  );
}

function Button({ variant = "primary", className, children, ...p }) {
  const base = "inline-flex items-center justify-center gap-2 h-9 px-3.5 rounded-md text-[13px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--bg) disabled:opacity-50 disabled:pointer-events-none";
  const variants = {
    primary: "bg-(--accent) text-(--accent-ink) hover:brightness-110",
    secondary: "bg-(--surface-2) text-(--ink) border border-(--border) hover:bg-(--border)",
    ghost: "text-(--ink) hover:bg-(--surface-2)",
    danger: "text-(--err) hover:bg-(--surface-2)",
  };
  return <button className={cn(base, variants[variant], className)} {...p}>{children}</button>;
}

/* ------------------------------------------------------------------ */
/*  Setup flow                                                         */
/* ------------------------------------------------------------------ */

function SetupFlow({ onFinish }) {
  const [step, setStep] = useState(0); // 0 welcome, 1.. managed/byo
  const [path, setPath] = useState(null); // "managed" | "byo"
  const [scanDone, setScanDone] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState({});
  const [downloadDone, setDownloadDone] = useState(false);
  const rm = useReducedMotion();

  // BYO form
  const [provider, setProvider] = useState("Ollama");
  const [baseUrl, setBaseUrl] = useState("http://localhost:11434/v1");
  const [apiKey, setApiKey] = useState("");
  const [roles, setRoles] = useState({
    reasoner: "llama3.1:8b",
    summarizer: "phi3.5",
    utility: "llama3.2:3b",
  });
  const [testState, setTestState] = useState("idle"); // idle | testing | success | failure

  // Hardware scan animation
  useEffect(() => {
    if (step !== 1 || path !== "managed" || scanDone) return;
    const t = setTimeout(() => setScanDone(true), rm ? 100 : 1400);
    return () => clearTimeout(t);
  }, [step, path, scanDone, rm]);

  // Download simulation
  useEffect(() => {
    if (step !== 3 || path !== "managed") return;
    if (downloadDone) return;
    const models = ["reasoner", "summarizer", "utility"];
    const id = setInterval(() => {
      setDownloadProgress(prev => {
        const next = { ...prev };
        let allDone = true;
        for (const m of models) {
          const cur = prev[m] ?? 0;
          if (cur < 100) {
            next[m] = Math.min(100, cur + (rm ? 100 : Math.random() * 9 + 3));
            allDone = false;
          }
        }
        return next;
      });
    }, rm ? 20 : 350);
    return () => clearInterval(id);
  }, [step, path, downloadDone, rm]);

  useEffect(() => {
    const models = ["reasoner", "summarizer", "utility"];
    if (models.every(m => (downloadProgress[m] ?? 0) >= 100)) {
      setDownloadDone(true);
    }
  }, [downloadProgress]);

  const runTest = () => {
    setTestState("testing");
    setTimeout(() => {
      // deterministic mock: succeed unless url is empty
      setTestState(baseUrl.trim().length > 5 ? "success" : "failure");
    }, rm ? 50 : 900);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-(--bg) px-6 py-12">
      <div className="w-full max-w-[640px]">
        <div className="mb-8 flex items-center gap-2 text-[12px] text-(--ink-faint) tracking-wide uppercase">
          <ShieldCheck className="w-3.5 h-3.5" /> Local-first workspace
        </div>

        {step === 0 && <WelcomeStep onChoose={p => { setPath(p); setStep(1); }} />}
        {step === 1 && path === "managed" && (
          <HardwareStep done={scanDone} onNext={() => setStep(2)} onBack={() => setStep(0)} />
        )}
        {step === 2 && path === "managed" && (
          <RecommendStep onNext={() => setStep(3)} onBack={() => setStep(1)} />
        )}
        {step === 3 && path === "managed" && (
          <DownloadStep
            progress={downloadProgress}
            done={downloadDone}
            onFinish={onFinish}
            onBack={() => setStep(2)}
          />
        )}
        {step === 1 && path === "byo" && (
          <ByoStep
            provider={provider} setProvider={setProvider}
            baseUrl={baseUrl} setBaseUrl={setBaseUrl}
            apiKey={apiKey} setApiKey={setApiKey}
            roles={roles} setRoles={setRoles}
            testState={testState} runTest={runTest}
            onFinish={onFinish}
            onBack={() => setStep(0)}
          />
        )}
      </div>
    </div>
  );
}

function WelcomeStep({ onChoose }) {
  return (
    <div>
      <h1 className="text-[28px] font-semibold tracking-tight text-(--ink) leading-tight">
        Set up your workspace
      </h1>
      <p className="mt-3 text-[14px] text-(--ink-muted) leading-relaxed max-w-[520px]">
        Everything you do here runs on your own machine. Nothing you ask, upload, or generate leaves this computer unless you share it yourself. Pick the setup that matches how you want to work.
      </p>

      <div className="mt-8 grid gap-3">
        <button
          onClick={() => onChoose("managed")}
          className="group text-left p-5 rounded-xl border border-(--border) bg-(--surface) hover:border-(--accent) hover:bg-(--surface) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) transition-colors"
        >
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-(--surface-2) border border-(--border) flex items-center justify-center">
                <Cpu className="w-4 h-4 text-(--accent)" />
              </div>
              <div>
                <div className="text-[15px] font-medium text-(--ink)">Set it up for me</div>
                <div className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
                  We'll check what your machine can handle and install the right models automatically.
                </div>
              </div>
            </div>
            <ArrowRight className="w-4 h-4 text-(--ink-faint) group-hover:text-(--accent) transition-colors mt-1" />
          </div>
        </button>

        <button
          onClick={() => onChoose("byo")}
          className="group text-left p-5 rounded-xl border border-(--border) bg-(--surface) hover:border-(--accent) hover:bg-(--surface) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) transition-colors"
        >
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-(--surface-2) border border-(--border) flex items-center justify-center">
                <Server className="w-4 h-4 text-(--accent)" />
              </div>
              <div>
                <div className="text-[15px] font-medium text-(--ink)">Connect my own local server</div>
                <div className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
                  Point the app at an Ollama, LM Studio, llama.cpp, or any OpenAI-compatible server you already run.
                </div>
              </div>
            </div>
            <ArrowRight className="w-4 h-4 text-(--ink-faint) group-hover:text-(--accent) transition-colors mt-1" />
          </div>
        </button>
      </div>
    </div>
  );
}

function HardwareStep({ done, onNext, onBack }) {
  return (
    <div>
      <StepCounter current={1} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">Checking your machine</h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        We'll read what you've got and pick models that fit. This takes a few seconds and you only do it once.
      </p>

      <div className="mt-8 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {Object.entries(HARDWARE).map(([k, v], i) => (
          <HardwareRow key={k} label={hardwareLabel(k)} value={v} revealed={done || i < 2} index={i} />
        ))}
      </div>

      {!done && (
        <div className="mt-5 flex items-center gap-2 text-[13px] text-(--ink-muted)">
          <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Scanningâ€¦
        </div>
      )}

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={onNext} disabled={!done}>Continue</Button>
      </div>
    </div>
  );
}

function hardwareLabel(k) {
  return { cpu: "Processor", ram: "Memory", gpu: "Graphics", vram: "Graphics memory" }[k];
}

function HardwareRow({ label, value, revealed, index }) {
  return (
    <div
      className="px-4 h-12 flex items-center justify-between text-[13px] transition-opacity duration-300"
      style={{ opacity: revealed ? 1 : 0.4, transitionDelay: `${index * 120}ms` }}
    >
      <span className="text-(--ink-muted)">{label}</span>
      <span className="font-medium text-(--ink)">{revealed ? value : "Readingâ€¦"}</span>
    </div>
  );
}

function RecommendStep({ onNext, onBack }) {
  const selected = MODELS.filter(m => m.fit === "ok");
  return (
    <div>
      <StepCounter current={2} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">Recommended setup</h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        These three models fit your machine. We'll use the bigger one when reasoning matters, and the smaller ones for summaries and quick tasks.
      </p>

      <div className="mt-8 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {selected.map(m => (
          <div key={m.id} className="p-4 flex items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[14px] font-medium text-(--ink)">{m.name}</div>
              <div className="mt-0.5 text-[12px] text-(--ink-muted)">{m.role} Â· {m.size}</div>
            </div>
            <FitBadge fit={m.fit} note={m.note} />
          </div>
        ))}
      </div>

      <div className="mt-6 p-4 rounded-xl border border-(--border) bg-(--surface-2)">
        <div className="text-[13px] text-(--ink) leading-relaxed">
          Curious about the models we skipped? Two others looked at and didn't make the cut â€” one's too large for this machine, one would run slowly under load. You can change the selection any time in settings.
        </div>
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={onNext}>Download models</Button>
      </div>
    </div>
  );
}

function DownloadStep({ progress, done, onFinish, onBack }) {
  const models = MODELS.filter(m => m.fit === "ok");
  return (
    <div>
      <StepCounter current={3} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">
        {done ? "You're ready" : "Downloading models"}
      </h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        {done
          ? "All three models are on your machine. Close this window and start working â€” everything runs locally from here."
          : "This runs in the background. You can keep this window open and the downloads will finish while you work."}
      </p>

      <div className="mt-8 space-y-4">
        {models.map(m => {
          const pct = Math.round(progress[m.id] ?? 0);
          return (
            <div key={m.id}>
              <div className="flex items-center justify-between text-[13px] mb-1.5">
                <span className="font-medium text-(--ink)">{m.name}</span>
                <span className="text-(--ink-muted) tabular-nums">{pct}% Â· {m.size}</span>
              </div>
              <div className="h-1.5 rounded-full bg-(--surface-2) overflow-hidden">
                <div
                  className="h-full bg-(--accent) transition-[width] duration-200"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack} disabled={!done}>Back</Button>
        <Button onClick={onFinish} disabled={!done}>Open workspace</Button>
      </div>
    </div>
  );
}

function ByoStep({
  provider, setProvider, baseUrl, setBaseUrl, apiKey, setApiKey,
  roles, setRoles, testState, runTest, onFinish, onBack,
}) {
  const fieldCls = "w-full h-9 px-3 rounded-md bg-(--surface) border border-(--border) text-[13px] text-(--ink) placeholder:text-(--ink-faint) focus:outline-none focus:ring-2 focus:ring-(--accent) focus:border-transparent";
  const labelCls = "block text-[12px] font-medium text-(--ink-muted) mb-1.5";

  return (
    <div>
      <StepCounter current={1} total={1} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">Connect a local server</h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        Point the app at a server you already run. We'll test the connection before you start.
      </p>

      <div className="mt-8 space-y-5">
        <div>
          <label className={labelCls}>Provider</label>
          <select value={provider} onChange={e => setProvider(e.target.value)} className={fieldCls}>
            {PROVIDERS.map(p => <option key={p}>{p}</option>)}
          </select>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3">
          <div>
            <label className={labelCls}>Base URL</label>
            <input
              value={baseUrl}
              onChange={e => setBaseUrl(e.target.value)}
              placeholder="http://localhost:11434/v1"
              className={fieldCls}
            />
          </div>
          <div>
            <label className={labelCls}>API key (optional)</label>
            <input
              type="password"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder="Leave blank if not required"
              className={fieldCls}
            />
          </div>
        </div>

        <div>
          <label className={labelCls}>Map models to tasks</label>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {[
              ["reasoner", "Main reasoner"],
              ["summarizer", "Summarizer"],
              ["utility", "Utility"],
            ].map(([k, label]) => (
              <div key={k}>
                <div className="text-[11px] text-(--ink-faint) mb-1">{label}</div>
                <select
                  value={roles[k]}
                  onChange={e => setRoles({ ...roles, [k]: e.target.value })}
                  className={fieldCls}
                >
                  <option>llama3.1:8b</option>
                  <option>llama3.2:3b</option>
                  <option>phi3.5</option>
                  <option>qwen2.5:14b</option>
                  <option>mistral:7b</option>
                </select>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <Button variant="secondary" onClick={runTest} disabled={testState === "testing"}>
            {testState === "testing" ? (
              <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Testing connectionâ€¦</>
            ) : (
              <><Link2 className="w-3.5 h-3.5" /> Test connection</>
            )}
          </Button>

          {testState === "success" && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-(--ok)">
              <Check className="w-3.5 h-3.5" strokeWidth={2.5} /> Connected. Server responded in 124 ms.
            </span>
          )}
          {testState === "failure" && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-(--err)">
              <WifiOff className="w-3.5 h-3.5" /> Couldn't reach the server. Check the URL and try again.
            </span>
          )}
        </div>
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={onFinish} disabled={testState !== "success"}>Save and continue</Button>
      </div>
    </div>
  );
}

function StepCounter({ current, total }) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "h-1 rounded-full transition-all",
            i < current ? "w-6 bg-(--accent)" : "w-2 bg-(--border-strong)"
          )}
        />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sidebar                                                            */
/* ------------------------------------------------------------------ */

function Sidebar({
  chats, folders, activeChatId, onSelectChat, onNewChat, onCreateFolder,
  onMoveChat, onDeleteChat, onRenameFolder, onDeleteFolder, onOpenSettings,
}) {
  const [q, setQ] = useState("");
  const [openFolders, setOpenFolders] = useState({ f1: true, f2: true });
  const [menuFor, setMenuFor] = useState(null); // chat id
  const menuRef = useRef(null);

  useEffect(() => {
    const h = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) setMenuFor(null); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return chats;
    return chats.filter(c => c.title.toLowerCase().includes(needle));
  }, [q, chats]);

  const byGroup = (group) => filtered.filter(c => c.group === group && !c.folder);
  const byFolder = (fid) => filtered.filter(c => c.folder === fid);

  const groups = [
    { id: "today", label: "Today", items: byGroup("today") },
    { id: "yesterday", label: "Yesterday", items: byGroup("yesterday") },
    { id: "week", label: "Previous 7 days", items: byGroup("week") },
    { id: "older", label: "Older", items: byGroup("older") },
  ];

  return (
    <aside className="w-[260px] shrink-0 bg-(--bg) border-r border-(--border) flex flex-col">
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="w-full h-9 rounded-md bg-(--accent) text-(--accent-ink) text-[13px] font-medium inline-flex items-center justify-center gap-2 hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--bg) transition"
        >
          <Plus className="w-4 h-4" strokeWidth={2.2} /> New chat
        </button>
      </div>

      <div className="px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-(--ink-faint)" />
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Search chats"
            className="w-full h-8 pl-8 pr-2.5 rounded-md bg-(--surface) border border-(--border) text-[13px] text-(--ink) placeholder:text-(--ink-faint) focus:outline-none focus:ring-2 focus:ring-(--accent) focus:border-transparent"
          />
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {folders.map(f => (
          <FolderRow
            key={f.id}
            folder={f}
            items={byFolder(f.id)}
            open={openFolders[f.id]}
            onToggle={() => setOpenFolders(o => ({ ...o, [f.id]: !o[f.id] }))}
            activeChatId={activeChatId}
            onSelectChat={onSelectChat}
            menuFor={menuFor}
            setMenuFor={setMenuFor}
            onMoveChat={onMoveChat}
            onDeleteChat={onDeleteChat}
            folders={folders}
            onRenameFolder={onRenameFolder}
            onDeleteFolder={onDeleteFolder}
          />
        ))}

        <button
          onClick={onCreateFolder}
          className="w-full h-8 mt-1 px-2 rounded-md text-left text-[12px] text-(--ink-muted) hover:bg-(--surface-2) hover:text-(--ink) inline-flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)"
        >
          <FolderPlus className="w-3.5 h-3.5" /> New folder
        </button>

        <div className="mt-3 space-y-3">
          {groups.map(g => g.items.length > 0 && (
            <div key={g.id}>
              <div className="px-2 h-6 flex items-center text-[11px] font-medium uppercase tracking-wide text-(--ink-faint)">
                {g.label}
              </div>
              <div className="space-y-0.5">
                {g.items.map(c => (
                  <ChatRow
                    key={c.id}
                    chat={c}
                    active={c.id === activeChatId}
                    onClick={() => onSelectChat(c.id)}
                    menuFor={menuFor}
                    setMenuFor={setMenuFor}
                    onMoveChat={onMoveChat}
                    onDeleteChat={onDeleteChat}
                    folders={folders}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </nav>

      <div className="p-3 border-t border-(--border) flex items-center justify-between">
        <button
          onClick={onOpenSettings}
          className="h-8 px-2 rounded-md text-[13px] text-(--ink-muted) hover:bg-(--surface-2) hover:text-(--ink) inline-flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)"
        >
          <SettingsIcon className="w-3.5 h-3.5" /> Settings
        </button>
        <LocalPill />
      </div>
    </aside>
  );
}

function FolderRow({
  folder, items, open, onToggle, activeChatId, onSelectChat,
  menuFor, setMenuFor, onMoveChat, onDeleteChat, folders, onRenameFolder, onDeleteFolder,
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(folder.name);
  const [folderMenu, setFolderMenu] = useState(false);

  return (
    <div>
      <div className="group flex items-center h-8 px-2 rounded-md hover:bg-(--surface-2)">
        <button onClick={onToggle} className="flex items-center gap-1.5 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) rounded">
          {open ? <ChevronDown className="w-3.5 h-3.5 text-(--ink-faint)" /> : <ChevronRight className="w-3.5 h-3.5 text-(--ink-faint)" />}
          {open ? <FolderOpen className="w-3.5 h-3.5 text-(--ink-muted)" /> : <Folder className="w-3.5 h-3.5 text-(--ink-muted)" />}
          {editing ? (
            <input
              autoFocus
              value={name}
              onChange={e => setName(e.target.value)}
              onBlur={() => { onRenameFolder(folder.id, name.trim() || folder.name); setEditing(false); }}
              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
              className="flex-1 min-w-0 bg-transparent text-[13px] text-(--ink) focus:outline-none"
              onClick={e => e.stopPropagation()}
            />
          ) : (
            <span className="text-[13px] text-(--ink) truncate">{folder.name}</span>
          )}
        </button>
        <div className="relative">
          <IconButton className="w-6 h-6 opacity-0 group-hover:opacity-100" onClick={(e) => { e.stopPropagation(); setFolderMenu(v => !v); }}>
            <MoreHorizontal className="w-3.5 h-3.5" />
          </IconButton>
          {folderMenu && (
            <Menu
              onClose={() => setFolderMenu(false)}
              items={[
                { label: "Rename", onClick: () => { setEditing(true); setFolderMenu(false); } },
                { label: "Delete folder", danger: true, onClick: () => { onDeleteFolder(folder.id); setFolderMenu(false); } },
              ]}
            />
          )}
        </div>
      </div>
      {open && (
        <div className="mt-0.5 space-y-0.5 pl-2">
          {items.length === 0 && (
            <div className="px-2 py-1 text-[12px] text-(--ink-faint)">Empty</div>
          )}
          {items.map(c => (
            <ChatRow
              key={c.id} chat={c} active={c.id === activeChatId}
              onClick={() => onSelectChat(c.id)}
              menuFor={menuFor} setMenuFor={setMenuFor}
              onMoveChat={onMoveChat} onDeleteChat={onDeleteChat} folders={folders}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ChatRow({ chat, active, onClick, menuFor, setMenuFor, onMoveChat, onDeleteChat, folders }) {
  return (
    <div className="group relative">
      <button
        onClick={onClick}
        className={cn(
          "w-full h-8 px-2 rounded-md text-left text-[13px] truncate flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)",
          active ? "bg-(--surface-2) text-(--ink)" : "text-(--ink) hover:bg-(--surface-2)"
        )}
      >
        <MessageSquare className="w-3.5 h-3.5 text-(--ink-faint) shrink-0" />
        <span className="truncate flex-1">{chat.title}</span>
      </button>
      <div className="absolute right-0 top-0 h-8 flex items-center">
        <IconButton
          className={cn("w-6 h-6", menuFor === chat.id ? "opacity-100" : "opacity-0 group-hover:opacity-100")}
          onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === chat.id ? null : chat.id); }}
        >
          <MoreHorizontal className="w-3.5 h-3.5" />
        </IconButton>
        {menuFor === chat.id && (
          <Menu
            onClose={() => setMenuFor(null)}
            items={[
              ...folders.map(f => ({
                label: f.name,
                icon: <Folder className="w-3.5 h-3.5" />,
                onClick: () => { onMoveChat(chat.id, chat.folder === f.id ? null : f.id); setMenuFor(null); },
              })),
              ...(folders.length > 0 ? [{ label: "Unfile", icon: <Move className="w-3.5 h-3.5" />, onClick: () => { onMoveChat(chat.id, null); setMenuFor(null); } }] : []),
              { label: "Delete", danger: true, icon: <Trash2 className="w-3.5 h-3.5" />, onClick: () => { onDeleteChat(chat.id); setMenuFor(null); } },
            ]}
          />
        )}
      </div>
    </div>
  );
}

function Menu({ items, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [onClose]);
  return (
    <div
      ref={ref}
      className="absolute right-0 top-8 z-40 min-w-[180px] rounded-lg border border-(--border) bg-(--surface) py-1 shadow-[0_1px_2px_rgba(28,25,22,.04),0_8px_24px_-8px_rgba(28,25,22,.10)]"
    >
      {items.map((it, i) => (
        <button
          key={i}
          onClick={it.onClick}
          className={cn(
            "w-full h-8 px-2.5 text-left text-[13px] inline-flex items-center gap-2 focus:outline-none focus-visible:bg-(--surface-2)",
            it.danger ? "text-(--err) hover:bg-(--surface-2)" : "text-(--ink) hover:bg-(--surface-2)"
          )}
        >
          {it.icon}
          <span>{it.label}</span>
        </button>
      ))}
    </div>
  );
}

function LocalPill() {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="h-7 px-2 rounded-full border border-(--border) bg-(--surface) inline-flex items-center gap-1.5 text-[11px] text-(--ink-muted) hover:bg-(--surface-2) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)"
        aria-label="Local status"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-(--ok)" />
        Local
      </button>
      {open && (
        <div className="absolute bottom-9 right-0 z-40 w-[240px] rounded-lg border border-(--border) bg-(--surface) p-3 text-[12px] shadow-[0_1px_2px_rgba(28,25,22,.04),0_8px_24px_-8px_rgba(28,25,22,.10)]">
          <div className="flex items-center gap-1.5 text-(--ink) font-medium">
            <ShieldCheck className="w-3.5 h-3.5 text-(--ok)" /> Running locally
          </div>
          <div className="mt-2 text-(--ink-muted) leading-relaxed">
            Active model: <span className="text-(--ink)">Qwen 2.5 14B</span><br/>
            Files, prompts, and outputs stay on this machine. Nothing is sent to a cloud service.
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Streaming text                                                     */
/* ------------------------------------------------------------------ */

function useStreamedText(text, active = true) {
  const rm = useReducedMotion();
  const [shown, setShown] = useState(active ? 0 : text.length);
  const lastText = useRef(text);

  useEffect(() => {
    if (text !== lastText.current) {
      lastText.current = text;
      setShown(active ? 0 : text.length);
    }
  }, [text, active]);

  useEffect(() => {
    if (rm || !active) { setShown(text.length); return; }
    if (shown >= text.length) return;
    const id = setTimeout(() => {
      setShown(n => Math.min(text.length, n + Math.max(1, Math.floor(text.length / 160))));
    }, 12);
    return () => clearTimeout(id);
  }, [shown, text, active, rm]);

  return { shown, done: shown >= text.length, slice: text.slice(0, shown) };
}

function StreamedText({ text, active = true }) {
  const { slice, done } = useStreamedText(text, active);
  return (
    <span>
      {slice}
      {!done && <span className="inline-block w-[2px] h-[1em] align-[-2px] ml-[1px] bg-(--accent) animate-pulse" />}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Chat                                                               */
/* ------------------------------------------------------------------ */

function MessageBubble({ msg, onOpenArtifact, active }) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[640px]">
          <div className="text-[14px] text-(--ink) leading-relaxed whitespace-pre-wrap">{msg.text}</div>
          {msg.files?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {msg.files.map((f, i) => (
                <span key={i} className="inline-flex items-center gap-1.5 h-7 px-2 rounded-md bg-(--surface-2) border border-(--border) text-[12px] text-(--ink-muted)">
                  <FileText className="w-3 h-3" /> {f.name} <span className="text-(--ink-faint)">Â· {f.size}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="w-6 h-6 rounded-md bg-(--surface-2) border border-(--border) flex items-center justify-center shrink-0 mt-0.5">
        <Sparkles className="w-3 h-3 text-(--accent)" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[14px] text-(--ink) leading-relaxed whitespace-pre-wrap">
          <StreamedText text={msg.text} active={active} />
        </div>
        {msg.artifacts?.length > 0 && (
          <div className="mt-4 space-y-2.5">
            {msg.artifacts.map(id => {
              const a = ARTIFACTS[id];
              if (!a) return null;
              return <ArtifactCard key={id} artifact={a} onOpen={() => onOpenArtifact(id)} />;
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState({ onChip, composer }) {
  const chips = [
    { label: "Summarize these files", prompt: "Summarize these files" },
    { label: "Turn a CSV into a dashboard", prompt: "Turn a CSV into a dashboard" },
    { label: "Draft a report", prompt: "Draft a report" },
  ];
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-[640px]">
        <h1 className="text-[22px] font-semibold tracking-tight text-(--ink)">What are we working on?</h1>
        <p className="mt-1.5 text-[14px] text-(--ink-muted) leading-relaxed">
          Drop a file or describe the task. Everything runs on your machine.
        </p>
        <div className="mt-6">{composer}</div>
        <div className="mt-4 flex flex-wrap gap-2">
          {chips.map(c => (
            <button
              key={c.label}
              onClick={() => onChip(c.prompt)}
              className="h-8 px-3 rounded-full border border-(--border) bg-(--surface) text-[12px] text-(--ink) hover:border-(--accent) hover:text-(--accent) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) transition-colors"
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function Composer({ onSend, disabled }) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState([]);
  const [web, setWeb] = useState(false);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef(null);

  const send = () => {
    const t = text.trim();
    if (!t && files.length === 0) return;
    onSend({ text: t, files: files.slice() });
    setText("");
    setFiles([]);
  };

  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const addFiles = (list) => {
    const arr = Array.from(list).map(f => ({ name: f.name, size: formatBytes(f.size) }));
    setFiles(prev => [...prev, ...arr]);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
      className={cn(
        "relative rounded-xl border bg-(--surface) transition-colors",
        drag ? "border-(--accent) bg-(--surface-2)" : "border-(--border)"
      )}
    >
      {drag && (
        <div className="absolute inset-0 rounded-xl pointer-events-none flex items-center justify-center">
          <div className="text-[13px] text-(--accent) font-medium">Drop files to attach</div>
        </div>
      )}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5 p-3 pb-0">
          {files.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 h-7 pl-2 pr-1 rounded-md bg-(--surface-2) border border-(--border) text-[12px] text-(--ink)">
              <FileText className="w-3 h-3 text-(--ink-muted)" />
              <span className="truncate max-w-[160px]">{f.name}</span>
              <span className="text-(--ink-faint)">Â· {f.size}</span>
              <button
                onClick={() => setFiles(fs => fs.filter((_, j) => j !== i))}
                className="w-5 h-5 rounded hover:bg-(--border) inline-flex items-center justify-center"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={onKey}
        rows={1}
        placeholder="Ask anything, or drop a file"
        className="w-full resize-none bg-transparent p-3 pb-1 text-[14px] text-(--ink) placeholder:text-(--ink-faint) focus:outline-none max-h-[240px]"
        style={{ minHeight: 44 }}
      />
      <div className="flex items-center justify-between px-2 pb-2">
        <div className="flex items-center gap-0.5">
          <IconButton onClick={() => fileRef.current?.click()} title="Attach files">
            <Paperclip className="w-4 h-4" />
          </IconButton>
          <input ref={fileRef} type="file" multiple className="hidden" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
          <button
            onClick={() => setWeb(v => !v)}
            className={cn(
              "h-8 px-2.5 rounded-md text-[12px] inline-flex items-center gap-1.5 border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)",
              web
                ? "bg-(--accent) text-(--accent-ink) border-(--accent)"
                : "bg-(--surface) text-(--ink-muted) border-(--border) hover:bg-(--surface-2)"
            )}
          >
            <Globe className="w-3.5 h-3.5" /> Web search
          </button>
        </div>
        <Button onClick={send} disabled={disabled || (!text.trim() && files.length === 0)}>
          <Send className="w-3.5 h-3.5" /> Send
        </Button>
      </div>
    </div>
  );
}

function formatBytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return Math.round(n / 1024) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

function ChatThread({ chat, onSend, onOpenArtifact }) {
  const scrollRef = useRef(null);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight }); }, [chat?.messages.length]);

  if (!chat) {
    return (
      <main className="flex-1 flex flex-col min-w-0">
        <EmptyState
          onChip={(p) => onSend({ text: p, files: [] })}
          composer={<Composer onSend={onSend} />}
        />
      </main>
    );
  }

  return (
    <main className="flex-1 flex flex-col min-w-0">
      <header className="h-12 border-b border-(--border) px-6 flex items-center justify-between">
        <div className="min-w-0">
          <div className="text-[14px] font-medium text-(--ink) truncate">{chat.title}</div>
          <div className="text-[11px] text-(--ink-faint)">
            {chat.folder ? FOLDERS.find(f => f.id === chat.folder)?.name ?? "" : "Unfiled"}
          </div>
        </div>
      </header>
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-[760px] mx-auto space-y-8">
          {chat.messages.map((m, i) => (
            <MessageBubble
              key={m.id}
              msg={m}
              onOpenArtifact={onOpenArtifact}
              active={i === chat.messages.length - 1 && m.role === "assistant"}
            />
          ))}
        </div>
      </div>
      <div className="border-t border-(--border) px-6 py-4">
        <div className="max-w-[760px] mx-auto">
          <Composer onSend={onSend} />
        </div>
      </div>
    </main>
  );
}

/* ------------------------------------------------------------------ */
/*  Artifacts                                                          */
/* ------------------------------------------------------------------ */

function ArtifactIcon({ type, className }) {
  const map = {
    pdf: FileCheck,
    dashboard: LayoutDashboard,
    chart: BarChart3,
    table: Table,
    markdown: FileText,
  };
  const I = map[type] || FileText;
  return <I className={className} />;
}

function ArtifactCard({ artifact, onOpen }) {
  const [expanded, setExpanded] = useState(true);
  const a = artifact;
  return (
    <div className="rounded-xl border border-(--border) bg-(--surface) overflow-hidden">
      <div className="h-11 px-3 flex items-center justify-between gap-2 border-b border-(--border)">
        <button
          onClick={() => setExpanded(v => !v)}
          className="flex items-center gap-2 min-w-0 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) rounded"
        >
          {expanded ? <ChevronDown className="w-3.5 h-3.5 text-(--ink-faint) shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-(--ink-faint) shrink-0" />}
          <ArtifactIcon type={a.type} className="w-3.5 h-3.5 text-(--accent) shrink-0" />
          <span className="text-[13px] font-medium text-(--ink) truncate">{a.title}</span>
          <span className="text-[11px] uppercase tracking-wide text-(--ink-faint)">{a.type}</span>
        </button>
        <IconButton onClick={onOpen} title="Open in side panel">
          <PanelRight className="w-4 h-4" />
        </IconButton>
      </div>
      {expanded && (
        <div className="p-3">
          <ArtifactPreview artifact={a} />
        </div>
      )}
    </div>
  );
}

function ArtifactPreview({ artifact }) {
  const a = artifact;
  if (a.type === "pdf") {
    return (
      <div className="aspect-[4/3] max-h-[220px] rounded-md bg-(--surface-2) border border-(--border) p-4 flex flex-col">
        <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">Proposal</div>
        <div className="mt-1 text-[13px] font-medium text-(--ink) leading-snug">{a.title}</div>
        <div className="mt-3 space-y-1.5">
          {[0, 1, 2, 3, 4].map(i => (
            <div key={i} className="h-1.5 rounded-full bg-(--border-strong)" style={{ width: `${88 - i * 10}%` }} />
          ))}
        </div>
        <div className="mt-auto text-[11px] text-(--ink-faint)">Page 1 of 3</div>
      </div>
    );
  }
  if (a.type === "dashboard") {
    return (
      <div className="grid grid-cols-4 gap-2">
        {a.body.kpis.map(k => (
          <div key={k.label} className="rounded-md bg-(--surface-2) border border-(--border) p-2.5">
            <div className="text-[10px] text-(--ink-faint) uppercase tracking-wide">{k.label}</div>
            <div className="mt-1 text-[15px] font-semibold text-(--ink) tabular-nums">{k.value}</div>
            <div className={cn("text-[10px] mt-0.5", k.positive ? "text-(--ok)" : "text-(--err)")}>{k.delta}</div>
          </div>
        ))}
      </div>
    );
  }
  if (a.type === "chart") {
    return (
      <div className="h-[160px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={a.body.series}>
            <XAxis dataKey="sku" tick={{ fontSize: 10, fill: "currentColor" }} stroke="var(--border)" />
            <YAxis tick={{ fontSize: 10, fill: "currentColor" }} stroke="var(--border)" />
            <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12, borderRadius: 8 }} />
            <Bar dataKey="onHand" fill="var(--accent)" radius={[3, 3, 0, 0]} />
            <Bar dataKey="projected" fill="var(--border-strong)" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }
  if (a.type === "table") {
    return (
      <div className="max-h-[180px] overflow-auto rounded-md border border-(--border)">
        <table className="w-full text-[12px]">
          <thead className="bg-(--surface-2) text-(--ink-muted)">
            <tr>{a.body.headers.map(h => <th key={h} className="text-left font-medium px-2.5 py-1.5">{h}</th>)}</tr>
          </thead>
          <tbody className="text-(--ink)">
            {a.body.rows.slice(0, 5).map((r, i) => (
              <tr key={i} className="border-t border-(--border)">
                {r.map((c, j) => <td key={j} className="px-2.5 py-1.5 tabular-nums">{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (a.type === "markdown") {
    return (
      <div className="text-[12px] text-(--ink) leading-relaxed max-h-[180px] overflow-auto space-y-2">
        {a.body.split("\
").slice(0, 8).map((l, i) => (
          <div key={i} className={l.startsWith("##") ? "font-medium text-[13px]" : "text-(--ink-muted)"}>{l || "\u00A0"}</div>
        ))}
        <div className="text-(--ink-faint) text-[11px]">â€¦ continued in side panel</div>
      </div>
    );
  }
  return null;
}

function ArtifactPanel({ artifact, onClose, width, onResizeStart }) {
  if (!artifact) return null;
  const a = artifact;
  return (
    <>
      {/* resize handle */}
      <div
        onMouseDown={onResizeStart}
        className="absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-(--accent)/30 active:bg-(--accent)/50 z-10"
      />
      <div className="h-full flex flex-col bg-(--bg)">
        <header className="h-12 border-b border-(--border) px-4 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <ArtifactIcon type={a.type} className="w-4 h-4 text-(--accent) shrink-0" />
            <div className="min-w-0">
              <div className="text-[13px] font-medium text-(--ink) truncate">{a.title}</div>
              <div className="text-[11px] text-(--ink-faint) uppercase tracking-wide">{a.type}</div>
            </div>
          </div>
          <div className="flex items-center gap-0.5">
            <IconButton title="Copy content"><Copy className="w-4 h-4" /></IconButton>
            <IconButton title="Download"><DownloadIcon className="w-4 h-4" /></IconButton>
            <IconButton onClick={onClose} title="Close panel"><X className="w-4 h-4" /></IconButton>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          <ArtifactFull artifact={a} />
        </div>
      </div>
    </>
  );
}

function ArtifactFull({ artifact }) {
  const a = artifact;

  if (a.type === "pdf") {
    return (
      <div className="max-w-[680px] mx-auto">
        <div className="rounded-xl border border-(--border) bg-(--surface) shadow-[0_1px_2px_rgba(28,25,22,.04),0_8px_24px_-8px_rgba(28,25,22,.10)] overflow-hidden">
          <div className="p-10">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">{a.body.from}</div>
                <div className="mt-0.5 text-[12px] text-(--ink-muted)">Prepared {a.body.prepared}</div>
              </div>
              <div className="text-right">
                <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">Prepared for</div>
                <div className="mt-0.5 text-[12px] text-(--ink)">{a.body.for}</div>
              </div>
            </div>
            <h1 className="mt-10 text-[22px] font-semibold tracking-tight text-(--ink) leading-tight">{a.title}</h1>
            {a.body.sections.map((s, i) => (
              <div key={i} className="mt-8">
                <h2 className="text-[15px] font-semibold text-(--ink)">{s.heading}</h2>
                {s.paragraphs.map((p, j) => (
                  <p key={j} className="mt-2 text-[13px] text-(--ink) leading-relaxed">{p}</p>
                ))}
                {s.table && (
                  <div className="mt-4 rounded-md border border-(--border) overflow-hidden">
                    <table className="w-full text-[12px]">
                      <thead className="bg-(--surface-2) text-(--ink-muted)">
                        <tr>{s.table.headers.map(h => <th key={h} className="text-left font-medium px-3 py-2">{h}</th>)}</tr>
                      </thead>
                      <tbody className="text-(--ink)">
                        {s.table.rows.map((r, j) => (
                          <tr key={j} className="border-t border-(--border)">
                            {r.map((c, k) => <td key={k} className="px-3 py-2">{c}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (a.type === "dashboard") {
    return (
      <div className="max-w-[880px] mx-auto space-y-5">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {a.body.kpis.map(k => (
            <div key={k.label} className="rounded-xl border border-(--border) bg-(--surface) p-4">
              <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">{k.label}</div>
              <div className="mt-1.5 text-[22px] font-semibold tracking-tight text-(--ink) tabular-nums">{k.value}</div>
              <div className={cn("text-[12px] mt-0.5", k.positive ? "text-(--ok)" : "text-(--err)")}>{k.delta}</div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="rounded-xl border border-(--border) bg-(--surface) p-4">
            <div className="text-[13px] font-medium text-(--ink)">Monthly recognized revenue</div>
            <div className="text-[11px] text-(--ink-muted)">Q2 2026, thousands USD</div>
            <div className="mt-4 h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={a.body.monthly}>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
                  <YAxis tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
                  <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12, borderRadius: 8 }} />
                  <Bar dataKey="revenue" fill="var(--accent)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="rounded-xl border border-(--border) bg-(--surface) p-4">
            <div className="text-[13px] font-medium text-(--ink)">New vs renewed</div>
            <div className="text-[11px] text-(--ink-muted)">By month, thousands USD</div>
            <div className="mt-4 h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={a.body.pipeline}>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
                  <YAxis tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
                  <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12, borderRadius: 8 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Area type="monotone" dataKey="renewed" stackId="1" stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.3} />
                  <Area type="monotone" dataKey="new" stackId="1" stroke="var(--ink-muted)" fill="var(--ink-muted)" fillOpacity={0.2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-(--border) bg-(--surface) overflow-hidden">
          <div className="px-4 py-3 border-b border-(--border) flex items-center justify-between">
            <div>
              <div className="text-[13px] font-medium text-(--ink)">Top customers</div>
              <div className="text-[11px] text-(--ink-muted)">Ranked by recognized revenue, Q2 2026</div>
            </div>
          </div>
          <table className="w-full text-[13px]">
            <thead className="bg-(--surface-2) text-(--ink-muted) text-[11px] uppercase tracking-wide">
              <tr>
                <th className="text-left font-medium px-4 py-2">Customer</th>
                <th className="text-left font-medium px-4 py-2">Segment</th>
                <th className="text-right font-medium px-4 py-2">Deals</th>
                <th className="text-right font-medium px-4 py-2">Revenue</th>
              </tr>
            </thead>
            <tbody className="text-(--ink)">
              {a.body.topCustomers.map((c, i) => (
                <tr key={i} className="border-t border-(--border)">
                  <td className="px-4 py-2.5">{c.customer}</td>
                  <td className="px-4 py-2.5 text-(--ink-muted)">{c.segment}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{c.deals}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">${(c.revenue / 1000).toFixed(1)}K</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (a.type === "chart") {
    return (
      <div className="max-w-[760px] mx-auto rounded-xl border border-(--border) bg-(--surface) p-5">
        <div className="text-[15px] font-medium text-(--ink)">{a.title}</div>
        <div className="text-[12px] text-(--ink-muted) mt-0.5">{a.summary}</div>
        <div className="mt-5 h-[340px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={a.body.series}>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis dataKey="sku" tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
              <YAxis tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
              <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12, borderRadius: 8 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="onHand" name="On hand" fill="var(--accent)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="projected" name="Projected end" fill="var(--border-strong)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4 flex items-center gap-2 text-[12px] text-(--err)">
          <AlertTriangle className="w-3.5 h-3.5" />
          <span>Four SKUs are trending toward a stockout before the end of the month.</span>
        </div>
      </div>
    );
  }

  if (a.type === "table") {
    return (
      <div className="max-w-[880px] mx-auto rounded-xl border border-(--border) bg-(--surface) overflow-hidden">
        <div className="px-5 py-4 border-b border-(--border)">
          <div className="text-[15px] font-medium text-(--ink)">{a.title}</div>
          <div className="text-[12px] text-(--ink-muted) mt-0.5">{a.summary}</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="bg-(--surface-2) text-(--ink-muted) text-[11px] uppercase tracking-wide">
              <tr>{a.body.headers.map(h => <th key={h} className={cn("font-medium px-4 py-2.5", ["On hand", "30-day demand", "Projected end"].includes(h) ? "text-right" : "text-left")}>{h}</th>)}</tr>
            </thead>
            <tbody className="text-(--ink)">
              {a.body.rows.map((r, i) => (
                <tr key={i} className="border-t border-(--border)">
                  {r.map((c, j) => (
                    <td key={j} className={cn("px-4 py-2.5", j >= 1 && j <= 3 ? "text-right tabular-nums" : "")}>
                      {j === 4 && c.startsWith("Yes") ? (
                        <span className="inline-flex items-center gap-1.5 text-(--err)"><AlertTriangle className="w-3 h-3" /> {c}</span>
                      ) : j === 4 && c === "Watch" ? (
                        <span className="text-(--warn)">{c}</span>
                      ) : j === 4 ? (
                        <span className="text-(--ok)">{c}</span>
                      ) : c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (a.type === "markdown") {
    return (
      <div className="max-w-[680px] mx-auto rounded-xl border border-(--border) bg-(--surface) p-8">
        <article className="prose-custom">
          {a.body.split("\
").map((line, i) => {
            if (line.startsWith("## ")) return <h2 key={i} className="text-[17px] font-semibold text-(--ink) mt-6 mb-2 first:mt-0">{line.slice(3)}</h2>;
            if (line.startsWith("- **")) {
              const m = line.match(/^- \*\*(.+?)\*\* â€” (.+)$/);
              if (m) {
                return (
                  <div key={i} className="flex gap-2 py-1 text-[13px] text-(--ink) leading-relaxed">
                    <span className="text-(--ink-faint) shrink-0">â€”</span>
                    <span><span className="font-medium">{m[1]}</span> â€” {m[2]}</span>
                  </div>
                );
              }
            }
            if (line.startsWith("- ")) {
              return <div key={i} className="flex gap-2 py-0.5 text-[13px] text-(--ink) leading-relaxed"><span className="text-(--ink-faint) shrink-0">â€”</span><span>{line.slice(2)}</span></div>;
            }
            if (line.trim() === "") return <div key={i} className="h-2" />;
            return <p key={i} className="text-[13px] text-(--ink) leading-relaxed">{line}</p>;
          })}
        </article>
      </div>
    );
  }
  return null;
}

/* ------------------------------------------------------------------ */
/*  Settings                                                           */
/* ------------------------------------------------------------------ */

function SettingsView({ onClose, onRerunSetup, mode, setMode, setupMode }) {
  const [tab, setTab] = useState("models");
  const tabs = [
    { id: "models", label: "Models" },
    { id: "setup", label: "Setup" },
    { id: "appearance", label: "Appearance" },
    { id: "privacy", label: "Privacy" },
  ];

  return (
    <div className="fixed inset-0 z-50 bg-(--ink)/30 flex items-center justify-center p-6">
      <div className="w-full max-w-[820px] h-[620px] max-h-[90vh] rounded-xl bg-(--bg) border border-(--border) shadow-[0_1px_2px_rgba(28,25,22,.04),0_8px_24px_-8px_rgba(28,25,22,.10)] flex overflow-hidden">
        <div className="w-[180px] shrink-0 border-r border-(--border) p-3">
          <div className="px-2 pb-2 text-[11px] uppercase tracking-wide text-(--ink-faint) font-medium">Settings</div>
          <div className="space-y-0.5">
            {tabs.map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={cn(
                  "w-full h-8 px-2 rounded-md text-left text-[13px] focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)",
                  tab === t.id ? "bg-(--surface-2) text-(--ink) font-medium" : "text-(--ink-muted) hover:bg-(--surface-2)"
                )}
              >{t.label}</button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          {tab === "models" && <ModelsSettings />}
          {tab === "setup" && <SetupSettings onRerunSetup={onRerunSetup} setupMode={setupMode} />}
          {tab === "appearance" && <AppearanceSettings mode={mode} setMode={setMode} />}
          {tab === "privacy" && <PrivacySettings />}
        </div>
        <button onClick={onClose} className="absolute top-4 right-4"><IconButton><X className="w-4 h-4" /></IconButton></button>
      </div>
    </div>
  );
}

function ModelsSettings() {
  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Active models</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        These are the models running on your machine. The indicator shows whether each one fits your hardware.
      </p>
      <div className="mt-5 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {MODELS.filter(m => m.role !== "Not selected").map(m => (
          <div key={m.id} className="p-4 flex items-center justify-between gap-4">
            <div>
              <div className="text-[14px] font-medium text-(--ink)">{m.name}</div>
              <div className="mt-0.5 text-[12px] text-(--ink-muted)">{m.role} Â· {m.size}</div>
            </div>
            <FitBadge fit={m.fit} note={m.note} />
          </div>
        ))}
      </div>

      <h4 className="mt-8 text-[14px] font-medium text-(--ink)">Other models considered</h4>
      <div className="mt-3 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {MODELS.filter(m => m.role === "Not selected").map(m => (
          <div key={m.id} className="p-4 flex items-center justify-between gap-4">
            <div>
              <div className="text-[14px] font-medium text-(--ink)">{m.name}</div>
              <div className="mt-0.5 text-[12px] text-(--ink-muted)">{m.size}</div>
            </div>
            <FitBadge fit={m.fit} note={m.note} />
          </div>
        ))}
      </div>
    </div>
  );
}

function SetupSettings({ onRerunSetup, setupMode }) {
  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Setup</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        Current mode: <span className="text-(--ink) font-medium">{setupMode === "managed" ? "Set it up for me" : "Connect my own local server"}</span>.
      </p>
      <div className="mt-5 space-y-2">
        <Button variant="secondary" onClick={onRerunSetup}>
          <RefreshCw className="w-3.5 h-3.5" /> Switch setup mode
        </Button>
        <p className="text-[12px] text-(--ink-muted) leading-relaxed">
          Switching will re-run the setup flow. Your chat history and files stay on the machine.
        </p>
      </div>
    </div>
  );
}

function AppearanceSettings({ mode, setMode }) {
  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Appearance</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">Choose how the workspace looks. You can change this any time.</p>
      <div className="mt-5 inline-flex rounded-lg border border-(--border) bg-(--surface) p-1">
        {[
          { id: "light", label: "Light", icon: Sun },
          { id: "dark", label: "Dark", icon: Moon },
        ].map(o => {
          const I = o.icon;
          const active = mode === o.id;
          return (
            <button
              key={o.id}
              onClick={() => setMode(o.id)}
              className={cn(
                "h-9 px-3 rounded-md text-[13px] inline-flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)",
                active ? "bg-(--surface-2) text-(--ink) font-medium" : "text-(--ink-muted)"
              )}
            >
              <I className="w-3.5 h-3.5" /> {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function PrivacySettings() {
  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Privacy</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        A plain-language summary of where your data lives and what the app does with it.
      </p>
      <div className="mt-5 space-y-3">
        {[
          { label: "Where your files are stored", value: "On this machine, in your user folder" },
          { label: "Where prompts and outputs are stored", value: "On this machine only" },
          { label: "Cloud services used", value: "None. The app does not contact external servers." },
          { label: "Telemetry", value: "None collected" },
        ].map(r => (
          <div key={r.label} className="rounded-xl border border-(--border) bg-(--surface) p-4 flex items-start justify-between gap-4">
            <div className="text-[13px] text-(--ink-muted)">{r.label}</div>
            <div className="text-[13px] text-(--ink) text-right max-w-[60%]">{r.value}</div>
          </div>
        ))}
      </div>
      <div className="mt-5 p-4 rounded-xl border border-(--border) bg-(--surface-2) flex items-start gap-3">
        <ShieldCheck className="w-4 h-4 text-(--ok) shrink-0 mt-0.5" />
        <div className="text-[13px] text-(--ink) leading-relaxed">
          If you ever want to remove everything the app has stored, open the app menu and choose <span className="font-medium">Reset workspace</span>. This deletes all chats, files, and models from this machine.
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  App shell                                                          */
/* ------------------------------------------------------------------ */

export default function App() {
  const [firstRun, setFirstRun] = useState(true);
  const [setupMode, setSetupMode] = useState("managed");
  const [chats, setChats] = useState(initialChats);
  const [folders, setFolders] = useState(FOLDERS);
  const [activeChatId, setActiveChatId] = useState("c1");
  const [artifactId, setArtifactId] = useState(null);
  const [panelWidth, setPanelWidth] = useState(480);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const activeChat = chats.find(c => c.id === activeChatId) || null;
  const activeArtifact = artifactId ? ARTIFACTS[artifactId] : null;

  const handleNewChat = () => {
    const id = "c" + Date.now();
    setChats(prev => [{ id, title: "New chat", folder: null, group: "today", messages: [] }, ...prev]);
    setActiveChatId(id);
  };

  const handleSend = ({ text, files }) => {
    if (!text.trim() && files.length === 0) return;
    let chatId = activeChatId;
    if (!chatId || !chats.find(c => c.id === chatId)) {
      chatId = "c" + Date.now();
      setChats(prev => [{ id: chatId, title: text.slice(0, 48) || files[0]?.name || "New chat", folder: null, group: "today", messages: [] }, ...prev]);
    }
    const userMsg = { id: "u" + Date.now(), role: "user", text: text.trim(), files: files.length ? files : undefined };

    // Pick a realistic mock reply based on prompt content
    const reply = pickMockReply(text, files);
    const asstMsg = { id: "a" + Date.now(), role: "assistant", text: reply.text, artifacts: reply.artifacts };

    setChats(prev => prev.map(c => c.id === chatId ? {
      ...c,
      title: c.messages.length === 0 ? (text.slice(0, 48) || files[0]?.name || c.title) : c.title,
      messages: [...c.messages, userMsg, asstMsg],
    } : c));
    setActiveChatId(chatId);
  };

  const handleCreateFolder = () => {
    const id = "f" + Date.now();
    const name = "New folder";
    setFolders(prev => [...prev, { id, name }]);
  };
  const handleMoveChat = (chatId, folderId) => {
    setChats(prev => prev.map(c => c.id === chatId ? { ...c, folder: folderId } : c));
  };
  const handleDeleteChat = (chatId) => {
    setChats(prev => prev.filter(c => c.id !== chatId));
    if (activeChatId === chatId) setActiveChatId(null);
  };
  const handleRenameFolder = (fid, name) => {
    setFolders(prev => prev.map(f => f.id === fid ? { ...f, name } : f));
  };
  const handleDeleteFolder = (fid) => {
    setFolders(prev => prev.filter(f => f.id !== fid));
    setChats(prev => prev.map(c => c.folder === fid ? { ...c, folder: null } : c));
  };

  const onResizeStart = (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = panelWidth;
    const move = (ev) => {
      const delta = startX - ev.clientX;
      setPanelWidth(Math.max(320, Math.min(window.innerWidth * 0.6, startW + delta)));
    };
    const up = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  };

  if (firstRun) {
    return (
      <ThemeProvider>
        <SetupFlow onFinish={() => setFirstRun(false)} />
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider>
      <div className="h-screen w-screen flex bg-(--bg) text-(--ink) font-sans antialiased">
        <Sidebar
          chats={chats}
          folders={folders}
          activeChatId={activeChatId}
          onSelectChat={setActiveChatId}
          onNewChat={handleNewChat}
          onCreateFolder={handleCreateFolder}
          onMoveChat={handleMoveChat}
          onDeleteChat={handleDeleteChat}
          onRenameFolder={handleRenameFolder}
          onDeleteFolder={handleDeleteFolder}
          onOpenSettings={() => setSettingsOpen(true)}
        />

        <div className="flex-1 flex min-w-0">
          <ChatThread
            chat={activeChat}
            onSend={handleSend}
            onOpenArtifact={(id) => setArtifactId(id)}
          />
          {activeArtifact && (
            <div
              className="relative border-l border-(--border) shrink-0"
              style={{ width: panelWidth }}
            >
              <ArtifactPanel
                artifact={activeArtifact}
                onClose={() => setArtifactId(null)}
                width={panelWidth}
                onResizeStart={onResizeStart}
              />
            </div>
          )}
        </div>

        {settingsOpen && (
          <ThemeConsumerSetMode>
            <SettingsView
              onClose={() => setSettingsOpen(false)}
              onRerunSetup={() => { setSettingsOpen(false); setFirstRun(true); }}
              setupMode={setupMode}
            />
          </ThemeConsumerSetMode>
        )}
      </div>
    </ThemeProvider>
  );
}

/* Helper to bridge theme mode from Settings to ThemeProvider */
function ThemeConsumerSetMode({ children }) {
  return <ThemeSettingsBridge>{children}</ThemeSettingsBridge>;
}
function ThemeSettingsBridge({ children }) {
  // SettingsView reads setMode from ThemeCtx, so we just render children inside existing provider.
  // To make SettingsView receive mode/setMode props we wrap it in an injector.
  const { mode, setMode } = useTheme();
  // clone first child with injected props
  const child = React.Children.only(children);
  return React.cloneElement(child, { mode, setMode });
}

/* ------------------------------------------------------------------ */
/*  Mock reply picker                                                  */
/* ------------------------------------------------------------------ */

function pickMockReply(text, files) {
  const t = (text || "").toLowerCase();
  if (files.length > 0 && (t.includes("dashboard") || t.includes("csv") || t.includes("revenue") || t.includes("sales"))) {
    return { text: "I read the file and put together a dashboard with the key totals, a monthly trend, and the rows that matter most. Open it on the right to drill in.", artifacts: ["a-dashboard"] };
  }
  if (t.includes("proposal") || t.includes("contract") || t.includes("renewal")) {
    return { text: "I drafted a proposal you can send as a PDF. It leads with outcomes, lays out the options side by side, and ends with a clear next step.", artifacts: ["a-pdf"] };
  }
  if (t.includes("forecast") || t.includes("inventory") || t.includes("sku")) {
    return { text: "I ran the forecast and flagged the items that are trending toward a stockout. The chart shows the shape of it; the table gives you every SKU to work from.", artifacts: ["a-chart", "a-table"] };
  }
  if (t.includes("notes") || t.includes("transcript") || t.includes("meeting")) {
    return { text: "I turned the transcript into clean notes with owners and dates. Sensitive discussion is kept intact rather than summarized.", artifacts: ["a-markdown"] };
  }
  if (t.includes("chart") || t.includes("graph") || t.includes("plot")) {
    return { text: "Here's the chart. I used bars for the two series so the comparison reads quickly; let me know if a line would work better for your audience.", artifacts: ["a-chart"] };
  }
  if (t.includes("table") || t.includes("spreadsheet")) {
    return { text: "Here's the data as a table. Sortable columns, the flags I called out in the text are color-coded in the Reorder column.", artifacts: ["a-table"] };
  }
  if (t.includes("report")) {
    return { text: "I put together a short report. The opening summarizes the finding, the middle shows the supporting detail, and the close gives you a recommendation and a next step.", artifacts: ["a-pdf"] };
  }
  return {
    text: "Got it. I'll work from what you gave me and come back with a draft you can review. If there's a format you prefer â€” a report, a dashboard, a table â€” say the word and I'll shape it that way.",
    artifacts: [],
  };
}","is_error":true,"tool_use_id":"toolu_019wJPDe7h5pkmhBtHsoSXiT"}]},"uuid":"18bfea0f-ab3a-4807-8b72-7a9d1004d77e","timestamp":"2026-06-28T19:13:02.541Z","toolUseResult":"Error: The user doesn't want to proceed with this tool use. The tool use was rejected (eg. if it was a file edit, the new_string was NOT written to the file). The user provided the following reason for the rejection:  Heres the mock:

// App.jsx â€” Local-first private AI workspace UI
//
// Design tokens (derive every value from these):
//
// Light palette
//   --bg:           #FAF9F7   (warm off-white base)
//   --surface:      #FFFFFF
//   --surface-2:    #F4F2EE   (subtle tinted surface)
//   --border:       #E8E5E0   (hairline)
//   --border-strong:#D4D0C9
//   --ink:          #1F1D1B   (quiet near-black)
//   --ink-muted:    #6B6762
//   --ink-faint:    #A39E96
//   --accent:       #2D5A5F   (muted deep teal â€” single accent)
//   --accent-ink:   #FFFFFF
//   --ok:           #4A7A52
//   --warn:         #A67535
//   --err:          #A5453A
//
// Dark palette (swap via .dark on <html>)
//   --bg:           #1A1917   (warm dark grey, not pure black)
//   --surface:      #232220
//   --surface-2:    #2A2926
//   --border:       #35332F
//   --border-strong:#45423D
//   --ink:          #EDEAE5
//   --ink-muted:    #8A867F
//   --ink-faint:    #605C56
//   --accent:       #6FB0B5
//   --accent-ink:   #1A1917
//   --ok:           #7AAE82
//   --warn:         #C99A5C
//   --err:          #C87064
//
// Type scale (px): 11 / 12 / 13 / 14 / 16 / 18 / 22 / 28
// Weights: 400 / 500 / 600
// Spacing scale (px): 2 / 4 / 6 / 8 / 10 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64
// Radius: 4 / 6 / 8 / 12
// Shadow: single level â€” 0 1px 2px rgba(28,25,22,.04), 0 8px 24px -8px rgba(28,25,22,.10)
//
// Slop-check notes: no gradients, no glass blur, no neon, no purple, one accent only,
// hairline borders + one shadow level, sentence case, plain verbs, no emoji-as-icon.

import React, {
  useEffect, useMemo, useRef, useState, useCallback, createContext, useContext,
} from "react";
import {
  Plus, Search, Settings as SettingsIcon, FolderPlus, Folder, MessageSquare,
  Send, Paperclip, Globe, X, ChevronDown, ChevronRight, MoreHorizontal,
  ArrowRight, Cpu, HardDrive, Download, Check, AlertTriangle, Ban,
  FileText, BarChart3, Table, LayoutDashboard, Download as DownloadIcon,
  Copy, PanelRight, Minimize2, Maximize2, FolderOpen, Move, Trash2,
  ShieldCheck, Wifi, WifiOff, Sun, Moon, Sparkles, FileCheck,
  ArrowLeft, RefreshCw, Link2, Server,
} from "lucide-react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, AreaChart, Area,
} from "recharts";

/* ------------------------------------------------------------------ */
/*  Theme context                                                      */
/* ------------------------------------------------------------------ */

const ThemeCtx = createContext();
const useTheme = () => useContext(ThemeCtx);

function ThemeProvider({ children }) {
  const [mode, setMode] = useState("light");
  useEffect(() => {
    document.documentElement.classList.toggle("dark", mode === "dark");
  }, [mode]);
  const toggle = () => setMode(m => (m === "light" ? "dark" : "light"));
  return (
    <ThemeCtx.Provider value={{ mode, toggle, setMode }}>
      {children}
    </ThemeCtx.Provider>
  );
}

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const HARDWARE = {
  cpu: "Apple M2 Pro â€” 12-core",
  ram: "32 GB unified memory",
  gpu: "Integrated 19-core GPU",
  vram: "24 GB shared",
};

const MODELS = [
  { id: "reasoner", name: "Qwen 2.5 14B", role: "Main reasoner", size: "9.2 GB", fit: "ok", note: "Runs well on your machine" },
  { id: "summarizer", name: "Phi-3.5 Mini", role: "Summarizer", size: "2.3 GB", fit: "ok", note: "Runs well on your machine" },
  { id: "utility", name: "Llama 3.2 3B", role: "Utility", size: "2.0 GB", fit: "ok", note: "Runs well on your machine" },
  { id: "big", name: "Llama 3.1 70B", role: "Not selected", size: "39 GB", fit: "bad", note: "Too large for this machine" },
  { id: "med", name: "Mistral 7B", role: "Not selected", size: "4.4 GB", fit: "warn", note: "Will run slowly under load" },
];

const PROVIDERS = ["Ollama", "LM Studio", "llama.cpp", "OpenAI-compatible"];

const FOLDERS = [
  { id: "f1", name: "Client work" },
  { id: "f2", name: "Internal" },
];

const initialChats = [
  {
    id: "c1", title: "Q2 revenue analysis", folder: null, group: "today",
    messages: [
      {
        id: "m1", role: "user",
        text: "Summarize Q2 revenue from the attached CSV and show me a dashboard with monthly totals and the top five customers.",
        files: [{ name: "q2_revenue.csv", size: "142 KB" }],
      },
      {
        id: "m2", role: "assistant",
        text: "Q2 closed at $1.28M in recognized revenue, up 11% from Q1. The strongest month was May, driven by three renewals in the mid-market segment. Your top customer by revenue this quarter was Halberd & Sons at $184K, followed by Northline, Greenleaf, Marlowe, and Finch. I put together a dashboard so you can scan the shape of the quarter at a glance and drill into the customer table when you need it.",
        artifacts: ["a-dashboard"],
      },
    ],
  },
  {
    id: "c2", title: "Draft client proposal for Greenleaf", folder: "f1", group: "today",
    messages: [
      { id: "m3", role: "user", text: "Draft a proposal for Greenleaf Landscaping to renew their service contract, with pricing options for 12 and 24 months." },
      {
        id: "m4", role: "assistant",
        text: "I drafted a proposal you can send as a PDF. It leads with the outcomes Greenleaf saw on the current contract, lays out two pricing options side by side, and ends with a simple next-step. Open it on the right to review â€” every section is editable before you export.",
        artifacts: ["a-pdf"],
      },
    ],
  },
  {
    id: "c3", title: "Sales team meeting notes", folder: "f2", group: "yesterday",
    messages: [
      { id: "m5", role: "user", text: "Here's the transcript from this morning's sales standup. Turn it into clean notes with owners and dates." },
      {
        id: "m6", role: "assistant",
        text: "Done. I captured the three blockers the team flagged, the owners for each action item, and the dates they committed to. The full note is on the right â€” I kept the discussion about the Marlowe renewal intact since it's sensitive.",
        artifacts: ["a-markdown"],
      },
    ],
  },
  {
    id: "c4", title: "Inventory forecast by SKU", folder: "f1", group: "week",
    messages: [
      { id: "m7", role: "user", text: "Forecast the next 30 days of inventory for our top 20 SKUs." },
      {
        id: "m8", role: "assistant",
        text: "I ran a 30-day forecast across the top 20 SKUs. Six of them are trending toward a stockout before the end of the month if the current sales pace holds â€” I called them out in the chart and the table so you can decide which to reorder first.",
        artifacts: ["a-chart", "a-table"],
      },
    ],
  },
  {
    id: "c5", title: "Rewrite homepage hero", folder: null, group: "older",
    messages: [
      { id: "m9", role: "user", text: "Give me three tighter versions of the homepage hero, same meaning, fewer words." },
      { id: "m10", role: "assistant", text: "Here are three rewrites. Option A keeps the original structure and just tightens the language. Option B leads with the outcome instead of the feature. Option C is the shortest â€” it trusts the reader to click through for detail.\
\
A. Run AI on your own machine. Turn files into reports, dashboards, and documents â€” no cloud, no configuration.\
\
B. Your files, answered. Ask questions across your documents and get finished artifacts back, all on your own hardware.\
\
C. Private AI that just runs. Drop a file, ask a question, get a report." },
    ],
  },
  {
    id: "c6", title: "Onboarding email sequence", folder: "f1", group: "older",
    messages: [
      { id: "m11", role: "user", text: "Sketch a 4-email onboarding sequence for new trial users." },
      { id: "m12", role: "assistant", text: "Four emails over ten days, each with one job:\
\
Day 0 â€” Welcome. One thing to do in the next five minutes.\
Day 2 â€” First win. A concrete example of a report they can produce today.\
Day 5 â€” Depth. A feature they haven't seen yet, shown through a real use case.\
Day 10 â€” Decision. A plain ask about what would make them stay." },
    ],
  },
];

/* ---- Artifact content -------------------------------------------- */

const ARTIFACTS = {
  "a-pdf": {
    id: "a-pdf",
    type: "pdf",
    title: "Greenleaf Landscaping â€” Q2 2026 Service Renewal Proposal",
    summary: "12- and 24-month pricing options with projected outcomes.",
    body: {
      prepared: "June 29, 2026",
      for: "Greenleaf Landscaping â€” Attn: Priya Anand, Operations",
      from: "Halcyon Grounds Co.",
      sections: [
        {
          heading: "What you've gotten on the current contract",
          paragraphs: [
            "Over the past twelve months Greenleaf moved from a reactive maintenance schedule to a routed, zone-based plan. Site visits dropped 18% while the number of documented issues resolved per visit rose 31%. The two properties that had the most callbacks in 2025 â€” the Elm Street depot and the Riverside campus â€” are now the two quietest sites in the book.",
            "Invoicing moved from per-visit to a fixed monthly rate in February. Cash flow on the account has been predictable every month since, and Greenleaf's accounts payable team has not flagged a single dispute.",
          ],
        },
        {
          heading: "What we're proposing for the next contract",
          paragraphs: [
            "Two options, same scope, same crew, same response times. The difference is commitment length and the rate.",
          ],
          table: {
            headers: ["Option", "Term", "Monthly rate", "Annual total", "Includes"],
            rows: [
              ["A", "12 months", "$8,400", "$100,800", "Weekly routing, 4h emergency response, quarterly site reports"],
              ["B", "24 months", "$7,650", "$91,800", "Weekly routing, 4h emergency response, quarterly site reports, two seasonal redesigns per year"],
            ],
          },
        },
        {
          heading: "What happens next",
          paragraphs: [
            "Reply with the option letter and a start date. We'll send a countersigned agreement within two business days and schedule the first quarterly review before the first invoice.",
          ],
        },
      ],
    },
  },

  "a-dashboard": {
    id: "a-dashboard",
    type: "dashboard",
    title: "Q2 2026 Revenue Dashboard",
    summary: "Quarterly totals, monthly trend, and top customers.",
    body: {
      kpis: [
        { label: "Recognized revenue", value: "$1.28M", delta: "+11% vs Q1", positive: true },
        { label: "Closed deals", value: "38", delta: "+4 vs Q1", positive: true },
        { label: "Average deal size", value: "$33.7K", delta: "+2.1%", positive: true },
        { label: "Days to close", value: "27", delta: "-3 days", positive: true },
      ],
      monthly: [
        { month: "Apr", revenue: 348 },
        { month: "May", revenue: 512 },
        { month: "Jun", revenue: 421 },
      ],
      pipeline: [
        { month: "Apr", new: 210, renewed: 138 },
        { month: "May", new: 280, renewed: 232 },
        { month: "Jun", new: 198, renewed: 223 },
      ],
      topCustomers: [
        { customer: "Halberd & Sons", revenue: 184200, deals: 2, segment: "Mid-market" },
        { customer: "Northline Fabricators", revenue: 156800, deals: 3, segment: "SMB" },
        { customer: "Greenleaf Landscaping", revenue: 121400, deals: 1, segment: "SMB" },
        { customer: "Marlowe & Co.", revenue: 108900, deals: 2, segment: "Mid-market" },
        { customer: "Finch Trading", revenue: 97300, deals: 1, segment: "SMB" },
      ],
    },
  },

  "a-chart": {
    id: "a-chart",
    type: "chart",
    title: "30-day inventory forecast â€” top 20 SKUs",
    summary: "Units on hand vs projected demand, with stockout risk flagged.",
    body: {
      series: [
        { sku: "SKU-1041", onHand: 840, projected: 410, flag: false },
        { sku: "SKU-1188", onHand: 312, projected: 485, flag: true },
        { sku: "SKU-1202", onHand: 605, projected: 540, flag: false },
        { sku: "SKU-1277", onHand: 240, projected: 380, flag: true },
        { sku: "SKU-1319", onHand: 900, projected: 612, flag: false },
        { sku: "SKU-1405", onHand: 188, projected: 260, flag: true },
        { sku: "SKU-1488", onHand: 720, projected: 505, flag: false },
        { sku: "SKU-1512", onHand: 290, projected: 440, flag: true },
      ],
    },
  },

  "a-table": {
    id: "a-table",
    type: "table",
    title: "Inventory forecast â€” detail",
    summary: "Projected end-of-month units and reorder flag for the top 20 SKUs.",
    body: {
      headers: ["SKU", "On hand", "30-day demand", "Projected end", "Reorder"],
      rows: [
        ["SKU-1041", "840", "430", "410", "No"],
        ["SKU-1188", "312", "490", "âˆ’178", "Yes â€” urgent"],
        ["SKU-1202", "605", "580", "25", "Watch"],
        ["SKU-1277", "240", "395", "âˆ’155", "Yes â€” urgent"],
        ["SKU-1319", "900", "420", "480", "No"],
        ["SKU-1405", "188", "270", "âˆ’82", "Yes"],
        ["SKU-1488", "720", "380", "340", "No"],
        ["SKU-1512", "290", "460", "âˆ’170", "Yes â€” urgent"],
        ["SKU-1601", "512", "300", "212", "No"],
        ["SKU-1655", "388", "410", "âˆ’22", "Watch"],
      ],
    },
  },

  "a-markdown": {
    id: "a-markdown",
    type: "markdown",
    title: "Sales standup â€” June 28, 2026",
    summary: "Attendees, decisions, owners, and dates.",
    body: `## Attendees\
Maya (lead), Daniel, Noor, Sam, Priya\
\
## Decisions made\
- The Marlowe renewal stays with Maya. No handoff this quarter.\
- New-demo decks move to the shorter 8-slide format starting next week.\
- Weekly pipeline review moves from Tuesday to Thursday.\
\
## Action items\
- **Daniel** â€” send the revised Marlowe pricing to Maya by **July 1**.\
- **Noor** â€” ship the 8-slide demo template to the team by **July 3**.\
- **Sam** â€” close the three stalled Halberd opportunities or write them off by **July 5**.\
- **Priya** â€” schedule pipeline reviews with each rep for the week of **July 7**.\
\
## Open questions\
- Do we extend the mid-market discount to Finch, or hold list price?\
- Should Q3 kickoff be in-person or remote? Maya will decide by July 2.\
\
## Notes\
The Marlowe conversation is sensitive. Please keep discussion inside this thread until the renewal is signed.`,
  },
};

/* ------------------------------------------------------------------ */
/*  Utilities                                                          */
/* ------------------------------------------------------------------ */

const cn = (...xs) => xs.filter(Boolean).join(" ");

const useReducedMotion = () => {
  const [rm, setRm] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setRm(mq.matches);
    const h = e => setRm(e.matches);
    mq.addEventListener("change", h);
    return () => mq.removeEventListener("change", h);
  }, []);
  return rm;
};

/* ------------------------------------------------------------------ */
/*  Tiny UI primitives                                                 */
/* ------------------------------------------------------------------ */

function FitBadge({ fit, note }) {
  if (fit === "ok")
    return (
      <span className="inline-flex items-center gap-1 text-[12px] text-(--ok)" title={note}>
        <Check className="w-3.5 h-3.5" strokeWidth={2.5} /> <span className="text-(--ink-muted)">Runs well</span>
      </span>
    );
  if (fit === "warn")
    return (
      <span className="inline-flex items-center gap-1 text-[12px] text-(--warn)" title={note}>
        <AlertTriangle className="w-3.5 h-3.5" strokeWidth={2.5} /> <span className="text-(--ink-muted)">Runs slowly</span>
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 text-[12px] text-(--err)" title={note}>
      <Ban className="w-3.5 h-3.5" strokeWidth={2.5} /> <span className="text-(--ink-muted)">Too large</span>
    </span>
  );
}

function IconButton({ className, ...p }) {
  return (
    <button
      {...p}
      className={cn(
        "inline-flex items-center justify-center w-8 h-8 rounded-md",
        "text-(--ink-muted) hover:text-(--ink) hover:bg-(--surface-2)",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--bg)",
        "transition-colors",
        className
      )}
    />
  );
}

function Button({ variant = "primary", className, children, ...p }) {
  const base = "inline-flex items-center justify-center gap-2 h-9 px-3.5 rounded-md text-[13px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--bg) disabled:opacity-50 disabled:pointer-events-none";
  const variants = {
    primary: "bg-(--accent) text-(--accent-ink) hover:brightness-110",
    secondary: "bg-(--surface-2) text-(--ink) border border-(--border) hover:bg-(--border)",
    ghost: "text-(--ink) hover:bg-(--surface-2)",
    danger: "text-(--err) hover:bg-(--surface-2)",
  };
  return <button className={cn(base, variants[variant], className)} {...p}>{children}</button>;
}

/* ------------------------------------------------------------------ */
/*  Setup flow                                                         */
/* ------------------------------------------------------------------ */

function SetupFlow({ onFinish }) {
  const [step, setStep] = useState(0); // 0 welcome, 1.. managed/byo
  const [path, setPath] = useState(null); // "managed" | "byo"
  const [scanDone, setScanDone] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState({});
  const [downloadDone, setDownloadDone] = useState(false);
  const rm = useReducedMotion();

  // BYO form
  const [provider, setProvider] = useState("Ollama");
  const [baseUrl, setBaseUrl] = useState("http://localhost:11434/v1");
  const [apiKey, setApiKey] = useState("");
  const [roles, setRoles] = useState({
    reasoner: "llama3.1:8b",
    summarizer: "phi3.5",
    utility: "llama3.2:3b",
  });
  const [testState, setTestState] = useState("idle"); // idle | testing | success | failure

  // Hardware scan animation
  useEffect(() => {
    if (step !== 1 || path !== "managed" || scanDone) return;
    const t = setTimeout(() => setScanDone(true), rm ? 100 : 1400);
    return () => clearTimeout(t);
  }, [step, path, scanDone, rm]);

  // Download simulation
  useEffect(() => {
    if (step !== 3 || path !== "managed") return;
    if (downloadDone) return;
    const models = ["reasoner", "summarizer", "utility"];
    const id = setInterval(() => {
      setDownloadProgress(prev => {
        const next = { ...prev };
        let allDone = true;
        for (const m of models) {
          const cur = prev[m] ?? 0;
          if (cur < 100) {
            next[m] = Math.min(100, cur + (rm ? 100 : Math.random() * 9 + 3));
            allDone = false;
          }
        }
        return next;
      });
    }, rm ? 20 : 350);
    return () => clearInterval(id);
  }, [step, path, downloadDone, rm]);

  useEffect(() => {
    const models = ["reasoner", "summarizer", "utility"];
    if (models.every(m => (downloadProgress[m] ?? 0) >= 100)) {
      setDownloadDone(true);
    }
  }, [downloadProgress]);

  const runTest = () => {
    setTestState("testing");
    setTimeout(() => {
      // deterministic mock: succeed unless url is empty
      setTestState(baseUrl.trim().length > 5 ? "success" : "failure");
    }, rm ? 50 : 900);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-(--bg) px-6 py-12">
      <div className="w-full max-w-[640px]">
        <div className="mb-8 flex items-center gap-2 text-[12px] text-(--ink-faint) tracking-wide uppercase">
          <ShieldCheck className="w-3.5 h-3.5" /> Local-first workspace
        </div>

        {step === 0 && <WelcomeStep onChoose={p => { setPath(p); setStep(1); }} />}
        {step === 1 && path === "managed" && (
          <HardwareStep done={scanDone} onNext={() => setStep(2)} onBack={() => setStep(0)} />
        )}
        {step === 2 && path === "managed" && (
          <RecommendStep onNext={() => setStep(3)} onBack={() => setStep(1)} />
        )}
        {step === 3 && path === "managed" && (
          <DownloadStep
            progress={downloadProgress}
            done={downloadDone}
            onFinish={onFinish}
            onBack={() => setStep(2)}
          />
        )}
        {step === 1 && path === "byo" && (
          <ByoStep
            provider={provider} setProvider={setProvider}
            baseUrl={baseUrl} setBaseUrl={setBaseUrl}
            apiKey={apiKey} setApiKey={setApiKey}
            roles={roles} setRoles={setRoles}
            testState={testState} runTest={runTest}
            onFinish={onFinish}
            onBack={() => setStep(0)}
          />
        )}
      </div>
    </div>
  );
}

function WelcomeStep({ onChoose }) {
  return (
    <div>
      <h1 className="text-[28px] font-semibold tracking-tight text-(--ink) leading-tight">
        Set up your workspace
      </h1>
      <p className="mt-3 text-[14px] text-(--ink-muted) leading-relaxed max-w-[520px]">
        Everything you do here runs on your own machine. Nothing you ask, upload, or generate leaves this computer unless you share it yourself. Pick the setup that matches how you want to work.
      </p>

      <div className="mt-8 grid gap-3">
        <button
          onClick={() => onChoose("managed")}
          className="group text-left p-5 rounded-xl border border-(--border) bg-(--surface) hover:border-(--accent) hover:bg-(--surface) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) transition-colors"
        >
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-(--surface-2) border border-(--border) flex items-center justify-center">
                <Cpu className="w-4 h-4 text-(--accent)" />
              </div>
              <div>
                <div className="text-[15px] font-medium text-(--ink)">Set it up for me</div>
                <div className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
                  We'll check what your machine can handle and install the right models automatically.
                </div>
              </div>
            </div>
            <ArrowRight className="w-4 h-4 text-(--ink-faint) group-hover:text-(--accent) transition-colors mt-1" />
          </div>
        </button>

        <button
          onClick={() => onChoose("byo")}
          className="group text-left p-5 rounded-xl border border-(--border) bg-(--surface) hover:border-(--accent) hover:bg-(--surface) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) transition-colors"
        >
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-(--surface-2) border border-(--border) flex items-center justify-center">
                <Server className="w-4 h-4 text-(--accent)" />
              </div>
              <div>
                <div className="text-[15px] font-medium text-(--ink)">Connect my own local server</div>
                <div className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
                  Point the app at an Ollama, LM Studio, llama.cpp, or any OpenAI-compatible server you already run.
                </div>
              </div>
            </div>
            <ArrowRight className="w-4 h-4 text-(--ink-faint) group-hover:text-(--accent) transition-colors mt-1" />
          </div>
        </button>
      </div>
    </div>
  );
}

function HardwareStep({ done, onNext, onBack }) {
  return (
    <div>
      <StepCounter current={1} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">Checking your machine</h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        We'll read what you've got and pick models that fit. This takes a few seconds and you only do it once.
      </p>

      <div className="mt-8 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {Object.entries(HARDWARE).map(([k, v], i) => (
          <HardwareRow key={k} label={hardwareLabel(k)} value={v} revealed={done || i < 2} index={i} />
        ))}
      </div>

      {!done && (
        <div className="mt-5 flex items-center gap-2 text-[13px] text-(--ink-muted)">
          <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Scanningâ€¦
        </div>
      )}

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={onNext} disabled={!done}>Continue</Button>
      </div>
    </div>
  );
}

function hardwareLabel(k) {
  return { cpu: "Processor", ram: "Memory", gpu: "Graphics", vram: "Graphics memory" }[k];
}

function HardwareRow({ label, value, revealed, index }) {
  return (
    <div
      className="px-4 h-12 flex items-center justify-between text-[13px] transition-opacity duration-300"
      style={{ opacity: revealed ? 1 : 0.4, transitionDelay: `${index * 120}ms` }}
    >
      <span className="text-(--ink-muted)">{label}</span>
      <span className="font-medium text-(--ink)">{revealed ? value : "Readingâ€¦"}</span>
    </div>
  );
}

function RecommendStep({ onNext, onBack }) {
  const selected = MODELS.filter(m => m.fit === "ok");
  return (
    <div>
      <StepCounter current={2} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">Recommended setup</h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        These three models fit your machine. We'll use the bigger one when reasoning matters, and the smaller ones for summaries and quick tasks.
      </p>

      <div className="mt-8 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {selected.map(m => (
          <div key={m.id} className="p-4 flex items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[14px] font-medium text-(--ink)">{m.name}</div>
              <div className="mt-0.5 text-[12px] text-(--ink-muted)">{m.role} Â· {m.size}</div>
            </div>
            <FitBadge fit={m.fit} note={m.note} />
          </div>
        ))}
      </div>

      <div className="mt-6 p-4 rounded-xl border border-(--border) bg-(--surface-2)">
        <div className="text-[13px] text-(--ink) leading-relaxed">
          Curious about the models we skipped? Two others looked at and didn't make the cut â€” one's too large for this machine, one would run slowly under load. You can change the selection any time in settings.
        </div>
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={onNext}>Download models</Button>
      </div>
    </div>
  );
}

function DownloadStep({ progress, done, onFinish, onBack }) {
  const models = MODELS.filter(m => m.fit === "ok");
  return (
    <div>
      <StepCounter current={3} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">
        {done ? "You're ready" : "Downloading models"}
      </h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        {done
          ? "All three models are on your machine. Close this window and start working â€” everything runs locally from here."
          : "This runs in the background. You can keep this window open and the downloads will finish while you work."}
      </p>

      <div className="mt-8 space-y-4">
        {models.map(m => {
          const pct = Math.round(progress[m.id] ?? 0);
          return (
            <div key={m.id}>
              <div className="flex items-center justify-between text-[13px] mb-1.5">
                <span className="font-medium text-(--ink)">{m.name}</span>
                <span className="text-(--ink-muted) tabular-nums">{pct}% Â· {m.size}</span>
              </div>
              <div className="h-1.5 rounded-full bg-(--surface-2) overflow-hidden">
                <div
                  className="h-full bg-(--accent) transition-[width] duration-200"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack} disabled={!done}>Back</Button>
        <Button onClick={onFinish} disabled={!done}>Open workspace</Button>
      </div>
    </div>
  );
}

function ByoStep({
  provider, setProvider, baseUrl, setBaseUrl, apiKey, setApiKey,
  roles, setRoles, testState, runTest, onFinish, onBack,
}) {
  const fieldCls = "w-full h-9 px-3 rounded-md bg-(--surface) border border-(--border) text-[13px] text-(--ink) placeholder:text-(--ink-faint) focus:outline-none focus:ring-2 focus:ring-(--accent) focus:border-transparent";
  const labelCls = "block text-[12px] font-medium text-(--ink-muted) mb-1.5";

  return (
    <div>
      <StepCounter current={1} total={1} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">Connect a local server</h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        Point the app at a server you already run. We'll test the connection before you start.
      </p>

      <div className="mt-8 space-y-5">
        <div>
          <label className={labelCls}>Provider</label>
          <select value={provider} onChange={e => setProvider(e.target.value)} className={fieldCls}>
            {PROVIDERS.map(p => <option key={p}>{p}</option>)}
          </select>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3">
          <div>
            <label className={labelCls}>Base URL</label>
            <input
              value={baseUrl}
              onChange={e => setBaseUrl(e.target.value)}
              placeholder="http://localhost:11434/v1"
              className={fieldCls}
            />
          </div>
          <div>
            <label className={labelCls}>API key (optional)</label>
            <input
              type="password"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder="Leave blank if not required"
              className={fieldCls}
            />
          </div>
        </div>

        <div>
          <label className={labelCls}>Map models to tasks</label>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {[
              ["reasoner", "Main reasoner"],
              ["summarizer", "Summarizer"],
              ["utility", "Utility"],
            ].map(([k, label]) => (
              <div key={k}>
                <div className="text-[11px] text-(--ink-faint) mb-1">{label}</div>
                <select
                  value={roles[k]}
                  onChange={e => setRoles({ ...roles, [k]: e.target.value })}
                  className={fieldCls}
                >
                  <option>llama3.1:8b</option>
                  <option>llama3.2:3b</option>
                  <option>phi3.5</option>
                  <option>qwen2.5:14b</option>
                  <option>mistral:7b</option>
                </select>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <Button variant="secondary" onClick={runTest} disabled={testState === "testing"}>
            {testState === "testing" ? (
              <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Testing connectionâ€¦</>
            ) : (
              <><Link2 className="w-3.5 h-3.5" /> Test connection</>
            )}
          </Button>

          {testState === "success" && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-(--ok)">
              <Check className="w-3.5 h-3.5" strokeWidth={2.5} /> Connected. Server responded in 124 ms.
            </span>
          )}
          {testState === "failure" && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-(--err)">
              <WifiOff className="w-3.5 h-3.5" /> Couldn't reach the server. Check the URL and try again.
            </span>
          )}
        </div>
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={onFinish} disabled={testState !== "success"}>Save and continue</Button>
      </div>
    </div>
  );
}

function StepCounter({ current, total }) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "h-1 rounded-full transition-all",
            i < current ? "w-6 bg-(--accent)" : "w-2 bg-(--border-strong)"
          )}
        />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sidebar                                                            */
/* ------------------------------------------------------------------ */

function Sidebar({
  chats, folders, activeChatId, onSelectChat, onNewChat, onCreateFolder,
  onMoveChat, onDeleteChat, onRenameFolder, onDeleteFolder, onOpenSettings,
}) {
  const [q, setQ] = useState("");
  const [openFolders, setOpenFolders] = useState({ f1: true, f2: true });
  const [menuFor, setMenuFor] = useState(null); // chat id
  const menuRef = useRef(null);

  useEffect(() => {
    const h = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) setMenuFor(null); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return chats;
    return chats.filter(c => c.title.toLowerCase().includes(needle));
  }, [q, chats]);

  const byGroup = (group) => filtered.filter(c => c.group === group && !c.folder);
  const byFolder = (fid) => filtered.filter(c => c.folder === fid);

  const groups = [
    { id: "today", label: "Today", items: byGroup("today") },
    { id: "yesterday", label: "Yesterday", items: byGroup("yesterday") },
    { id: "week", label: "Previous 7 days", items: byGroup("week") },
    { id: "older", label: "Older", items: byGroup("older") },
  ];

  return (
    <aside className="w-[260px] shrink-0 bg-(--bg) border-r border-(--border) flex flex-col">
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="w-full h-9 rounded-md bg-(--accent) text-(--accent-ink) text-[13px] font-medium inline-flex items-center justify-center gap-2 hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--bg) transition"
        >
          <Plus className="w-4 h-4" strokeWidth={2.2} /> New chat
        </button>
      </div>

      <div className="px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-(--ink-faint)" />
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Search chats"
            className="w-full h-8 pl-8 pr-2.5 rounded-md bg-(--surface) border border-(--border) text-[13px] text-(--ink) placeholder:text-(--ink-faint) focus:outline-none focus:ring-2 focus:ring-(--accent) focus:border-transparent"
          />
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {folders.map(f => (
          <FolderRow
            key={f.id}
            folder={f}
            items={byFolder(f.id)}
            open={openFolders[f.id]}
            onToggle={() => setOpenFolders(o => ({ ...o, [f.id]: !o[f.id] }))}
            activeChatId={activeChatId}
            onSelectChat={onSelectChat}
            menuFor={menuFor}
            setMenuFor={setMenuFor}
            onMoveChat={onMoveChat}
            onDeleteChat={onDeleteChat}
            folders={folders}
            onRenameFolder={onRenameFolder}
            onDeleteFolder={onDeleteFolder}
          />
        ))}

        <button
          onClick={onCreateFolder}
          className="w-full h-8 mt-1 px-2 rounded-md text-left text-[12px] text-(--ink-muted) hover:bg-(--surface-2) hover:text-(--ink) inline-flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)"
        >
          <FolderPlus className="w-3.5 h-3.5" /> New folder
        </button>

        <div className="mt-3 space-y-3">
          {groups.map(g => g.items.length > 0 && (
            <div key={g.id}>
              <div className="px-2 h-6 flex items-center text-[11px] font-medium uppercase tracking-wide text-(--ink-faint)">
                {g.label}
              </div>
              <div className="space-y-0.5">
                {g.items.map(c => (
                  <ChatRow
                    key={c.id}
                    chat={c}
                    active={c.id === activeChatId}
                    onClick={() => onSelectChat(c.id)}
                    menuFor={menuFor}
                    setMenuFor={setMenuFor}
                    onMoveChat={onMoveChat}
                    onDeleteChat={onDeleteChat}
                    folders={folders}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </nav>

      <div className="p-3 border-t border-(--border) flex items-center justify-between">
        <button
          onClick={onOpenSettings}
          className="h-8 px-2 rounded-md text-[13px] text-(--ink-muted) hover:bg-(--surface-2) hover:text-(--ink) inline-flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)"
        >
          <SettingsIcon className="w-3.5 h-3.5" /> Settings
        </button>
        <LocalPill />
      </div>
    </aside>
  );
}

function FolderRow({
  folder, items, open, onToggle, activeChatId, onSelectChat,
  menuFor, setMenuFor, onMoveChat, onDeleteChat, folders, onRenameFolder, onDeleteFolder,
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(folder.name);
  const [folderMenu, setFolderMenu] = useState(false);

  return (
    <div>
      <div className="group flex items-center h-8 px-2 rounded-md hover:bg-(--surface-2)">
        <button onClick={onToggle} className="flex items-center gap-1.5 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) rounded">
          {open ? <ChevronDown className="w-3.5 h-3.5 text-(--ink-faint)" /> : <ChevronRight className="w-3.5 h-3.5 text-(--ink-faint)" />}
          {open ? <FolderOpen className="w-3.5 h-3.5 text-(--ink-muted)" /> : <Folder className="w-3.5 h-3.5 text-(--ink-muted)" />}
          {editing ? (
            <input
              autoFocus
              value={name}
              onChange={e => setName(e.target.value)}
              onBlur={() => { onRenameFolder(folder.id, name.trim() || folder.name); setEditing(false); }}
              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
              className="flex-1 min-w-0 bg-transparent text-[13px] text-(--ink) focus:outline-none"
              onClick={e => e.stopPropagation()}
            />
          ) : (
            <span className="text-[13px] text-(--ink) truncate">{folder.name}</span>
          )}
        </button>
        <div className="relative">
          <IconButton className="w-6 h-6 opacity-0 group-hover:opacity-100" onClick={(e) => { e.stopPropagation(); setFolderMenu(v => !v); }}>
            <MoreHorizontal className="w-3.5 h-3.5" />
          </IconButton>
          {folderMenu && (
            <Menu
              onClose={() => setFolderMenu(false)}
              items={[
                { label: "Rename", onClick: () => { setEditing(true); setFolderMenu(false); } },
                { label: "Delete folder", danger: true, onClick: () => { onDeleteFolder(folder.id); setFolderMenu(false); } },
              ]}
            />
          )}
        </div>
      </div>
      {open && (
        <div className="mt-0.5 space-y-0.5 pl-2">
          {items.length === 0 && (
            <div className="px-2 py-1 text-[12px] text-(--ink-faint)">Empty</div>
          )}
          {items.map(c => (
            <ChatRow
              key={c.id} chat={c} active={c.id === activeChatId}
              onClick={() => onSelectChat(c.id)}
              menuFor={menuFor} setMenuFor={setMenuFor}
              onMoveChat={onMoveChat} onDeleteChat={onDeleteChat} folders={folders}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ChatRow({ chat, active, onClick, menuFor, setMenuFor, onMoveChat, onDeleteChat, folders }) {
  return (
    <div className="group relative">
      <button
        onClick={onClick}
        className={cn(
          "w-full h-8 px-2 rounded-md text-left text-[13px] truncate flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)",
          active ? "bg-(--surface-2) text-(--ink)" : "text-(--ink) hover:bg-(--surface-2)"
        )}
      >
        <MessageSquare className="w-3.5 h-3.5 text-(--ink-faint) shrink-0" />
        <span className="truncate flex-1">{chat.title}</span>
      </button>
      <div className="absolute right-0 top-0 h-8 flex items-center">
        <IconButton
          className={cn("w-6 h-6", menuFor === chat.id ? "opacity-100" : "opacity-0 group-hover:opacity-100")}
          onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === chat.id ? null : chat.id); }}
        >
          <MoreHorizontal className="w-3.5 h-3.5" />
        </IconButton>
        {menuFor === chat.id && (
          <Menu
            onClose={() => setMenuFor(null)}
            items={[
              ...folders.map(f => ({
                label: f.name,
                icon: <Folder className="w-3.5 h-3.5" />,
                onClick: () => { onMoveChat(chat.id, chat.folder === f.id ? null : f.id); setMenuFor(null); },
              })),
              ...(folders.length > 0 ? [{ label: "Unfile", icon: <Move className="w-3.5 h-3.5" />, onClick: () => { onMoveChat(chat.id, null); setMenuFor(null); } }] : []),
              { label: "Delete", danger: true, icon: <Trash2 className="w-3.5 h-3.5" />, onClick: () => { onDeleteChat(chat.id); setMenuFor(null); } },
            ]}
          />
        )}
      </div>
    </div>
  );
}

function Menu({ items, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [onClose]);
  return (
    <div
      ref={ref}
      className="absolute right-0 top-8 z-40 min-w-[180px] rounded-lg border border-(--border) bg-(--surface) py-1 shadow-[0_1px_2px_rgba(28,25,22,.04),0_8px_24px_-8px_rgba(28,25,22,.10)]"
    >
      {items.map((it, i) => (
        <button
          key={i}
          onClick={it.onClick}
          className={cn(
            "w-full h-8 px-2.5 text-left text-[13px] inline-flex items-center gap-2 focus:outline-none focus-visible:bg-(--surface-2)",
            it.danger ? "text-(--err) hover:bg-(--surface-2)" : "text-(--ink) hover:bg-(--surface-2)"
          )}
        >
          {it.icon}
          <span>{it.label}</span>
        </button>
      ))}
    </div>
  );
}

function LocalPill() {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="h-7 px-2 rounded-full border border-(--border) bg-(--surface) inline-flex items-center gap-1.5 text-[11px] text-(--ink-muted) hover:bg-(--surface-2) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)"
        aria-label="Local status"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-(--ok)" />
        Local
      </button>
      {open && (
        <div className="absolute bottom-9 right-0 z-40 w-[240px] rounded-lg border border-(--border) bg-(--surface) p-3 text-[12px] shadow-[0_1px_2px_rgba(28,25,22,.04),0_8px_24px_-8px_rgba(28,25,22,.10)]">
          <div className="flex items-center gap-1.5 text-(--ink) font-medium">
            <ShieldCheck className="w-3.5 h-3.5 text-(--ok)" /> Running locally
          </div>
          <div className="mt-2 text-(--ink-muted) leading-relaxed">
            Active model: <span className="text-(--ink)">Qwen 2.5 14B</span><br/>
            Files, prompts, and outputs stay on this machine. Nothing is sent to a cloud service.
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Streaming text                                                     */
/* ------------------------------------------------------------------ */

function useStreamedText(text, active = true) {
  const rm = useReducedMotion();
  const [shown, setShown] = useState(active ? 0 : text.length);
  const lastText = useRef(text);

  useEffect(() => {
    if (text !== lastText.current) {
      lastText.current = text;
      setShown(active ? 0 : text.length);
    }
  }, [text, active]);

  useEffect(() => {
    if (rm || !active) { setShown(text.length); return; }
    if (shown >= text.length) return;
    const id = setTimeout(() => {
      setShown(n => Math.min(text.length, n + Math.max(1, Math.floor(text.length / 160))));
    }, 12);
    return () => clearTimeout(id);
  }, [shown, text, active, rm]);

  return { shown, done: shown >= text.length, slice: text.slice(0, shown) };
}

function StreamedText({ text, active = true }) {
  const { slice, done } = useStreamedText(text, active);
  return (
    <span>
      {slice}
      {!done && <span className="inline-block w-[2px] h-[1em] align-[-2px] ml-[1px] bg-(--accent) animate-pulse" />}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Chat                                                               */
/* ------------------------------------------------------------------ */

function MessageBubble({ msg, onOpenArtifact, active }) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[640px]">
          <div className="text-[14px] text-(--ink) leading-relaxed whitespace-pre-wrap">{msg.text}</div>
          {msg.files?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {msg.files.map((f, i) => (
                <span key={i} className="inline-flex items-center gap-1.5 h-7 px-2 rounded-md bg-(--surface-2) border border-(--border) text-[12px] text-(--ink-muted)">
                  <FileText className="w-3 h-3" /> {f.name} <span className="text-(--ink-faint)">Â· {f.size}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="w-6 h-6 rounded-md bg-(--surface-2) border border-(--border) flex items-center justify-center shrink-0 mt-0.5">
        <Sparkles className="w-3 h-3 text-(--accent)" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[14px] text-(--ink) leading-relaxed whitespace-pre-wrap">
          <StreamedText text={msg.text} active={active} />
        </div>
        {msg.artifacts?.length > 0 && (
          <div className="mt-4 space-y-2.5">
            {msg.artifacts.map(id => {
              const a = ARTIFACTS[id];
              if (!a) return null;
              return <ArtifactCard key={id} artifact={a} onOpen={() => onOpenArtifact(id)} />;
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState({ onChip, composer }) {
  const chips = [
    { label: "Summarize these files", prompt: "Summarize these files" },
    { label: "Turn a CSV into a dashboard", prompt: "Turn a CSV into a dashboard" },
    { label: "Draft a report", prompt: "Draft a report" },
  ];
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-[640px]">
        <h1 className="text-[22px] font-semibold tracking-tight text-(--ink)">What are we working on?</h1>
        <p className="mt-1.5 text-[14px] text-(--ink-muted) leading-relaxed">
          Drop a file or describe the task. Everything runs on your machine.
        </p>
        <div className="mt-6">{composer}</div>
        <div className="mt-4 flex flex-wrap gap-2">
          {chips.map(c => (
            <button
              key={c.label}
              onClick={() => onChip(c.prompt)}
              className="h-8 px-3 rounded-full border border-(--border) bg-(--surface) text-[12px] text-(--ink) hover:border-(--accent) hover:text-(--accent) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) transition-colors"
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function Composer({ onSend, disabled }) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState([]);
  const [web, setWeb] = useState(false);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef(null);

  const send = () => {
    const t = text.trim();
    if (!t && files.length === 0) return;
    onSend({ text: t, files: files.slice() });
    setText("");
    setFiles([]);
  };

  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const addFiles = (list) => {
    const arr = Array.from(list).map(f => ({ name: f.name, size: formatBytes(f.size) }));
    setFiles(prev => [...prev, ...arr]);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
      className={cn(
        "relative rounded-xl border bg-(--surface) transition-colors",
        drag ? "border-(--accent) bg-(--surface-2)" : "border-(--border)"
      )}
    >
      {drag && (
        <div className="absolute inset-0 rounded-xl pointer-events-none flex items-center justify-center">
          <div className="text-[13px] text-(--accent) font-medium">Drop files to attach</div>
        </div>
      )}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5 p-3 pb-0">
          {files.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 h-7 pl-2 pr-1 rounded-md bg-(--surface-2) border border-(--border) text-[12px] text-(--ink)">
              <FileText className="w-3 h-3 text-(--ink-muted)" />
              <span className="truncate max-w-[160px]">{f.name}</span>
              <span className="text-(--ink-faint)">Â· {f.size}</span>
              <button
                onClick={() => setFiles(fs => fs.filter((_, j) => j !== i))}
                className="w-5 h-5 rounded hover:bg-(--border) inline-flex items-center justify-center"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={onKey}
        rows={1}
        placeholder="Ask anything, or drop a file"
        className="w-full resize-none bg-transparent p-3 pb-1 text-[14px] text-(--ink) placeholder:text-(--ink-faint) focus:outline-none max-h-[240px]"
        style={{ minHeight: 44 }}
      />
      <div className="flex items-center justify-between px-2 pb-2">
        <div className="flex items-center gap-0.5">
          <IconButton onClick={() => fileRef.current?.click()} title="Attach files">
            <Paperclip className="w-4 h-4" />
          </IconButton>
          <input ref={fileRef} type="file" multiple className="hidden" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
          <button
            onClick={() => setWeb(v => !v)}
            className={cn(
              "h-8 px-2.5 rounded-md text-[12px] inline-flex items-center gap-1.5 border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)",
              web
                ? "bg-(--accent) text-(--accent-ink) border-(--accent)"
                : "bg-(--surface) text-(--ink-muted) border-(--border) hover:bg-(--surface-2)"
            )}
          >
            <Globe className="w-3.5 h-3.5" /> Web search
          </button>
        </div>
        <Button onClick={send} disabled={disabled || (!text.trim() && files.length === 0)}>
          <Send className="w-3.5 h-3.5" /> Send
        </Button>
      </div>
    </div>
  );
}

function formatBytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return Math.round(n / 1024) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

function ChatThread({ chat, onSend, onOpenArtifact }) {
  const scrollRef = useRef(null);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight }); }, [chat?.messages.length]);

  if (!chat) {
    return (
      <main className="flex-1 flex flex-col min-w-0">
        <EmptyState
          onChip={(p) => onSend({ text: p, files: [] })}
          composer={<Composer onSend={onSend} />}
        />
      </main>
    );
  }

  return (
    <main className="flex-1 flex flex-col min-w-0">
      <header className="h-12 border-b border-(--border) px-6 flex items-center justify-between">
        <div className="min-w-0">
          <div className="text-[14px] font-medium text-(--ink) truncate">{chat.title}</div>
          <div className="text-[11px] text-(--ink-faint)">
            {chat.folder ? FOLDERS.find(f => f.id === chat.folder)?.name ?? "" : "Unfiled"}
          </div>
        </div>
      </header>
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-[760px] mx-auto space-y-8">
          {chat.messages.map((m, i) => (
            <MessageBubble
              key={m.id}
              msg={m}
              onOpenArtifact={onOpenArtifact}
              active={i === chat.messages.length - 1 && m.role === "assistant"}
            />
          ))}
        </div>
      </div>
      <div className="border-t border-(--border) px-6 py-4">
        <div className="max-w-[760px] mx-auto">
          <Composer onSend={onSend} />
        </div>
      </div>
    </main>
  );
}

/* ------------------------------------------------------------------ */
/*  Artifacts                                                          */
/* ------------------------------------------------------------------ */

function ArtifactIcon({ type, className }) {
  const map = {
    pdf: FileCheck,
    dashboard: LayoutDashboard,
    chart: BarChart3,
    table: Table,
    markdown: FileText,
  };
  const I = map[type] || FileText;
  return <I className={className} />;
}

function ArtifactCard({ artifact, onOpen }) {
  const [expanded, setExpanded] = useState(true);
  const a = artifact;
  return (
    <div className="rounded-xl border border-(--border) bg-(--surface) overflow-hidden">
      <div className="h-11 px-3 flex items-center justify-between gap-2 border-b border-(--border)">
        <button
          onClick={() => setExpanded(v => !v)}
          className="flex items-center gap-2 min-w-0 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) rounded"
        >
          {expanded ? <ChevronDown className="w-3.5 h-3.5 text-(--ink-faint) shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-(--ink-faint) shrink-0" />}
          <ArtifactIcon type={a.type} className="w-3.5 h-3.5 text-(--accent) shrink-0" />
          <span className="text-[13px] font-medium text-(--ink) truncate">{a.title}</span>
          <span className="text-[11px] uppercase tracking-wide text-(--ink-faint)">{a.type}</span>
        </button>
        <IconButton onClick={onOpen} title="Open in side panel">
          <PanelRight className="w-4 h-4" />
        </IconButton>
      </div>
      {expanded && (
        <div className="p-3">
          <ArtifactPreview artifact={a} />
        </div>
      )}
    </div>
  );
}

function ArtifactPreview({ artifact }) {
  const a = artifact;
  if (a.type === "pdf") {
    return (
      <div className="aspect-[4/3] max-h-[220px] rounded-md bg-(--surface-2) border border-(--border) p-4 flex flex-col">
        <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">Proposal</div>
        <div className="mt-1 text-[13px] font-medium text-(--ink) leading-snug">{a.title}</div>
        <div className="mt-3 space-y-1.5">
          {[0, 1, 2, 3, 4].map(i => (
            <div key={i} className="h-1.5 rounded-full bg-(--border-strong)" style={{ width: `${88 - i * 10}%` }} />
          ))}
        </div>
        <div className="mt-auto text-[11px] text-(--ink-faint)">Page 1 of 3</div>
      </div>
    );
  }
  if (a.type === "dashboard") {
    return (
      <div className="grid grid-cols-4 gap-2">
        {a.body.kpis.map(k => (
          <div key={k.label} className="rounded-md bg-(--surface-2) border border-(--border) p-2.5">
            <div className="text-[10px] text-(--ink-faint) uppercase tracking-wide">{k.label}</div>
            <div className="mt-1 text-[15px] font-semibold text-(--ink) tabular-nums">{k.value}</div>
            <div className={cn("text-[10px] mt-0.5", k.positive ? "text-(--ok)" : "text-(--err)")}>{k.delta}</div>
          </div>
        ))}
      </div>
    );
  }
  if (a.type === "chart") {
    return (
      <div className="h-[160px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={a.body.series}>
            <XAxis dataKey="sku" tick={{ fontSize: 10, fill: "currentColor" }} stroke="var(--border)" />
            <YAxis tick={{ fontSize: 10, fill: "currentColor" }} stroke="var(--border)" />
            <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12, borderRadius: 8 }} />
            <Bar dataKey="onHand" fill="var(--accent)" radius={[3, 3, 0, 0]} />
            <Bar dataKey="projected" fill="var(--border-strong)" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }
  if (a.type === "table") {
    return (
      <div className="max-h-[180px] overflow-auto rounded-md border border-(--border)">
        <table className="w-full text-[12px]">
          <thead className="bg-(--surface-2) text-(--ink-muted)">
            <tr>{a.body.headers.map(h => <th key={h} className="text-left font-medium px-2.5 py-1.5">{h}</th>)}</tr>
          </thead>
          <tbody className="text-(--ink)">
            {a.body.rows.slice(0, 5).map((r, i) => (
              <tr key={i} className="border-t border-(--border)">
                {r.map((c, j) => <td key={j} className="px-2.5 py-1.5 tabular-nums">{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (a.type === "markdown") {
    return (
      <div className="text-[12px] text-(--ink) leading-relaxed max-h-[180px] overflow-auto space-y-2">
        {a.body.split("\
").slice(0, 8).map((l, i) => (
          <div key={i} className={l.startsWith("##") ? "font-medium text-[13px]" : "text-(--ink-muted)"}>{l || "\u00A0"}</div>
        ))}
        <div className="text-(--ink-faint) text-[11px]">â€¦ continued in side panel</div>
      </div>
    );
  }
  return null;
}

function ArtifactPanel({ artifact, onClose, width, onResizeStart }) {
  if (!artifact) return null;
  const a = artifact;
  return (
    <>
      {/* resize handle */}
      <div
        onMouseDown={onResizeStart}
        className="absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-(--accent)/30 active:bg-(--accent)/50 z-10"
      />
      <div className="h-full flex flex-col bg-(--bg)">
        <header className="h-12 border-b border-(--border) px-4 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <ArtifactIcon type={a.type} className="w-4 h-4 text-(--accent) shrink-0" />
            <div className="min-w-0">
              <div className="text-[13px] font-medium text-(--ink) truncate">{a.title}</div>
              <div className="text-[11px] text-(--ink-faint) uppercase tracking-wide">{a.type}</div>
            </div>
          </div>
          <div className="flex items-center gap-0.5">
            <IconButton title="Copy content"><Copy className="w-4 h-4" /></IconButton>
            <IconButton title="Download"><DownloadIcon className="w-4 h-4" /></IconButton>
            <IconButton onClick={onClose} title="Close panel"><X className="w-4 h-4" /></IconButton>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          <ArtifactFull artifact={a} />
        </div>
      </div>
    </>
  );
}

function ArtifactFull({ artifact }) {
  const a = artifact;

  if (a.type === "pdf") {
    return (
      <div className="max-w-[680px] mx-auto">
        <div className="rounded-xl border border-(--border) bg-(--surface) shadow-[0_1px_2px_rgba(28,25,22,.04),0_8px_24px_-8px_rgba(28,25,22,.10)] overflow-hidden">
          <div className="p-10">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">{a.body.from}</div>
                <div className="mt-0.5 text-[12px] text-(--ink-muted)">Prepared {a.body.prepared}</div>
              </div>
              <div className="text-right">
                <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">Prepared for</div>
                <div className="mt-0.5 text-[12px] text-(--ink)">{a.body.for}</div>
              </div>
            </div>
            <h1 className="mt-10 text-[22px] font-semibold tracking-tight text-(--ink) leading-tight">{a.title}</h1>
            {a.body.sections.map((s, i) => (
              <div key={i} className="mt-8">
                <h2 className="text-[15px] font-semibold text-(--ink)">{s.heading}</h2>
                {s.paragraphs.map((p, j) => (
                  <p key={j} className="mt-2 text-[13px] text-(--ink) leading-relaxed">{p}</p>
                ))}
                {s.table && (
                  <div className="mt-4 rounded-md border border-(--border) overflow-hidden">
                    <table className="w-full text-[12px]">
                      <thead className="bg-(--surface-2) text-(--ink-muted)">
                        <tr>{s.table.headers.map(h => <th key={h} className="text-left font-medium px-3 py-2">{h}</th>)}</tr>
                      </thead>
                      <tbody className="text-(--ink)">
                        {s.table.rows.map((r, j) => (
                          <tr key={j} className="border-t border-(--border)">
                            {r.map((c, k) => <td key={k} className="px-3 py-2">{c}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (a.type === "dashboard") {
    return (
      <div className="max-w-[880px] mx-auto space-y-5">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {a.body.kpis.map(k => (
            <div key={k.label} className="rounded-xl border border-(--border) bg-(--surface) p-4">
              <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">{k.label}</div>
              <div className="mt-1.5 text-[22px] font-semibold tracking-tight text-(--ink) tabular-nums">{k.value}</div>
              <div className={cn("text-[12px] mt-0.5", k.positive ? "text-(--ok)" : "text-(--err)")}>{k.delta}</div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="rounded-xl border border-(--border) bg-(--surface) p-4">
            <div className="text-[13px] font-medium text-(--ink)">Monthly recognized revenue</div>
            <div className="text-[11px] text-(--ink-muted)">Q2 2026, thousands USD</div>
            <div className="mt-4 h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={a.body.monthly}>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
                  <YAxis tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
                  <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12, borderRadius: 8 }} />
                  <Bar dataKey="revenue" fill="var(--accent)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="rounded-xl border border-(--border) bg-(--surface) p-4">
            <div className="text-[13px] font-medium text-(--ink)">New vs renewed</div>
            <div className="text-[11px] text-(--ink-muted)">By month, thousands USD</div>
            <div className="mt-4 h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={a.body.pipeline}>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
                  <YAxis tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
                  <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12, borderRadius: 8 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Area type="monotone" dataKey="renewed" stackId="1" stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.3} />
                  <Area type="monotone" dataKey="new" stackId="1" stroke="var(--ink-muted)" fill="var(--ink-muted)" fillOpacity={0.2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-(--border) bg-(--surface) overflow-hidden">
          <div className="px-4 py-3 border-b border-(--border) flex items-center justify-between">
            <div>
              <div className="text-[13px] font-medium text-(--ink)">Top customers</div>
              <div className="text-[11px] text-(--ink-muted)">Ranked by recognized revenue, Q2 2026</div>
            </div>
          </div>
          <table className="w-full text-[13px]">
            <thead className="bg-(--surface-2) text-(--ink-muted) text-[11px] uppercase tracking-wide">
              <tr>
                <th className="text-left font-medium px-4 py-2">Customer</th>
                <th className="text-left font-medium px-4 py-2">Segment</th>
                <th className="text-right font-medium px-4 py-2">Deals</th>
                <th className="text-right font-medium px-4 py-2">Revenue</th>
              </tr>
            </thead>
            <tbody className="text-(--ink)">
              {a.body.topCustomers.map((c, i) => (
                <tr key={i} className="border-t border-(--border)">
                  <td className="px-4 py-2.5">{c.customer}</td>
                  <td className="px-4 py-2.5 text-(--ink-muted)">{c.segment}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{c.deals}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">${(c.revenue / 1000).toFixed(1)}K</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (a.type === "chart") {
    return (
      <div className="max-w-[760px] mx-auto rounded-xl border border-(--border) bg-(--surface) p-5">
        <div className="text-[15px] font-medium text-(--ink)">{a.title}</div>
        <div className="text-[12px] text-(--ink-muted) mt-0.5">{a.summary}</div>
        <div className="mt-5 h-[340px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={a.body.series}>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis dataKey="sku" tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
              <YAxis tick={{ fontSize: 11, fill: "currentColor" }} stroke="var(--border)" />
              <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12, borderRadius: 8 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="onHand" name="On hand" fill="var(--accent)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="projected" name="Projected end" fill="var(--border-strong)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4 flex items-center gap-2 text-[12px] text-(--err)">
          <AlertTriangle className="w-3.5 h-3.5" />
          <span>Four SKUs are trending toward a stockout before the end of the month.</span>
        </div>
      </div>
    );
  }

  if (a.type === "table") {
    return (
      <div className="max-w-[880px] mx-auto rounded-xl border border-(--border) bg-(--surface) overflow-hidden">
        <div className="px-5 py-4 border-b border-(--border)">
          <div className="text-[15px] font-medium text-(--ink)">{a.title}</div>
          <div className="text-[12px] text-(--ink-muted) mt-0.5">{a.summary}</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="bg-(--surface-2) text-(--ink-muted) text-[11px] uppercase tracking-wide">
              <tr>{a.body.headers.map(h => <th key={h} className={cn("font-medium px-4 py-2.5", ["On hand", "30-day demand", "Projected end"].includes(h) ? "text-right" : "text-left")}>{h}</th>)}</tr>
            </thead>
            <tbody className="text-(--ink)">
              {a.body.rows.map((r, i) => (
                <tr key={i} className="border-t border-(--border)">
                  {r.map((c, j) => (
                    <td key={j} className={cn("px-4 py-2.5", j >= 1 && j <= 3 ? "text-right tabular-nums" : "")}>
                      {j === 4 && c.startsWith("Yes") ? (
                        <span className="inline-flex items-center gap-1.5 text-(--err)"><AlertTriangle className="w-3 h-3" /> {c}</span>
                      ) : j === 4 && c === "Watch" ? (
                        <span className="text-(--warn)">{c}</span>
                      ) : j === 4 ? (
                        <span className="text-(--ok)">{c}</span>
                      ) : c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (a.type === "markdown") {
    return (
      <div className="max-w-[680px] mx-auto rounded-xl border border-(--border) bg-(--surface) p-8">
        <article className="prose-custom">
          {a.body.split("\
").map((line, i) => {
            if (line.startsWith("## ")) return <h2 key={i} className="text-[17px] font-semibold text-(--ink) mt-6 mb-2 first:mt-0">{line.slice(3)}</h2>;
            if (line.startsWith("- **")) {
              const m = line.match(/^- \*\*(.+?)\*\* â€” (.+)$/);
              if (m) {
                return (
                  <div key={i} className="flex gap-2 py-1 text-[13px] text-(--ink) leading-relaxed">
                    <span className="text-(--ink-faint) shrink-0">â€”</span>
                    <span><span className="font-medium">{m[1]}</span> â€” {m[2]}</span>
                  </div>
                );
              }
            }
            if (line.startsWith("- ")) {
              return <div key={i} className="flex gap-2 py-0.5 text-[13px] text-(--ink) leading-relaxed"><span className="text-(--ink-faint) shrink-0">â€”</span><span>{line.slice(2)}</span></div>;
            }
            if (line.trim() === "") return <div key={i} className="h-2" />;
            return <p key={i} className="text-[13px] text-(--ink) leading-relaxed">{line}</p>;
          })}
        </article>
      </div>
    );
  }
  return null;
}

/* ------------------------------------------------------------------ */
/*  Settings                                                           */
/* ------------------------------------------------------------------ */

function SettingsView({ onClose, onRerunSetup, mode, setMode, setupMode }) {
  const [tab, setTab] = useState("models");
  const tabs = [
    { id: "models", label: "Models" },
    { id: "setup", label: "Setup" },
    { id: "appearance", label: "Appearance" },
    { id: "privacy", label: "Privacy" },
  ];

  return (
    <div className="fixed inset-0 z-50 bg-(--ink)/30 flex items-center justify-center p-6">
      <div className="w-full max-w-[820px] h-[620px] max-h-[90vh] rounded-xl bg-(--bg) border border-(--border) shadow-[0_1px_2px_rgba(28,25,22,.04),0_8px_24px_-8px_rgba(28,25,22,.10)] flex overflow-hidden">
        <div className="w-[180px] shrink-0 border-r border-(--border) p-3">
          <div className="px-2 pb-2 text-[11px] uppercase tracking-wide text-(--ink-faint) font-medium">Settings</div>
          <div className="space-y-0.5">
            {tabs.map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={cn(
                  "w-full h-8 px-2 rounded-md text-left text-[13px] focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)",
                  tab === t.id ? "bg-(--surface-2) text-(--ink) font-medium" : "text-(--ink-muted) hover:bg-(--surface-2)"
                )}
              >{t.label}</button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          {tab === "models" && <ModelsSettings />}
          {tab === "setup" && <SetupSettings onRerunSetup={onRerunSetup} setupMode={setupMode} />}
          {tab === "appearance" && <AppearanceSettings mode={mode} setMode={setMode} />}
          {tab === "privacy" && <PrivacySettings />}
        </div>
        <button onClick={onClose} className="absolute top-4 right-4"><IconButton><X className="w-4 h-4" /></IconButton></button>
      </div>
    </div>
  );
}

function ModelsSettings() {
  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Active models</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        These are the models running on your machine. The indicator shows whether each one fits your hardware.
      </p>
      <div className="mt-5 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {MODELS.filter(m => m.role !== "Not selected").map(m => (
          <div key={m.id} className="p-4 flex items-center justify-between gap-4">
            <div>
              <div className="text-[14px] font-medium text-(--ink)">{m.name}</div>
              <div className="mt-0.5 text-[12px] text-(--ink-muted)">{m.role} Â· {m.size}</div>
            </div>
            <FitBadge fit={m.fit} note={m.note} />
          </div>
        ))}
      </div>

      <h4 className="mt-8 text-[14px] font-medium text-(--ink)">Other models considered</h4>
      <div className="mt-3 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {MODELS.filter(m => m.role === "Not selected").map(m => (
          <div key={m.id} className="p-4 flex items-center justify-between gap-4">
            <div>
              <div className="text-[14px] font-medium text-(--ink)">{m.name}</div>
              <div className="mt-0.5 text-[12px] text-(--ink-muted)">{m.size}</div>
            </div>
            <FitBadge fit={m.fit} note={m.note} />
          </div>
        ))}
      </div>
    </div>
  );
}

function SetupSettings({ onRerunSetup, setupMode }) {
  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Setup</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        Current mode: <span className="text-(--ink) font-medium">{setupMode === "managed" ? "Set it up for me" : "Connect my own local server"}</span>.
      </p>
      <div className="mt-5 space-y-2">
        <Button variant="secondary" onClick={onRerunSetup}>
          <RefreshCw className="w-3.5 h-3.5" /> Switch setup mode
        </Button>
        <p className="text-[12px] text-(--ink-muted) leading-relaxed">
          Switching will re-run the setup flow. Your chat history and files stay on the machine.
        </p>
      </div>
    </div>
  );
}

function AppearanceSettings({ mode, setMode }) {
  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Appearance</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">Choose how the workspace looks. You can change this any time.</p>
      <div className="mt-5 inline-flex rounded-lg border border-(--border) bg-(--surface) p-1">
        {[
          { id: "light", label: "Light", icon: Sun },
          { id: "dark", label: "Dark", icon: Moon },
        ].map(o => {
          const I = o.icon;
          const active = mode === o.id;
          return (
            <button
              key={o.id}
              onClick={() => setMode(o.id)}
              className={cn(
                "h-9 px-3 rounded-md text-[13px] inline-flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)",
                active ? "bg-(--surface-2) text-(--ink) font-medium" : "text-(--ink-muted)"
              )}
            >
              <I className="w-3.5 h-3.5" /> {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function PrivacySettings() {
  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Privacy</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        A plain-language summary of where your data lives and what the app does with it.
      </p>
      <div className="mt-5 space-y-3">
        {[
          { label: "Where your files are stored", value: "On this machine, in your user folder" },
          { label: "Where prompts and outputs are stored", value: "On this machine only" },
          { label: "Cloud services used", value: "None. The app does not contact external servers." },
          { label: "Telemetry", value: "None collected" },
        ].map(r => (
          <div key={r.label} className="rounded-xl border border-(--border) bg-(--surface) p-4 flex items-start justify-between gap-4">
            <div className="text-[13px] text-(--ink-muted)">{r.label}</div>
            <div className="text-[13px] text-(--ink) text-right max-w-[60%]">{r.value}</div>
          </div>
        ))}
      </div>
      <div className="mt-5 p-4 rounded-xl border border-(--border) bg-(--surface-2) flex items-start gap-3">
        <ShieldCheck className="w-4 h-4 text-(--ok) shrink-0 mt-0.5" />
        <div className="text-[13px] text-(--ink) leading-relaxed">
          If you ever want to remove everything the app has stored, open the app menu and choose <span className="font-medium">Reset workspace</span>. This deletes all chats, files, and models from this machine.
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  App shell                                                          */
/* ------------------------------------------------------------------ */

export default function App() {
  const [firstRun, setFirstRun] = useState(true);
  const [setupMode, setSetupMode] = useState("managed");
  const [chats, setChats] = useState(initialChats);
  const [folders, setFolders] = useState(FOLDERS);
  const [activeChatId, setActiveChatId] = useState("c1");
  const [artifactId, setArtifactId] = useState(null);
  const [panelWidth, setPanelWidth] = useState(480);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const activeChat = chats.find(c => c.id === activeChatId) || null;
  const activeArtifact = artifactId ? ARTIFACTS[artifactId] : null;

  const handleNewChat = () => {
    const id = "c" + Date.now();
    setChats(prev => [{ id, title: "New chat", folder: null, group: "today", messages: [] }, ...prev]);
    setActiveChatId(id);
  };

  const handleSend = ({ text, files }) => {
    if (!text.trim() && files.length === 0) return;
    let chatId = activeChatId;
    if (!chatId || !chats.find(c => c.id === chatId)) {
      chatId = "c" + Date.now();
      setChats(prev => [{ id: chatId, title: text.slice(0, 48) || files[0]?.name || "New chat", folder: null, group: "today", messages: [] }, ...prev]);
    }
    const userMsg = { id: "u" + Date.now(), role: "user", text: text.trim(), files: files.length ? files : undefined };

    // Pick a realistic mock reply based on prompt content
    const reply = pickMockReply(text, files);
    const asstMsg = { id: "a" + Date.now(), role: "assistant", text: reply.text, artifacts: reply.artifacts };

    setChats(prev => prev.map(c => c.id === chatId ? {
      ...c,
      title: c.messages.length === 0 ? (text.slice(0, 48) || files[0]?.name || c.title) : c.title,
      messages: [...c.messages, userMsg, asstMsg],
    } : c));
    setActiveChatId(chatId);
  };

  const handleCreateFolder = () => {
    const id = "f" + Date.now();
    const name = "New folder";
    setFolders(prev => [...prev, { id, name }]);
  };
  const handleMoveChat = (chatId, folderId) => {
    setChats(prev => prev.map(c => c.id === chatId ? { ...c, folder: folderId } : c));
  };
  const handleDeleteChat = (chatId) => {
    setChats(prev => prev.filter(c => c.id !== chatId));
    if (activeChatId === chatId) setActiveChatId(null);
  };
  const handleRenameFolder = (fid, name) => {
    setFolders(prev => prev.map(f => f.id === fid ? { ...f, name } : f));
  };
  const handleDeleteFolder = (fid) => {
    setFolders(prev => prev.filter(f => f.id !== fid));
    setChats(prev => prev.map(c => c.folder === fid ? { ...c, folder: null } : c));
  };

  const onResizeStart = (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = panelWidth;
    const move = (ev) => {
      const delta = startX - ev.clientX;
      setPanelWidth(Math.max(320, Math.min(window.innerWidth * 0.6, startW + delta)));
    };
    const up = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  };

  if (firstRun) {
    return (
      <ThemeProvider>
        <SetupFlow onFinish={() => setFirstRun(false)} />
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider>
      <div className="h-screen w-screen flex bg-(--bg) text-(--ink) font-sans antialiased">
        <Sidebar
          chats={chats}
          folders={folders}
          activeChatId={activeChatId}
          onSelectChat={setActiveChatId}
          onNewChat={handleNewChat}
          onCreateFolder={handleCreateFolder}
          onMoveChat={handleMoveChat}
          onDeleteChat={handleDeleteChat}
          onRenameFolder={handleRenameFolder}
          onDeleteFolder={handleDeleteFolder}
          onOpenSettings={() => setSettingsOpen(true)}
        />

        <div className="flex-1 flex min-w-0">
          <ChatThread
            chat={activeChat}
            onSend={handleSend}
            onOpenArtifact={(id) => setArtifactId(id)}
          />
          {activeArtifact && (
            <div
              className="relative border-l border-(--border) shrink-0"
              style={{ width: panelWidth }}
            >
              <ArtifactPanel
                artifact={activeArtifact}
                onClose={() => setArtifactId(null)}
                width={panelWidth}
                onResizeStart={onResizeStart}
              />
            </div>
          )}
        </div>

        {settingsOpen && (
          <ThemeConsumerSetMode>
            <SettingsView
              onClose={() => setSettingsOpen(false)}
              onRerunSetup={() => { setSettingsOpen(false); setFirstRun(true); }}
              setupMode={setupMode}
            />
          </ThemeConsumerSetMode>
        )}
      </div>
    </ThemeProvider>
  );
}

/* Helper to bridge theme mode from Settings to ThemeProvider */
function ThemeConsumerSetMode({ children }) {
  return <ThemeSettingsBridge>{children}</ThemeSettingsBridge>;
}
function ThemeSettingsBridge({ children }) {
  // SettingsView reads setMode from ThemeCtx, so we just render children inside existing provider.
  // To make SettingsView receive mode/setMode props we wrap it in an injector.
  const { mode, setMode } = useTheme();
  // clone first child with injected props
  const child = React.Children.only(children);
  return React.cloneElement(child, { mode, setMode });
}

/* ------------------------------------------------------------------ */
/*  Mock reply picker                                                  */
/* ------------------------------------------------------------------ */

function pickMockReply(text, files) {
  const t = (text || "").toLowerCase();
  if (files.length > 0 && (t.includes("dashboard") || t.includes("csv") || t.includes("revenue") || t.includes("sales"))) {
    return { text: "I read the file and put together a dashboard with the key totals, a monthly trend, and the rows that matter most. Open it on the right to drill in.", artifacts: ["a-dashboard"] };
  }
  if (t.includes("proposal") || t.includes("contract") || t.includes("renewal")) {
    return { text: "I drafted a proposal you can send as a PDF. It leads with outcomes, lays out the options side by side, and ends with a clear next step.", artifacts: ["a-pdf"] };
  }
  if (t.includes("forecast") || t.includes("inventory") || t.includes("sku")) {
    return { text: "I ran the forecast and flagged the items that are trending toward a stockout. The chart shows the shape of it; the table gives you every SKU to work from.", artifacts: ["a-chart", "a-table"] };
  }
  if (t.includes("notes") || t.includes("transcript") || t.includes("meeting")) {
    return { text: "I turned the transcript into clean notes with owners and dates. Sensitive discussion is kept intact rather than summarized.", artifacts: ["a-markdown"] };
  }
  if (t.includes("chart") || t.includes("graph") || t.includes("plot")) {
    return { text: "Here's the chart. I used bars for the two series so the comparison reads quickly; let me know if a line would work better for your audience.", artifacts: ["a-chart"] };
  }
  if (t.includes("table") || t.includes("spreadsheet")) {
    return { text: "Here's the data as a table. Sortable columns, the flags I called out in the text are color-coded in the Reorder column.", artifacts: ["a-table"] };
  }
  if (t.includes("report")) {
    return { text: "I put together a short report. The opening summarizes the finding, the middle shows the supporting detail, and the close gives you a recommendation and a next step.", artifacts: ["a-pdf"] };
  }
  return {
    text: "Got it. I'll work from what you gave me and come back with a draft you can review. If there's a format you prefer â€” a report, a dashboard, a table â€” say the word and I'll shape it that way.",
    artifacts: [],
  };\