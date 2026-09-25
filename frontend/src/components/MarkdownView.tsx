import katex from "katex";
import type { Block } from "../types/api";

function renderMath(latex: string, display: boolean): string {
  try {
    return katex.renderToString(latex, {
      displayMode: display,
      throwOnError: false,
      output: "html",
      trust: false,
      strict: "ignore",
    });
  } catch {
    return `<code>${escapeHtml(latex)}</code>`;
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

interface Seg { kind: "text" | "math"; value: string }

function splitInlineMath(text: string): Seg[] {
  const segs: Seg[] = [];
  const re = /\$([^$\n]+)\$/g;
  let last = 0;
  for (let m = re.exec(text); m !== null; m = re.exec(text)) {
    if (m.index > last) segs.push({ kind: "text", value: text.slice(last, m.index) });
    segs.push({ kind: "math", value: m[1] });
    last = m.index + m[0].length;
  }
  if (last < text.length) segs.push({ kind: "text", value: text.slice(last) });
  return segs;
}

function TextWithMath({ text }: { text: string }) {
  return (
    <>
      {splitInlineMath(text).map((s, i) =>
        s.kind === "math" ? (
          <span key={i} dangerouslySetInnerHTML={{ __html: renderMath(s.value, false) }} />
        ) : (
          <span key={i}>{s.value}</span>
        ),
      )}
    </>
  );
}

export default function MarkdownView({ blocks, pageNo }: { blocks: Block[]; pageNo: number }) {
  return (
    <div className="md-body">
      {blocks.length === 0 && <p className="muted">Trang chưa có nội dung chữ nào.</p>}
      {blocks.map((b) => {
        switch (b.type) {
          case "skipped_visual":
            return (
              <div key={b.block_id} className="visual-note">
                ⚠️ Hình minh họa tại trang PDF {pageNo} chưa được xử lý
                {b.bbox ? ` (vùng: ${b.bbox.map(Math.round).join(", ")})` : ""}.
              </div>
            );
          case "formula":
            return (
              <span
                key={b.block_id}
                className="formula-block"
                dangerouslySetInnerHTML={{ __html: renderMath(b.text ?? "", true) }}
              />
            );
          case "heading":
            return <h3 key={b.block_id}><TextWithMath text={b.text ?? ""} /></h3>;
          case "table":
            return <pre key={b.block_id} className="tablepre">{b.text}</pre>;
          case "list":
            return (
              <ul key={b.block_id}>
                {(b.text ?? "").split("\n").filter(Boolean).map((li, i) => (
                  <li key={i}><TextWithMath text={li} /></li>
                ))}
              </ul>
            );
          default:
            return <p key={b.block_id}><TextWithMath text={b.text ?? ""} /></p>;
        }
      })}
    </div>
  );
}
