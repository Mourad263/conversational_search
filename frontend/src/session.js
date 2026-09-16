const STORAGE_KEY = "conv_search_session_id";

export function getSessionId() {
  let id = sessionStorage.getItem(STORAGE_KEY);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(STORAGE_KEY, id);
  }
  return id;
}

export function newSessionId() {
  const id = crypto.randomUUID();
  sessionStorage.setItem(STORAGE_KEY, id);
  return id;
}
