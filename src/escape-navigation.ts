import { useEffect, useRef } from "react"

type Kind = "modal" | "panel" | "navigation"
type Action = () => void | boolean | Promise<void | boolean>
type Layer = { kind: Kind; priority: number; element?: { current: HTMLElement | null }; action: Action }
const layers = new Map<number, Layer>()
const rank: Record<Kind, number> = { modal: 300, panel: 200, navigation: 100 }
let sequence = 0, installed = false, pending = false
const visible = (element: HTMLElement | null) => !!element && !element.closest("[hidden],[inert]") && element.getClientRects().length > 0

// Single application entry point. Native controls/IME keep their own Escape.
function escape(event: KeyboardEvent) {
  if (event.key !== "Escape" || event.defaultPrevented || event.isComposing || event.repeat || event.altKey || event.ctrlKey || event.metaKey) return
  if (event.target instanceof HTMLSelectElement) {
    try { if (event.target.matches(":open")) return } catch { return }
  }
  const consume = () => { event.preventDefault();event.stopImmediatePropagation() }
  const native = Array.from(document.querySelectorAll<HTMLDialogElement>("dialog[open]")).filter(visible)
  const top = native.find(d => d.contains(document.activeElement)) ?? native.at(-1)
  if (top) {
    consume()
    // Honor each dialog's existing dirty/busy cancellation guard.
    const cancelled = new Event("cancel", { cancelable: true })
    top.dispatchEvent(cancelled)
    if (!cancelled.defaultPrevented && top.open) top.close()
    return
  }
  const target = [...layers.entries()].filter(([, l]) => !l.element || visible(l.element.current))
    .sort((a, b) => rank[b[1].kind] + b[1].priority - rank[a[1].kind] - a[1].priority || b[0] - a[0])[0]?.[1]
  if (!target) return
  if (pending && target.kind !== "modal") { consume();return }
  const action = target.action()
  if (action === false) return
  consume()
  if (action instanceof Promise) {
    pending = true
    void action.catch(error => console.error("뒤로 가기 처리 실패", error)).finally(() => { pending = false })
  }
}

export function useEscapeLayer(kind: Kind, enabled: boolean, action: Action, element?: { current: HTMLElement | null }, priority = 0) {
  const current = useRef(action);current.current = action
  useEffect(() => {
    if (!enabled) return
    const id = ++sequence;layers.set(id, { kind, priority, element, action: () => current.current() })
    if (!installed) { window.addEventListener("keydown", escape);installed = true }
    return () => {
      layers.delete(id)
      if (!layers.size && installed) { window.removeEventListener("keydown", escape);installed = false }
    }
  }, [kind, enabled, element, priority])
}
