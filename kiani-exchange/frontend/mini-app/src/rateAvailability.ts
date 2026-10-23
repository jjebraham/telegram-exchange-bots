import type { ExchangeType } from './exchangeMath';

export const MINIMUM_TRADE_SOURCES = 2;

export type RateSourceState = {
  ok: boolean;
  receivedAt: number | null;
  expiresAt?: number;
  transactionRatesAvailable?: boolean;
  sourceCount?: number;
};

export type RateSources = {
  shahidi: RateSourceState;
  canonical: RateSourceState;
  current: RateSourceState;
  currentTry?: RateSourceState;
};

export const sourceForTrade = (
  type: ExchangeType,
): 'canonical' | 'shahidi' =>
  type === 'buy_lira' || type === 'sell_lira'
    ? 'canonical'
    : 'shahidi';

export const isDisplayReady = (
  source: RateSourceState,
  now = Date.now(),
): boolean =>
  source.ok &&
  source.receivedAt !== null &&
  now >= source.receivedAt &&
  now - source.receivedAt <= 90_000 &&
  (source.expiresAt === undefined || now < source.expiresAt);

export const isSourceReady = (
  source: RateSourceState,
  now = Date.now(),
): boolean =>
  isDisplayReady(source, now) &&
  source.transactionRatesAvailable === true &&
  Number.isInteger(source.sourceCount) &&
  (source.sourceCount ?? 0) >= MINIMUM_TRADE_SOURCES;

export const isTradeReady = (
  sources: RateSources,
  type: ExchangeType,
  now = Date.now(),
): boolean =>
  isSourceReady(sources.current, now) &&
  (!(type.includes('lira')) || isSourceReady(sources.currentTry ?? sources.current, now)) &&
  isSourceReady(sources[sourceForTrade(type)], now);
