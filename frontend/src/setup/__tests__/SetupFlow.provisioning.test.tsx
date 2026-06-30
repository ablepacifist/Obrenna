import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { SetupFlow } from '../SetupFlow'

vi.mock('../../hooks/useReducedMotion', () => ({
  useReducedMotion: () => true,
}))

vi.mock('../../hooks/useIsDesktop', () => ({
  useIsDesktop: () => false,
}))

vi.mock('../../lib/tauri', () => ({
  getDataDir: async () => '',
}))

vi.mock('../WelcomeStep', () => ({
  WelcomeStep: ({ onChoose }: { onChoose: (p: 'managed' | 'byo') => void }) => (
    <button onClick={() => onChoose('managed')}>choose-managed</button>
  ),
}))

vi.mock('../HardwareStep', () => ({
  HardwareStep: ({ onNext }: { onNext: () => void }) => (
    <button onClick={onNext}>hardware-next</button>
  ),
}))

vi.mock('../RecommendStep', () => ({
  RecommendStep: ({ onConfirm, onNext }: { onConfirm: () => void; onNext: () => void }) => (
    <>
      <button onClick={onConfirm}>confirm-plan</button>
      <button onClick={onNext}>recommend-next</button>
    </>
  ),
}))

vi.mock('../DownloadStep', () => ({
  DownloadStep: ({ done }: { done: boolean }) => (
    <div data-testid="download-step" data-done={String(done)} />
  ),
}))

const confirmManagedPlan = vi.fn()
const getManagedPlan = vi.fn()
const getProvisioningJob = vi.fn()
const getProvisioningEventsUrl = vi.fn()

vi.mock('../../lib/api', () => ({
  getHardware: async () => ({ os: 'windows', cpu: 'amd', recommended_profile: 'local', gpu: [] }),
  getManagedPlan: (...args: unknown[]) => getManagedPlan(...args),
  confirmManagedPlan: (...args: unknown[]) => confirmManagedPlan(...args),
  getProvisioningJob: (...args: unknown[]) => getProvisioningJob(...args),
  getProvisioningEventsUrl: (...args: unknown[]) => getProvisioningEventsUrl(...args),
  retryProvisioningJob: async () => ({ ok: true, job_id: 'job-1', status: 'queued', retried: 1 }),
  saveAppSettings: async () => ({ setup_complete: true, setup_mode: 'managed', theme: 'system', active_models: [], managed_plan: {} }),
  saveModelEndpoint: async () => ({ provider: 'openai_compatible', base_url: 'http://localhost:11434/v1', api_key: '', models: {} }),
  testModelEndpoint: async () => ({ ok: true, models: [], latency_ms: 5 }),
}))

class MockEventSource {
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null
  addEventListener() {}
  close() {}
}

beforeEach(() => {
  ;(globalThis as unknown as { EventSource: typeof EventSource }).EventSource = MockEventSource as unknown as typeof EventSource
  getManagedPlan.mockResolvedValue({
    path: 'gpu',
    plan_id: 'T0-subfloor',
    helper_count: 1,
    fingerprint_hash: 'fp',
    runtime_priority: [],
    runtime_forbidden: [],
    required_launch_flags: [],
    recommended_setup_mode: 'managed',
    action: 'proceed_managed',
    detection_warnings: [],
    orchestrator: { model: 'qwen3.5-0.8b-claude-opus-reasoning-distilled', quant: 'Q4_K_M', device: 'gpu' },
    summarizer: { model: 'granite-4.0-h-350m', quant: 'Q4_K_M', device: 'cpu' },
    utility: { model: 'granite-4.0-h-350m', quant: 'IQ3_XXS', device: 'cpu' },
    validation_stubbed: true,
  })
  confirmManagedPlan.mockResolvedValue({
    confirmed: true,
    job_id: 'job-1',
    status: 'queued',
    runtime_kind: 'ollama',
    supports_pull: true,
    supports_streaming_progress: true,
    reused: false,
    plan: {
      path: 'gpu',
      plan_id: 'T0-subfloor',
      helper_count: 1,
      fingerprint_hash: 'fp',
      runtime_priority: [],
      runtime_forbidden: [],
      required_launch_flags: [],
      recommended_setup_mode: 'managed',
      action: 'proceed_managed',
      detection_warnings: [],
      orchestrator: { model: 'qwen3.5-0.8b-claude-opus-reasoning-distilled', quant: 'Q4_K_M', device: 'gpu' },
      summarizer: { model: 'granite-4.0-h-350m', quant: 'Q4_K_M', device: 'cpu' },
      utility: { model: 'granite-4.0-h-350m', quant: 'IQ3_XXS', device: 'cpu' },
      validation_stubbed: true,
    },
  })
  getProvisioningJob.mockResolvedValue({
    id: 'job-1',
    fingerprint_hash: 'fp',
    runtime_kind: 'ollama',
    status: 'complete',
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    items: [
      {
        id: 'it-1',
        role: 'orchestrator',
        model_slug: 'qwen3.5-0.8b-claude-opus-reasoning-distilled',
        quant: 'Q4_K_M',
        status: 'ready',
        progress_pct: 100,
        bytes_downloaded: 10,
        bytes_total: 10,
        updated_at: new Date().toISOString(),
      },
    ],
  })
  getProvisioningEventsUrl.mockResolvedValue('http://localhost:8000/api/setup/provisioning/job-1/events')
})

describe('SetupFlow provisioning', () => {
  it('confirms plan and reaches real download step state', async () => {
    render(<SetupFlow onFinish={() => {}} />)

    fireEvent.click(screen.getByText('choose-managed'))
    await waitFor(() => {
      expect(getManagedPlan).toHaveBeenCalledTimes(1)
    })
    fireEvent.click(await screen.findByText('hardware-next'))

    const confirmBtn = await screen.findByText('confirm-plan')
    fireEvent.click(confirmBtn)
    fireEvent.click(screen.getByText('recommend-next'))

    await waitFor(() => {
      expect(confirmManagedPlan).toHaveBeenCalledTimes(1)
      expect(getProvisioningJob).toHaveBeenCalledWith('job-1')
      expect(screen.getByTestId('download-step')).toHaveAttribute('data-done', 'true')
    })
  })
})
