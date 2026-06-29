import { useEffect, useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import {
  type CatalogModel, type HardwareInfo, type ModelEndpointConfig,
  getHardware, getModelCatalog,
  saveAppSettings, saveModelEndpoint, testModelEndpoint,
} from '../lib/api'
import { useReducedMotion } from '../hooks/useReducedMotion'
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
  const [step, setStep] = useState(0)
  const [path, setPath] = useState<'managed' | 'byo' | null>(null)

  // managed flow
  const [hardware, setHardware] = useState<HardwareInfo | null>(null)
  const [hardwareDone, setHardwareDone] = useState(false)
  const [catalog, setCatalog] = useState<CatalogModel[]>([])
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

  // Fetch hardware when entering hardware step
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

  // Fetch catalog when entering recommend step
  useEffect(() => {
    if (step !== 2 || path !== 'managed') return
    getModelCatalog().then(setCatalog).catch(() => {})
  }, [step, path])

  // Simulated download progress
  useEffect(() => {
    if (step !== 3 || path !== 'managed' || downloadDone) return
    const selected = catalog.filter(m => m.fit === 'ok').map(m => m.id)
    if (selected.length === 0) { setDownloadDone(true); return }
    const id = setInterval(() => {
      setDownloadProgress(prev => {
        const next = { ...prev }
        let allDone = true
        for (const mid of selected) {
          const cur = prev[mid] ?? 0
          if (cur < 100) {
            next[mid] = Math.min(100, cur + (rm ? 100 : Math.random() * 9 + 3))
            allDone = false
          }
        }
        if (allDone) setDownloadDone(true)
        return next
      })
    }, rm ? 20 : 350)
    return () => clearInterval(id)
  }, [step, path, downloadDone, catalog, rm])

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

  const handleManagedFinish = async () => {
    const activeModels = catalog.filter(m => m.fit === 'ok').map(m => m.id)
    await saveAppSettings({ setup_complete: true, setup_mode: 'managed', theme: 'system', active_models: activeModels })
      .catch(() => {})
    onFinish()
  }

  const handleByoFinish = async () => {
    await saveModelEndpoint({
      provider: 'openai_compatible',
      base_url: baseUrl,
      api_key: apiKey,
      models: { main_reasoner: roles.reasoner, summarizer: roles.summarizer, utility: roles.utility },
    }).catch(() => {})
    await saveAppSettings({ setup_complete: true, setup_mode: 'byo', theme: 'system', active_models: [] })
      .catch(() => {})
    onFinish()
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-(--bg) px-6 py-12">
      <div className="w-full max-w-[640px]">
        <div className="mb-8 flex items-center gap-2 text-[12px] text-(--ink-faint) tracking-wide uppercase">
          <ShieldCheck className="w-3.5 h-3.5" /> Local-first workspace
        </div>

        {step === 0 && (
          <WelcomeStep onChoose={p => { setPath(p); setStep(1) }} />
        )}

        {step === 1 && path === 'managed' && (
          <HardwareStep
            hardware={hardware}
            done={hardwareDone}
            onNext={() => setStep(2)}
            onBack={() => setStep(0)}
          />
        )}

        {step === 2 && path === 'managed' && (
          <RecommendStep
            catalog={catalog}
            onNext={() => setStep(3)}
            onBack={() => setStep(1)}
          />
        )}

        {step === 3 && path === 'managed' && (
          <DownloadStep
            models={catalog}
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
