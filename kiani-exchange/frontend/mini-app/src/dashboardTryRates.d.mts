import type { Rates } from './exchangeMath';

export function dashboardRatesWithCanonicalTry(
  generalRates: Rates,
  canonicalRates: Pick<Rates, 'buy_lira' | 'sell_lira'>,
  canonicalAvailable: boolean,
): Rates;

