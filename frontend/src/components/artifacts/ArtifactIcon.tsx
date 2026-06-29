import { BarChart3, FileCheck, FileText, LayoutDashboard, Table } from 'lucide-react'

interface ArtifactIconProps {
  type: string
  className?: string
}

export function ArtifactIcon({ type, className }: ArtifactIconProps) {
  const map: Record<string, React.ElementType> = {
    dashboard: LayoutDashboard,
    report: FileCheck,
    chart: BarChart3,
    table: Table,
    document: FileText,
  }
  const I = map[type] ?? FileText
  return <I className={className} />
}
