import { useState } from "react";
import { Check, Copy, ShieldAlert } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";


function ReportPreview({ markdown, safetyNotice }) {
  const [copyStatus, setCopyStatus] = useState("idle");

  function copyWithTextArea(text) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.setAttribute("readonly", "");
    textArea.style.position = "fixed";
    textArea.style.opacity = "0";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    textArea.setSelectionRange(0, text.length);
    const copied = document.execCommand("copy");
    document.body.removeChild(textArea);
    if (!copied) {
      throw new Error("Copy command failed");
    }
  }

  function copyWithClipboard(text) {
    return new Promise((resolve, reject) => {
      const timeoutId = window.setTimeout(() => reject(new Error("Clipboard timed out")), 1500);
      navigator.clipboard.writeText(text).then(
        () => {
          window.clearTimeout(timeoutId);
          resolve();
        },
        (error) => {
          window.clearTimeout(timeoutId);
          reject(error);
        },
      );
    });
  }

  async function copyReport() {
    setCopyStatus("copying");
    try {
      if (navigator.clipboard && window.isSecureContext) {
        try {
          await copyWithClipboard(markdown);
        } catch {
          copyWithTextArea(markdown);
        }
      } else {
        copyWithTextArea(markdown);
      }
      setCopyStatus("success");
      window.setTimeout(() => setCopyStatus("idle"), 3500);
    } catch {
      setCopyStatus("error");
      window.setTimeout(() => setCopyStatus("idle"), 3500);
    }
  }

  return (
    <div className="report-preview">
      <div className="report-toolbar">
        <div>
          <strong>Markdown 完整方案报告</strong>
          <span>可复制到课程设计文档、调试记录或项目说明中。</span>
        </div>
        <div className="copy-action">
          <button className="button button-secondary button-compact" type="button" onClick={copyReport}>
            {copyStatus === "success" ? (
              <Check size={16} aria-hidden="true" />
            ) : (
              <Copy size={16} aria-hidden="true" />
            )}
            {copyStatus === "copying"
              ? "正在复制"
              : copyStatus === "success"
                ? "复制成功"
                : "复制 Markdown"}
          </button>
          <span className="copy-feedback" aria-live="polite">
            {copyStatus === "error" ? "复制失败，请手动选择报告内容。" : ""}
          </span>
        </div>
      </div>

      <article className="markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
      </article>

      <div className="report-safety-notice">
        <ShieldAlert size={18} aria-hidden="true" />
        <span>安全提示：{safetyNotice}</span>
      </div>
    </div>
  );
}


export default ReportPreview;
