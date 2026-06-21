// ponytail: minimal wrapper, add more ops if needed
import Decimal from "decimal.js";

export const d = (val: string | number | undefined | null): Decimal =>
  new Decimal(val ?? 0);

export const add = (a: string | number, b: string | number): string =>
  new Decimal(a).plus(b).toFixed(2);

export const sub = (a: string | number, b: string | number): string =>
  new Decimal(a).minus(b).toFixed(2);

export const mul = (a: string | number, b: string | number): string =>
  new Decimal(a).times(b).toFixed(2);

export const div = (a: string | number, b: string | number): string =>
  new Decimal(a).div(b).toFixed(2);

export const sum = (vals: (string | number)[]): string =>
  vals.reduce((acc, v) => acc.plus(v ?? 0), new Decimal(0)).toFixed(2);

export const format = (val: string | number): string =>
  new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(
    Number(val)
  );

export const isPositive = (val: string | number): boolean =>
  new Decimal(val).gt(0);

export const isNegative = (val: string | number): boolean =>
  new Decimal(val).lt(0);

export const isZero = (val: string | number): boolean =>
  new Decimal(val).eq(0);

export const percent = (part: string | number, total: string | number): number =>
  d(total).gt(0) ? d(part).div(total).times(100).toNumber() : 0;
