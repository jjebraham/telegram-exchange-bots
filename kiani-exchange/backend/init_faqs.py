#!/usr/bin/env python3
"""Initialize FAQ entries in the database."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import get_db, init_db

FAQS = [
    {
        "question_fa": "چطور ثبت نام کنم؟",
        "answer_fa": "روی دکمه ثبت نام بزنید و با وارد کردن نام، نام خانوادگی، کد ملی، تاریخ تولد، به اشتراک گذاری شماره تلگرام ایرانی و شماره کارت بانکی به نام خودتان ثبت نام کنید.",
        "category": "registration",
        "sort_order": 1,
    },
    {
        "question_fa": "کدام شماره تلفن قابل قبول است؟",
        "answer_fa": "تنها شماره تلفن ایران مورد قبول است و فقط با به اشتراک گذاری شماره تلفن تلگرام تان می\u200cتوانید ثبت نام را تکمیل کنید.",
        "category": "registration",
        "sort_order": 2,
    },
    {
        "question_fa": "چطور کارت جدید ثبت کنم؟",
        "answer_fa": "پس از ورود به حساب کاربری، از منوی 'کارت های بانکی من' روی گزینه 'اضافه کردن کارت جدید' بزنید و 16 رقم کارت بانکی خود را وارد کنید (فقط کارت بانکی به نام خودتان مورد قبول است).",
        "category": "banking",
        "sort_order": 3,
    },
    {
        "question_fa": "واریز های ریالی چقدر زمان می\u200cبرد؟",
        "answer_fa": "واریز های ریالی در اولین سیکل پایا به حساب بانکی شما در ایران واریز می\u200cشود.\nسیکل\u200cهای پایا: ساعت 04:00، 11:00، 14:00، 19:00.\nپرداخت\u200cهای تعطیلی به اولین روز کاری موکول می\u200cشود.",
        "category": "payments",
        "sort_order": 4,
    },
    {
        "question_fa": "در صورت خرید تتر واریز تتر چقدر زمان می\u200cبرد؟",
        "answer_fa": "اگر اولین واریز ریالی شما به حساب ما باشد، مبلغ واریزی شما به مدت 72 ساعت نزد ما به امانت باقی می\u200cماند سپس واریز می\u200cشود.\nاز خرید دوم به بعد ظرف یک ساعت تراکنش انجام می\u200cشود.",
        "category": "tether",
        "sort_order": 5,
    },
    {
        "question_fa": "آیا می\u200cتوانم از حساب شخص دیگری استفاده کنم؟",
        "answer_fa": "خیر، شما تنها از حساب بانکی به نام خودتان می\u200cتوانید واریز ریالی داشته باشید. برای واریز از حساب شخص ثالث، او باید در ربات ثبت نام و احراز هویت کند.",
        "category": "general",
        "sort_order": 6,
    },
]


def main():
    init_db()
    db = get_db()

    existing = db.execute("SELECT COUNT(*) as c FROM faqs").fetchone()["c"]
    if existing > 0:
        print(f"FAQs already exist ({existing} entries). Skipping initialization.")
        db.close()
        return

    for faq in FAQS:
        db.execute(
            "INSERT INTO faqs (question_fa, answer_fa, category, sort_order) VALUES (?, ?, ?, ?)",
            (faq["question_fa"], faq["answer_fa"], faq["category"], faq["sort_order"])
        )

    db.commit()
    db.close()
    print(f"Inserted {len(FAQS)} FAQs successfully.")


if __name__ == "__main__":
    main()
