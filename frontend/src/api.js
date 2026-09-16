const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

// POST /session/{session_id}/message -- the one and only conversational
// endpoint (src/api/routes.py). One user Send = exactly one call here;
// assistant_message/products/recommendations all come back in this same
// response, so nothing else ever needs to be called per turn.
export async function sendMessage(sessionId, message) {
  const response = await fetch(`${BASE_URL}/session/${encodeURIComponent(sessionId)}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json();
}
