import { isArabicText } from "../arabic.js";
import ProductSection from "./ProductSection.jsx";

export default function MessageBubble({ turn }) {
  const arabic = isArabicText(turn.text);
  const bubbleClass = `bubble bubble-${turn.role}${turn.isError ? " bubble-error" : ""}`;
  const recLabel = arabic ? "مقترح لك" : "Recommended for you";

  return (
    <div className={`bubble-row bubble-row-${turn.role}`}>
      <div className={bubbleClass} dir={arabic ? "rtl" : "ltr"}>
        {turn.text}
      </div>
      {turn.role === "assistant" && (
        <>
          <ProductSection products={turn.products} />
          <ProductSection title={recLabel} products={turn.recommendations} />
        </>
      )}
    </div>
  );
}
