// Which settings the panel shows for each kind of component and for wires.
// Keys match the engine's field names (engine/models.py), so exported designs run as-is.
import type { ComponentType } from './design'

export type Field = {
  key: string
  label: string
  kind: 'number' | 'toggle' | 'choice'
  choices?: string[] // for 'choice'; for replica_of the panel fills in the databases
  optional?: boolean // blank means "not set" (the engine's default)
  min?: number
  step?: number
  hint?: string
}

const ALL_BUT_CLIENT: ComponentType[] = ['load_balancer', 'app_server', 'database', 'cache', 'replica', 'queue']

export const COMPONENT_FIELDS: { field: Field; types: ComponentType[] }[] = [
  { types: ALL_BUT_CLIENT, field: { key: 'instances', label: 'Instances', kind: 'number', min: 1, step: 1 } },
  {
    types: ['app_server'],
    field: { key: 'max_instances', label: 'Autoscale up to', kind: 'number', optional: true, min: 1, step: 1, hint: 'Blank: fixed size' },
  },
  { types: ['app_server'], field: { key: 'warmup_s', label: 'Boot time (s)', kind: 'number', optional: true, min: 0 } },
  {
    types: ['load_balancer', 'app_server', 'database', 'cache', 'replica'],
    field: { key: 'timeout_ms', label: 'Drop requests waiting over (ms)', kind: 'number', optional: true, min: 1, hint: 'Blank: wait forever' },
  },
  { types: ['app_server'], field: { key: 'balancing', label: 'Balancing', kind: 'choice', choices: ['round_robin', 'least_outstanding'] } },
  { types: ['app_server'], field: { key: 'rollout', label: 'Deploys', kind: 'choice', choices: ['global', 'canary'] } },
  { types: ['app_server'], field: { key: 'cpu_guard', label: 'CPU guard', kind: 'toggle' } },
  { types: ['cache'], field: { key: 'ttl_s', label: 'Cache TTL (s)', kind: 'number', optional: true, min: 1 } },
  { types: ['replica'], field: { key: 'replica_of', label: 'Copies database', kind: 'choice', choices: [] } },
  {
    types: ['queue'],
    field: { key: 'partitions', label: 'Partitions', kind: 'number', optional: true, min: 1, step: 1, hint: 'Max consumers reading at once (default 4)' },
  },
  {
    types: ['queue'],
    field: { key: 'max_backlog', label: 'Max backlog (messages)', kind: 'number', optional: true, min: 1, step: 1000, hint: 'Default 1,000,000; past it, messages are lost' },
  },
  { types: ['database'], field: { key: 'failover', label: 'Failover', kind: 'choice', choices: ['within_region', 'cross_region'] } },
]

export const EDGE_FIELDS: Field[] = [
  { key: 'calls_per_request', label: 'Calls per request', kind: 'number', optional: true, min: 0.1, step: 0.1 },
  { key: 'parallel', label: 'Make calls in parallel', kind: 'toggle' },
  { key: 'retries', label: 'Retries', kind: 'number', optional: true, min: 0, step: 1 },
  { key: 'retry_delay_ms', label: 'Retry delay (ms)', kind: 'number', optional: true, min: 1 },
  { key: 'backoff', label: 'Backoff', kind: 'choice', choices: ['fixed', 'exponential'] },
  { key: 'jitter', label: 'Jitter', kind: 'toggle' },
  { key: 'retry_budget', label: 'Retry budget (0–1)', kind: 'number', optional: true, min: 0.01, step: 0.05 },
  { key: 'caller_timeout_ms', label: 'Caller gives up after (ms)', kind: 'number', optional: true, min: 1 },
  { key: 'pool_size', label: 'Connection pool', kind: 'number', optional: true, min: 1, step: 1 },
]
