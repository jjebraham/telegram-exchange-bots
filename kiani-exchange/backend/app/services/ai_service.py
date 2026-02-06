from typing import Tuple
from sqlalchemy.orm import Session
from ..database import FAQ
import re


class AIService:
    """
    Simple AI chatbot service using keyword matching and FAQ database.
    For production, integrate with OpenAI/Claude API or train a custom model.
    """

    def __init__(self):
        self.keyword_map = {
            "ثبت نام": ["ثبت نام", "register", "ساخت حساب", "عضویت"],
            "احراز هویت": ["احراز", "kyc", "تایید", "مدارک", "کارت ملی"],
            "کارت بانکی": ["کارت", "بانک", "bank card", "شماره کارت"],
            "تراکنش": ["تراکنش", "transaction", "خرید", "فروش", "معامله"],
            "نرخ": ["نرخ", "rate", "قیمت", "price"],
            "لیر": ["لیر", "lira", "try", "ترکیه"],
            "تتر": ["تتر", "usdt", "tether"],
            "ریال": ["ریال", "irr", "تومان"],
            "زمان": ["زمان", "time", "مدت", "چقدر", "کی"],
            "کارمزد": ["کارمزد", "fee", "هزینه", "commission"],
        }

        self.responses = {
            "greeting": "سلام! من دستیار هوشمند صرافی کیانی هستم. چطور می‌تونم کمکتون کنم؟",
            "default": (
                "متاسفانه نتونستم سوالتون رو درست متوجه بشم. "
                "می‌تونید با پشتیبانی در @TL905411603664 در ارتباط باشید."
            ),
        }

    async def get_answer(self, question: str, db: Session) -> Tuple[str, float]:
        """
        Get answer for user question.
        Returns: (answer, confidence_score)
        """
        question = question.lower().strip()

        if any(word in question for word in ["سلام", "hello", "hi", "صبح بخیر", "عصر بخیر"]):
            return self.responses["greeting"], 1.0

        faqs = db.query(FAQ).filter(FAQ.is_active == True).all()

        best_match = None
        best_score = 0.0

        for faq in faqs:
            score = self._calculate_similarity(question, faq.question_fa.lower())
            if score > best_score:
                best_score = score
                best_match = faq

        if best_match and best_score > 0.5:
            return best_match.answer_fa, best_score

        category = self._detect_category(question)
        if category:
            category_faqs = [f for f in faqs if f.category == category]
            if category_faqs:
                return category_faqs[0].answer_fa, 0.6

        return self.responses["default"], 0.0

    def _calculate_similarity(self, query: str, reference: str) -> float:
        """
        Calculate similarity score between query and reference.
        Simple implementation - can be improved with more advanced NLP.
        """
        query_words = set(self._tokenize(query))
        ref_words = set(self._tokenize(reference))

        if not query_words or not ref_words:
            return 0.0

        intersection = query_words.intersection(ref_words)
        union = query_words.union(ref_words)

        return len(intersection) / len(union)

    def _tokenize(self, text: str) -> list:
        """Tokenize Persian/English text."""
        text = re.sub(r"[^\w\s]", " ", text)
        return [word for word in text.split() if len(word) > 1]

    def _detect_category(self, question: str) -> str:
        """Detect question category based on keywords."""
        question = question.lower()

        for category, keywords in self.keyword_map.items():
            if any(keyword in question for keyword in keywords):
                if any(k in keywords for k in ["ثبت نام", "register"]):
                    return "registration"
                if any(k in keywords for k in ["احراز", "kyc"]):
                    return "kyc"
                if any(k in keywords for k in ["تراکنش", "transaction"]):
                    return "transactions"
                return "general"

        return "general"

    async def get_suggestions(self, partial_query: str, db: Session) -> list:
        """Get suggested questions based on partial query."""
        partial_query = partial_query.lower().strip()

        if len(partial_query) < 3:
            return []

        faqs = db.query(FAQ).filter(FAQ.is_active == True).limit(5).all()

        suggestions = []
        for faq in faqs:
            if partial_query in faq.question_fa.lower():
                suggestions.append(faq.question_fa)

        return suggestions[:5]

    def get_quick_replies(self) -> list:
        """Get quick reply options for users."""
        return [
            "چطور ثبت نام کنم؟",
            "کارت بانکی چطور اضافه کنم؟",
            "زمان واریز ریالی چقدره؟",
            "کارمزد تراکنش‌ها چقدره؟",
            "نرخ لیر چنده؟",
            "نرخ تتر چنده؟",
        ]
