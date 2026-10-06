// The components a player can drag onto the canvas.
import type { ComponentType } from './design'
import './Palette.css'

export const PALETTE: { type: ComponentType; name: string; idBase: string; price: number }[] = [
  { type: 'load_balancer', name: 'Load balancer', idBase: 'lb', price: 40 },
  { type: 'app_server', name: 'App server', idBase: 'app', price: 90 },
  { type: 'cache', name: 'Cache', idBase: 'cache', price: 120 },
  { type: 'database', name: 'Database', idBase: 'db', price: 380 },
  { type: 'replica', name: 'Read replica', idBase: 'replica', price: 260 },
]

export const DRAG_FORMAT = 'application/x-scale-or-fail-component'

export function Palette() {
  return (
    <aside className="palette" aria-label="Components">
      <h2 className="palette__title">Components</h2>
      {PALETTE.map((item) => (
        <div
          key={item.type}
          className="palette__item"
          draggable
          onDragStart={(event) => {
            event.dataTransfer.setData(DRAG_FORMAT, item.type)
            event.dataTransfer.effectAllowed = 'move'
          }}
        >
          <span>{item.name}</span>
          <span className="palette__price">${item.price}/hr</span>
        </div>
      ))}
      <p className="palette__hint">
        Drag a component onto the canvas. Drag from a box’s right dot to another box to wire them.
        Select something and press Backspace to delete it.
      </p>
    </aside>
  )
}
