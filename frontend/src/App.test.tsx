// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('@xyflow/react', async () => {
  const React = await import('react')
  const passthrough = ({ children }: { children?: React.ReactNode }) => React.createElement('div', null, children)
  return {
    Background: passthrough,
    BackgroundVariant: { Dots: 'dots' },
    Controls: passthrough,
    Handle: () => null,
    MiniMap: passthrough,
    Position: { Left: 'left', Right: 'right' },
    ReactFlow: passthrough,
    addEdge: (edge: unknown, edges: unknown[]) => [...edges, edge],
    useEdgesState: (initial: unknown[]) => {
      const [value, setValue] = React.useState(initial)
      return [value, setValue, () => {}]
    },
    useNodesState: (initial: unknown[]) => {
      const [value, setValue] = React.useState(initial)
      return [value, setValue, () => {}]
    },
  }
})

const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
})

afterEach(() => {
  cleanup()
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
    const picker = document.querySelector('input[type="file"]')
    expect(picker).not.toBeNull()
    fireEvent.change(picker!, { target: { files: [file] } })

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
