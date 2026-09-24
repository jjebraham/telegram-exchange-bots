"""Compact X views of the existing, safety-assessed Telegram message bodies.

Only explicit rows and numeric fields are copied. Unknown/missing formats fail
closed instead of posting raw HTML, contact links or incomplete price tables.
"""
import html
import re
from decimal import Decimal
from x_post_policy import finish

POST_TYPES = (
    "alanchande-usdt-exchanges", "alanchande-iran-fx", "kiani-hawala",
    "kiani-try", "kiani-examples-reverse", "kiani-examples",
    "alanchande-fx-pulse", "alanchande-turkey-gold", "alanchande-iran-gold",
    "bank-comparison", "alanchande-daily-digest",
)
GOLD_TYPES = {"alanchande-turkey-gold", "alanchande-iran-gold"}
NUMBER = r"[0-9][0-9,]*(?:\.[0-9]+)?"


def plain(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text)).translate(
        str.maketrans("۰۱۲۳۴۵۶۷۸۹٬", "0123456789,"))


def table(text):
    match = re.search(r"<pre>(.*?)</pre>", text, re.S)
    if not match:
        raise ValueError("Expected Telegram price table")
    return [line.replace("\u200e", "").strip().split()
            for line in plain(match[1]).splitlines() if line.strip()][1:]


def number(value):
    if not re.fullmatch(NUMBER, value) or Decimal(value.replace(",", "")) <= 0:
        raise ValueError(f"Invalid price field: {value!r}")
    return value


def pct(value):
    if not re.fullmatch(r"[+\-]?\d+(?:\.\d+)?%|—", value):
        raise ValueError("Invalid percentage field")
    return value


def million(value):
    value = Decimal(number(value).replace(",", "")) / 1000000
    return f"{value:.3f}".rstrip("0").rstrip(".") + "M"


def field(text, label):
    match = re.search(re.escape(label) + r"\s*:?[\s　]*(" + NUMBER + r")", plain(text))
    if not match:
        raise ValueError(f"Missing numeric field: {label}")
    return number(match[1])


