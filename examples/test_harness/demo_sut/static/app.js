(function () {
  function buildOrderPayload(sku, qtyValue, keyPrefix) {
    const qty = Number(qtyValue);
    if (!sku || !Number.isInteger(qty) || qty <= 0) {
      return { ok: false, error: "Quantity must be a positive integer" };
    }
    return {
      ok: true,
      payload: { sku: String(sku), qty: qty, idempotency_key: (keyPrefix || "ui") + "-" + Date.now() },
    };
  }
  function formatPrice(cents) {
    return "$" + (Number(cents) / 100).toFixed(2);
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { buildOrderPayload, formatPrice };
  }
})();
