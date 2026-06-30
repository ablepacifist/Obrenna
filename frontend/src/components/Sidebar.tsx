import { useEffect, useMemo, useState } from 'react'
import { FolderPlus, Plus, Search, Settings as SettingsIcon } from 'lucide-react'
import {
  type ChatDTO, type FolderDTO,
  listChats, listFolders, createChat, createFolder,
  updateChat, deleteChat, renameFolder, deleteFolder,
} from '../lib/api'
import { FolderRow } from './sidebar/FolderRow'
import { ChatRow } from './sidebar/ChatRow'
import { LocalPill } from './sidebar/LocalPill'

interface SidebarProps {
  activeChatId: string | null
  onSelectChat: (id: string) => void
  onNewChat: () => void
  onOpenSettings: () => void
  onDeleteActiveChat?: () => void
  sidebarTick?: number
}

function timeGroup(updatedAt: string): string {
  const d = new Date(updatedAt)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000)
  if (diffDays === 0) return 'today'
  if (diffDays === 1) return 'yesterday'
  if (diffDays <= 7) return 'week'
  return 'older'
}

const GROUP_LABELS: Record<string, string> = {
  today: 'Today',
  yesterday: 'Yesterday',
  week: 'Previous 7 days',
  older: 'Older',
}

export function Sidebar({ activeChatId, onSelectChat, onNewChat, onOpenSettings, onDeleteActiveChat, sidebarTick }: SidebarProps) {
  const [chats, setChats] = useState<ChatDTO[]>([])
  const [folders, setFolders] = useState<FolderDTO[]>([])
  const [q, setQ] = useState('')
  const [openFolders, setOpenFolders] = useState<Record<string, boolean>>({})
  const [menuFor, setMenuFor] = useState<string | null>(null)

  const reload = async () => {
    const [c, f] = await Promise.all([listChats(), listFolders()])
    setChats(c)
    setFolders(f)
    setOpenFolders(prev => {
      const next = { ...prev }
      f.forEach(folder => { if (!(folder.id in next)) next[folder.id] = true })
      return next
    })
  }

  useEffect(() => { reload() }, [sidebarTick])

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return chats
    return chats.filter(c => c.title.toLowerCase().includes(needle))
  }, [q, chats])

  const byFolder = (fid: string) => filtered.filter(c => c.folder_id === fid)
  const unfiledByGroup = (group: string) => filtered.filter(c => !c.folder_id && timeGroup(c.updated_at) === group)

  const groups = ['today', 'yesterday', 'week', 'older']

  const handleNewChat = async () => {
    const chat = await createChat()
    setChats(prev => [chat, ...prev])
    onSelectChat(chat.id)
  }

  const handleCreateFolder = async () => {
    const folder = await createFolder()
    setFolders(prev => [...prev, folder])
    setOpenFolders(prev => ({ ...prev, [folder.id]: true }))
  }

 const handleMoveChat = async (chatId: string, folderId: string | null) => {
    const updated = await updateChat(chatId, folderId === null ? { unfile: true } : { folder_id: folderId })
    setChats(prev => prev.map(c => c.id === chatId ? updated : c))
  }

  const handleDeleteChat = async (chatId: string) => {
    await deleteChat(chatId)
    setChats(prev => prev.filter(c => c.id !== chatId))
    if (activeChatId === chatId) {
      onDeleteActiveChat?.()
    }
  }

  const handleRenameFolder = async (fid: string, name: string) => {
    const updated = await renameFolder(fid, name)
    setFolders(prev => prev.map(f => f.id === fid ? updated : f))
  }

  const handleDeleteFolder = async (fid: string) => {
    await deleteFolder(fid)
    setFolders(prev => prev.filter(f => f.id !== fid))
    setChats(prev => prev.map(c => c.folder_id === fid ? { ...c, folder_id: undefined } : c))
  }

  return (
    <aside className="w-[260px] shrink-0 bg-(--bg) border-r border-(--border) flex flex-col">
      <div className="p-3">
        <button
          onClick={handleNewChat}
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
            open={openFolders[f.id] ?? true}
            onToggle={() => setOpenFolders(o => ({ ...o, [f.id]: !o[f.id] }))}
            activeChatId={activeChatId}
            onSelectChat={onSelectChat}
            menuFor={menuFor}
            setMenuFor={setMenuFor}
            onMoveChat={handleMoveChat}
            onDeleteChat={handleDeleteChat}
            onRenameFolder={handleRenameFolder}
            onDeleteFolder={handleDeleteFolder}
            folders={folders}
          />
        ))}

        <button
          onClick={handleCreateFolder}
          className="w-full h-8 mt-1 px-2 rounded-md text-left text-[12px] text-(--ink-muted) hover:bg-(--surface-2) hover:text-(--ink) inline-flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)"
        >
          <FolderPlus className="w-3.5 h-3.5" /> New folder
        </button>

        <div className="mt-3 space-y-3">
          {groups.map(g => {
            const items = unfiledByGroup(g)
            if (items.length === 0) return null
            return (
              <div key={g}>
                <div className="px-2 h-6 flex items-center text-[11px] font-medium uppercase tracking-wide text-(--ink-faint)">
                  {GROUP_LABELS[g]}
                </div>
                <div className="space-y-0.5">
                  {items.map(c => (
                    <ChatRow
                      key={c.id}
                      chat={c}
                      active={c.id === activeChatId}
                      onClick={() => onSelectChat(c.id)}
                      menuFor={menuFor}
                      setMenuFor={setMenuFor}
                      onMoveChat={handleMoveChat}
                      onDeleteChat={handleDeleteChat}
                      folders={folders}
                    />
                  ))}
                </div>
              </div>
            )
          })}
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
  )
}
