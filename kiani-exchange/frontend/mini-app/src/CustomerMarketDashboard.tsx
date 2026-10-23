import { isDisplayReady, isTradeReady } from './rateAvailability';
import type { RateSources } from './rateAvailability';
import { useEffect, useRef, useState } from 'react';
import type { ExchangeType, Rates } from './exchangeMath';

const safeLocale = (value: unknown, minimumFractionDigits = 0): string => {
  const number = Number(value ?? 0);
  return (Number.isFinite(number) ? number : 0).toLocaleString('fa-IR', { minimumFractionDigits, maximumFractionDigits: 2 });
};

type MarketRateSlabProps = {
  title: string;
  code: string;
  buy: number;
  sell: number;
  delta: number;
  changedBuy: boolean;
  changedSell: boolean;
  available: boolean;
  indicative: boolean;
  sourceCount?: number;
};

function MarketRateSlab({
  title,
  code,
  buy,
  sell,
  delta,
  changedBuy,
  changedSell,
  available,
  indicative,
  sourceCount,
}: MarketRateSlabProps) {
  const direction =
    Math.abs(delta) < 0.001 ? 'flat' : delta > 0 ? 'up' : 'down';

  return (
    <section className="ke-market-slab">
      <div className="ke-market-slab-head">
        <div className="ke-market-name">
          <strong>{title}</strong>
          <span>{available ? `${code}${indicative ? ' · نمایشی' : ''}` : 'موقتاً ناموجود'}</span>
        </div>

        <div className={`ke-market-trend ${direction}`}>
          <span aria-hidden="true">
            {direction === 'up' ? '▲' : direction === 'down' ? '▼' : '—'}
          </span>
          <span>
            {direction === 'flat'
              ? 'بدون تغییر'
              : `${Math.abs(delta).toLocaleString('fa-IR', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}٪`}
          </span>
        </div>
      </div>

      {available && indicative && (
        <p className="text-xs leading-6" style={{ margin: '0 16px 8px', color: 'var(--ke-brass)' }}>
          {sourceCount === 1
            ? 'نرخ تقریبی؛ در انتظار تأیید منبع دوم'
            : 'نرخ نمایشی؛ تأییدشده از چند منبع'}
        </p>
      )}

      <div className="ke-market-sides">
        <div className="ke-market-side buy">
          <div className="ke-market-side-label">شما می‌خرید</div>
          <div className="ke-market-price">
            <span className={`ke-market-number ${changedBuy ? 'is-changed' : ''}`}>
              {available ? safeLocale(buy) : '—'}
            </span>
            <span className="ke-market-unit">تومان</span>
          </div>
        </div>

        <div className="ke-market-divider" />

        <div className="ke-market-side sell">
          <div className="ke-market-side-label">شما می‌فروشید</div>
          <div className="ke-market-price">
            <span className={`ke-market-number ${changedSell ? 'is-changed' : ''}`}>
              {available ? safeLocale(sell) : '—'}
            </span>
            <span className="ke-market-unit">تومان</span>
          </div>
        </div>
      </div>

      <div className="ke-market-spread">
        <span>اختلاف خرید و فروش</span>
        <span>
          <strong>{available ? safeLocale(Math.abs(buy - sell)) : '—'}</strong> {available ? 'تومان' : ''}
        </span>
      </div>
    </section>
  );
}

