import { isArabicText } from "../arabic.js";

function formatBrand(brand) {
  if (!brand) return null;
  return brand
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default function ProductCard({ product }) {
  const brand = formatBrand(product.brand_normalized);
  const hasSpecial =
    product.special_price != null &&
    product.price != null &&
    product.special_price < product.price;

  return (
    <div className="product-card">
      <div className="product-name">{product.name_en}</div>
      {product.name_ar && (
        <div className="product-name-ar" dir={isArabicText(product.name_ar) ? "rtl" : "ltr"}>
          {product.name_ar}
        </div>
      )}
      {brand && <div className="product-brand">{brand}</div>}
      <div className="product-price-row">
        {product.price != null && (
          <span className={hasSpecial ? "product-price product-price-strike" : "product-price"}>
            {product.price.toFixed(2)} EGP
          </span>
        )}
        {hasSpecial && <span className="product-special-price">{product.special_price.toFixed(2)} EGP</span>}
      </div>
    </div>
  );
}
