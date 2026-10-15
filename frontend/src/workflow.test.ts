import { describe, expect, it } from 'vitest'
import { canvasFromWorkflow, connectionError, defaultWorkflow, initialEdges, initialNodes, parseWorkflowDocument, snapshotWorkflow } from './workflow'

describe('workflow canvas contract', () => {
  it('keeps layout and domain settings while rebuilding rendering metadata', () => {
    const moved = initialNodes.map((node) => ({ ...node, position: { x: node.position.x + 30, y: -70 }, selected: true }))
    const snapshot = snapshotWorkflow(defaultWorkflow, moved, initialEdges)
    const restored = canvasFromWorkflow(snapshot)
    expect(restored.nodes.map((node) => node.position)).toEqual(moved.map((node) => node.position))
    expect(restored.nodes[0]).not.toHaveProperty('selected')
    expect(snapshotWorkflow(snapshot, restored.nodes, restored.edges)).toEqual(snapshot)
  })

  it('restores older run snapshots with the default canvas layout', () => {
    expect(canvasFromWorkflow(defaultWorkflow).nodes.map((node) => node.position)).toEqual(initialNodes.map((node) => node.position))
    const legacy = JSON.stringify({ workflow: defaultWorkflow, nodes: initialNodes, edges: initialEdges })
    expect(parseWorkflowDocument(legacy)).toEqual(snapshotWorkflow(defaultWorkflow, initialNodes, initialEdges))
    expect(() => parseWorkflowDocument('null')).toThrow('JSON object')
    expect(() => parseWorkflowDocument('{"workflow":{}}')).toThrow('missing its canvas')
  })

  it('allows only missing adjacent typed connections with both endpoints present', () => {
    const connection = initialEdges[0]
    expect(connectionError(connection, initialNodes, [])).toBeNull()
    expect(connectionError(connection, initialNodes, initialEdges)).toMatch(/already connected/)
    expect(connectionError({ ...connection, sourceHandle: 'wrong_port' }, initialNodes, [])).toMatch(/matching ports/)
    expect(connectionError({ ...connection, source: 'results', target: 'variables' }, initialNodes, [])).toMatch(/matching ports/)
    expect(connectionError(connection, initialNodes.slice(1), [])).toMatch(/both nodes/)
  })
})
