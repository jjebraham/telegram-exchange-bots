from .store_base import ReferralDBBase
from .store_referrals import ReferralMixin
from .store_reports import ReportsMixin


class ReferralDB(ReferralMixin, ReportsMixin, ReferralDBBase):
    pass
