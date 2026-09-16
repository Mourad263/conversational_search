import ProductCard from "./ProductCard.jsx";

// Used for both plain search `products` (no title) and `recommendations`
// (labeled, e.g. "Recommended for you") -- never merged into one list.
export default function ProductSection({ title, products }) {
  if (!products || products.length === 0) return null;
  return (
    <div className="product-section">
      {title && <div className="product-section-title">{title}</div>}
      <div className="product-grid">
        {products.map((p) => (
          <ProductCard key={p.id} product={p} />
        ))}
      </div>
    </div>
  );
}
