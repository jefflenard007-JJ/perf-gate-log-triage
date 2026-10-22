// k6 load test for shop-api (from the reliability-platform project).
// Run:  k6 run -e BASE_URL=http://localhost:8000 --summary-export=summary.json loadtests/k6/orders-load.js
// Thresholds make k6 itself exit non-zero; perfgate then compares the summary to the baseline.
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export const options = {
  scenarios: {
    steady_load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 20 }, // ramp up
        { duration: '2m', target: 20 },  // steady state
        { duration: '20s', target: 0 },  // ramp down
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],                  // < 1% errors
    http_req_duration: ['p(95)<300', 'p(99)<800'],   // latency SLO
    'http_req_duration{name:POST /orders}': ['p(95)<300'],
    checks: ['rate>0.99'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(50)', 'p(95)', 'p(99)'],
};

const items = ['keyboard', 'mouse', 'monitor', 'headset', 'webcam'];

export default function () {
  const payload = JSON.stringify({
    item: items[Math.floor(Math.random() * items.length)],
    quantity: 1 + Math.floor(Math.random() * 5),
  });
  const created = http.post(`${BASE_URL}/orders`, payload, {
    headers: { 'Content-Type': 'application/json' },
    tags: { name: 'POST /orders' },
  });
  check(created, { 'order created (201)': (r) => r.status === 201 });

  if (created.status === 201) {
    const id = created.json('id');
    const fetched = http.get(`${BASE_URL}/orders/${id}`, { tags: { name: 'GET /orders/{id}' } });
    check(fetched, { 'order fetched (200)': (r) => r.status === 200 });
  }

  const list = http.get(`${BASE_URL}/orders`, { tags: { name: 'GET /orders' } });
  check(list, { 'orders listed (200)': (r) => r.status === 200 });

  sleep(0.5 + Math.random()); // think time
}
