import { useEffect, useRef, useState, type KeyboardEvent } from "react"
import "./ocr-mode-dialog.css"

export type OcrMode = "precise"
export type LiteraryProfile = "auto" | "poetry" | "prose" | "drama" | "commentary" | "other"

export default function OcrModeDialog({ onChoose, onClose, returnFocus }: { onChoose: (mode: OcrMode, profile: LiteraryProfile) => void; onClose: () => void; returnFocus: { current: HTMLButtonElement | null } }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const firstControl = useRef<HTMLSelectElement>(null)
  const [profile, setProfile] = useState<LiteraryProfile>("auto")
  useEffect(() => {
    dialog.current?.showModal()
    firstControl.current?.focus({ preventScroll: true })
    return () => { requestAnimationFrame(() => returnFocus.current?.focus({ preventScroll: true })) }
  }, [returnFocus])
  const trapFocus = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key !== "Tab" || event.altKey || event.ctrlKey || event.metaKey || event.nativeEvent.isComposing) return
    const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not([disabled]), select:not([disabled]), input:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])')]
    const first = controls[0], last = controls[controls.length - 1]
    if (!first || !last) return
    if (event.shiftKey && document.activeElement === first) { event.preventDefault();last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault();first.focus() }
  }
  const choose = () => { dialog.current?.close();onChoose("precise", profile) }
  return <dialog ref={dialog} aria-labelledby="ocr-mode-title" aria-describedby="ocr-mode-description" className="ocr-mode-dialog" onKeyDown={trapFocus} onCancel={onClose} onClose={onClose}>
    <header><div><p className="ocr-mode-eyebrow">자료 가져오기</p><h2 id="ocr-mode-title">고정밀 OCR로 가져오기</h2></div><button className="ocr-mode-close" aria-label="자료 가져오기 닫기" onClick={() => dialog.current?.close()}>×</button></header>
    <p id="ocr-mode-description">정상 텍스트가 있는 PDF는 직접 추출하고, 스캔·이미지는 고정밀 OCR로 읽습니다.</p>
    <label className="ocr-import-profile">자료의 장르<select ref={firstControl} autoFocus aria-label="고정밀 장르 프로필" value={profile} onChange={e => setProfile(e.target.value as LiteraryProfile)}><option value="auto">미지정 · 구조 검수</option><option value="poetry">시</option><option value="prose">소설·산문</option><option value="drama">희곡</option><option value="commentary">문학 해설</option><option value="other">기타</option></select></label>
    <div className="ocr-import-summary"><strong>원본과 대조하고 확정하세요</strong><p>여러 인식 결과와 구조 분석으로 불일치·누락 후보를 표시합니다. 필요한 영역만 다시 인식할 수 있습니다.</p><p>자료에 따라 처리 시간과 메모리가 더 필요할 수 있습니다.</p></div>
    <button className="ocr-mode-submit" onClick={choose}>파일 선택 →</button>
    <p className="ocr-mode-note">검수 후 확정하며, 기존 확정 원문은 자동으로 바뀌지 않습니다.</p>
  </dialog>
}
