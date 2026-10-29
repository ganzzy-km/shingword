import { useEffect, useRef, useState } from "react"
import { api, errorMessage } from "./api"

export default function TextSourceDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [title, setTitle] = useState("")
  const [author, setAuthor] = useState("")
  const [content, setContent] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  useEffect(() => { dialog.current?.showModal() }, [])

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy || !title.trim() || !content.trim()) return
    const form = new FormData()
    form.append("file", new File([content], "직접 입력한 작품.txt", { type: "text/plain;charset=utf-8" }))
    form.append("title", title.trim())
    form.append("author", author.trim())
    form.append("scope", "PRIVATE")
    form.append("documentType", "TEXT")
    form.append("accessMode", "VIEW")
    setBusy(true)
    setError("")
    try {
      await api.post("/source-documents", form)
      onSaved()
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }

  return <dialog ref={dialog} aria-labelledby="text-source-heading" onCancel={event => { if (busy) event.preventDefault(); else onClose() }} onClose={onClose} className="w-[calc(100%_-_2rem)] max-w-3xl max-h-[90vh] rounded-xl bg-white p-5 sm:p-7 overflow-auto">
    <form onSubmit={event => void save(event)} className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 id="text-source-heading" className="text-xl font-semibold">텍스트로 작품 등록</h2>
        <button type="button" disabled={busy} onClick={onClose} className="rounded-lg border px-3 py-2 disabled:opacity-50">닫기</button>
      </div>
      <p className="text-sm text-[#64748B]">직접 적거나 붙여 넣은 글을 개인 작품 자료로 저장합니다. 파일 자료처럼 열람하고 분석할 글에 연결할 수 있습니다.</p>
      <label className="block text-sm font-medium">작품 제목<input autoFocus required maxLength={200} value={title} onChange={event => setTitle(event.target.value)} disabled={busy} className="block w-full mt-2 border rounded-lg p-3" /></label>
      <label className="block text-sm font-medium">작가 (선택)<input maxLength={200} value={author} onChange={event => setAuthor(event.target.value)} disabled={busy} className="block w-full mt-2 border rounded-lg p-3" /></label>
      <label htmlFor="text-source-content" className="block text-sm font-medium">작품 본문</label>
      <textarea id="text-source-content" required rows={12} value={content} onChange={event => setContent(event.target.value)} disabled={busy} placeholder="작품 본문을 입력하거나 붙여 넣어 주세요." className="block w-full border rounded-lg p-3 leading-7 resize-y" />
      {error && <p role="alert" className="text-sm text-[#C62828]">{error} 입력한 글은 그대로 유지됩니다.</p>}
      <div className="flex justify-end"><button type="submit" disabled={busy || !title.trim() || !content.trim()} className="rounded-lg bg-[#087F8C] text-white px-5 py-3 disabled:opacity-50">{busy ? "등록 중…" : "작품 등록"}</button></div>
    </form>
  </dialog>
}
