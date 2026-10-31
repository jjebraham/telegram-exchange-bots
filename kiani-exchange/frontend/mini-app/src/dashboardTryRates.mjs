export const dashboardRatesWithCanonicalTry = (
  generalRates,
  canonicalRates,
  canonicalAvailable,
) => {
  const hasValidCanonicalRates =
    canonicalAvailable &&
    Number.isFinite(canonicalRates.buy_lira) &&
    canonicalRates.buy_lira > 0 &&
    Number.isFinite(canonicalRates.sell_lira) &&
    canonicalRates.sell_lira > 0 &&
    canonicalRates.buy_lira >= canonicalRates.sell_lira;

  return {
    ...generalRates,
    buy_lira: hasValidCanonicalRates ? canonicalRates.buy_lira : 0,
    sell_lira: hasValidCanonicalRates ? canonicalRates.sell_lira : 0,
  };
};

