import { Folder, MessageSquare, MoreHorizontal, Move, Trash2 } from 'lucide-react'
import { cn } from '../../lib/cn'
import type { ChatDTO, FolderDTO } from '../../lib/api'
import { IconButton } from '../ui/IconButton'
import { Menu } from '../ui/Menu'

interface ChatRowProps {
  chat: ChatDTO
  active: boolean
  onClick: () => void
  menuFor: string | null
  setMenuFor: (id: string | null) => void
  onMoveChat: (chatId: string, folderId: string | null) => void
  onDeleteChat: (chatId: string) => void
  folders: FolderDTO[]
}

export function ChatRow({
  chat, active, onClick, menuFor, setMenuFor,
  onMoveChat, onDeleteChat, folders,
}: ChatRowProps) {
  const open = menuFor === chat.id
  return (
    <div className="group relative">
      <button
        onClick={onClick}
        className={cn(
          'w-full h-8 px-2 rounded-md text-left text-[13px] truncate flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)',
          active ? 'bg-(--surface-2) text-(--ink)' : 'text-(--ink) hover:bg-(--surface-2)',
        )}
      >
        <MessageSquare className="w-3.5 h-3.5 text-(--ink-faint) shrink-0" />
        <span className="truncate flex-1">{chat.title}</span>
      </button>
      <div className="absolute right-0 top-0 h-8 flex items-center">
        <IconButton
          className={cn('w-6 h-6', open ? 'opacity-100' : 'opacity-0 group-hover:opacity-100')}
          onClick={e => { e.stopPropagation(); setMenuFor(open ? null : chat.id) }}
        >
          <MoreHorizontal className="w-3.5 h-3.5" />
        </IconButton>
        {open && (
          <Menu
            onClose={() => setMenuFor(null)}
            items={[
              ...folders.map(f => ({
                label: f.name,
                icon: <Folder className="w-3.5 h-3.5" />,
                onClick: () => { onMoveChat(chat.id, chat.folder_id === f.id ? null : f.id); setMenuFor(null) },
              })),
              ...(folders.length > 0 ? [{
                label: 'Unfile',
                icon: <Move className="w-3.5 h-3.5" />,
                onClick: () => { onMoveChat(chat.id, null); setMenuFor(null) },
              }] : []),
              {
                label: 'Delete',
                danger: true,
                icon: <Trash2 className="w-3.5 h-3.5" />,
                onClick: () => { onDeleteChat(chat.id); setMenuFor(null) },
              },
            ]}
          />
        )}
      </div>
    </div>
  )
}
