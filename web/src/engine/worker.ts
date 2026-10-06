// A Web Worker that runs the Python engine with Pyodide, off the main thread so the page
// stays responsive. It loads once, then answers "run this design against this scenario".

const PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/'

// The engine's own Python files, bundled in as text at build time.
const engineFiles = import.meta.glob('../../../engine/*.py', { query: '?raw', import: 'default', eager: true })

type Pyodide = {
  loadPackage: (names: string[]) => Promise<void>
  runPython: (code: string) => unknown
  FS: { mkdirTree: (path: string) => void; writeFile: (path: string, data: string) => void }
  globals: { get: (name: string) => (...args: string[]) => string }
}

async function startEngine() {
  postMessage({ type: 'status', status: 'Loading Python…' })
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`)
  const pyodide: Pyodide = await loadPyodide({ indexURL: PYODIDE_URL })

  postMessage({ type: 'status', status: 'Loading the engine…' })
  await pyodide.loadPackage(['pydantic', 'pyyaml'])
  pyodide.FS.mkdirTree('/home/pyodide/engine')
  for (const [path, source] of Object.entries(engineFiles)) {
    const name = path.split('/').at(-1)!
    if (name === 'cli.py') continue // the terminal UI needs rich; the browser doesn't
    pyodide.FS.writeFile(`/home/pyodide/engine/${name}`, source as string)
  }
  pyodide.runPython('import sys; sys.path.insert(0, "/home/pyodide")\nfrom engine.web_api import run')
  return pyodide.globals.get('run')
}

const ready = startEngine()
ready.then(
  () => postMessage({ type: 'status', status: 'ready' }),
  (error) => postMessage({ type: 'status', status: `error: ${error}` }),
)

onmessage = async (event: MessageEvent<{ id: number; design: string; scenario: string }>) => {
  const { id, design, scenario } = event.data
  try {
    const run = await ready
    postMessage({ type: 'result', id, result: JSON.parse(run(design, scenario)) })
  } catch (error) {
    postMessage({ type: 'result', id, result: { ok: false, error: String(error) } })
  }
}
