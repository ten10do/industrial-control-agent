import { useState } from "react";
import { Check, Copy, Download, ShieldAlert } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";


function ReportPreview({
  markdown,
  safetyNotice,
  exportAllowed = true,
  loadExport,
  downloadName = "control-plan.md",
}) {
  const [copyStatus, setCopyStatus] = useState("idle");
  const [downloadStatus, setDownloadStatus] = useState("idle");

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

  async function getExportContent() {
    if (!exportAllowed) {
      throw new Error("Export is locked");
    }
    return loadExport ? await loadExport() : markdown;
  }

  async function copyReport() {
    setCopyStatus("copying");
    try {
      const exportedMarkdown = await getExportContent();
      if (navigator.clipboard && window.isSecureContext) {
        try {
          await copyWithClipboard(exportedMarkdown);
        } catch {
          copyWithTextArea(exportedMarkdown);
        }
      } else {
        copyWithTextArea(exportedMarkdown);
      }
      setCopyStatus("success");
      window.setTimeout(() => setCopyStatus("idle"), 3500);
    } catch {
      setCopyStatus("error");
      window.setTimeout(() => setCopyStatus("idle"), 3500);
    }
  }

  async function downloadReport() {
    setDownloadStatus("downloading");
    try {
      const exportedMarkdown = await getExportContent();
      const objectUrl = URL.createObjectURL(
        new Blob([exportedMarkdown], { type: "text/markdown;charset=utf-8" }),
      );
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = downloadName;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(objectUrl);
      setDownloadStatus("success");
      window.setTimeout(() => setDownloadStatus("idle"), 3500);
    } catch {
      setDownloadStatus("error");
      window.setTimeout(() => setDownloadStatus("idle"), 3500);
    }
  }

  const isBusy = copyStatus === "copying" || downloadStatus === "downloading";

  return (
    <div className="report-preview">
      <div className="report-toolbar">
        <div>
          <strong>Markdown 完整方案报告</strong>
          <span>复制和下载都会重新经过后端导出权限检查。</span>
        </div>
        <div className="copy-action">
          <button
            className="button button-secondary button-compact"
            type="button"
            onClick={copyReport}
            disabled={!exportAllowed || isBusy}
          >
            {copyStatus === "success"
              ? <Check size={16} aria-hidden="true" />
              : <Copy size={16} aria-hidden="true" />}
            {copyStatus === "copying"
              ? "正在校验并复制"
              : copyStatus === "success"
                ? "复制成功"
                : "复制 Markdown"}
          </button>
          <button
            className="button button-secondary button-compact"
            type="button"
            onClick={downloadReport}
            disabled={!exportAllowed || isBusy}
          >
            <Download size={16} aria-hidden="true" />
            {downloadStatus === "downloading"
              ? "正在校验并下载"
              : downloadStatus === "success"
                ? "下载成功"
                : "下载 Markdown"}
          </button>
          <span className="copy-feedback" aria-live="polite">
            {!exportAllowed
              ? "完成后端安全审批后方可导出。"
              : copyStatus === "error" || downloadStatus === "error"
                ? "导出失败，请检查审批状态后重试。"
                : ""}
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
