import { useRef, useState } from 'react'
import { FileText, Globe, Paperclip, Send, X } from 'lucide-react'
import { cn } from '../../lib/cn'
import { Button } from '../ui/Button'
import { IconButton } from '../ui/IconButton'

const ALLOWED_EXTENSIONS = new Set([
  'csv', 'txt', 'pdf', 'xlsx', 'xls', 'json', 'log', 'md', 'xml',
  'html', 'htm', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'sh', 'bat', 'ps1',
  'js', 'ts', 'jsx', 'tsx', 'py', 'rb', 'go', 'rs', 'c', 'cpp', 'h', 'hpp',
])

function getFileExtension(name: string): string {
  const parts = name.split('.')
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : ''
}

function isAllowedFile(file: File): boolean {
  return ALLOWED_EXTENSIONS.has(getFileExtension(file.name))
}

export interface AttachedFile {
  file: File
  name: string
  size: string
}

interface ComposerProps {
  onSend: (text: string, files: File[]) => void
  disabled?: boolean
  initialText?: string
  webSearchEnabled?: boolean
  onWebSearchChange?: (enabled: boolean) => void
  workersEnabled?: boolean
  onWorkersChange?: (enabled: boolean) => void
}

function formatBytes(n: number): string {
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return Math.round(n / 1024) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}

export function Composer({ onSend, disabled, initialText = '', webSearchEnabled = false, onWebSearchChange, workersEnabled = true, onWorkersChange }: ComposerProps) {
  const [text, setText] = useState(initialText)
  const [files, setFiles] = useState<AttachedFile[]>([])
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const send = () => {
    const t = text.trim()
    if (!t && files.length === 0) return
    onSend(t, files.map(f => f.file))
    setText('')
    setFiles([])
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  const addFiles = (list: FileList | null) => {
    if (!list) return
    const arr: AttachedFile[] = []
    const unsupported: string[] = []
    for (const f of Array.from(list)) {
      if (isAllowedFile(f)) {
        arr.push({ file: f, name: f.name, size: formatBytes(f.size) })
      } else {
        unsupported.push(f.name)
      }
    }
    if (unsupported.length > 0) {
      const exts = Array.from(new Set(unsupported.map(name => getFileExtension(name)))).join(', ')
      window.alert(`These file types are not supported: ${exts}. Only text-based files (CSV, TXT, PDF, XLSX, JSON, code, etc.) can be attached.`)
    }
    if (arr.length > 0) {
      setFiles(prev => [...prev, ...arr])
    }
  }

  return (
    <div
      onDragOver={e => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files) }}
      className={cn(
        'relative rounded-xl border bg-(--surface) transition-colors',
        drag ? 'border-(--accent) bg-(--surface-2)' : 'border-(--border)',
      )}
    >
      {drag && (
        <div className="absolute inset-0 rounded-xl pointer-events-none flex items-center justify-center">
          <div className="text-[13px] text-(--accent) font-medium">Drop files to attach</div>
        </div>
      )}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5 p-3 pb-0">
          {files.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 h-7 pl-2 pr-1 rounded-md bg-(--surface-2) border border-(--border) text-[12px] text-(--ink)">
              <FileText className="w-3 h-3 text-(--ink-muted)" />
              <span className="truncate max-w-[160px]">{f.name}</span>
              <span className="text-(--ink-faint)">· {f.size}</span>
              <button
                onClick={() => setFiles(fs => fs.filter((_, j) => j !== i))}
                className="w-5 h-5 rounded hover:bg-(--border) inline-flex items-center justify-center"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={onKey}
        rows={1}
        placeholder="Ask anything, or drop a file"
        className="w-full resize-none bg-transparent p-3 pb-1 text-[14px] text-(--ink) placeholder:text-(--ink-faint) focus:outline-none max-h-[240px]"
        style={{ minHeight: 44 }}
      />
      <div className="flex items-center justify-between px-2 pb-2">
        <div className="flex items-center gap-0.5">
          <IconButton onClick={() => fileRef.current?.click()} title="Attach files">
            <Paperclip className="w-4 h-4" />
          </IconButton>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept=".csv,.txt,.pdf,.xlsx,.xls,.json,.log,.md,.xml,.html,.htm,.yaml,.yml,.toml,.ini,.cfg,.conf,.sh,.bat,.ps1,.js,.ts,.jsx,.tsx,.py,.rb,.go,.rs,.c,.cpp,.h,.hpp"
            className="hidden"
            onChange={e => { addFiles(e.target.files); e.target.value = '' }}
          />
          <button
            onClick={() => onWebSearchChange?.(!webSearchEnabled)}
            title="Toggle web search"
            className={cn(
              'h-8 px-2.5 rounded-md text-[12px] inline-flex items-center gap-1.5 border transition-colors',
              webSearchEnabled
                ? 'border-(--accent) bg-(--accent)/10 text-(--accent)'
                : 'border-(--border) bg-(--surface) text-(--ink-faint) hover:border-(--border)/80 hover:text-(--ink-muted)',
            )}
          >
            <Globe className={cn('w-3.5 h-3.5', webSearchEnabled && 'text-(--accent)')} /> Web search
          </button>
          <button
            onClick={() => onWorkersChange?.(!workersEnabled)}
            title="Toggle worker models"
            className={cn(
              'h-8 px-2.5 rounded-md text-[12px] inline-flex items-center gap-1.5 border transition-colors',
              workersEnabled
                ? 'border-(--accent) bg-(--accent)/10 text-(--accent)'
                : 'border-(--border) bg-(--surface) text-(--ink-faint) hover:border-(--border)/80 hover:text-(--ink-muted)',
            )}
          >
            <FileText className={cn('w-3.5 h-3.5', workersEnabled && 'text-(--accent)')} /> Workers
          </button>
        </div>
        <Button onClick={send} disabled={disabled || (!text.trim() && files.length === 0)}>
          <Send className="w-3.5 h-3.5" /> Send
        </Button>
      </div>
    </div>
  )
}
