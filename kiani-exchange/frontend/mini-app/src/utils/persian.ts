import {
  digitsFaToEn,
  digitsArToEn,
  addCommas,
  removeCommas,
  digitsEnToFa,
  phoneNumberNormalizer,
  isPhoneNumberValid,
  toPersianChars,
  halfSpace,
  verifyCardNumber,
  isShebaValid,
  verifyIranianNationalId,
} from '@persian-tools/persian-tools';

export const normalizeDigitsToEn = (value: string): string => digitsArToEn(digitsFaToEn(value || ''));

export const normalizeNumberInput = (value: string): string => {
  const normalized = normalizeDigitsToEn((value || '').trim());
  const noCommas = String(removeCommas(normalized));
  return noCommas === 'NaN' ? normalized.replace(/,/g, '') : noCommas;
};

export const formatFaNumber = (value: number | string): string => {
  const raw = normalizeDigitsToEn(String(value ?? '0')).replace(/,/g, '');
  const n = Number(raw);
  if (!Number.isFinite(n)) return '۰';
  return digitsEnToFa(addCommas(n));
};

export const normalizePhone = (value: string): string => phoneNumberNormalizer(normalizeDigitsToEn(value || ''), '0');

export const isValidIranPhone = (value: string): boolean => isPhoneNumberValid(normalizePhone(value || ''));

export const cleanPersianText = (value: string): string => halfSpace(toPersianChars((value || '').trim()));

export const isCardNumberValid = (value: string): boolean => Boolean(verifyCardNumber(Number(normalizeNumberInput(value || ''))));
export const isNationalIdValid = (value: string): boolean => Boolean(verifyIranianNationalId(normalizeDigitsToEn(value || '')));

export { isShebaValid, addCommas, removeCommas };
