import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import './App.css'
import { canvasFromWorkflow, connectionError, defaultWorkflow, initialEdges, initialNodes, parseWorkflowDocument, snapshotWorkflow, type Constraint, type FlowNodeData, type Variable, type Workflow } from './workflow'

type ApiEvaluation = {
  evaluation_id: string
  sequence: number
  source: string
  parameters: Record<string, number>
  metrics: Record<string, number>
  objective_value: number
  constraint_violations: number[]
  feasible: boolean
  cache_hit: boolean
}
type Run = {
  run_id: string
  status: string
  workflow: Workflow
  summary: {
    evaluation_count: number
    feasible_count: number
    cache_hit_count: number
    best_objective: number
    best_parameters: Record<string, number>
    best_feasible: boolean
    objective_direction: string
  } | null
  error: string | null
  evaluations: ApiEvaluation[]
}
type RunHistory = { run_id: string; status: string; name: string; created_at: string }
type RunEvent = { event_id: number; type: string; payload: Record<string, unknown>; created_at: string }
type ColumnRole = 'ignore' | 'parameter' | 'metric'
type DatasetPreview = {
  filename: string
  format: 'csv' | 'openfoam_dat'
  row_count: number
  columns: { name: string; source_name: string; example: string | number }[]
  metric_candidates: string[]
  parameter_candidates: string[]
  sample_rows: Record<string, string | number>[]
}
type ImportedDataset = {
  dataset_id: string
  filename: string
  source_format: string
  aggregation: string
  row_count: number
  source_row_count: number
  best_objective: number
  objective_direction: 'minimize' | 'maximize'
  best_parameters: Record<string, number>
  best_metrics: Record<string, number>
  best_feasible: boolean
  feasible_count: number
  evaluations: { sequence: number; parameters: Record<string, number>; metrics: Record<string, number>; objective_value: number; constraint_violations: number[]; feasible: boolean }[]
}
type DatasetHistory = { dataset_id: string; filename: string; source_format: string; row_count: number; created_at: string }

function WorkflowNode({ data, selected }: NodeProps<Node<FlowNodeData>>) {
  return (
    <div className={`workflow-node ${data.color} ${selected ? 'selected' : ''}`}>
      {data.inputHandle && <Handle id={data.inputHandle} type="target" position={Position.Left} />}
      <div className="node-icon"><span /></div>
      <div className="node-copy">
        <strong>{data.title}</strong>
        <small>{data.meta}</small>
      </div>
      {data.outputHandle && <Handle id={data.outputHandle} type="source" position={Position.Right} />}
    </div>
  )
}

const nodeTypes = { workflow: WorkflowNode }
const API = '/api/v1'
const wait = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds))

async function readJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof body.detail === 'string'
      ? body.detail
      : Array.isArray(body.detail) && typeof body.detail[0]?.msg === 'string'
        ? body.detail[0].msg
        : `Request failed (${response.status})`
    throw new Error(detail)
  }
  return body as T
}

