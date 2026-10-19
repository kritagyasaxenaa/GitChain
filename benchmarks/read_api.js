import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const baseUrl = (__ENV.BASE_URL || '').replace(/\/$/, '');
const virtualUsers = Number(__ENV.VUS || 10);
const duration = __ENV.DURATION || '3m';

if (!baseUrl) {
  throw new Error('Set BASE_URL to the public HTTPS URL of a staging node.');
}

const liveLatency = new Trend('health_live_latency', true);
const statusLatency = new Trend('chain_status_latency', true);
const locatorLatency = new Trend('chain_locator_latency', true);

export const options = {
  scenarios: {
    read_api: {
      executor: 'constant-vus',
      vus: virtualUsers,
      duration,
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(95)', 'p(99)', 'count'],
};

export default function () {
  const live = http.get(`${baseUrl}/health/live`, { tags: { route: 'health_live' } });
  liveLatency.add(live.timings.duration);
  check(live, { 'health live returns 200': (response) => response.status === 200 });

  const status = http.get(`${baseUrl}/chain/status`, { tags: { route: 'chain_status' } });
  statusLatency.add(status.timings.duration);
  check(status, { 'chain status returns 200': (response) => response.status === 200 });

  const locator = http.get(`${baseUrl}/chain/locator?limit=32`, { tags: { route: 'chain_locator' } });
  locatorLatency.add(locator.timings.duration);
  check(locator, { 'chain locator returns 200': (response) => response.status === 200 });
}
