import { CartSummary } from './components/CartSummary.jsx';

// The layout-shift page renders a button visually buried under a banner.
// It looks broken, but it never throws — no page errors, no console errors.
function LayoutShift() {
  return (
    <div>
      <div style={{ position: 'relative', height: 120 }}>
        <button style={{ position: 'absolute', top: 40, left: 0 }}>Pay now</button>
        <div
          style={{
            position: 'absolute',
            top: 30,
            left: -10,
            width: 240,
            height: 60,
            background: 'rgba(255, 245, 200, 0.97)',
            border: '1px solid #e0c860',
            padding: 4,
          }}
        >
          Limited-time offer: free shipping today!
        </div>
      </div>
    </div>
  );
}

const FIXTURES = {
  'null-cart': () => <CartSummary cart={null} />,
  'ok': () => <CartSummary cart={{ total: 42 }} />,
  'layout-shift': () => <LayoutShift />,
};

export default function App() {
  const path = window.location.pathname;
  const fixture = new URLSearchParams(window.location.search).get('fixture');

  if (path === '/cart') {
    const renderFixture = FIXTURES[fixture] ?? FIXTURES['ok'];
    return (
      <div>
        <h1>Your cart</h1>
        {renderFixture()}
      </div>
    );
  }

  return (
    <div>
      <h1>ProofRun Demo Shop</h1>
      <p>A tiny storefront with a seeded bug, used to demo certified bug reports.</p>
      <a href="/cart?fixture=ok">Go to cart</a>
    </div>
  );
}
