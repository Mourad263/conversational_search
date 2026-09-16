export default function ChatInput({ value, onChange, onSend, disabled }) {
  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
    // Shift+Enter: default textarea behavior (newline) is left alone.
  }

  return (
    <div className="chat-input-row">
      <textarea
        className="chat-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Type your message..."
        rows={1}
        disabled={disabled}
      />
      <button className="send-button" onClick={onSend} disabled={disabled || !value.trim()}>
        Send
      </button>
    </div>
  );
}
