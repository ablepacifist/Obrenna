import { Check, Link2, RefreshCw, WifiOff } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { StepCounter } from '../components/ui/StepCounter'

const PROVIDERS = ['Ollama', 'LM Studio', 'llama.cpp', 'OpenAI-compatible']

interface ByoStepProps {
  provider: string
  setProvider: (v: string) => void
  baseUrl: string
  setBaseUrl: (v: string) => void
  apiKey: string
  setApiKey: (v: string) => void
  roles: Record<string, string>
  setRoles: (v: Record<string, string>) => void
  testState: 'idle' | 'testing' | 'success' | 'failure'
  latencyMs?: number
  runTest: () => void
  onFinish: () => void
  onBack: () => void
}

const fieldCls =
  'w-full h-9 px-3 rounded-md bg-(--surface) border border-(--border) text-[13px] text-(--ink) placeholder:text-(--ink-faint) focus:outline-none focus:ring-2 focus:ring-(--accent) focus:border-transparent'
const labelCls = 'block text-[12px] font-medium text-(--ink-muted) mb-1.5'

export function ByoStep({
  provider, setProvider, baseUrl, setBaseUrl, apiKey, setApiKey,
  roles, setRoles, testState, latencyMs, runTest, onFinish, onBack,
}: ByoStepProps) {
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
              ['reasoner', 'Main reasoner'],
              ['summarizer', 'Summarizer'],
              ['utility', 'Utility'],
            ].map(([k, label]) => (
              <div key={k}>
                <div className="text-[11px] text-(--ink-faint) mb-1">{label}</div>
                <input
                  value={roles[k] ?? ''}
                  onChange={e => setRoles({ ...roles, [k]: e.target.value })}
                  placeholder="model name"
                  className={fieldCls}
                />
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <Button variant="secondary" onClick={runTest} disabled={testState === 'testing'}>
            {testState === 'testing' ? (
              <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Testing connection…</>
            ) : (
              <><Link2 className="w-3.5 h-3.5" /> Test connection</>
            )}
          </Button>

          {testState === 'success' && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-(--ok)">
              <Check className="w-3.5 h-3.5" strokeWidth={2.5} />
              Connected{latencyMs ? `. Server responded in ${latencyMs} ms.` : '.'}
            </span>
          )}
          {testState === 'failure' && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-(--err)">
              <WifiOff className="w-3.5 h-3.5" /> Couldn't reach the server. Check the URL and try again.
            </span>
          )}
        </div>
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={onFinish} disabled={testState !== 'success'}>Save and continue</Button>
      </div>
    </div>
  )
}
