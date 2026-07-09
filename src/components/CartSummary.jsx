export function CartSummary({ cart }) {
  const total = cart.total.toFixed(2);          // crashes when cart is null
  return <div>Total: ${total}</div>;
}
