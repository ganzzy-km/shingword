/** Presentation only: one existing essay remains one book, with no separate state. */
export default function BookCover({ title, work }: { title: string; work: string }) {
  return <div className="book-cover">
    <div className="book-spine" />
    <div className="cover-border">
      <span className="cover-kicker">GEULBIT · ESSAY</span>
      <h2>{title || "제목 없는 글"}</h2>
      <div className="cover-line" />
      <span className="cover-work">{work || "나의 에세이"}</span>
      <span className="cover-emblem" aria-hidden="true">❧</span>
      <span className="cover-footer">글 빛</span>
    </div>
  </div>
}
