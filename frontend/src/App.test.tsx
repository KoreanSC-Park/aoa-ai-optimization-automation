// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { defaultWorkflow, initialEdges, initialNodes, snapshotWorkflow } from './workflow'
import type { Edge, Node, NodeChange, EdgeChange } from '@xyflow/react'

vi.mock('@xyflow/react', async () => {
  const React = await import('react')
  const actual = await vi.importActual<typeof import('@xyflow/react')>('@xyflow/react')
  const passthrough = ({ children }: { children?: React.ReactNode }) => React.createElement('div', null, children)
  return {
    ...actual,
    Background: passthrough,
    BackgroundVariant: { Dots: 'dots' },
    Controls: passthrough,
    Handle: () => null,
    MiniMap: passthrough,
    Position: { Left: 'left', Right: 'right' },
    ReactFlow: ({ children, nodes, edges, onNodesChange, onEdgesChange }: {
      children: React.ReactNode; nodes: Node[]; edges: Edge[];
      onNodesChange: (changes: NodeChange[]) => void; onEdgesChange: (changes: EdgeChange[]) => void;
    }) => React.createElement('div', null, children,
      React.createElement('output', { 'data-testid': 'canvas-layout' }, JSON.stringify(nodes.map(({ id, position }) => ({ id, position })))),
      React.createElement('button', { onClick: () => onNodesChange([{ id: 'variables', type: 'position', position: { x: 900, y: 300 } }]) }, 'Move test node'),
      React.createElement('button', { onClick: () => {
        onNodesChange([{ id: 'solver', type: 'remove' }])
        onEdgesChange(edges.filter((edge) => edge.source === 'solver' || edge.target === 'solver').map((edge) => ({ id: edge.id, type: 'remove' })))
      } }, 'Delete test solver'),
    ),
  }
})

const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
})

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('result import API contract', () => {
  it('renders string-valued CSV preview fields and uses the imported objective direction', async () => {
    const calls: { path: string; init?: RequestInit }[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      calls.push({ path, init })
      if (path.endsWith('/health')) return response({ status: 'ok' })
      if (path.endsWith('/runs')) return response({ runs: [] })
      if (path.endsWith('/datasets') && init?.method !== 'POST') return response({ datasets: [] })
      if (path.endsWith('/datasets/preview')) return response({
        filename: 'sweep.csv', format: 'csv', row_count: 1,
        columns: [
          { name: 'case', source_name: 'case', example: 'baseline-a' },
          { name: 'x', source_name: 'x', example: '1.25' },
          { name: 'Cd', source_name: 'Cd', example: '0.42' },
        ],
        metric_candidates: ['x', 'Cd'], parameter_candidates: ['x', 'Cd'],
        sample_rows: [{ case: 'baseline-a', x: '1.25', Cd: '0.42' }],
      })
      if (path.endsWith('/datasets/import')) return response({
        dataset_id: 'data-contract', filename: 'sweep.csv', source_format: 'csv', aggregation: 'all',
        row_count: 1, source_row_count: 1, best_objective: 0.42, objective_direction: 'maximize',
        best_parameters: { x: 1.25 }, best_metrics: { Cd: 0.42 }, best_feasible: true, feasible_count: 1,
        evaluations: [{ sequence: 1, parameters: { x: 1.25 }, metrics: { Cd: 0.42 }, objective_value: 0.42, constraint_violations: [], feasible: true }],
      })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    const file = new File(['case,x,Cd\nbaseline-a,1.25,0.42\n'], 'sweep.csv', { type: 'text/csv' })
    Object.defineProperty(file, 'text', { value: async () => 'case,x,Cd\nbaseline-a,1.25,0.42\n' })
    fireEvent.change(screen.getByLabelText('Choose solver result file'), { target: { files: [file] } })

    expect(await screen.findByText('baseline-a')).toBeTruthy()
    expect(screen.getByText('1.25')).toBeTruthy()
    expect(screen.getByText('0.42')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Import and analyze' }))
    expect(await screen.findByText('BEST MAXIMIZE')).toBeTruthy()
    const importCall = calls.find((call) => call.path.endsWith('/datasets/import'))
    expect(importCall).toBeTruthy()
    expect(JSON.parse(String(importCall?.init?.body))).toMatchObject({
      parameter_columns: ['x'], metric_columns: ['Cd'], objective_expression: 'Cd',
    })
  })

  it('disables an incompatible two-variable benchmark when only one variable remains', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.endsWith('/health')) return response({ status: 'ok' })
      if (path.endsWith('/runs')) return response({ runs: [] })
      if (path.endsWith('/datasets')) return response({ datasets: [] })
      throw new Error(`Unexpected request: ${path}`)
    }))
    render(<App />)

    await screen.findByRole('button', { name: 'Run workflow' })
    fireEvent.click(screen.getByRole('button', { name: 'Remove y' }))
    fireEvent.change(screen.getByLabelText('Mock benchmark'), { target: { value: 'rosenbrock' } })

    expect(screen.getByText(/requires at least two design variables/i)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Run workflow' })).toHaveProperty('disabled', true)
  })
})


