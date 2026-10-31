import assert from 'node:assert/strict';
import test from 'node:test';
import { dashboardRatesWithCanonicalTry } from '../src/dashboardTryRates.mjs';

const generalRates = {
  buy_lira: 5510,
  sell_lira: 5340,
  buy_usdt: 610000,
  sell_usdt: 600000,
  usdt_to_lira: 35.4,
  lira_to_usdt: 36.2,
  foreign_payment: 625000,
};

test('uses canonical TRY buy and sell without replacing other display rates', () => {
  const canonicalRates = { buy_lira: 5460, sell_lira: 5340 };

  assert.deepEqual(
    dashboardRatesWithCanonicalTry(generalRates, canonicalRates, true),
    {
      ...generalRates,
      buy_lira: 5460,
      sell_lira: 5340,
    },
  );
});

test('fails closed instead of falling back to general TRY when canonical data is unavailable', () => {
  const canonicalRates = { buy_lira: 0, sell_lira: 0 };

  assert.deepEqual(
    dashboardRatesWithCanonicalTry(generalRates, canonicalRates, false),
    {
      ...generalRates,
      buy_lira: 0,
      sell_lira: 0,
    },
  );
});

test('fails closed for an invalid canonical quote even when marked available', () => {
  const canonicalRates = { buy_lira: 5300, sell_lira: 5400 };

  assert.equal(
    dashboardRatesWithCanonicalTry(generalRates, canonicalRates, true).buy_lira,
    0,
  );
  assert.equal(
    dashboardRatesWithCanonicalTry(generalRates, canonicalRates, true).sell_lira,
    0,
  );
});

