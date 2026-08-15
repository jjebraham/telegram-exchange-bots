export type ExchangeType =
  | 'buy_lira'
  | 'sell_lira'
  | 'buy_usdt'
  | 'sell_usdt'
  | 'convert_usdt_to_lira'
  | 'convert_lira_to_usdt';

export interface Rates {
  buy_lira: number;
  sell_lira: number;
  buy_usdt: number;
  sell_usdt: number;
  usdt_to_lira: number;
  lira_to_usdt: number;
  foreign_payment: number;
}

export const deriveRates = (usdtIrr: number, usdtTry: number, settings?: Record<string, number>): Rates => {
  const effToman = usdtIrr / 10;
  const tomanToTl = settings?.toman_to_tl_factor ?? 0.995;
  const tlToToman = settings?.tl_to_toman_factor ?? 0.94;
  const buyUsdt = settings?.buy_usdt_factor ?? 1.01;
  const sellUsdt = settings?.sell_usdt_factor ?? 0.99;
  const usdtToLira = settings?.usdt_to_lira_factor ?? 0.98;
  const liraToUsdt = settings?.lira_to_usdt_factor ?? 1.02;
  const foreignPayment = settings?.foreign_payment_factor ?? 1.05;
  return {
    buy_lira: Math.round(((effToman / usdtTry) * tomanToTl) / 10) * 10,
    sell_lira: Math.round(((effToman / usdtTry) * tlToToman) / 10) * 10,
    buy_usdt: Math.round((effToman * buyUsdt) / 10) * 10,
    sell_usdt: Math.round((effToman * sellUsdt) / 10) * 10,
    usdt_to_lira: parseFloat((usdtTry * usdtToLira).toFixed(2)),
    lira_to_usdt: parseFloat((usdtTry * liraToUsdt).toFixed(2)),
    foreign_payment: Math.round((effToman * foreignPayment) / 10) * 10,
  };
};

export const calculateFee = (exchangeType: ExchangeType, sendAmount: number): number => {
  if (exchangeType === 'sell_lira') return sendAmount < 5000 ? 160 : 0;
  if (exchangeType === 'buy_lira') return sendAmount < 15_000_000 ? 160 : 0;
  if (
    exchangeType === 'buy_usdt' ||
    exchangeType === 'sell_usdt' ||
    exchangeType === 'convert_usdt_to_lira' ||
    exchangeType === 'convert_lira_to_usdt'
  ) {
    return 5;
  }
  return 0;
};

export const calculateReceiveAmount = (exchangeType: ExchangeType, sendAmount: number, rates: Rates) => {
  const fee = calculateFee(exchangeType, sendAmount);
  let netSendAmount = sendAmount;
  let receiveAmount = 0;

  switch (exchangeType) {
    case 'buy_lira':
      receiveAmount = sendAmount / rates.buy_lira - fee;
      break;
    case 'sell_lira':
      netSendAmount = Math.max(sendAmount - fee, 0);
      receiveAmount = netSendAmount * rates.sell_lira;
      break;
    case 'buy_usdt':
      receiveAmount = sendAmount / rates.buy_usdt - fee;
      break;
    case 'sell_usdt':
      netSendAmount = Math.max(sendAmount - fee, 0);
      receiveAmount = netSendAmount * rates.sell_usdt;
      break;
    case 'convert_usdt_to_lira':
      netSendAmount = Math.max(sendAmount - fee, 0);
      receiveAmount = netSendAmount * rates.usdt_to_lira;
      break;
    case 'convert_lira_to_usdt':
      receiveAmount = sendAmount / rates.lira_to_usdt - fee;
      break;
  }

  return {
    fee,
    netSendAmount,
    receiveAmount: Math.max(receiveAmount, 0),
  };
};
