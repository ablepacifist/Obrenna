import { useState } from 'react'
import { ChevronDown, ChevronRight, Folder, FolderOpen, MoreHorizontal } from 'lucide-react'
import type { ChatDTO, FolderDTO } from '../../lib/api'
import { IconButton } from '../ui/IconButton'
import { Menu } from '../ui/Menu'
import { ChatRow } from './ChatRow'

interface FolderRowProps {
  folder: FolderDTO
  items: ChatDTO[]
  open: boolean
  onToggle: () => void
  activeChatId: string | null
  onSelectChat: (id: string) => void
  menuFor: string | null
  setMenuFor: (id: string | null) => void
  onMoveChat: (chatId: string, folderId: string | null) => void
  onDeleteChat: (chatId: string) => void
  onRenameFolder: (fid: string, name: string) => void
  onDeleteFolder: (fid: string) => void
  folders: FolderDTO[]
}

export function FolderRow({
  folder, items, open, onToggle, activeChatId, onSelectChat,
  menuFor, setMenuFor, onMoveChat, onDeleteChat, onRenameFolder, onDeleteFolder, folders,
}: FolderRowProps) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(folder.name)
  const [folderMenu, setFolderMenu] = useState(false)

  return (
    <div>
      <div className="group flex items-center h-8 px-2 rounded-md hover:bg-(--surface-2)">
        <button
          onClick={onToggle}
          className="flex items-center gap-1.5 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) rounded"
        >
          {open
            ? <ChevronDown className="w-3.5 h-3.5 text-(--ink-faint)" />
            : <ChevronRight className="w-3.5 h-3.5 text-(--ink-faint)" />}
          {open
            ? <FolderOpen className="w-3.5 h-3.5 text-(--ink-muted)" />
            : <Folder className="w-3.5 h-3.5 text-(--ink-muted)" />}
          {editing ? (
            <input
              autoFocus
              value={name}
              onChange={e => setName(e.target.value)}
              onBlur={() => { onRenameFolder(folder.id, name.trim() || folder.name); setEditing(false) }}
              onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
              className="flex-1 min-w-0 bg-transparent text-[13px] text-(--ink) focus:outline-none"
              onClick={e => e.stopPropagation()}
            />
          ) : (
            <span className="text-[13px] text-(--ink) truncate">{folder.name}</span>
          )}
        </button>
        <div className="relative">
          <IconButton
            className="w-6 h-6 opacity-0 group-hover:opacity-100"
            onClick={e => { e.stopPropagation(); setFolderMenu(v => !v) }}
          >
            <MoreHorizontal className="w-3.5 h-3.5" />
          </IconButton>
          {folderMenu && (
            <Menu
              onClose={() => setFolderMenu(false)}
              items={[
                { label: 'Rename', onClick: () => { setEditing(true); setFolderMenu(false) } },
                { label: 'Delete folder', danger: true, onClick: () => { onDeleteFolder(folder.id); setFolderMenu(false) } },
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
  )
}