function mockWorkflowApi(rejectValidation = false) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/health')) return response({ status: 'ok' })
    if (path.endsWith('/runs')) return response({ runs: [] })
    if (path.endsWith('/datasets')) return response({ datasets: [] })
    if (path.endsWith('/workflows/validate')) {
      if (rejectValidation) return response({ detail: 'Unsupported workflow schema version' }, 422)
      return response({ valid: true, workflow: JSON.parse(String(init?.body)) })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function workflowFile(content: string) {
  const file = new File([content], 'workflow.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => content })
  return file
}

describe('workflow documents', () => {
  it('round-trips settings, positions and connections through browser save/load', async () => {
    mockWorkflowApi()
    render(<App />)
    await screen.findByText('Local engine ready')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByRole('button', { name: 'Saved' })
    fireEvent.click(screen.getByRole('button', { name: 'Move test node' }))
    expect(screen.getByRole('button', { name: 'Save' })).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Workflow name'), { target: { value: 'Saved experiment' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByRole('button', { name: 'Saved' })
    const saved = JSON.parse(localStorage.getItem('aoa-workflow-v1')!)
    expect(saved.graph.nodes[0]).toMatchObject({ version: 1, position: { x: 900, y: 300 } })
    expect(saved.graph.nodes[0]).not.toHaveProperty('data')
    fireEvent.click(screen.getByRole('button', { name: 'Delete test solver' }))
    expect(screen.getByRole('button', { name: 'Add Mock solver node' })).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Workflow name'), { target: { value: 'Unsaved experiment' } })
    fireEvent.click(screen.getByRole('button', { name: 'Load' }))
    await waitFor(() => expect(screen.getByLabelText('Workflow name')).toHaveProperty('value', 'Saved experiment'))
    expect(screen.getByTestId('canvas-layout').textContent).toContain('"x":900,"y":300')
    expect(screen.getByRole('button', { name: 'Select Mock solver node' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Saved' })).toBeTruthy()
  })

  it('restores deleted supported nodes and edges from the palette', async () => {
    mockWorkflowApi()
    render(<App />)
    await screen.findByText('Local engine ready')
    fireEvent.click(screen.getByRole('button', { name: 'Delete test solver' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add Mock solver node' }))
    fireEvent.click(screen.getByRole('button', { name: 'Restore connections' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByRole('button', { name: 'Saved' })
    const saved = JSON.parse(localStorage.getItem('aoa-workflow-v1')!)
    expect(saved.graph.nodes).toHaveLength(6)
    expect(saved.graph.edges).toHaveLength(5)
    expect(new Set(saved.graph.nodes.map((node: Node) => node.id)).size).toBe(6)
  })

  it('imports portable JSON and migrates an older browser document', async () => {
    mockWorkflowApi()
    render(<App />)
    await screen.findByText('Local engine ready')
    const portable = snapshotWorkflow({ ...defaultWorkflow, name: 'Portable experiment' }, initialNodes, initialEdges)
    fireEvent.change(screen.getByLabelText('Import workflow JSON'), { target: { files: [workflowFile(JSON.stringify(portable))] } })
    await waitFor(() => expect(screen.getByLabelText('Workflow name')).toHaveProperty('value', 'Portable experiment'))
    localStorage.setItem('aoa-workflow-v1', JSON.stringify({ workflow: { ...defaultWorkflow, name: 'Legacy experiment' }, nodes: initialNodes, edges: initialEdges }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load' })).toHaveProperty('disabled', false))
    fireEvent.click(screen.getByRole('button', { name: 'Load' }))
    await waitFor(() => expect(screen.getByLabelText('Workflow name')).toHaveProperty('value', 'Legacy experiment'))
  })

  it('preserves the current editor and saved document when imported data is rejected', async () => {
    mockWorkflowApi(true)
    const previous = JSON.stringify(defaultWorkflow)
    localStorage.setItem('aoa-workflow-v1', previous)
    render(<App />)
    await screen.findByText('Local engine ready')
    fireEvent.change(screen.getByLabelText('Workflow name'), { target: { value: 'Keep my edits' } })
    fireEvent.click(screen.getByRole('button', { name: 'Move test node' }))
    fireEvent.change(screen.getByLabelText('Import workflow JSON'), { target: { files: [workflowFile('{"schema_version":99}')] } })
    await screen.findByText('Unsupported workflow schema version')
    expect(screen.getByLabelText('Workflow name')).toHaveProperty('value', 'Keep my edits')
    expect(screen.getByTestId('canvas-layout').textContent).toContain('"x":900,"y":300')
    expect(localStorage.getItem('aoa-workflow-v1')).toBe(previous)
  })

  it('reports storage failure without marking unsaved work as saved', async () => {
    mockWorkflowApi()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Browser storage is full') })
    render(<App />)
    await screen.findByText('Local engine ready')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByText('Browser storage is full')
    expect(screen.getByRole('button', { name: 'Save' })).toBeTruthy()
  })
})
