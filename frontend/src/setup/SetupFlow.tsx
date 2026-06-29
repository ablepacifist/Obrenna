import { useEffect, useState } from 'react'
import { FolderOpen, ShieldCheck } from 'lucide-react'
import {
  type HardwareInfo, type ManagedPlan, type ModelEndpointConfig, type CatalogModel,
  getHardware, getManagedPlan, saveAppSettings, saveModelEndpoint, testModelEndpoint,
} from '../lib/api'
import { useReducedMotion } from '../hooks/useReducedMotion'
import { useIsDesktop } from '../hooks/useIsDesktop'
import { getDataDir } from '../lib/tauri'
import { WelcomeStep } from './WelcomeStep'
import { HardwareStep } from './HardwareStep'
import { RecommendStep } from './RecommendStep'
import { DownloadStep } from './DownloadStep'
import { ByoStep } from './ByoStep'

interface SetupFlowProps {
  onFinish: () => void
}

export function SetupFlow({ onFinish }: SetupFlowProps) {
  const rm = useReducedMotion()
  const isDesktop = useIsDesktop()
  const [step, setStep] = useState(0)
  const [path, setPath] = useState<'managed' | 'byo' | null>(null)
  const [dataDir, setDataDir] = useState('')
  const [ollamaFound, setOllamaFound] = useState<boolean | null>(null)

  // managed flow
  const [hardware, setHardware] = useState<HardwareInfo | null>(null)
  const [hardwareDone, setHardwareDone] = useState(false)
  const [plan, setPlan] = useState<ManagedPlan | null>(null)
  const [planConfirmed, setPlanConfirmed] = useState(false)
  const [catalog] = useState<CatalogModel[]>([])
  const [downloadProgress, setDownloadProgress] = useState<Record<string, number>>({})
  const [downloadDone, setDownloadDone] = useState(false)

  // byo flow
  const [provider, setProvider] = useState('Ollama')
  const [baseUrl, setBaseUrl] = useState('http://localhost:11434/v1')
  const [apiKey, setApiKey] = useState('')
  const [roles, setRoles] = useState<Record<string, string>>({
    reasoner: 'llama3.1:8b',
    summarizer: 'phi3.5',
    utility: 'llama3.2:3b',
  })
  const [testState, setTestState] = useState<'idle' | 'testing' | 'success' | 'failure'>('idle')
  const [latencyMs, setLatencyMs] = useState<number | undefined>()

  // Desktop: load data dir and check for Ollama on mount
  useEffect(() => {
    if (!isDesktop) return
    getDataDir().then(d => setDataDir(d)).catch(() => {})
    fetch('http://localhost:11434/api/tags')
      .then(r => r.ok ? setOllamaFound(true) : setOllamaFound(false))
      .catch(() => setOllamaFound(false))
  }, [isDesktop])

  const handleOpenDataDir = async () => {
    const { openDataDir } = await import('../lib/tauri')
    await openDataDir().catch(() => {})
  }

  // Fetch hardware when entering managed hardware step
  useEffect(() => {
    if (step !== 1 || path !== 'managed') return
    getHardware()
      .then(hw => {
        setHardware(hw)
        const delay = rm ? 50 : 1400
        setTimeout(() => setHardwareDone(true), delay)
      })
      .catch(() => setHardwareDone(true))
  }, [step, path, rm])

  // Fetch managed plan when hardware is done
  useEffect(() => {
    if (step !== 1 || path !== 'managed' || !hardwareDone) return
    setPlanConfirmed(false)
    getManagedPlan()
      .then(p => {
        setPlan(p)
        // If the plan routes to BYO, skip recommend step and go to BYO
        if (p.recommended_setup_mode === 'byo') {
          setPath('byo')
          setStep(1)
        }
      })
      .catch(() => {})
  }, [step, path, hardwareDone])

  // Simulated download progress
  useEffect(() => {
    if (step !== 3 || path !== 'managed' || downloadDone) return
    if (!plan) { setDownloadDone(true); return }
    const selected = [
      { id: plan.orchestrator?.model || 'orchestrator' },
      ...(plan.summarizer ? [{ id: plan.summarizer.model }] : []),
      ...(plan.utility ? [{ id: plan.utility.model }] : []),
    ]
    const id = setInterval(() => {
      setDownloadProgress(prev => {
        const next = { ...prev }
        let allDone = true
        for (const m of selected) {
          const cur = prev[m.id] ?? 0
          if (cur < 100) {
            next[m.id] = Math.min(100, cur + (rm ? 100 : Math.random() * 9 + 3))
            allDone = false
          }
        }
        if (allDone) setDownloadDone(true)
        return next
      })
    }, rm ? 20 : 350)
    return () => clearInterval(id)
  }, [step, path, downloadDone, plan, rm])

  const runTest = async () => {
    setTestState('testing')
    try {
      const cfg: ModelEndpointConfig = {
        provider: 'openai_compatible',
        base_url: baseUrl,
        api_key: apiKey,
        models: { main_reasoner: roles.reasoner, summarizer: roles.summarizer, utility: roles.utility },
      }
      const result = await testModelEndpoint(cfg)
      setLatencyMs(result.latency_ms)
      setTestState(result.ok ? 'success' : 'failure')
    } catch {
      setTestState('failure')
    }
  }

  const handlePlanConfirm = async () => {
    if (!plan) return
    // Save the managed plan to app settings
    const activeModels: string[] = []
    if (plan.orchestrator) activeModels.push(plan.orchestrator.model)
    if (plan.summarizer) activeModels.push(plan.summarizer.model)
    if (plan.utility) activeModels.push(plan.utility.model)

    await saveAppSettings({
      setup_complete: true,
      setup_mode: plan.recommended_setup_mode === 'managed' ? 'managed' : 'byo',
      theme: 'system',
      active_models: activeModels,
      managed_plan: { ...plan },
    }).catch(() => {})

    setPlanConfirmed(true)
  }

  const handleManagedFinish = async () => {
    await saveAppSettings({
      setup_complete: true,
      setup_mode: 'managed',
      theme: 'system',
      active_models: [],
      managed_plan: {},
    }).catch(() => {})
    onFinish()
  }

  const handleByoFinish = async () => {
    await saveModelEndpoint({
      provider: 'openai_compatible',
      base_url: baseUrl,
      api_key: apiKey,
      models: { main_reasoner: roles.reasoner, summarizer: roles.summarizer, utility: roles.utility },
    }).catch(() => {})
    await saveAppSettings({
      setup_complete: true,
      setup_mode: 'byo',
      theme: 'system',
      active_models: [],
      managed_plan: {},
    }).catch(() => {})
    onFinish()
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-(--bg) px-6 py-12">
      <div className="w-full max-w-[640px]">
        <div className="mb-8 flex items-center gap-2 text-[12px] text-(--ink-faint) tracking-wide uppercase">
          <ShieldCheck className="w-3.5 h-3.5" /> Local-first workspace
        </div>

        {isDesktop && step === 0 && (
          <div className="mb-6 flex items-center justify-between text-[12px] text-(--ink-faint) bg-(--surface) border border-(--border) rounded-lg px-3 py-2">
            <span className="truncate">{dataDir || 'Loading data directory…'}</span>
            <button onClick={handleOpenDataDir} className="ml-2 inline-flex items-center gap-1 hover:text-(--accent) transition-colors">
              <FolderOpen className="w-3 h-3" /> Open folder
            </button>
          </div>
        )}

        {isDesktop && step === 0 && ollamaFound === true && (
          <div className="mb-4 text-[12px] text-(--ok) bg-(--ok)/5 border border-(--ok)/20 rounded-lg px-3 py-2">
            Local Ollama server detected at localhost:11434
          </div>
        )}

        {step === 0 && (
          <WelcomeStep
            onChoose={p => { setPath(p); setStep(1) }}
            isDesktop={isDesktop}
          />
        )}

        {step === 1 && path === 'managed' && (
          <HardwareStep
            hardware={hardware}
            done={hardwareDone}
            plan={plan}
            onNext={() => setStep(2)}
            onBack={() => setStep(0)}
          />
        )}

        {step === 2 && path === 'managed' && plan && (
          <RecommendStep
            plan={plan}
            onNext={() => setStep(3)}
            onBack={() => setStep(1)}
            onConfirm={handlePlanConfirm}
            confirmed={planConfirmed}
          />
        )}

        {step === 3 && path === 'managed' && (
          <DownloadStep
            models={plan ? [
              { id: plan.orchestrator?.model || 'orchestrator', name: plan.orchestrator?.model || 'Orchestrator', role: 'Orchestrator', size: `${plan.orchestrator?.quant} ~2GB`, size_gb: 2, fit: 'ok' as const, note: '' },
              ...(plan.summarizer ? [{ id: plan.summarizer.model, name: plan.summarizer.model, role: 'Summarizer', size: `${plan.summarizer.quant} ~2GB`, size_gb: 2, fit: 'ok' as const, note: '' }] : []),
              ...(plan.utility ? [{ id: plan.utility.model, name: plan.utility.model, role: 'Utility', size: `${plan.utility.quant} ~1GB`, size_gb: 1, fit: 'ok' as const, note: '' }] : []),
            ] : catalog}
            progress={downloadProgress}
            done={downloadDone}
            onFinish={handleManagedFinish}
            onBack={() => setStep(2)}
          />
        )}

        {step === 1 && path === 'byo' && (
          <ByoStep
            provider={provider} setProvider={setProvider}
            baseUrl={baseUrl} setBaseUrl={setBaseUrl}
            apiKey={apiKey} setApiKey={setApiKey}
            roles={roles} setRoles={setRoles}
            testState={testState} latencyMs={latencyMs}
            runTest={runTest}
            onFinish={handleByoFinish}
            onBack={() => setStep(0)}
          />
        )}
      </div>
    </div>
  )
}
