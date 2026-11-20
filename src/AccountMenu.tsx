import { useEffect, useRef, useState } from "react"
import { api, resetApiSession, errorMessage, type AccountSession } from "./api"

export default function AccountMenu({ account, onLogout, onAdmin }: {
  account: AccountSession
  onLogout: () => Promise<boolean>
  onAdmin: () => void
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [withdrawal, setWithdrawal] = useState(false)
  const [confirmation, setConfirmation] = useState("")
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { if (open) dialog.current?.showModal(); else dialog.current?.close() }, [open])
  const name = account.displayName || account.email || "내 계정"
  return <div className="account-controls">
    <button className="account-trigger" aria-label="내 계정" aria-haspopup="dialog" onClick={() => setOpen(true)}>
      {account.pictureUrl ? <img className="account-avatar" src={account.pictureUrl} alt="" referrerPolicy="no-referrer" /> : <span className="account-avatar" aria-hidden="true">{name.slice(0, 1)}</span>}
      <span className="account-trigger-label">{name}</span>
    </button>
    <dialog ref={dialog} className="gb-modal account-dialog" aria-labelledby="account-title" onCancel={() => setOpen(false)} onClose={() => setOpen(false)}>
      <button className="modal-close icon-btn" aria-label="계정 창 닫기" onClick={() => setOpen(false)}>×</button>
      <h2 id="account-title">내 계정</h2>
      {account.pictureUrl && <img className="account-avatar account-photo" src={account.pictureUrl} alt="Google 프로필" referrerPolicy="no-referrer" />}
      <dl>
        <dt>Google 프로필 이름</dt><dd>{account.displayName || "현재 로그인에서 제공되지 않음"}</dd>
        <dt>Google 이메일</dt><dd>{account.email || "제공되지 않음"}</dd>
        <dt>로그인 방식</dt><dd>{account.loginMethod || "Google OIDC"}</dd>
        <dt>권한</dt><dd>{account.role}</dd>
        <dt>승인 상태</dt><dd>승인 완료 · {account.status}</dd>
      </dl>
      <p>내 글 목록에서 원문과 분석을 열람하고 글별 삭제를 요청할 수 있습니다. 그 밖의 개인정보 문의는 알고 계신 서비스 운영자에게 직접 연락해 주세요.</p>
      {withdrawal && <div role="group" aria-label="계정 탈퇴 확인">
        <p>탈퇴하면 즉시 접근과 세션이 차단되며 개인 글과 종속 자료를 정리합니다. 계정·동의 기록은 2개월 후 삭제하거나 공용 자료의 최소 익명 소유권 참조만 남깁니다. 취소할 수 없습니다.</p>
        <label>확인하려면 ‘탈퇴’를 입력하세요 <input type="text" style={{display:"block",width:"100%",minHeight:44,padding:"8px 12px",border:"1px solid currentColor",borderRadius:8,margin:"8px 0",background:"white",color:"#233e31"}} aria-label="탈퇴 확인 입력" value={confirmation} onChange={e => setConfirmation(e.target.value)} disabled={busy} /></label>
        <button className="gb-outline" disabled={busy || confirmation !== "탈퇴"} onClick={async () => {
          setBusy(true); setError("");
          try {
            const result = await api.post<{accountDisabled:boolean;filesPending:number}>("/account/withdraw", {confirmation:"WITHDRAW"});
            if (!result.accountDisabled) throw new Error("탈퇴 완료를 확인할 수 없습니다.");
            window.alert(result.filesPending ? "계정 접근을 차단했습니다. 일부 파일 정리는 아직 진행 중이며 운영자가 확인해야 합니다." : "계정 탈퇴와 개인 자료 정리가 완료되었습니다. 계정·동의 기록은 2개월 후 정리됩니다.");
            resetApiSession(); window.dispatchEvent(new Event("geulbit-auth-required")); setOpen(false);
          } catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
        }}>계정 탈퇴 확정</button>
        <button className="gb-outline" disabled={busy} onClick={() => {setWithdrawal(false);setConfirmation("")}}>취소</button>
      </div>}
      {error && <p role="alert">{error}</p>}
      <div className="account-actions">
        <button className="gb-outline" disabled={busy} onClick={() => {setWithdrawal(true);setConfirmation("");setError("")}}>개인정보 관리·계정 탈퇴</button>
        {account.role === "ADMIN" && <button className="gb-outline" onClick={() => { setOpen(false); onAdmin() }}>관리자 운영</button>}
        <button className="gb-outline" disabled={busy} onClick={async () => { setBusy(true); setError(""); try { if (!await onLogout()) setError("작성 중인 글을 저장할 수 없습니다. 저장 상태를 확인한 후 다시 시도해 주세요.") } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) } }}>{busy ? "로그아웃 중…" : "로그아웃"}</button>
      </div>
    </dialog>
  </div>
}
