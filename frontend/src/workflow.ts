import type { Connection, Edge, Node } from '@xyflow/react'

export type Variable = { name: string; lower: number; upper: number }
export type Constraint = { name: string; expression: string; relation: '<=' | '>='; bound: number }
export type Workflow = {
  schema_version: 1
  name: string
  variables: Variable[]
  doe: { method: 'lhs' | 'random'; samples: number; seed: number }
  solver: { kind: 'sphere' | 'rosenbrock' | 'branin'; retry_attempts: number }
  objective: { name: string; expression: string; direction: 'minimize' | 'maximize' }
  constraints: Constraint[]
  optimizer: { engine: 'optuna_tpe'; trials: number; seed: number }
  graph: {
    nodes: { id: string; type: string; version?: 1; position?: { x: number; y: number } | null }[]
    edges: { source: string; target: string; source_handle: string; target_handle: string }[]
  }
}
export type FlowNodeData = { title: string; meta: string; color: string; inputHandle?: string; outputHandle?: string; active?: boolean; [key: string]: unknown }
export const defaultWorkflow: Workflow = {
  schema_version: 1,
  name: 'Sphere benchmark',
  variables: [
    { name: 'x', lower: -5, upper: 5 },
    { name: 'y', lower: -5, upper: 5 },
  ],
  doe: { method: 'lhs', samples: 20, seed: 42 },
  solver: { kind: 'sphere', retry_attempts: 1 },
  objective: { name: 'objective', expression: 'sphere', direction: 'minimize' },
  constraints: [],
  optimizer: { engine: 'optuna_tpe', trials: 50, seed: 43 },
  graph: {
    nodes: [
      { id: 'variables', type: 'design_variables' }, { id: 'doe', type: 'doe' },
      { id: 'solver', type: 'mock_solver' }, { id: 'objective', type: 'objective' },
      { id: 'optimizer', type: 'optuna_optimizer' }, { id: 'results', type: 'results' },
    ],
    edges: [
      { source: 'variables', target: 'doe', source_handle: 'design_space', target_handle: 'design_space' },
      { source: 'doe', target: 'solver', source_handle: 'candidate_batch', target_handle: 'candidate' },
      { source: 'solver', target: 'objective', source_handle: 'solver_result', target_handle: 'solver_result' },
      { source: 'objective', target: 'optimizer', source_handle: 'objective_vector', target_handle: 'evaluation_result' },
      { source: 'optimizer', target: 'results', source_handle: 'run_summary', target_handle: 'run_summary' },
    ],
  },
}

export const initialNodes: Node<FlowNodeData>[] = [
  { id: 'variables', type: 'workflow', position: { x: 48, y: 142 }, data: { title: 'Design variables', meta: '2 continuous · bounded', color: 'mint', outputHandle: 'design_space' } },
  { id: 'doe', type: 'workflow', position: { x: 286, y: 142 }, data: { title: 'Design of experiments', meta: 'LHS · 20 samples', color: 'blue', inputHandle: 'design_space', outputHandle: 'candidate_batch' } },
  { id: 'solver', type: 'workflow', position: { x: 524, y: 142 }, data: { title: 'Mock solver', meta: 'Sphere benchmark', color: 'violet', inputHandle: 'candidate', outputHandle: 'solver_result' } },
  { id: 'objective', type: 'workflow', position: { x: 762, y: 142 }, data: { title: 'Objective + constraints', meta: 'Minimize sphere', color: 'amber', inputHandle: 'solver_result', outputHandle: 'objective_vector' } },
  { id: 'optimizer', type: 'workflow', position: { x: 1000, y: 142 }, data: { title: 'Optuna TPE', meta: '50 adaptive trials', color: 'pink', inputHandle: 'evaluation_result', outputHandle: 'run_summary' } },
  { id: 'results', type: 'workflow', position: { x: 1238, y: 142 }, data: { title: 'Results', meta: 'History · CSV export', color: 'green', inputHandle: 'run_summary' } },
]

export const initialEdges: Edge[] = initialNodes.slice(0, -1).map((node, index) => ({
  id: `e${index + 1}`,
  source: node.id,
  target: initialNodes[index + 1].id,
  sourceHandle: node.data.outputHandle,
  targetHandle: initialNodes[index + 1].data.inputHandle,
  animated: false,
  style: { stroke: '#566277', strokeWidth: 1.5 },
}))


// Store domain data and layout only; React Flow rendering state is reconstructed.
export function snapshotWorkflow(workflow: Workflow, nodes: Node<FlowNodeData>[], edges: Edge[]): Workflow {
  return {
    ...workflow,
    graph: {
      nodes: nodes.map((node) => ({
        id: node.id,
        type: workflow.graph.nodes.find((entry) => entry.id === node.id)?.type
          ?? defaultWorkflow.graph.nodes.find((entry) => entry.id === node.id)?.type ?? '',
        version: workflow.graph.nodes.find((entry) => entry.id === node.id)?.version ?? 1,
        position: node.position,
      })),
      edges: edges.map((edge) => ({
        source: edge.source, target: edge.target,
        source_handle: edge.sourceHandle ?? '', target_handle: edge.targetHandle ?? '',
      })),
    },
  }
}

export function canvasFromWorkflow(workflow: Workflow) {
  const nodes = workflow.graph.nodes.map((entry) => {
    const template = initialNodes.find((node) => node.id === entry.id)
    if (!template) throw new Error(`Unsupported workflow node: ${entry.id}`)
    return { ...template, position: entry.position ?? template.position, data: { ...template.data } }
  })
  const edges: Edge[] = workflow.graph.edges.map((edge, index) => ({
    id: `e${index + 1}`, source: edge.source, target: edge.target,
    sourceHandle: edge.source_handle, targetHandle: edge.target_handle,
    style: { stroke: '#566277', strokeWidth: 1.5 },
  }))
  return { nodes, edges }
}

export function parseWorkflowDocument(source: string): unknown {
  const parsed = JSON.parse(source)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Choose an AOA workflow JSON object.')
  }
  // Migrate the browser envelope written by the first mock MVP.
  if ('workflow' in parsed) {
    if (!Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges)) {
      throw new Error('The saved browser workflow is missing its canvas.')
    }
    return snapshotWorkflow(parsed.workflow, parsed.nodes, parsed.edges)
  }
  return parsed
}

export function connectionError(connection: Connection | Edge, nodes: Node[], edges: Edge[]): string | null {
  if (!nodes.some((node) => node.id === connection.source) || !nodes.some((node) => node.id === connection.target)) {
    return 'Add both nodes before connecting them.'
  }
  const matches = (edge: Edge) => edge.source === connection.source && edge.target === connection.target
    && edge.sourceHandle === connection.sourceHandle && edge.targetHandle === connection.targetHandle
  if (!initialEdges.some(matches)) return 'Connect adjacent pipeline nodes using their matching ports.'
  if (edges.some(matches)) return 'These ports are already connected.'
  return null
}