function App() {
  const [workflow, setWorkflow] = useState<Workflow>(defaultWorkflow)
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
  const [selected, setSelected] = useState('variables')
  const [service, setService] = useState<'checking' | 'online' | 'offline'>('checking')
  const [busy, setBusy] = useState(false)
  const [run, setRun] = useState<Run | null>(null)
  const [runHistory, setRunHistory] = useState<RunHistory[]>([])
  const [datasetPreview, setDatasetPreview] = useState<DatasetPreview | null>(null)
  const [datasetContent, setDatasetContent] = useState('')
  const [columnRoles, setColumnRoles] = useState<Record<string, ColumnRole>>({})
  const [importAggregation, setImportAggregation] = useState<'all' | 'last' | 'mean'>('all')
  const [importObjective, setImportObjective] = useState('')
  const [importBusy, setImportBusy] = useState(false)
  const [importedDataset, setImportedDataset] = useState<ImportedDataset | null>(null)
  const [datasetHistory, setDatasetHistory] = useState<DatasetHistory[]>([])
  const [events, setEvents] = useState<RunEvent[]>([])
  const [error, setError] = useState('')
  const [savedSource, setSavedSource] = useState('')
  const [documentBusy, setDocumentBusy] = useState(false)
  const workflowSnapshot = useMemo(() => snapshotWorkflow(workflow, nodes, edges), [workflow, nodes, edges])
  const saved = savedSource === JSON.stringify(workflowSnapshot)

  const nodeConfig = useMemo(() => ({
    variables: `${workflow.variables.length} continuous · bounded`,
    doe: `${workflow.doe.method.toUpperCase()} · ${workflow.doe.samples} samples`,
    solver: `${workflow.solver.kind} · mock`,
    objective: `${workflow.objective.direction} ${workflow.objective.expression}`,
    optimizer: `${workflow.optimizer.trials} adaptive trials`,
    results: run?.summary ? `${run.summary.evaluation_count} evaluations · ${run.status}` : 'History · CSV export',
  }), [workflow, run])

  useEffect(() => {
    setNodes((current) => current.map((node) => ({
      ...node,
      data: {
        ...node.data,
        meta: nodeConfig[node.id as keyof typeof nodeConfig] ?? node.data.meta,
        active: node.id === selected,
      },
    })))
  }, [nodeConfig, selected, setNodes])

  useEffect(() => {
    readJson<{ status: string }>(`/health`).then(() => setService('online')).catch(() => setService('offline'))
  }, [])

  useEffect(() => {
    if (service === 'online') {
      readJson<{ runs: RunHistory[] }>('/runs').then((result) => setRunHistory(result.runs)).catch(() => undefined)
      readJson<{ datasets: DatasetHistory[] }>('/datasets').then((result) => setDatasetHistory(result.datasets)).catch(() => undefined)
    }
  }, [service])

  const onConnect = useCallback((connection: Connection) => {
    const problem = connectionError(connection, nodes, edges)
    if (problem) {
      setError(problem)
      return
    }
    setEdges((current) => addEdge({ ...connection, style: { stroke: '#7f8da4', strokeWidth: 1.5 } }, current))
    setError('')
  }, [nodes, edges, setEdges])

  const updateWorkflow = <K extends keyof Workflow>(key: K, value: Workflow[K]) => {
    setWorkflow((current) => ({ ...current, [key]: value }))
    setError('')
  }

  const applyWorkflow = (next: Workflow, fromBrowser = false) => {
    const canvas = canvasFromWorkflow(next)
    setWorkflow(next)
    setNodes(canvas.nodes)
    setEdges(canvas.edges)
    setSelected('variables')
    setRun(null)
    setEvents([])
    setSavedSource(fromBrowser ? JSON.stringify(snapshotWorkflow(next, canvas.nodes, canvas.edges)) : '')
    setError('')
  }

  const saveWorkflow = async (exportFile = false) => {
    setDocumentBusy(true)
    setError('')
    try {
      const validated = await readJson<{ workflow: Workflow }>('/workflows/validate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(workflowSnapshot),
      })
      const source = JSON.stringify(validated.workflow, null, 2)
      if (exportFile) {
        const url = URL.createObjectURL(new Blob([source], { type: 'application/json' }))
        const link = document.createElement('a')
        link.href = url
        link.download = 'aoa-workflow.json'
        link.click()
        window.setTimeout(() => URL.revokeObjectURL(url), 0)
      } else {
        localStorage.setItem('aoa-workflow-v1', source)
        setSavedSource(JSON.stringify(workflowSnapshot))
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save this workflow.')
    } finally {
      setDocumentBusy(false)
    }
  }

  const loadWorkflow = async (file?: File) => {
    setDocumentBusy(true)
    setError('')
    try {
      if (file && file.size > 256_000) throw new Error('Workflow files are limited to 256 KB of JSON.')
      const source = file ? await file.text() : localStorage.getItem('aoa-workflow-v1')
      if (!source) throw new Error('No workflow is saved in this browser. Use Import JSON to open a file.')
      const validated = await readJson<{ workflow: Workflow }>('/workflows/validate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(parseWorkflowDocument(source)),
      })
      applyWorkflow(validated.workflow, !file)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load this workflow.')
    } finally {
      setDocumentBusy(false)
    }
  }

  const selectNode = (nodeId: string) => {
    setSelected(nodeId)
    setNodes((current) => current.map((node) => ({ ...node, selected: node.id === nodeId })))
    const section = nodeId === 'objective' ? 'solver' : nodeId
    document.getElementById(`settings-${section}`)?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  }

  const addNode = (template: Node<FlowNodeData>) => {
    if (!nodes.some((node) => node.id === template.id)) {
      setNodes((current) => [...current, { ...template, data: { ...template.data } }])
      setError('')
    }
    selectNode(template.id)
  }

  const runWorkflow = async () => {
    setBusy(true)
    setError('')
    setRun(null)
    setEvents([])
    try {
      const submittedWorkflow = workflowSnapshot
      await readJson('/workflows/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(submittedWorkflow),
      })
      const created = await readJson<{ run_id: string }>(`/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ workflow: submittedWorkflow }),
      })
      let eventCursor = 0
      for (let attempt = 0; attempt < 300; attempt += 1) {
        const current = await readJson<Run>(`/runs/${created.run_id}`)
        setRun(current)
        const update = await readJson<{ events: RunEvent[] }>(`/runs/${created.run_id}/events?after=${eventCursor}`)
        if (update.events.length) {
          eventCursor = update.events[update.events.length - 1].event_id
          setEvents((previous) => [...previous, ...update.events])
        }
        if (current.status === 'completed') break
        if (current.status === 'failed') throw new Error(current.error || 'The run failed.')
        await wait(250)
        if (attempt === 299) throw new Error('The run is taking longer than expected. Its status is saved; refresh to check again.')
      }
      const history = await readJson<{ runs: RunHistory[] }>('/runs')
      setRunHistory(history.runs)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not run this workflow.')
      if (caught instanceof TypeError) setService('offline')
    } finally {
      setBusy(false)
    }
  }

  const previewImport = async (file: File) => {
    setError('')
    setImportedDataset(null)
    setDatasetPreview(null)
    if (file.size > 2_000_000) {
      setError('Import files are limited to 2 MB of text.')
      return
    }
    try {
      const content = await file.text()
      const format = file.name.toLowerCase().endsWith('.dat') ? 'openfoam_dat' : 'csv'
      const preview = await readJson<DatasetPreview>('/datasets/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, content, format }),
      })
      setDatasetContent(content)
      setDatasetPreview(preview)
      const variableNames = new Set(workflow.variables.map((variable) => variable.name))
      const nextRoles: Record<string, ColumnRole> = {}
      for (const column of preview.columns) {
        if (['time', 'iteration', 'step'].includes(column.name.toLowerCase())) nextRoles[column.name] = 'ignore'
        else if (variableNames.has(column.name)) nextRoles[column.name] = 'parameter'
        else nextRoles[column.name] = preview.metric_candidates.includes(column.name) ? 'metric' : 'ignore'
      }
      if (!Object.values(nextRoles).includes('metric') && preview.metric_candidates[0]) nextRoles[preview.metric_candidates[0]] = 'metric'
      setColumnRoles(nextRoles)
      setImportAggregation(preview.format === 'openfoam_dat' ? 'mean' : 'all')
      const recommended = preview.metric_candidates.includes('Cd') ? 'Cd' : preview.metric_candidates[0]
      setImportObjective(recommended ?? '')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not preview this result file.')
    }
  }

  const importResults = async () => {
    if (!datasetPreview) return
    const parameterColumns = Object.entries(columnRoles).filter(([, role]) => role === 'parameter').map(([name]) => name)
    const metricColumns = Object.entries(columnRoles).filter(([, role]) => role === 'metric').map(([name]) => name)
    if (metricColumns.length === 0) {
      setError('Choose at least one output metric column before importing.')
      return
    }
    setImportBusy(true)
    setError('')
    try {
      const result = await readJson<ImportedDataset>('/datasets/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: datasetPreview.filename,
          content: datasetContent,
          format: datasetPreview.format,
          parameter_columns: parameterColumns,
          metric_columns: metricColumns,
          aggregation: importAggregation,
          objective_expression: importObjective,
          objective_direction: workflow.objective.direction,
          constraints: workflow.constraints,
        }),
      })
      setImportedDataset(result)
      const history = await readJson<{ datasets: DatasetHistory[] }>('/datasets')
      setDatasetHistory(history.datasets)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not import this result file.')
    } finally {
      setImportBusy(false)
    }
  }

  const selectDataset = async (datasetId: string) => {
    try {
      setImportedDataset(await readJson<ImportedDataset>(`/datasets/${datasetId}`))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load that dataset.')
    }
  }

  const setVariable = (index: number, key: keyof Variable, value: string) => {
    const next = [...workflow.variables]
    next[index] = { ...next[index], [key]: key === 'name' ? value : Number(value) }
    updateWorkflow('variables', next)
  }

  const addVariable = () => {
    if (workflow.variables.length >= 8) return
    const name = `x${workflow.variables.length + 1}`
    updateWorkflow('variables', [...workflow.variables, { name, lower: -5, upper: 5 }])
  }

  const updateConstraint = (index: number, key: keyof Constraint, value: string) => {
    const next = [...workflow.constraints]
    next[index] = {
      ...next[index],
      [key]: key === 'bound' ? Number(value) : value,
    }
    updateWorkflow('constraints', next)
  }

  const addConstraint = () => {
    updateWorkflow('constraints', [
      ...workflow.constraints,
      { name: `constraint_${workflow.constraints.length + 1}`, expression: workflow.variables.map((variable) => variable.name).join(' + '), relation: '<=', bound: 1 },
    ])
  }

  const selectRun = async (runId: string) => {
    try {
      const restored = await readJson<Run>(`/runs/${runId}`)
      applyWorkflow(restored.workflow)
      setRun(restored)
      const eventResult = await readJson<{ events: RunEvent[] }>(`/runs/${runId}/events`)
      setEvents(eventResult.events)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load that run.')
    }
  }

  const currentNode = nodes.find((node) => node.id === selected)
  const inspectorTitle = currentNode?.data.title ?? 'Workflow settings'
  const resultWorkflow = run?.workflow ?? workflow

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#home"><span className="brand-mark">A</span><span>AOA</span></a>
        <div className="topbar-middle"><span className="workspace-path">WORKSPACE <b>/</b> OPTIMIZATION STUDIO</span><span className={`connection ${service}`}><i />{service === 'online' ? 'Local engine ready' : service === 'offline' ? 'Engine offline' : 'Checking engine'}</span></div>
        <div className="topbar-actions">
          <span className="mode-pill">LOCAL · MOCK SOLVER</span>
          <button className="quiet-button" onClick={() => void loadWorkflow()} disabled={busy || documentBusy || service !== 'online'}>Load</button>
          <button className={`quiet-button ${saved ? 'saved' : ''}`} onClick={() => void saveWorkflow()} disabled={busy || documentBusy || service !== 'online'}>{saved ? 'Saved' : 'Save'}</button>
          <button className="quiet-button" onClick={() => void saveWorkflow(true)} disabled={busy || documentBusy || service !== 'online'}>Export JSON</button>
          <label className="file-picker workflow-picker">Import JSON<input aria-label="Import workflow JSON" type="file" accept=".json,application/json" disabled={busy || documentBusy || service !== 'online'} onChange={(event) => { const file = event.target.files?.[0]; if (file) void loadWorkflow(file); event.currentTarget.value = '' }} /></label>
        </div>
      </header>

      <div className="main-layout">
        <section className="studio">
          <div className="page-heading">
            <div><p className="eyebrow">OPTIMIZATION WORKFLOW</p><h1>Design a better outcome.</h1><p className="subtitle">Configure a reproducible experiment, then run it against a deterministic benchmark.</p></div>
            <div className="heading-actions"><div className="engine-chip"><span className="engine-dot" /> Optuna TPE <small>enabled</small></div><button className="run-button" onClick={runWorkflow} disabled={busy || documentBusy || service !== 'online' || (workflow.solver.kind !== 'sphere' && workflow.variables.length < 2)}><span className={busy ? 'spinner' : 'play'} />{busy ? 'Running workflow…' : 'Run workflow'}</button></div>
          </div>

          {error && <div className="error-banner" role="alert"><strong>Needs attention</strong><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}

          <div className="section-heading"><div><h2>Workflow canvas</h2><p>Select a node to edit its settings. Drag to rearrange.</p></div><div className="canvas-legend"><span><i className="legend-port" /> Data flow</span><span><i className="legend-seed" /> Reproducible seed</span></div></div>

          <div className="canvas-frame">
            <div className="node-palette" role="toolbar" aria-label="Workflow node palette">
              {initialNodes.map((template) => {
                const exists = nodes.some((node) => node.id === template.id)
                return <button key={template.id} className={selected === template.id ? 'active' : ''} disabled={busy || documentBusy} aria-label={`${exists ? 'Select' : 'Add'} ${template.data.title} node`} onClick={() => addNode(template)}>{exists ? '' : '+ '}{template.data.title}</button>
              })}
              <button disabled={busy || documentBusy} onClick={() => { setEdges(initialEdges.filter((edge) => nodes.some((node) => node.id === edge.source) && nodes.some((node) => node.id === edge.target))); setError('') }}>Restore connections</button>
            </div>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              isValidConnection={(connection) => connectionError(connection, nodes, edges) === null}
              onNodeClick={(_, node) => selectNode(node.id)}
              nodesDraggable={!busy && !documentBusy}
              nodesConnectable={!busy && !documentBusy}
              deleteKeyCode={busy || documentBusy ? null : ['Backspace', 'Delete']}
              fitView
              fitViewOptions={{ padding: 0.18, minZoom: 0.45, maxZoom: 1 }}
              minZoom={0.35}
              maxZoom={1.25}
              proOptions={{ hideAttribution: true }}
            >
              <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#263043" />
              <MiniMap pannable zoomable nodeColor={(node) => ({ mint: '#91dab7', blue: '#8bb5ff', violet: '#b2a1ff', amber: '#f1c785', pink: '#efa1c8', green: '#78cfab' }[String(node.data.color)] ?? '#738199')} />
              <Controls showInteractive={false} />
            </ReactFlow>
            <div className="canvas-footer"><span><b>01</b> / FLOW</span><span>{nodes.length} NODES <i>·</i> {edges.length} CONNECTIONS <i>·</i> DAG</span></div>
          </div>

          <section className="results-section" id="settings-results">
            <div className="section-heading results-heading"><div><h2>Run results</h2><p>{run ? `${run.run_id} · ${run.status}` : 'Your evaluations and best candidate will appear here.'}</p></div><div className="results-actions">{runHistory.length > 0 && <select className="history-select" aria-label="Load a previous run" defaultValue="" disabled={busy || documentBusy} onChange={(event) => event.target.value && void selectRun(event.target.value)}><option value="">Recent runs</option>{runHistory.map((item) => <option key={item.run_id} value={item.run_id}>{item.name} · {item.run_id.slice(-6)} · {item.status}</option>)}</select>}{run?.status === 'completed' && <a className="export-link" href={`${API}/runs/${run.run_id}/results.csv`} download>↓ Export CSV</a>}</div></div>
            {run?.summary && <div className="summary-grid">
              <article className="summary-card summary-best"><span>BEST {run.summary.objective_direction.toUpperCase()}</span><strong>{formatNumber(run.summary.best_objective)}</strong><small>{run.summary.best_feasible ? 'Feasible candidate' : 'No feasible candidate'}</small></article>
              <article className="summary-card"><span>EVALUATIONS</span><strong>{run.summary.evaluation_count}</strong><small>{run.summary.feasible_count} feasible</small></article>
              <article className="summary-card"><span>CACHE REUSE</span><strong>{run.summary.cache_hit_count}</strong><small>solver results reused</small></article>
              <article className="summary-card summary-parameters"><span>BEST PARAMETERS</span><strong>{Object.entries(run.summary.best_parameters).map(([key, value]) => `${key} ${formatNumber(value)}`).join(' · ')}</strong><small>{resultWorkflow.objective.expression}</small></article>
            </div>}
            {run?.evaluations.length ? <div className="results-card">
              <div className="chart-header"><div><strong>Objective history</strong><small>Lower is better when minimizing</small></div><span>DOE <i className="dot-blue" /> OPTUNA <i className="dot-pink" /></span></div>
              <ObjectiveChart evaluations={run.evaluations} />
              <div className="table-scroll"><table><thead><tr><th>#</th><th>Source</th>{resultWorkflow.variables.map((variable) => <th key={variable.name}>{variable.name}</th>)}<th>Objective</th><th>Constraint</th><th>Cache</th></tr></thead><tbody>{run.evaluations.slice(-12).reverse().map((evaluation) => <tr key={evaluation.evaluation_id}><td>{evaluation.sequence.toString().padStart(2, '0')}</td><td><span className={`source-tag ${evaluation.source}`}>{evaluation.source === 'doe' ? 'DOE' : 'TPE'}</span></td>{resultWorkflow.variables.map((variable) => <td key={variable.name}>{formatNumber(evaluation.parameters[variable.name])}</td>)}<td className="objective-cell">{formatNumber(evaluation.objective_value)}</td><td><span className={`feasibility ${evaluation.feasible ? 'yes' : 'no'}`}>{evaluation.feasible ? 'Feasible' : 'Outside'}</span></td><td>{evaluation.cache_hit ? 'Reused' : 'New'}</td></tr>)}</tbody></table></div>
              <p className="table-note">Showing the latest 12 of {run.evaluations.length} evaluations.</p>
            </div> : <div className="empty-results"><div className="empty-icon">↗</div><strong>No run yet</strong><p>Start a workflow to see candidate scores, feasibility, and evaluation history.</p></div>}
            {events.length > 0 && <details className="event-panel"><summary>Run event journal <span>{events.length} events</span></summary><div>{events.slice(-8).map((event) => <p key={event.event_id}><code>{event.event_id.toString().padStart(3, '0')}</code><b>{event.type}</b><small>{new Date(event.created_at).toLocaleTimeString()}</small></p>)}</div></details>}
          </section>

          <section className="import-section">
            <div className="section-heading results-heading"><div><h2>Use existing solver results</h2><p>Import numeric CSV data or OpenFOAM force-coefficient tables. No solver is launched.</p></div>{datasetHistory.length > 0 && <select className="history-select" aria-label="Load an imported dataset" defaultValue="" onChange={(event) => event.target.value && void selectDataset(event.target.value)}><option value="">Imported datasets</option>{datasetHistory.map((dataset) => <option key={dataset.dataset_id} value={dataset.dataset_id}>{dataset.filename} · {dataset.row_count} rows</option>)}</select>}</div>
            <div className="import-card">
              <div className="import-topline"><div><span className="import-icon">↥</span><div><strong>Bring in existing results</strong><small>Headered numeric CSV or OpenFOAM postProcessing .dat</small></div></div><label className="file-picker">Choose file<input aria-label="Choose solver result file" type="file" accept=".csv,.dat,text/csv,text/plain" onChange={(event) => { const file = event.target.files?.[0]; if (file) void previewImport(file); event.currentTarget.value = '' }} /></label></div>
              <p className="import-disclosure">Files are parsed locally by AOA and only normalized numeric rows are saved. Inputs and output metrics stay in separate columns.</p>
              {datasetPreview && <>
                <div className="file-summary"><span><b>{datasetPreview.filename}</b> · {datasetPreview.format === 'openfoam_dat' ? 'OpenFOAM .dat' : 'numeric CSV'} · {datasetPreview.row_count} data rows</span><span>Map columns to inputs or outputs</span></div>
                <div className="mapping-table"><div className="mapping-header"><span>Column</span><span>Example</span><span>Use as</span></div>{datasetPreview.columns.map((column) => <div className="mapping-row" key={column.name}><span title={column.source_name}>{column.name}{column.source_name !== column.name && <small> ({column.source_name})</small>}</span><span>{formatPreviewValue(column.example)}</span><select aria-label={`Use ${column.name} as`} value={columnRoles[column.name] ?? 'ignore'} onChange={(event) => setColumnRoles((current) => ({ ...current, [column.name]: event.target.value as ColumnRole }))}><option value="ignore">Ignore</option><option value="parameter">Input parameter</option><option value="metric">Output metric</option></select></div>)}</div>
                <div className="import-options"><label className="field-label">Time-series reduction<select value={importAggregation} disabled={datasetPreview.format === 'csv'} onChange={(event) => setImportAggregation(event.target.value as 'all' | 'last' | 'mean')}><option value="all">Keep all CSV rows</option><option value="last">Use last time row</option><option value="mean">Use time average</option></select></label><label className="field-label">Objective expression<input value={importObjective} onChange={(event) => setImportObjective(event.target.value)} placeholder="e.g. Cd" /><small>Use mapped input/output names.</small></label></div>
                <button className="import-button" onClick={importResults} disabled={importBusy || service !== 'online'}>{importBusy ? 'Importing and scoring…' : 'Import and analyze'}</button>
              </>}
              {importedDataset && <div className="imported-results"><div className="imported-summary"><div><span>BEST {importedDataset.objective_direction.toUpperCase()}</span><strong>{formatNumber(importedDataset.best_objective)}</strong><small>{importedDataset.best_feasible ? 'Feasible' : 'No feasible row'}</small></div><div><span>DATA ROWS</span><strong>{importedDataset.row_count}</strong><small>{importedDataset.source_format === 'openfoam_dat' ? `${importedDataset.aggregation} of ${importedDataset.source_row_count} time steps` : `${importedDataset.feasible_count} feasible`}</small></div><a className="export-link" href={`${API}/datasets/${importedDataset.dataset_id}/results.csv`} download>↓ Export CSV</a></div><div className="table-scroll"><table><thead><tr><th>#</th>{Object.keys(importedDataset.best_parameters).map((key) => <th key={key}>{key} input</th>)}{Object.keys(importedDataset.best_metrics).map((key) => <th key={key}>{key} output</th>)}<th>Objective</th><th>Feasible</th></tr></thead><tbody>{importedDataset.evaluations.slice(-8).reverse().map((evaluation) => <tr key={evaluation.sequence}><td>{evaluation.sequence.toString().padStart(2, '0')}</td>{Object.keys(importedDataset.best_parameters).map((key) => <td key={key}>{formatNumber(evaluation.parameters[key])}</td>)}{Object.keys(importedDataset.best_metrics).map((key) => <td key={key}>{formatNumber(evaluation.metrics[key])}</td>)}<td className="objective-cell">{formatNumber(evaluation.objective_value)}</td><td><span className={`feasibility ${evaluation.feasible ? 'yes' : 'no'}`}>{evaluation.feasible ? 'Yes' : 'No'}</span></td></tr>)}</tbody></table></div></div>}
              {!datasetPreview && !importedDataset && <div className="import-empty"><span>CSV</span><span>.dat</span><p>For OpenFOAM, supported input is a headered numeric `# Time …` table, such as common forceCoeffs output. Raw fields, vectors, and VTK are outside this importer.</p></div>}
            </div>
          </section>
        </section>

        <aside className="inspector">
          <div className="inspector-top"><div><p className="eyebrow">NODE INSPECTOR</p><h2>{inspectorTitle}</h2></div><button className="more-button" aria-label="More settings">···</button></div>
          <p className="inspector-help">Set bounds, sample strategy, model, and scoring rules for this experiment.</p>

          <fieldset className="workflow-fields" disabled={busy || documentBusy}>
          <label className="field-label">Workflow name<input value={workflow.name} onChange={(event) => updateWorkflow('name', event.target.value)} maxLength={100} /></label>

          <section className="inspector-group" id="settings-variables"><div className="group-heading"><div><span className="step-number">01</span><strong>Design variables</strong></div><button className="text-button" onClick={addVariable} disabled={workflow.variables.length >= 8}>+ Add</button></div>
            <div className="variables-list">{workflow.variables.map((variable, index) => <div className="variable-row" key={`${index}-${variable.name}`}><input aria-label={`Variable ${index + 1} name`} className="variable-name" value={variable.name} onChange={(event) => setVariable(index, 'name', event.target.value)} /><label><small>MIN</small><input aria-label={`${variable.name} minimum`} type="number" step="any" value={variable.lower} onChange={(event) => setVariable(index, 'lower', event.target.value)} /></label><span className="range-arrow">→</span><label><small>MAX</small><input aria-label={`${variable.name} maximum`} type="number" step="any" value={variable.upper} onChange={(event) => setVariable(index, 'upper', event.target.value)} /></label>{workflow.variables.length > 1 && <button className="remove-button" onClick={() => updateWorkflow('variables', workflow.variables.filter((_, itemIndex) => itemIndex !== index))} aria-label={`Remove ${variable.name}`}>×</button>}</div>)}</div>
          </section>

          <section className="inspector-group" id="settings-doe"><div className="group-heading"><div><span className="step-number">02</span><strong>Design of experiments</strong></div><span className="mini-tag">DOE</span></div>
            <div className="two-col-fields"><label className="field-label">Sampling<select value={workflow.doe.method} onChange={(event) => updateWorkflow('doe', { ...workflow.doe, method: event.target.value as Workflow['doe']['method'] })}><option value="lhs">Latin hypercube</option><option value="random">Random</option></select></label><label className="field-label">Samples<input type="number" min="0" max="500" value={workflow.doe.samples} onChange={(event) => updateWorkflow('doe', { ...workflow.doe, samples: Number(event.target.value) })} /></label></div>
            <label className="field-label seed-field">Random seed<input type="number" min="0" value={workflow.doe.seed} onChange={(event) => updateWorkflow('doe', { ...workflow.doe, seed: Number(event.target.value) })} /><small>Same seed reproduces the design.</small></label>
          </section>

          <section className="inspector-group" id="settings-solver"><div className="group-heading"><div><span className="step-number">03</span><strong>Solver + score</strong></div></div>
            <label className="field-label">Mock benchmark<select value={workflow.solver.kind} onChange={(event) => { const kind = event.target.value as Workflow['solver']['kind']; updateWorkflow('solver', { ...workflow.solver, kind }); updateWorkflow('objective', { ...workflow.objective, expression: kind }) }}><option value="sphere">Sphere · smooth bowl</option><option value="rosenbrock">Rosenbrock · narrow valley</option><option value="branin">Branin · multimodal</option></select></label>
            {workflow.solver.kind !== 'sphere' && workflow.variables.length < 2 && <p className="field-hint">This benchmark requires at least two design variables. Add a variable to enable Run workflow, or select Sphere.</p>}
            <label className="field-label retry-field">Retry on transient solver startup<input type="number" min="1" max="3" value={workflow.solver.retry_attempts} onChange={(event) => updateWorkflow('solver', { ...workflow.solver, retry_attempts: Number(event.target.value) })} /><small>Bounded to 1–3 attempts. Mock runs do not simulate solver failures.</small></label>
            <div className="two-col-fields"><label className="field-label">Objective formula<input value={workflow.objective.expression} onChange={(event) => updateWorkflow('objective', { ...workflow.objective, expression: event.target.value })} placeholder="e.g. sphere" /></label><label className="field-label">Goal<select value={workflow.objective.direction} onChange={(event) => updateWorkflow('objective', { ...workflow.objective, direction: event.target.value as Workflow['objective']['direction'] })}><option value="minimize">Minimize</option><option value="maximize">Maximize</option></select></label></div>
            <p className="field-hint">Safe math only: + − × ÷, powers, abs, sqrt, log, exp, min, max. Try `sphere`, `x*x + y*y`, or a solver metric name.</p>
            <div className="constraint-heading"><span>Constraints <small>{workflow.constraints.length}</small></span><button className="text-button" onClick={addConstraint}>+ Add</button></div>
            {workflow.constraints.map((constraint, index) => <div className="constraint-row" key={index}><input aria-label="Constraint name" value={constraint.name} onChange={(event) => updateConstraint(index, 'name', event.target.value)} /><input aria-label="Constraint expression" value={constraint.expression} onChange={(event) => updateConstraint(index, 'expression', event.target.value)} /><select aria-label="Constraint relation" value={constraint.relation} onChange={(event) => updateConstraint(index, 'relation', event.target.value)}><option value="<=">≤</option><option value=">=">≥</option></select><input aria-label="Constraint bound" type="number" step="any" value={constraint.bound} onChange={(event) => updateConstraint(index, 'bound', event.target.value)} /><button className="remove-button" onClick={() => updateWorkflow('constraints', workflow.constraints.filter((_, itemIndex) => itemIndex !== index))} aria-label="Remove constraint">×</button></div>)}
          </section>

          <section className="inspector-group" id="settings-optimizer"><div className="group-heading"><div><span className="step-number">04</span><strong>Optimizer</strong></div><span className="mini-tag implemented">IMPLEMENTED</span></div>
            <label className="field-label">Strategy<select value={workflow.optimizer.engine} disabled><option value="optuna_tpe">Optuna TPE · adaptive</option></select></label>
            <div className="two-col-fields"><label className="field-label">Trials<input type="number" min="0" max="500" value={workflow.optimizer.trials} onChange={(event) => updateWorkflow('optimizer', { ...workflow.optimizer, trials: Number(event.target.value) })} /></label><label className="field-label">TPE seed<input type="number" min="0" value={workflow.optimizer.seed} onChange={(event) => updateWorkflow('optimizer', { ...workflow.optimizer, seed: Number(event.target.value) })} /></label></div>
            <p className="future-engines"><span>Next adapters</span> BoTorch GP-BO <i>·</i> pymoo NSGA-II</p>
          </section>

          </fieldset>
          <div className="fluent-note"><div className="fluent-icon">F</div><div><strong>Live Fluent · not configured</strong><p>Requires a locally verified Fluent/PyFluent version and a valid commercial license. This workflow uses the no-license mock solver.</p></div></div>
          <div className="inspector-footer"><span>WORKFLOW SCHEMA <b>v1</b></span><span>API <b>v1</b></span></div>
        </aside>
      </div>
    </main>
  )
}

