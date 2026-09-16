import { useEffect, useRef, useState } from "react";
import { getSessionId, newSessionId } from "./session.js";
import { sendMessage } from "./api.js";
import MessageBubble from "./components/MessageBubble.jsx";
import ChatInput from "./components/ChatInput.jsx";

// Exact backend greeting (src/response/messages.py's GREETING_EN) --
// hardcoded here deliberately: it is shown with zero API/LLM calls.
const GREETING_EN = "Hello! How can I help you?";
const ERROR_TEXT = "Sorry, I'm having trouble reaching the server. Please try again in a moment.";

function makeGreetingTurn() {
  return { id: crypto.randomUUID(), role: "assistant", text: GREETING_EN, products: [], recommendations: [] };
}

export default function App() {
  const [sessionId, setSessionId] = useState(() => getSessionId());
  const [messages, setMessages] = useState(() => [makeGreetingTurn()]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending]);

  async function handleSend() {
    const text = input.trim();
    if (!text || pending) return; // guards against duplicate submission while loading

    const userTurn = { id: crypto.randomUUID(), role: "user", text };
    setMessages((prev) => [...prev, userTurn]);
    setInput("");
    setPending(true);

    try {
      // Exactly one backend call per Send -- assistant_message/products/
      // recommendations all arrive together in this one response.
      const data = await sendMessage(sessionId, text);
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: data.assistant_message || "",
          products: data.products || [],
          recommendations: data.recommendations || [],
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: ERROR_TEXT,
          isError: true,
          products: [],
          recommendations: [],
        },
      ]);
    } finally {
      setPending(false);
    }
  }

  function handleNewChat() {
    // A new session_id is enough -- backend's own 45-minute inactivity
    // expiration already reclaims the old session; nothing to delete here.
    const id = newSessionId();
    setSessionId(id);
    setMessages([makeGreetingTurn()]);
    setInput("");
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Conversational Shopping Assistant</span>
        <button className="new-chat-button" onClick={handleNewChat}>
          New Chat
        </button>
      </header>

      <main className="chat-window">
        {messages.map((turn) => (
          <MessageBubble key={turn.id} turn={turn} />
        ))}
        {pending && (
          <div className="bubble-row bubble-row-assistant">
            <div className="bubble bubble-assistant bubble-loading" aria-label="Assistant is typing">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      <footer className="chat-input-area">
        <ChatInput value={input} onChange={setInput} onSend={handleSend} disabled={pending} />
      </footer>
    </div>
  );
}
