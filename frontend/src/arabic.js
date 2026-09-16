// Presentation-only check (bubble/text direction). NOT semantic classification --
// the backend's understand() is the sole authority on meaning/language.
const ARABIC_RE = /[؀-ۿݐ-ݿ]/;

export function isArabicText(text) {
  return !!text && ARABIC_RE.test(text);
}
