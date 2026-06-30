import { useEffect, useState } from 'react'
import { ThemeProvider } from './theme/ThemeProvider'
import { ToastProvider } from './components/ui/Toast'
import { AnimationPreferenceProvider } from './context/AnimationPreferenceContext'
import { getAppSettings } from './lib/api'
import { getConfig } from './lib/config'
import { SetupFlow } from './setup/SetupFlow'
import { Sidebar } from './components/Sidebar'
import { ChatThread } from './components/chat/ChatThread'
import { ArtifactPanel } from './components/artifacts/ArtifactPanel'
import { SettingsView } from './components/settings/SettingsView'

export default function App() {
  const [setupDone, setSetupDone] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeChatId, setActiveChatId] = useState<string | null>(null)
  const [openArtifactId, setOpenArtifactId] = useState<string | null>(null)
  const [panelWidth, setPanelWidth] = useState(480)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [newChatTick, setNewChatTick] = useState(0)
  const [sidebarTick, setSidebarTick] = useState(0)

  useEffect(() => {
    getConfig().then(async () => {
      try {
        const s = await getAppSettings()
        setSetupDone(s.setup_complete)
      } catch {
        setSetupDone(false)
      }
      setLoading(false)
    }).catch(() => {
      setLoading(false)
      setSetupDone(false)
    })
  }, [])

  const onResizeStart = (e: React.MouseEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = panelWidth
    const move = (ev: MouseEvent) => {
      const delta = startX - ev.clientX
      setPanelWidth(Math.max(320, Math.min(window.innerWidth * 0.6, startW + delta)))
    }
    const up = () => {
      document.removeEventListener('mousemove', move)
      document.removeEventListener('mouseup', up)
    }
    document.addEventListener('mousemove', move)
    document.addEventListener('mouseup', up)
  }

 if (loading || setupDone === null) {
   return (
        <ThemeProvider>
          <AnimationPreferenceProvider>
          <ToastProvider>
            <div className="min-h-screen bg-(--bg) flex items-center justify-center">
              <div className="text-[13px] text-(--ink-muted)">Loading…</div>
            </div>
          </ToastProvider>
          </AnimationPreferenceProvider>
        </ThemeProvider>
      )
   }

   if (!setupDone) {
     return (
        <ThemeProvider>
          <AnimationPreferenceProvider>
          <ToastProvider>
            <SetupFlow onFinish={() => setSetupDone(true)} />
          </ToastProvider>
          </AnimationPreferenceProvider>
        </ThemeProvider>
      )
   }

 return (
      <ThemeProvider>
        <AnimationPreferenceProvider>
        <ToastProvider>
        <div className="h-screen w-screen flex bg-(--bg) text-(--ink) antialiased">
        <Sidebar
          activeChatId={activeChatId}
          onSelectChat={id => { setActiveChatId(id); setOpenArtifactId(null) }}
          onNewChat={() => { setActiveChatId(null); setOpenArtifactId(null); setNewChatTick(t => t + 1) }}
          onOpenSettings={() => setSettingsOpen(true)}
          onDeleteActiveChat={() => { setActiveChatId(null); setOpenArtifactId(null) }}
          sidebarTick={sidebarTick}
        />

        <div className="flex-1 flex min-w-0">
          <ChatThread
            key={activeChatId ?? `new-${newChatTick}`}
            chatId={activeChatId}
            onChatCreated={id => { setActiveChatId(id); setSidebarTick(t => t + 1) }}
            onOpenArtifact={id => setOpenArtifactId(id)}
          />
          {openArtifactId && (
            <div
              className="relative border-l border-(--border) shrink-0"
              style={{ width: panelWidth }}
            >
              <ArtifactPanel
                artifactId={openArtifactId}
                onClose={() => setOpenArtifactId(null)}
                onResizeStart={onResizeStart}
              />
            </div>
          )}
        </div>

        {settingsOpen && (
          <SettingsView
            onClose={() => setSettingsOpen(false)}
            onRerunSetup={() => { setSettingsOpen(false); setSetupDone(false) }}
          />
        )}
       </div>
        </ToastProvider>
        </AnimationPreferenceProvider>
      </ThemeProvider>
    )
}
