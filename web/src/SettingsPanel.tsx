// Edit the selected component or wire, and export the finished design.
import type { Edge as FlowEdge, Node as FlowNode } from '@xyflow/react'
import type { Dispatch, SetStateAction } from 'react'
import type { Component, Edge } from './design'
import { designProblems, downloadYaml, toDesign } from './exportDesign'
import { COMPONENT_FIELDS, EDGE_FIELDS, type Field } from './fields'
import { edgeLabel } from './layout'
import './SettingsPanel.css'

type Props = {
  nodes: FlowNode[]
  edges: FlowEdge[]
  setNodes: Dispatch<SetStateAction<FlowNode[]>>
  setEdges: Dispatch<SetStateAction<FlowEdge[]>>
}

type Values = Record<string, unknown>

function FieldInput({ field, values, onChange }: { field: Field; values: Values; onChange: (key: string, value: unknown) => void }) {
  const id = `field-${field.key}`
  const value = values[field.key]
  return (
    <div className="settings__field">
      <label htmlFor={id}>{field.label}</label>
      {field.kind === 'number' && (
        <input
          id={id}
          type="number"
          min={field.min}
          step={field.step ?? 'any'}
          placeholder={field.hint}
          value={value === undefined ? '' : String(value)}
          onChange={(e) => onChange(field.key, e.target.value === '' ? undefined : Number(e.target.value))}
        />
      )}
      {field.kind === 'toggle' && (
        <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(field.key, e.target.checked || undefined)} />
      )}
      {field.kind === 'choice' && (
        <select id={id} value={(value as string) ?? field.choices?.[0] ?? ''} onChange={(e) => onChange(field.key, e.target.value)}>
          {field.choices?.map((choice) => (
            <option key={choice} value={choice}>
              {choice.replaceAll('_', ' ')}
            </option>
          ))}
        </select>
      )}
    </div>
  )
}

function withValue(values: Values, key: string, value: unknown): Values {
  const next = { ...values }
  if (value === undefined) delete next[key] // blank means "use the engine's default"
  else next[key] = value
  return next
}

export function SettingsPanel({ nodes, edges, setNodes, setEdges }: Props) {
  const node = nodes.find((n) => n.selected)
  const edge = node ? undefined : edges.find((e) => e.selected)
  const design = toDesign(nodes, edges)
  const problems = designProblems(design)

  let body
  if (node) {
    const component = (node.data as { component: Component }).component
    const databases = nodes
      .map((n) => (n.data as { component: Component }).component)
      .filter((c) => c.type === 'database')
      .map((c) => c.id)
    const fields = COMPONENT_FIELDS.filter((f) => f.types.includes(component.type)).map(({ field }) =>
      field.key === 'replica_of' ? { ...field, choices: databases } : field,
    )
    const update = (key: string, value: unknown) =>
      setNodes((all) =>
        all.map((n) => (n.id === node.id ? { ...n, data: { ...n.data, component: withValue(component, key, value) } } : n)),
      )
    body = (
      <>
        <h2 className="settings__title">{component.id}</h2>
        {fields.length === 0 && <p className="settings__note">Users have no settings. Traffic comes from the scenario.</p>}
        {fields.map((f) => (
          <FieldInput key={f.key} field={f} values={component} onChange={update} />
        ))}
      </>
    )
  } else if (edge) {
    const data = ((edge.data as { edge?: Edge })?.edge ?? { source: edge.source, target: edge.target }) as Edge
    const update = (key: string, value: unknown) =>
      setEdges((all) =>
        all.map((e) => {
          if (e.id !== edge.id) return e
          const next = withValue(data, key, value) as Edge
          return { ...e, label: edgeLabel(next), data: { ...e.data, edge: next } }
        }),
      )
    body = (
      <>
        <h2 className="settings__title">
          {edge.source} → {edge.target}
        </h2>
        {EDGE_FIELDS.map((f) => (
          <FieldInput key={f.key} field={f} values={data} onChange={update} />
        ))}
      </>
    )
  } else {
    body = <p className="settings__note">Select a component or a wire to change its settings.</p>
  }

  return (
    <aside className="settings" aria-label="Settings">
      <div className="settings__body">{body}</div>
      <div className="settings__footer">
        {problems.map((p) => (
          <p key={p} className="settings__problem">
            {p}
          </p>
        ))}
        <button type="button" disabled={problems.length > 0} onClick={() => downloadYaml(design)}>
          Export design
        </button>
      </div>
    </aside>
  )
}
