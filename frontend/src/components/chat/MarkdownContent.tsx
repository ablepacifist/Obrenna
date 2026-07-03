import { Children, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import { StreamingScrambleText } from './StreamingScrambleText'

interface Props {
  children: string
  className?: string
  streaming?: boolean
}

function renderInlineChildren(children: ReactNode, streaming: boolean) {
  if (!streaming) return children

  return Children.map(children, child => {
    if (typeof child === 'string') {
      return <StreamingScrambleText text={child} active />
    }
    return child
  })
}

function createComponents(streaming: boolean): Components {
  return {
    p: ({ children }) => (
      <p className="mb-3 last:mb-0 leading-relaxed">{renderInlineChildren(children, streaming)}</p>
    ),
    h1: ({ children }) => (
      <h1 className="text-xl font-semibold mb-3 mt-4 first:mt-0 text-(--ink)">{renderInlineChildren(children, streaming)}</h1>
    ),
    h2: ({ children }) => (
      <h2 className="text-lg font-semibold mb-2 mt-4 first:mt-0 text-(--ink)">{renderInlineChildren(children, streaming)}</h2>
    ),
    h3: ({ children }) => (
      <h3 className="text-base font-semibold mb-2 mt-3 first:mt-0 text-(--ink)">{renderInlineChildren(children, streaming)}</h3>
    ),
    h4: ({ children }) => (
      <h4 className="text-sm font-semibold mb-2 mt-2 first:mt-0 text-(--ink)">{renderInlineChildren(children, streaming)}</h4>
    ),
    ul: ({ children }) => (
      <ul className="list-disc pl-5 mb-3 space-y-1">{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className="list-decimal pl-5 mb-3 space-y-1">{children}</ol>
    ),
    li: ({ children }) => (
      <li className="text-(--ink) leading-relaxed">{renderInlineChildren(children, streaming)}</li>
    ),
    code: ({ children, className }) => {
      const isBlock = className?.startsWith('language-')
      if (isBlock) {
        return <code className="text-sm font-mono">{children}</code>
      }
      return (
        <code className="bg-(--surface-2) text-(--ink) px-1 py-0.5 rounded text-[13px] font-mono">
          {children}
        </code>
      )
    },
    pre: ({ children }) => (
      <pre className="bg-(--surface-2) border border-(--border) rounded-(--r-md) p-3 mb-3 overflow-x-auto text-sm font-mono">
        {children}
      </pre>
    ),
    blockquote: ({ children }) => (
      <blockquote className="border-l-2 border-(--border) pl-3 italic text-(--ink-muted) mb-3">
        {renderInlineChildren(children, streaming)}
      </blockquote>
    ),
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-(--accent) underline hover:opacity-80 transition-opacity"
      >
        {children}
      </a>
    ),
    strong: ({ children }) => (
      <strong className="font-semibold text-(--ink)">{renderInlineChildren(children, streaming)}</strong>
    ),
    em: ({ children }) => (
      <em className="italic">{renderInlineChildren(children, streaming)}</em>
    ),
    table: ({ children }) => (
      <div className="overflow-x-auto mb-3">
        <table className="w-full text-sm border-collapse">{children}</table>
      </div>
    ),
    th: ({ children }) => (
      <th className="text-left px-3 py-2 border-b border-(--border) font-semibold text-(--ink) bg-(--surface-2)">
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td className="px-3 py-2 border-b border-(--border) text-(--ink-muted)">{children}</td>
    ),
    hr: () => <hr className="border-(--border) mb-3 mt-3" />,
  }
}

export function MarkdownContent({ children, className, streaming = false }: Props) {
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={createComponents(streaming)}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
