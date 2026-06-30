import { useEffect, useState } from 'react'
import { FolderOpen, ShieldCheck } from 'lucide-react'
import {
  type HardwareInfo, type ManagedPlan, type ModelEndpointConfig, type CatalogModel,
  confirmManagedPlan,
  getHardware,
  getManagedPlan,
  getModelCatalog,
  getProvisioningEventsUrl,
  getProvisioningJob,
  retryProvisioningJob,
  saveAppSettings,
  saveModelEndpoint,
  testModelEndpoint,
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
  const [catalog, setCatalog] = useState<CatalogModel[]>([])
  const [downloadProgress, setDownloadProgress] = useState<Record<string, number>>({})
  const [downloadStatus, setDownloadStatus] = useState<Record<string, string>>({})
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [downloadDone, setDownloadDone] = useState(false)
  const [provisionJobId, setProvisionJobId] = useState<string | null>(null)

  useEffect(() => {
    getModelCatalog()
      .then(setCatalog)
      .catch(() => setCatalog([]))
  }, [])

  // byo flow
  const [provider, setProvider] = useState('Ollama')
  const [baseUrl, setBaseUrl] = useState('http://localhost:11434/v1')
  const [apiKey, setApiKey] = useState('')
  const [roles, setRoles] = useState<Record<string, string>>({
    reasoner: 'qwen3.5-9b-claude-opus-reasoning-distilled',
    summarizer: 'granite4.0-h-micro-3b',
    utility: 'qwen3.5-0.8b',
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

  // Managed provisioning progress via SSE (with polling fallback)
  useEffect(() => {
    if (step !== 3 || path !== 'managed' || !provisionJobId) return

    let cancelled = false
    let es: EventSource | null = null
    let pollTimer: number | undefined

    const applySnapshot = (snapshot: Awaited<ReturnType<typeof getProvisioningJob>>) => {
      if (cancelled) return
      const progress: Record<string, number> = {}
      const status: Record<string, string> = {}
      for (const item of snapshot.items) {
        progress[item.model_slug] = item.progress_pct ?? 0
        status[item.model_slug] = item.status
      }
      setDownloadProgress(progress)
      setDownloadStatus(status)
      if (snapshot.status === 'complete') {
        setDownloadDone(true)
        setDownloadError(null)
      } else if (snapshot.status === 'partial_failed' || snapshot.status === 'failed') {
        setDownloadDone(false)
        setDownloadError(snapshot.error_message || 'One or more models failed to provision.')
      }
    }

    const startPolling = () => {
      if (pollTimer) return
      pollTimer = window.setInterval(async () => {
        try {
          const snapshot = await getProvisioningJob(provisionJobId)
          applySnapshot(snapshot)
          if (snapshot.status === 'complete' || snapshot.status === 'partial_failed' || snapshot.status === 'failed') {
            if (pollTimer) {
              window.clearInterval(pollTimer)
              pollTimer = undefined
            }
          }
        } catch {
          // keep polling
        }
      }, 1500)
    }

    ;(async () => {
      try {
        const snapshot = await getProvisioningJob(provisionJobId)
        applySnapshot(snapshot)
      } catch {
        // handled by fallback polling
      }

      try {
        const url = await getProvisioningEventsUrl(provisionJobId)
        es = new EventSource(url)

        const onEvent = (evt: MessageEvent) => {
          if (cancelled) return
          try {
            const wrapped = JSON.parse(evt.data) as { event?: string; payload?: Record<string, unknown> }
            const payload = wrapped.payload || {}
            const modelSlug = String(payload.model_slug || '')
            const modelStatus = String(payload.status || '')
            const pct = Number(payload.progress_pct ?? 0)

            if (modelSlug) {
              if (!Number.isNaN(pct)) {
                setDownloadProgress(prev => ({ ...prev, [modelSlug]: Math.max(0, Math.min(100, Math.round(pct))) }))
              }
              if (modelStatus) {
                setDownloadStatus(prev => ({ ...prev, [modelSlug]: modelStatus }))
              }
            }

            if (wrapped.event === 'job_status') {
              if (modelStatus === 'complete') {
                setDownloadDone(true)
                setDownloadError(null)
                es?.close()
              }
              if (modelStatus === 'partial_failed' || modelStatus === 'failed') {
                setDownloadDone(false)
                setDownloadError(String(payload.error || 'One or more models failed to provision.'))
                es?.close()
              }
            }
          } catch {
            // ignore malformed event
          }
        }

        es.addEventListener('model_progress', onEvent)
        es.addEventListener('model_ready', onEvent)
        es.addEventListener('model_failed', onEvent)
        es.addEventListener('job_status', onEvent)
        es.onerror = () => {
          es?.close()
          startPolling()
        }
      } catch {
        startPolling()
      }
    })()

    return () => {
      cancelled = true
      es?.close()
      if (pollTimer) {
        window.clearInterval(pollTimer)
      }
    }
  }, [step, path, provisionJobId])

  const runTest = async () => {
    setTestState('testing')
    try {
      const cfg: ModelEndpointConfig = {
        provider: 'openai_compatible',
        base_url: baseUrl,
        api_key: apiKey,
        models: { orchestrator: roles.reasoner, summarizer: roles.summarizer, utility: roles.utility },
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
    setDownloadDone(false)
    setDownloadError(null)
    setDownloadProgress({})
    setDownloadStatus({})

    const result = await confirmManagedPlan()
    setPlan(result.plan)
    setProvisionJobId(result.job_id)
    setPlanConfirmed(true)
  }

  const handleManagedFinish = async () => {
    const orchestratorModel = plan?.orchestrator?.model || ''
    const summarizerModel = plan?.summarizer?.model || ''
    const utilityModel = plan?.utility?.model || ''
    await saveModelEndpoint({
      provider: 'openai_compatible',
      base_url: 'http://localhost:11434/v1',
      api_key: '',
      models: { orchestrator: orchestratorModel, summarizer: summarizerModel, utility: utilityModel },
    }).catch(() => {})
    onFinish()
  }

  const handleRetryDownload = async () => {
    if (!provisionJobId) return
    setDownloadError(null)
    setDownloadDone(false)
    await retryProvisioningJob(provisionJobId).catch(() => {})
  }

  const handleByoFinish = async () => {
    await saveModelEndpoint({
      provider: 'openai_compatible',
      base_url: baseUrl,
      api_key: apiKey,
      models: { orchestrator: roles.reasoner, summarizer: roles.summarizer, utility: roles.utility },
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
            status={downloadStatus}
            error={downloadError}
            done={downloadDone}
            onRetry={handleRetryDownload}
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
