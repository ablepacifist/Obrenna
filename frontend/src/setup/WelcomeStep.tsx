import { ArrowRight, Cpu, Server } from 'lucide-react'

interface WelcomeStepProps {
  onChoose: (path: 'managed' | 'byo') => void
  isDesktop?: boolean
  ollamaFound?: boolean | null
}

export function WelcomeStep({ onChoose, isDesktop, ollamaFound }: WelcomeStepProps) {
  return (
    <div>
      <h1 className="text-[28px] font-semibold tracking-tight text-(--ink) leading-tight">
        Set up your workspace
      </h1>
      <p className="mt-3 text-[14px] text-(--ink-muted) leading-relaxed max-w-[520px]">
        Everything you do here runs on your own machine. Nothing you ask, upload, or generate leaves
        this computer unless you share it yourself. Pick the setup that matches how you want to work.
      </p>

      <div className="mt-8 grid gap-3">
        <button
          onClick={() => onChoose('managed')}
          className="group text-left p-5 rounded-xl border border-(--border) bg-(--surface) hover:border-(--accent) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) transition-colors"
        >
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-(--surface-2) border border-(--border) flex items-center justify-center">
                <Cpu className="w-4 h-4 text-(--accent)" />
              </div>
              <div>
                <div className="text-[15px] font-medium text-(--ink)">Set it up for me</div>
                <div className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
                  {isDesktop
                    ? 'We\'ll check your hardware and set up the right models locally.'
                    : 'We\'ll check what your machine can handle and install the right models automatically.'}
                </div>
              </div>
            </div>
            <ArrowRight className="w-4 h-4 text-(--ink-faint) group-hover:text-(--accent) transition-colors mt-1" />
          </div>
        </button>

        <button
          onClick={() => onChoose('byo')}
          className="group text-left p-5 rounded-xl border border-(--border) bg-(--surface) hover:border-(--accent) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) transition-colors"
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
  )
}