function formatNumber(value: number | undefined) {
  if (value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 })
}

function formatPreviewValue(value: string | number) {
  if (typeof value === 'number') return formatNumber(value)
  const numeric = value.trim() === '' ? Number.NaN : Number(value)
  return Number.isFinite(numeric) ? formatNumber(numeric) : value || '—'
}

function ObjectiveChart({ evaluations }: { evaluations: ApiEvaluation[] }) {
  const width = 760
  const height = 160
  const padding = 16
  const values = evaluations.map((evaluation) => evaluation.objective_value)
  const low = Math.min(...values)
  const high = Math.max(...values)
  const points = evaluations.map((evaluation, index) => {
    const x = padding + (index / Math.max(1, evaluations.length - 1)) * (width - padding * 2)
    const ratio = high === low ? 0.5 : (evaluation.objective_value - low) / (high - low)
    const y = height - padding - ratio * (height - padding * 2)
    return { ...evaluation, x, y }
  })
  const line = points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ')
  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Objective value by evaluation sequence">
        {[0, 1, 2, 3].map((lineIndex) => <line key={lineIndex} x1={padding} x2={width - padding} y1={padding + lineIndex * ((height - padding * 2) / 3)} y2={padding + lineIndex * ((height - padding * 2) / 3)} className="chart-grid" />)}
        <path d={line} className="chart-line" />
        {points.map((point) => <circle key={point.evaluation_id} cx={point.x} cy={point.y} r="3.8" className={`chart-point ${point.source}`}><title>#{point.sequence} {point.source}: {formatNumber(point.objective_value)}</title></circle>)}
      </svg>
      <div className="chart-axis"><span>1 · {formatNumber(values[0])}</span><span>Evaluation sequence</span><span>{evaluations.length} · {formatNumber(values[values.length - 1])}</span></div>
    </div>
  )
}

export default App
