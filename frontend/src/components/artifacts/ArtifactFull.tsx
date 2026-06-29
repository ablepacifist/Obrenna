import type { Artifact } from '../../lib/types/artifact'
import { DashboardRenderer } from './renderers/DashboardRenderer'
import { ReportRenderer } from './renderers/ReportRenderer'
import { ChartRenderer } from './renderers/ChartRenderer'
import { TableRenderer } from './renderers/TableRenderer'
import { DocumentRenderer } from './renderers/DocumentRenderer'

interface ArtifactFullProps {
  artifact: Artifact
}

export function ArtifactFull({ artifact }: ArtifactFullProps) {
  switch (artifact.artifact_type) {
    case 'dashboard': return <DashboardRenderer artifact={artifact} />
    case 'report': return <ReportRenderer artifact={artifact} />
    case 'chart': return <ChartRenderer artifact={artifact} />
    case 'table': return <TableRenderer artifact={artifact} />
    case 'document': return <DocumentRenderer artifact={artifact} />
    default: return null
  }
}
