import { AlertTriangle, X } from "lucide-react";


function ErrorMessage({ message, onDismiss }) {
  return (
    <div className="error-message" role="alert">
      <AlertTriangle size={19} aria-hidden="true" />
      <span>{message}</span>
      <button
        type="button"
        className="icon-button error-dismiss"
        onClick={onDismiss}
        title="关闭错误提示"
        aria-label="关闭错误提示"
      >
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}


export default ErrorMessage;