def render(post, text):
    if post not in POST_TYPES:
        raise ValueError("Unknown X post type")
    lines = []
    if post == "alanchande-usdt-exchanges":
        rows = table(text)
        expected = ["Wallex", "Nobitex", "Ramzinex", "Bitpin", "AbanTether", "Tabdeal", "Exir"]
        if [r[0] for r in rows] != expected or any(len(r) != 5 for r in rows):
            raise ValueError("Expected all seven USDT exchanges in canonical order")
        lines = ["💎 تتر در صرافی‌های ایران"]
        for name, sell, buy, change, _ in rows:
            pair = number(sell) + ("/" + number(buy) if buy != "—" else "")
            change = " " + pct(change) if buy != "—" else ""
            lines.append(f"{name.replace('AbanTether', 'Aban')} {pair}{change}")
        lines.append("میانگین: " + field(text, "میانگین قیمت خرید") + "/" +
                     field(text, "میانگین قیمت فروش") + " تومان")
    elif post == "alanchande-iran-fx":
        rows = {r[1]: r[2:] for r in table(text) if len(r) == 5}
        lines = ["💱 ارز آزاد ایران | تومان"]
        for code in "USD EUR GBP CHF CAD AUD AED TRY CNY AFN KWD".split():
            rate, change, _ = rows[code]
            lines.append(f"{code} {number(rate)} {pct(change)}")
    elif post == "kiani-try":
        clean = plain(text)
        buy = re.search(r"BUY\s+TL\s+(" + NUMBER + ")", clean)
        sell = re.search(r"SELL\s+TL\s+(" + NUMBER + ")", clean)
        if not buy or not sell:
            raise ValueError("Missing Kiani TRY quote")
        lines = ["🇹🇷 نرخ لیر ترکیه | تومان", f"خرید لیر از ما: {number(buy[1])}",
                 f"فروش لیر به ما: {number(sell[1])}", "",
                 "قبل از واریز، نرخ را تأیید کنید.", "صرافی کیانی"]
    elif post in {"kiani-examples", "kiani-examples-reverse"}:
        reverse = post.endswith("reverse")
        rows = table(text)
        if len(rows) != 3 or any(len(r) != 2 for r in rows):
            raise ValueError("Expected three calculator rows")
        lines = ["🧮 دریافت تومان در ایران" if reverse else "🧮 دریافت لیر در ترکیه"]
        for amount, cost in rows:
            lines.append(f"{million(amount)} تومان ← {number(cost)} TL" if reverse
                         else f"{number(amount)} TL ← {million(cost)} تومان")
        rate = field(text, "بر اساس نرخ خرید فعلی" if reverse else "بر اساس نرخ فروش فعلی")
        lines += ["", f"مبنای محاسبه: {rate} تومان برای هر لیر", "صرافی کیانی"]
    elif post == "alanchande-fx-pulse":
        rows = table(text)
        if len(rows) != 2:
            raise ValueError("Expected USD and EUR pulse")
        lines = ["📊 نبض ارز ترکیه | 24H"]
        for row, code in zip(rows, ("USD", "EUR")):
            if len(row) != 3 or code not in row[0]:
                raise ValueError("Unexpected pulse row")
            lines.append(f"{code}/TRY {number(row[1])}  {pct(row[2])}")
        lines += ["", "نرخ میانی Kapalıçarşı", "🕒 استانبول", "صرفاً جهت اطلاع‌رسانی"]
    elif post in {"alanchande-turkey-gold", "bank-comparison"}:
        gold = post in GOLD_TYPES
        names = ({"GRAM": "GRAM", "CEYREK": "ÇEYREK", "YARIM": "YARIM", "TAM": "TAM"}
                 if gold else {"KAPALI": "Kapalı", "GARANTI": "Garanti", "ISBANK": "İşbank",
                               "KUVEYT": "Kuveyt", "ZIRAAT": "Ziraat"})
        rows = table(text)
        if len(rows) != len(names):
            raise ValueError("Incomplete gold/bank table")
        lines = ["🥇 طلای ترکیه | Kapalıçarşı" if gold else "🏦 دلار در ترکیه | USD/TRY"]
        for row, key in zip(rows, names):
            if len(row) != 4 or row[0].lstrip("🌕🇺🇸") != key:
                raise ValueError("Unexpected gold/bank row")
            lines.append(f"{names[key]} {number(row[1])}/{number(row[2])}" +
                         (f"  {pct(row[3])}" if gold else ""))
        lines += ["", "SELL/BUY | TL"]
    elif post == "alanchande-iran-gold":
        lines = ["🪙 طلا و سکه ایران | تومان"]
        for label, short in [("سکه امامی", "امامی"), ("سکه بهار آزادی", "بهار"),
                             ("نیم سکه", "نیم"), ("ربع سکه", "ربع"), ("سکه گرمی", "گرمی"),
                             ("طلای ۱۸ عیار", "طلای 18 عیار"), ("مثقال طلا", "مثقال")]:
            lines.append(f"{short} {million(field(text, plain(label)))}")
        lines += ["", "صرفاً جهت اطلاع‌رسانی"]
    elif post == "kiani-hawala":
        lines = ["💸 حواله به ایران | تومان"]
        for code, label in [("USD", "دلار آمریکا"), ("EUR", "یورو"), ("GBP", "پوند انگلیس"),
                            ("CAD", "دلار کانادا"), ("AUD", "دلار استرالیا"),
                            ("SEK", "کرون سوئد"), ("TRY", "لیر ترکیه")]:
            lines.append(f"{code} {field(text, label)}")
        lines += ["", "نرخ‌ها لحظه‌ای و قبل از واریز نیازمند تأیید هستند."]
    else:
        lines = ["📌 خلاصه روز بازار"]
        lines.append(" | ".join(f"{code} {field(text, label)}" for code, label in
                                [("USD", "دلار آمریکا"), ("EUR", "یورو"), ("USDT", "تتر"), ("TRY", "لیر ترکیه")]))
        lines.append(f"امامی {million(field(text, 'سکه امامی (طرح جدید)'))} | "
                     f"طلای18 {million(field(text, 'گرم طلای 18 عیار'))} | XAU ${field(text, 'انس طلا')}")
        crypto = {code: field(text, f"({code})") for code in ("BTC", "ETH", "BNB", "SOL", "XRP")}
        lines += [" | ".join(f"{code} ${crypto[code]}" for code in keys)
                  for keys in [("BTC", "ETH", "BNB"), ("SOL", "XRP")]]
    return finish("\n".join(lines), gold=post in GOLD_TYPES)