export default function DashboardPage({
  rates,
  loading,
  onExchangeClick,
  onRefresh,
  updatedAt,
  refreshedAt,
  deltas,
  changed,
  rateError,
  rateSources,
}: {
  rates: Rates;
  loading: boolean;
  onExchangeClick: (type: ExchangeType) => void;
  onRefresh: () => Promise<boolean>;
  updatedAt: number | null;
  refreshedAt: number | null;
  deltas: { usdt: number; try: number };
  changed: Set<string>;
  rateError: boolean;
  rateSources: RateSources;
}) {
  const [now, setNow] = useState(() => Date.now());
  const usdtAvailable = isDisplayReady(rateSources.current, now);
  const tryAvailable = isDisplayReady(rateSources.currentTry ?? rateSources.current, now);
  const displayAvailable = usdtAvailable || tryAvailable;
  const usdtTradable = isTradeReady(rateSources, 'buy_usdt', now);
  const tryTradable = isTradeReady(rateSources, 'buy_lira', now);
  const [manualRefreshing, setManualRefreshing] = useState(false);
  const [refreshDone, setRefreshDone] = useState(false);
  const loadStartedAt = useRef(Date.now());
  const doneTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);

    return () => {
      window.clearInterval(timer);
      if (doneTimerRef.current) clearTimeout(doneTimerRef.current);
    };
  }, []);

  const refreshRates = async () => {
    if (manualRefreshing || loading) return;

    setManualRefreshing(true);
    setRefreshDone(false);

    try {
      if (await onRefresh()) {
        setRefreshDone(true);
        if (doneTimerRef.current) clearTimeout(doneTimerRef.current);
        doneTimerRef.current = setTimeout(() => setRefreshDone(false), 1800);
      }
    } finally {
      setManualRefreshing(false);
    }
  };

  const lastUpdatedAt = updatedAt ?? 0;
  const ageSeconds = lastUpdatedAt
    ? Math.max(0, Math.floor((now - lastUpdatedAt) / 1000))
    : 0;
  const isStale = lastUpdatedAt > 0 && !displayAvailable;
  const ageText =
    ageSeconds < 5
      ? 'هم‌اکنون'
      : ageSeconds < 60
        ? `${ageSeconds.toLocaleString('fa-IR')} ثانیه پیش`
        : `${Math.floor(ageSeconds / 60).toLocaleString('fa-IR')} دقیقه پیش`;

  const autoRefreshSeconds = 20;
  const refreshAgeSeconds = refreshedAt ? Math.max(0, Math.floor((now - refreshedAt) / 1000)) : 0;
  const autoLeft = Math.max(0, autoRefreshSeconds - refreshAgeSeconds);
  const autoProgress = Math.min(1, refreshAgeSeconds / autoRefreshSeconds);

  const loadingElapsed = Math.max(
    0,
    Math.floor((now - loadStartedAt.current) / 1000),
  );
  const loadProgress = Math.min(0.94, 1 - Math.exp(-loadingElapsed / 5));
  const waitStage =
    loadingElapsed >= 13
      ? {
          title: 'نرخ‌ها در حال آماده‌سازی است',
          body: 'شبکه کمی کند است، اما درخواست شما هنوز فعال است.',
        }
      : loadingElapsed >= 7
        ? {
            title: 'چند لحظه دیگر',
            body: 'اتصال برقرار است و داده‌ها در حال رسیدن‌اند.',
          }
        : loadingElapsed >= 3
          ? {
              title: 'دریافت نرخ لحظه‌ای بازار',
              body: 'نرخ تتر و لیر از منابع بازار خوانده می‌شود.',
            }
          : {
              title: 'در حال اتصال به سرور',
              body: 'ارتباط با سرور صرافی در حال برقراری است.',
            };

  return (
    <div className="ke-market-home">
      <div className="ke-market-toolbar">
        <div>
          <div className="ke-market-title-row">
            <h2>بازار</h2>
            <span className="ke-market-live-badge">OTC</span>
          </div>

          <div className={`ke-market-freshness ${isStale ? 'is-stale' : ''}`}>
            <span className="ke-fresh-dot" />
            <span>
              {isStale
                ? 'نرخ‌ها نیاز به بروزرسانی دارند'
                : `آخرین نرخ ${ageText}`}
            </span>
            {!isStale && lastUpdatedAt > 0 && (
              <span>
                · بروزرسانی خودکار تا {autoLeft.toLocaleString('fa-IR')} ثانیه
              </span>
            )}
          </div>
        </div>

        <button
          type="button"
          className={`ke-market-refresh ${manualRefreshing ? 'is-loading' : ''} ${refreshDone ? 'is-done' : ''}`}
          onClick={() => void refreshRates()}
          disabled={manualRefreshing || loading}
          aria-busy={manualRefreshing}
        >
          <span
            className="ke-refresh-ring"
            style={{
              background: `conic-gradient(var(--ke-brass) ${autoProgress * 360}deg, var(--ke-line-soft) 0deg)`,
            }}
            aria-hidden="true"
          >
            <span>{refreshDone ? '✓' : '↻'}</span>
          </span>
          <span>
            {manualRefreshing
              ? 'در حال بروزرسانی'
              : refreshDone
                ? 'بروز شد'
                : 'بروزرسانی'}
          </span>
        </button>
      </div>

      {!displayAvailable && (rateError || !loading) && (
        <div className="ke-rate-error" role="alert">
          <span>دریافت نرخ‌های تازه انجام نشد؛ برای نمایش قیمت تتر و لیر دوباره تلاش کنید.</span>
          <button type="button" onClick={() => void refreshRates()}>تلاش دوباره</button>
        </div>
      )}

      {loading && !usdtAvailable && !tryAvailable ? (
        <>
          <div className="ke-market-skeletons" aria-hidden="true">
            <div className="ke-market-skeleton" />
            <div className="ke-market-skeleton" />
            <div className="ke-market-skeleton strip" />
          </div>

          <div
            className="ke-rate-wait-scrim"
            role="dialog"
            aria-live="polite"
            aria-label="در حال دریافت نرخ‌ها"
          >
            <div className="ke-rate-wait">
              <div
                className="ke-rate-progress"
                style={{
                  background: `conic-gradient(var(--ke-brass) ${loadProgress * 360}deg, var(--ke-line-soft) 0deg)`,
                }}
              >
                <div className="ke-rate-progress-inner">
                  {loadingElapsed.toLocaleString('fa-IR')}″
                </div>
              </div>

              <h3>{waitStage.title}</h3>
              <p>{waitStage.body}</p>

              {loadingElapsed >= 6 && (
                <div className="ke-rate-hold">
                  صفحه را نبندید، نرخ‌ها به‌زودی نمایش داده می‌شوند
                </div>
              )}

              {loadingElapsed >= 25 && (
                <button
                  type="button"
                  className="ke-rate-retry"
                  onClick={() => void refreshRates()}
                >
                  تلاش دوباره
                </button>
              )}
            </div>
          </div>
        </>
      ) : (
        <>
          <MarketRateSlab
            title="تتر"
            available={usdtAvailable}
            indicative={!usdtTradable}
            sourceCount={rateSources.current.sourceCount}
            code="USDT"
            buy={rates.buy_usdt}
            sell={rates.sell_usdt}
            delta={deltas.usdt}
            changedBuy={changed.has('usdt-buy')}
            changedSell={changed.has('usdt-sell')}
          />

          <MarketRateSlab
            title="لیر"
            available={tryAvailable}
            indicative={!tryTradable}
            sourceCount={(rateSources.currentTry ?? rateSources.current).sourceCount}
            code="TRY"
            buy={rates.buy_lira}
            sell={rates.sell_lira}
            delta={deltas.try}
            changedBuy={changed.has('try-buy')}
            changedSell={changed.has('try-sell')}
          />

          <section className="ke-market-conversions">
            <div className="ke-market-conversion-cell">
              <span>تبدیل تتر به لیر</span>
              <strong>{tryAvailable ? safeLocale(rates.usdt_to_lira, 2) + ' لیر' : '—'}</strong>
            </div>
            <div className="ke-market-conversion-divider" />
            <div className="ke-market-conversion-cell">
              <span>تبدیل لیر به تتر</span>
              <strong>{tryAvailable ? safeLocale(rates.lira_to_usdt, 2) + ' لیر' : '—'}</strong>
            </div>
          </section>

          <div className="ke-market-reference">
            <span>دلار خرید از سایت‌های خارجی</span>
            <strong>{usdtAvailable ? safeLocale(rates.foreign_payment) + ' تومان' : '—'}</strong>
          </div>
          {displayAvailable && <p className="text-xs leading-6" style={{ color: 'var(--ke-muted)' }}>نرخ نهایی معامله پیش از ثبت سفارش نمایش داده می‌شود.</p>}
        </>
      )}

      <h2 className="ke-trade-heading">معامله</h2>

      {displayAvailable && !usdtTradable && !tryTradable && (
        <p className="text-xs leading-6" role="status" style={{ color: 'var(--ke-muted)' }}>
          قیمت‌ها برای اطلاع شما نمایش داده می‌شوند؛ ثبت سفارش پس از تأیید نرخ فعال می‌شود.
        </p>
      )}

      <div className="ke-trade-tiles">
        {[
          { label: 'خرید تتر', icon: '₮', kind: 'buy', type: 'buy_usdt' as ExchangeType },
          { label: 'فروش تتر', icon: '₮', kind: 'sell', type: 'sell_usdt' as ExchangeType },
          { label: 'خرید لیر', icon: '₺', kind: 'buy', type: 'buy_lira' as ExchangeType },
          { label: 'فروش لیر', icon: '₺', kind: 'sell', type: 'sell_lira' as ExchangeType },
          { label: 'تبدیل تتر به لیر', icon: '⇄', kind: 'swap', type: 'convert_usdt_to_lira' as ExchangeType },
          { label: 'تبدیل لیر به تتر', icon: '⇄', kind: 'swap', type: 'convert_lira_to_usdt' as ExchangeType },
        ].map((action) => (
          <button
            key={action.type}
            type="button"
            className={`ke-trade-tile ${action.kind}`}
            onClick={() => onExchangeClick(action.type)}
            disabled={!isTradeReady(
              rateSources,
              action.type,
              now,
            )}
            title={!isTradeReady(
              rateSources,
              action.type,
              now,
            ) ? 'نرخ موقتاً در دسترس نیست' : undefined}
          >
            <span className="ke-trade-icon">{action.icon}</span>
            <span>{action.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
